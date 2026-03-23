import asyncio
import websockets
import json
import aiohttp
from datetime import datetime
import asyncpg
from dotenv import load_dotenv
import os

load_dotenv()
phpsessid_e = os.getenv('PHPSESSID_E')
golden_key_e = os.getenv('GOLDEN_KEY_E')
csrf_t_e = os.getenv('CSRF_TOKEN_E')
phpsessid_d = os.getenv('PHPSESSID_D')
golden_key_d = os.getenv('GOLDEN_KEY_D')
csrf_t_d = os.getenv('CSRF_TOKEN_D')

class FunPayBot:
    def __init__(self, dsn):
        self.dsn = dsn
        self.pool = None
        self.ws = None
        self.golden_key = None
    
    async def init_db(self):
        """Инициализация пула соединений с БД"""
        self.pool = await asyncpg.create_pool(self.dsn)
        print("✅ База данных подключена")
    
    async def get_golden_key(self, cookies):
        """Получение golden_key для WebSocket"""
        # Здесь нужно будет сделать запрос к FunPay API
        # Пока Заглушки
        return golden_key_e

    async def connect_websocket(self):
        """Подключение к WebSocket FunPay"""
        # Получаем golden_key из БД или настроек
        # Пока Заглушки
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT golden_key FROM bot_settings WHERE id=1")
            if row:
                self.golden_key = row['golden_key']
        
        if not self.golden_key:
            print("❌ Golden key не найден. Нужно сначала авторизоваться")
            return
        
        uri = f"wss://api.funpay.com/ws?golden_key={self.golden_key}"

         
        try:
            async with websockets.connect(uri) as websocket:
                self.ws = websocket
                print("✅ WebSocket подключен")
                
                # Отправляем ping для поддержания соединения (каждые 30 секунд)
                async def send_ping():
                    while True:
                        await asyncio.sleep(30)
                        try:
                            await websocket.send(json.dumps({"type": "ping"}))
                            print(f"[{datetime.now()}] Ping отправлен")
                        except:
                            break

                 # Запускаем ping в фоне
                asyncio.create_task(send_ping())
                
                # Слушаем сообщения
                await self.listen_messages()
                
        except Exception as e:
            print(f"❌ Ошибка WebSocket: {e}")
            await asyncio.sleep(5)  # Переподключение через 5 секунд
            await self.connect_websocket()

    async def listen_messages(self):
        """Прослушивание входящих сообщений"""
        async for message in self.ws:
            try:
                data = json.loads(message)
                print(f"📩 Получено: {data}")
                
                # Обрабатываем разные типы сообщений
                if data.get('type') == 'new_message':
                    await self.handle_new_message(data)
                elif data.get('type') == 'pong':
                    print(f"[{datetime.now()}] Pong получен")
                    
            except json.JSONDecodeError:
                print(f"❌ Не удалось распарсить: {message}")

    async def handle_new_message(self, data):
        """Обработка нового сообщения"""
        # Извлекаем данные сообщения
        # Структура может отличаться, нужно смотреть реальные данные
        chat_id = data.get('chat_id')
        message_text = data.get('text', '').lower()
        message_id = data.get('id')
        
        # Проверяем, не отвечали ли уже на это сообщение
        async with self.pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM chat_history WHERE message_id=$1)",
                message_id
            )
            
        if exists:
            print(f"⏭️ Сообщение {message_id} уже обработано")
            return
        
        # Логика автоответчика
        response = self.get_auto_response(message_text)
        
        if response:
            await self.send_message(chat_id, response)
            
            # Сохраняем в историю
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO chat_history (chat_id, message_id, responded) VALUES ($1, $2, $3)",
                    chat_id, message_id, True
                )

    def get_auto_response(self, message_text):
        """Определяем ответ по шаблонам"""
        # То самое сообщение из скриншота
        base_message = """Приветствую! 🎉🎉

Можно смело оплачивать: ваш заказ мгновенно выдаст наш бот, который работает 24/7.
✔️ А подтверждаете вы оплату — только после получения аккаунта.
✖️ Если вы видите лот, значит аренда аккаунта доступна и есть в наличии!
🔗 По количеству доступных аккаунтов можете уточнить у админа.
📅 Хотите купить несколько аккаунтов? — Оплачивайте их разными лотами.

💡 Введите команду !help или !помощь — чтобы показать весь список доступных команд.
👥 !админ — Вызвать администратора для помощи, если бот не справляется с вашим вопросом.
🟢 (На связи с 10:00 до 00:00 по МСК)."""     
                # Простая логика: отвечаем на приветствия
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

    async def send_message(self, chat_id, text):
        """Отправка сообщения через API FunPay"""
        # Нужно получить CSRF токен из БД. Пока Заглушки
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT csrf_token, funpay_cookie FROM bot_settings WHERE id=1"
            )
        
        if not row:
            print("❌ Нет токена для отправки")
            return
        
        headers = {
            'x-csrf-token': row['csrf_token'],
            'cookie': row['funpay_cookie'],
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8'
        }
        
        data = {
            'chat_id': chat_id,
            'text': text
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                'https://funpay.com/chat/sendMessage',
                headers=headers,
                data=data
            ) as resp:
                if resp.status == 200:
                    print(f"✅ Сообщение отправлено в чат {chat_id}")
                else:
                    print(f"❌ Ошибка отправки: {resp.status}")

    async def run(self):
        """Запуск бота"""
        await self.init_db()
        await self.connect_websocket()

# Точка входа
async def main():
    # Строка подключения к PostgreSQL
    DSN = "postgresql://user:password@localhost/funpay_bot"
    
    bot = FunPayBot(DSN)
    
    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен")
    finally:
        if bot.pool:
            await bot.pool.close()

if __name__ == "__main__":
    asyncio.run(main())