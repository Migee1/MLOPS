from steam_manager import SteamAccountManager
import asyncio
import websockets
import json
import aiohttp
from datetime import datetime
import asyncpg
import logging
from typing import Optional, Dict
import random

#Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class FunPayBot:
    """Класс для 1 Аккаунта"""
    def __init__(self, account_data: Dict):
        self.suffix = account_data['e']
        self.phpsessid = account_data['phpsessid']
        self.golden_key = account_data['golden_key']
        self.csrf_token = account_data['csrf_token']
        self.ws = None
        self.connected = False
        self.last_pong = datetime.now()
        self.message_count = 0

    @property
    def name(self):
        return f"Аккаунт-{self.suffix}"
    
    def get_headers(self):
        """Заголовки для HTTP запросов этого аккаунта"""
        return {
            'x-csrf-token': self.csrf_token,
            'cookie': f'PHPSESSID={self.phpsessid}',
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36' 
        }
    
class MultiFunPayBot:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool = None
        self.accounts: Dict[str, FunPayAccount] = {}  # suffix -> account
        self.tasks = []

    async def init_db(self):
        """Инициализация пула соединений с БД"""
        self.pool = await asyncpg.create_pool(self.dsn)
        logger.info("База данных подключена")
        
        # Загружаем аккаунты из БД
        await self.load_accounts()

    async def load_accounts(self):
        """Загрузка аккаунтов FunPay из БД"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM funpay_accounts WHERE is_active = TRUE"
            )

        for row in rows:
            account = FunPayAccount(dict(row))
            self.accounts[account.suffix] = account
            logger.info(f"✅ Загружен {account.name}")
        
        logger.info(f"✅ Всего загружено аккаунтов: {len(self.accounts)}")

    async def log_event(self, account_suffix: str, event_type: str, message: str):
        """Логирование событий в БД"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO bot_logs (account_suffix, event_type, message) VALUES ($1, $2, $3)",
                    account_suffix, event_type, message
                )
        except Exception as e:
            logger.error(f"Ошибка при логировании: {e}")

    async def connect_account(self, account: FunPayAccount):
        """Подключение конкретного аккаунта к WebSocket"""
        uri = f"wss://api.funpay.com/ws?golden_key={account.golden_key}"
        
        while True:  # Бесконечный цикл переподключения
            try:
                logger.info(f"🔄 {account.name}: Подключение к WebSocket...")
                
                async with websockets.connect(
                    uri,
                    ping_interval=20,  # Ping каждые 20 секунд
                    ping_timeout=10      # Таймаут ожидания pong
                ) as websocket:
                    account.ws = websocket
                    account.connected = True
                    account.last_pong = datetime.now()
                    
                    # Обновляем время последнего подключения в БД
                    async with self.pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE funpay_accounts SET last_connected = NOW() WHERE account_suffix = $1",
                            account.suffix
                        )
                    
                    await self.log_event(account.suffix, "connect", "WebSocket подключен")
                    logger.info(f"✅ {account.name}: WebSocket подключен")
                    
                    # Слушаем сообщения для этого аккаунта
                    await self.listen_account_messages(account)
                    
            except websockets.exceptions.ConnectionClosed:
                logger.warning(f"⚠️ {account.name}: Соединение закрыто, переподключение...")
                await self.log_event(account.suffix, "disconnect", "Соединение закрыто")
                
            except Exception as e:
                logger.error(f"❌ {account.name}: Ошибка: {e}")
                await self.log_event(account.suffix, "error", str(e))
            
            account.connected = False
            await asyncio.sleep(5)  # Пауза перед переподключением

    async def listen_account_messages(self, account: FunPayAccount):
        """Прослушивание сообщений для конкретного аккаунта"""
        async for message in account.ws:
            try:
                data = json.loads(message)
                
                # Обработка разных типов сообщений
                if data.get('type') == 'new_message':
                    await self.handle_new_message(account, data)
                elif data.get('type') == 'pong':
                    account.last_pong = datetime.now()
                    account.message_count += 1
                    if account.message_count % 10 == 0:  # Лог каждый 10-й pong
                        logger.debug(f"💓 {account.name}: Pong получен")
                else:
                    logger.debug(f"📨 {account.name}: {data.get('type')}")
                    
            except json.JSONDecodeError:
                logger.error(f"❌ {account.name}: Не удалось распарсить: {message}")
            except Exception as e:
                logger.error(f"❌ {account.name}: Ошибка обработки: {e}")

    async def handle_new_message(self, account: FunPayAccount, data: Dict):
        """Обработка нового сообщения для конкретного аккаунта"""
        try:
            # Извлекаем данные сообщения
            # Структура может отличаться, нужно подставить реальные ключи
            chat_id = data.get('chat_id') or data.get('chatId')
            message_text = data.get('text', '').lower()
            message_id = data.get('id') or data.get('messageId')
            
            if not all([chat_id, message_id]):
                logger.warning(f"⚠️ {account.name}: Неполные данные сообщения: {data}")
                return
            
            logger.info(f"💬 {account.name}: Новое сообщение от {chat_id}: {message_text[:50]}...")
            
            # Проверяем, не отвечали ли уже
            async with self.pool.acquire() as conn:
                exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM chat_history WHERE message_id=$1 AND account_suffix=$2)",
                    message_id, account.suffix
                )
                
            if exists:
                logger.debug(f"⏭️ {account.name}: Сообщение {message_id} уже обработано")
                return
            
            # Получаем ответ
            response = self.get_auto_response(account, message_text)
            
            if response:
                await self.send_message(account, chat_id, response)
                
                # Сохраняем в историю
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO chat_history (chat_id, message_id, responded, account_suffix) VALUES ($1, $2, $3, $4)",
                        chat_id, message_id, True, account.suffix
                    )
                
                await self.log_event(account.suffix, "response", f"Ответ в чат {chat_id}")
                logger.info(f"✅ {account.name}: Ответ отправлен в {chat_id}")
                
        except Exception as e:
            logger.error(f"❌ {account.name}: Ошибка обработки сообщения: {e}")
            await self.log_event(account.suffix, "error", f"handle_message: {e}")

    def get_auto_response(self, account: FunPayAccount, message_text: str) -> Optional[str]:
        """Определяем ответ по шаблонам"""
        # Сообщение
        base_message = """Приветствую! 🎉🎉

Можно смело оплачивать: ваш заказ мгновенно выдаст наш бот, который работает 24/7.
✔️ А подтверждаете вы оплату — только после получения аккаунта.
✖️ Если вы видите лот, значит аренда аккаунта доступна и есть в наличии!
🔗 По количеству доступных аккаунтов можете уточнить у админа.
📅 Хотите купить несколько аккаунтов? — Оплачивайте их разными лотами.

💡 Введите команду !help или !помощь — чтобы показать весь список доступных команд.
👥 !админ — Вызвать администратора для помощи, если бот не справляется с вашим вопросом.
🟢 (На связи с 10:00 до 00:00 по МСК)."""     
                # Отвечаем на приветствия
        greetings = ['привет', 'здравствуйте', 'добрый', 'hello', 'hi', 'здорова', 'хай', 'йоу', 'салам']
        
        if any(greet in message_text for greet in greetings):
            return base_message
        
        # Команды. Пока Заглушки
        if '!help' in message_text or '!помощь' in message_text:
            return "Список команд:\n!help - это сообщение\n!админ - связаться с администратором"
        
        if '!админ' in message_text:
            # Здесь можно создать тикет или переслать админу. Пока Заглушки
            return "Ваш запрос передан администратору. Ожидайте ответа в рабочее время (10:00-00:00 МСК)."
        
        return None

    async def send_message(self, account: FunPayAccount, chat_id: str, text: str):
        """Отправка сообщения через API FunPay"""
        
        data = {
            'chat_id': chat_id,  # или 'chat_id', нужно проверить
            'text': text
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    'https://funpay.com/chat/sendMessage',
                    headers=account.get_headers(),
                    data=data
                ) as resp:
                    if resp.status == 200:
                        logger.info(f"✅ {account.name}: Сообщение отправлено в чат {chat_id}")
                    else:
                        error_text = await resp.text()
                        logger.error(f"❌ {account.name}: Ошибка отправки {resp.status}: {error_text}")
                        await self.log_event(account.suffix, "send_error", f"Status {resp.status}")
                        
            except Exception as e:
                logger.error(f"❌ {account.name}: Ошибка при отправке: {e}")
                await self.log_event(account.suffix, "send_error", str(e))
    
    async def health_check(self):
        """Периодическая проверка здоровья всех аккаунтов"""
        while True:
            await asyncio.sleep(60)  # Проверка каждую минуту
            
            for suffix, account in self.accounts.items():
                status = "✅" if account.connected else "❌"
                time_since_pong = (datetime.now() - account.last_pong).seconds if account.last_pong else -1
                
                logger.info(f"📊 {account.name}: {status} | Pong: {time_since_pong}s ago")
                
                # Если давно не было pong, переподключаем
                if account.connected and time_since_pong > 90:
                    logger.warning(f"⚠️ {account.name}: Нет pong > 90s, переподключаю...")
                    if account.ws:
                        await account.ws.close()

    async def run(self):
        """Запуск бота"""
        await self.init_db()
        
        if not self.accounts:
            logger.error("❌ Нет активных аккаунтов в БД!")
            return
        
        # Запускаем подключение для каждого аккаунта
        tasks = []
        for account in self.accounts.values():
            task = asyncio.create_task(self.connect_account(account))
            tasks.append(task)
        
        # Запускаем проверку здоровья
        health_task = asyncio.create_task(self.health_check())
        tasks.append(health_task)
        
        # Ждем все задачи
        try:
            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            logger.info("🛑 Получен сигнал остановки")
        finally:
            # Закрываем все соединения
            for account in self.accounts.values():
                if account.ws:
                    await account.ws.close()
            
            if self.pool:
                await self.pool.close()
# Точка входа
async def main():
    # Строка подключения к PostgreSQL (замени на свои данные)
    DSN = "postgresql://postgres:mvp17@locaalhost/funpay_bot"
    
    bot = MultiFunPayBot(DSN)
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())