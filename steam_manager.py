import asyncio
import pyotp
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
import logging
from steampy.client import SteamClient
from steampy.models import GameOptions, Currency
from steampy.exceptions import ApiException, LoginRequired

logger = logging.getLogger(__name__)

class SteamAccountManager:
    """Менеджер для управления Steam аккаунтами"""
    
    def __init__(self, db_pool):
        self.pool = db_pool
        self.active_sessions = {}  # account_id -> SteamClient
        self.totp_cache = {}       # account_id -> текущий код (кэш)
        
    def generate_totp_code(self, shared_secret: str) -> str:
        """
        Генерация текущего кода Steam Guard
        Используем pyotp для TOTP
        """
        try:
            totp = pyotp.TOTP(shared_secret)
            code = totp.now()
            logger.debug(f"Сгенерирован TOTP код: {code}")
            return code
        except Exception as e:
            logger.error(f"Ошибка генерации TOTP: {e}")
            return None
        
    async def get_account_info(self, account_id: int) -> Optional[Dict]:
        """Получить информацию об аккаунте из БД"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM steam_accounts WHERE id = $1",
                account_id
            )
            return dict(row) if row else None
    
    async def get_available_accounts(self, funpay_suffix: str = None) -> list:
        """Получить список доступных аккаунтов"""
        query = "SELECT * FROM steam_accounts WHERE status = 'available'"
        params = []
        
        if funpay_suffix:
            query += " AND funpay_suffix = $1"
            params.append(funpay_suffix)
            
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]
        
    async def rent_account(self, account_id: int, renter_info: Dict) -> bool:
        """
        Аренда аккаунта
        renter_info: {'funpay_chat_id': '...', 'funpay_suffix': 'e', 'rent_days': 7}
        """
        async with self.pool.acquire() as conn:
            # Проверяем, доступен ли аккаунт
            account = await conn.fetchrow(
                "SELECT * FROM steam_accounts WHERE id = $1 AND status = 'available'",
                account_id
            )
            
            if not account:
                logger.error(f"Аккаунт {account_id} недоступен для аренды")
                return False
            
            # Рассчитываем время аренды
            rent_days = renter_info.get('rent_days', 1)
            rent_start = datetime.now()
            rent_expires = rent_start + timedelta(days=rent_days)
            
            # Обновляем статус аккаунта
            await conn.execute("""
                UPDATE steam_accounts 
                SET status = 'rented',
                    current_renter = $1,
                    funpay_chat_id = $2,
                    rent_start = $3,
                    rent_expires = $4
                WHERE id = $5
            """, 
                renter_info.get('funpay_user_id', 'unknown'),
                renter_info.get('funpay_chat_id'),
                rent_start,
                rent_expires,
                account_id
            )
            
            # Логируем операцию
            await conn.execute("""
                INSERT INTO steam_operations (account_id, operation_type, operator, details)
                VALUES ($1, 'rent', 'system', $2)
            """, account_id, json.dumps(renter_info))
            
            logger.info(f"✅ Аккаунт {account['login']} арендован до {rent_expires}")
            return True
    
    async def generate_credentials_message(self, account_id: int) -> Dict:
        """
        Генерирует сообщение с данными для входа
        Возвращает логин, пароль и текущий TOTP код
        """
        account = await self.get_account_info(account_id)
        if not account:
            return None
        
        # Генерируем актуальный TOTP код
        totp_code = None
        if account.get('shared_secret'):
            totp_code = self.generate_totp_code(account['shared_secret'])
        
        # Кэшируем код для быстрой выдачи
        self.totp_cache[account_id] = {
            'code': totp_code,
            'generated_at': datetime.now()
        }
        
        return {
            'login': account['login'],
            'password': account['password'],
            'totp_code': totp_code,
            'expires_at': account['rent_expires']
        }
    
    async def force_logout(self, account_id: int) -> bool:
        """
        Принудительный выход с аккаунта
        Меняем пароль и/или отзываем токены
        """
        account = await self.get_account_info(account_id)
        if not account:
            return False
        
        try:
            # Создаем клиент Steam для этого аккаунта
            steam_client = SteamClient(account['login'], account['password'])
            
            # Генерируем код для входа
            totp_code = self.generate_totp_code(account['shared_secret'])
            
            # Логинимся
            steam_client.login(totp_code)
            
            # Меняем пароль
            new_password = self._generate_random_password()
            steam_client.change_password(account['password'], new_password)
            
            # Обновляем пароль в БД
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    UPDATE steam_accounts 
                    SET password = $1, status = 'available', 
                        current_renter = NULL, funpay_chat_id = NULL,
                        rent_start = NULL, rent_expires = NULL
                    WHERE id = $2
                """, new_password, account_id)
                
                await conn.execute("""
                    INSERT INTO steam_operations (account_id, operation_type, operator, details)
                    VALUES ($1, 'force_close', 'system', $2)
                """, account_id, json.dumps({'old_password': account['password'], 'new_password': new_password}))
            
            logger.info(f"✅ Аккаунт {account['login']} принудительно закрыт, пароль изменен")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка при принудительном выходе {account['login']}: {e}")
            return False
        
    def _generate_random_password(self,length=16) -> str:
        """Генерация случайного пароля"""
        import random
        import string
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(random.choice(chars) for _ in range(length))
    
    async def check_expired_rentals(self):
        """Проверка и закрытие просроченных аренд"""
        async with self.pool.acquire() as conn
        #  Поиск просроченных аренд
        expired = await conn.fetch("""
            SELECT id, login FROM steam_accounts 
            WHERE status = 'rented' 
            AND rent_expires < NOW()
            """)
        
        for account in expired:
            logger.info(f"Просрочена аренда аккаунта {account['login']}")
            await self.force_logout(account['id'])

    async def extend_rental(self, account_id: int, extra_days: int) -> bool:
        """Продление аренды"""
        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE steam_accounts 
                SET rent_expires = rent_expires + ($1 || ' days')::INTERVAL
                WHERE id = $2 AND status = 'rented'
                RETURNING id
            """, extra_days, account_id)
            
            if result:
                logger.info(f"✅ Аренда аккаунта {account_id} продлена на {extra_days} дней")
                return True
            return False
    
    async def get_rental_info(self, account_id: int) -> Optional[Dict]:
        """Получить информацию о текущей аренде"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT login, current_renter, rent_start, rent_expires 
                FROM steam_accounts 
                WHERE id = $1 AND status = 'rented'
            """, account_id)
            
            if row:
                return {
                    'login': row['login'],
                    'renter': row['current_renter'],
                    'started': row['rent_start'],
                    'expires': row['rent_expires'],
                    'remaining_days': (row['rent_expires'] - datetime.now()).days
                }
            return None