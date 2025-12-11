import os
import sys
import logging
import asyncio
import signal
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Set
import json
import traceback
import hashlib
import secrets
from pathlib import Path

import aiohttp
from aiohttp import web

# Импорты aiogram
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ContentType
from aiogram.exceptions import TelegramUnauthorizedError, TelegramBadRequest

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Глобальные переменные
bot_instance = None
dp_instance = None
shutdown_flag = False
restart_count = 0
max_restarts = 100
restart_delay = 10
PORT = int(os.environ.get("PORT", 8080))

# Конфигурация системы доступа
ACCESS_CONFIG = {
    "admin_ids": [],  # Заполняется из env или файла
    "price_per_course": 2990,  # рублей за полный курс
}

# Файлы для хранения данных
DATA_FILES = {
    "paid_users": "paid_users.json",
    "user_settings": "user_settings.json"
}

# Класс для управления доступом
class AccessManager:
    """Менеджер доступа к боту"""
    
    def __init__(self):
        self.paid_users = self.load_data("paid_users")
        self.user_settings = self.load_data("user_settings")
        
        # Загружаем admin_ids из переменных окружения
        admin_ids_str = os.getenv('ADMIN_IDS', '')
        if admin_ids_str:
            ACCESS_CONFIG["admin_ids"] = [int(id.strip()) for id in admin_ids_str.split(',')]
    
    def load_data(self, data_type: str) -> Dict:
        """Загрузить данные из файла"""
        file_path = DATA_FILES.get(data_type)
        if not file_path:
            return {}
        
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading {data_type}: {e}")
                return {}
        return {}
    
    def save_data(self, data_type: str, data: Dict):
        """Сохранить данные в файл"""
        file_path = DATA_FILES.get(data_type)
        if not file_path:
            return
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving {data_type}: {e}")
    
    def is_admin(self, user_id: int) -> bool:
        """Проверить, является ли пользователь администратором"""
        return user_id in ACCESS_CONFIG["admin_ids"]
    
    def has_access(self, user_id: int) -> Tuple[bool, str, Optional[datetime]]:
        """
        Проверить доступ пользователя
        
        Returns:
            Tuple[has_access, access_type, expiry_date]
        """
        user_id_str = str(user_id)
        
        # Проверка администратора
        if self.is_admin(user_id):
            return True, "admin", None
        
        # Проверка платного доступа
        if user_id_str in self.paid_users:
            user_data = self.paid_users[user_id_str]
            return True, "paid", None  # Постоянный доступ
        
        return False, "none", None
    
    def grant_access_by_id(self, user_id: int, admin_id: int, username: str = "") -> bool:
        """Предоставить доступ пользователю по ID"""
        user_id_str = str(user_id)
        
        if user_id_str in self.paid_users:
            return False  # Уже имеет доступ
        
        # Добавляем пользователя в список платных
        self.paid_users[user_id_str] = {
            "granted_date": datetime.now().isoformat(),
            "granted_by": admin_id,
            "username": username,
            "access_type": "permanent",
            "payment_date": datetime.now().isoformat(),
            "price": ACCESS_CONFIG["price_per_course"]
        }
        
        self.save_data("paid_users", self.paid_users)
        return True
    
    def grant_access_by_username(self, username: str, admin_id: int) -> Tuple[bool, str, Optional[int]]:
        """Предоставить доступ по username Telegram"""
        try:
            # Удаляем @ если есть
            username = username.replace('@', '').strip()
            
            # Пытаемся найти пользователя по username
            # В реальном боте мы бы сделали запрос к API Telegram,
            # но здесь мы храним маппинг username -> ID
            # Для демо-версии будем просить администратора указать ID
            
            return False, f"Для выдачи доступа по username @{username} необходимо указать ID пользователя.", None
            
        except Exception as e:
            logger.error(f"Error granting access by username: {e}")
            return False, f"Ошибка: {str(e)}", None
    
    def revoke_access(self, user_id: int) -> bool:
        """Отозвать доступ пользователя"""
        user_id_str = str(user_id)
        
        if user_id_str in self.paid_users:
            del self.paid_users[user_id_str]
            self.save_data("paid_users", self.paid_users)
            return True
        
        return False
    
    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """Найти пользователя по username"""
        username = username.replace('@', '').strip().lower()
        
        for user_id_str, user_data in self.paid_users.items():
            if user_data.get("username", "").lower() == username:
                return {"user_id": int(user_id_str), **user_data}
        
        return None
    
    def get_user_stats(self) -> Dict:
        """Получить статистику пользователей"""
        total_paid = len(self.paid_users)
        
        # Доходы (теоретические)
        total_income = sum(user_data.get("price", 0) for user_data in self.paid_users.values())
        
        return {
            "total_paid": total_paid,
            "total_income": total_income,
            "avg_income_per_user": total_income / total_paid if total_paid > 0 else 0
        }
    
    def get_user_info(self, user_id: int) -> Dict:
        """Получить информацию о пользователе"""
        user_id_str = str(user_id)
        has_access, access_type, expiry_date = self.has_access(user_id)
        
        info = {
            "user_id": user_id,
            "has_access": has_access,
            "access_type": access_type,
            "expiry_date": expiry_date
        }
        
        if user_id_str in self.paid_users:
            info.update(self.paid_users[user_id_str])
        
        return info

# Инициализация менеджера доступа
access_manager = AccessManager()

# Обработчики сигналов для graceful shutdown
def signal_handler(sig, frame):
    """Обработчик сигналов для graceful shutdown"""
    global shutdown_flag
    logger.info(f"Получен сигнал {sig}, инициируется graceful shutdown...")
    shutdown_flag = True
    
    if bot_instance and dp_instance:
        asyncio.create_task(shutdown())
    else:
        sys.exit(0)

async def shutdown():
    """Корректное завершение работы бота"""
    logger.info("Начинаем graceful shutdown...")
    
    try:
        # Сохраняем данные доступа
        access_manager.save_data("paid_users", access_manager.paid_users)
        
        # Останавливаем polling
        if dp_instance:
            await dp_instance.stop_polling()
            logger.info("Polling успешно остановлен")
        
        # Закрываем сессию бота
        if bot_instance:
            await bot_instance.session.close()
            logger.info("Сессия бота успешно закрыта")
            
    except Exception as e:
        logger.error(f"Ошибка при завершении: {e}")
    finally:
        logger.info("Shutdown завершен")
        sys.exit(0)

# Регистрация обработчиков сигналов
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

# Проверка токена бота
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    logger.error("BOT_TOKEN не установлен! Установите переменную окружения.")
    sys.exit(1)

# Инициализация бота с настройками по умолчанию
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

# Хранилище состояний
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Состояния пользователя
class UserState(StatesGroup):
    viewing_module = State()
    waiting_feedback = State()
    taking_test = State()
    test_question = State()
    admin_menu = State()
    admin_grant_access = State()
    admin_revoke_access = State()

# Конфигурация аудиофайлов
AUDIO_CONFIG = {
    "base_path": "audio/",
    "default_format": ".mp3",
}

# Данные курса с аудио (упрощенная версия для примера)
MODULES = [
    {
        "id": 1,
        "day": 1,
        "title": "Основы мира тендеров",
        "emoji": "📚",
        "content": """<b>📚 День 1 | Модуль 1: Основы мира тендеров</b>

✅ <b>Что такое тендер?</b>
Это конкурентная форма размещения заказов на поставку товаров, выполнение работ или оказание услуг, при которой заказчик выбирает исполнителя на основе заранее объявленных критериев.

Проще говоря, это процедура, где несколько компаний (поставщиков) предлагают свои условия (в первую очередь цену) для победы в контракте, а заказчик выбирает самое выгодное для себя предложение.""",
        "task": "Найти и изучить 2 тендера в вашей сфере деятельности",
        "audio_file": "module1.mp3",
        "audio_duration": 120,
        "audio_title": "Основы тендерной системы",
        "has_audio": True
    },
    {
        "id": 2,
        "day": 2,
        "title": "44-ФЗ",
        "emoji": "🏛️",
        "content": """<b>🏛️ День 2 | Модуль 2: 44-ФЗ</b>

✅ <b>Ключевые способы закупок:</b>

<b>Конкурентные закупки:</b>
• Аукцион в электронной форме (побеждает самый дешевый)
• Конкурс в электронной форме (лучшие условия)
• Электронный запрос котировок (быстро, для небольших сумм)""",
        "task": "Изучить документацию к одному аукциону по 44-ФЗ",
        "audio_file": "module2.mp3",
        "audio_duration": 180,
        "audio_title": "Работа с 44-ФЗ: практическое руководство",
        "has_audio": True
    },
    {
        "id": 3,
        "day": 3,
        "title": "223-ФЗ",
        "emoji": "🏢",
        "content": """<b>🏢 День 3 | Модуль 3: 223-ФЗ</b>

✅ <b>Главное отличие:</b>
1. У каждого заказчика своё <b>Положение о закупке</b>
2. Регулирует корпоративные закупки — заказы госкорпораций и крупного бизнеса""",
        "task": "Найти и изучить Положение о закупке компании по 223-ФЗ",
        "audio_file": "module3.mp3",
        "audio_duration": 150,
        "audio_title": "Корпоративные закупки по 223-ФЗ",
        "has_audio": True
    },
    {
        "id": 4,
        "day": 4,
        "title": "Коммерческие тендеры",
        "emoji": "💼",
        "content": """<b>💼 День 4 | Модуль 4: Коммерческие тендеры</b>

✅ <b>Ключевые способы закупок:</b>

<b>Конкурентные:</b>
• Запрос предложений
• Аукционы
• Конкурсы""",
        "task": "Составить список потенциальных заказчиков и зарегистрироваться на B2B-Center",
        "audio_file": "module4.mp3",
        "audio_duration": 165,
        "audio_title": "Стратегии работы с коммерческими заказчиками",
        "has_audio": True
    },
    {
        "id": 5,
        "day": 5,
        "title": "Практический старт",
        "emoji": "🚀",
        "content": """<b>🚀 День 5 | Модуль 5: Практический старт</b>

✅ <b>Пошаговый план действий:</b>

1. <b>Получите ЭЦП:</b>
   • Для ООО/ИП — в Налоговом органе
   • Для ФЛ - в аккредитованном УЦ (https://uc-itcom.ru)
   • оформить УКЭП физлица и машиночитаемую доверенность (МЧД) на сотрудника компании""",
        "task": "Составить пошаговый план действий",
        "audio_file": "module5.mp3",
        "audio_duration": 210,
        "audio_title": "Практический план: первые шаги в тендерах",
        "has_audio": True
    },
    {
        "id": 6,
        "day": 6,
        "title": "Итоги курса",
        "emoji": "🏆",
        "content": """<b>🏆 День 6 | Модуль 6: Итоги курса</b>

✅ <b>Итоги курса:</b>

После прохождения вы знаете:
1. Разницу между 44-ФЗ, 223-ФЗ и коммерческими закупками
2. Основные шаги для участия
3. Где искать информацию и тендеры
4. Практический план действий""",
        "task": "Составить план действий на первую неделю по чек-листу",
        "audio_file": "module6.mp3",
        "audio_duration": 180,
        "audio_title": "Итоги курса: чек-лист первых шагов и план действий",
        "has_audio": True
    }
]

# Тестовые вопросы (упрощенная версия)
TEST_QUESTIONS = [
    {
        "id": 1,
        "question": "Какой федеральный закон регулирует закупки государственных бюджетных учреждений?",
        "options": {
            "а": "223-ФЗ",
            "б": "44-ФЗ",
            "в": "94-ФЗ",
            "г": "Гражданский кодекс РФ"
        },
        "correct": "б",
        "correct_text": "б) 44-ФЗ"
    },
    {
        "id": 2,
        "question": "Основное отличие закупок по 223-ФЗ от закупок по 44-ФЗ заключается в том, что:",
        "options": {
            "а": "У каждого заказчика по 223-ФЗ есть собственное Положение о закупке",
            "б": "Закупки по 223-ФЗ всегда проводятся в виде аукциона",
            "в": "Для участия в закупках по 223-ФЗ не требуется электронная подпись",
            "г": "Закупки по 223-ФЗ не размещаются на официальных сайтах"
        },
        "correct": "а",
        "correct_text": "а) У каждого заказчика по 223-ФЗ есть собственное Положение о закупке"
    }
]

# Дополнительные материалы
ADDITIONAL_MATERIALS = {
    "links": {
        "ЕИС": "https://zakupki.gov.ru",
        "Госуслуги": "https://www.gosuslugi.ru",
        "B2B-Center": "https://www.b2b-center.ru",
        "Техподдержка курса": "https://tritika.ru"
    },
    "contacts": {
        "email": "info@tritika.ru",
        "phone": "+7(4922)223-222",
        "mobile": "+7-904-653-69-87"
    }
}

# Словарь для хранения прогресса пользователей
user_progress = {}

# Мидлварь для проверки доступа
async def check_access_middleware(handler, event, data):
    """Проверка доступа пользователя"""
    # Получаем сообщение или callback
    if hasattr(event, 'message'):
        message = event.message
    elif hasattr(event, 'callback_query'):
        message = event.callback_query.message
    else:
        return await handler(event, data)
    
    user_id = message.from_user.id
    
    # Проверяем доступ
    has_access, access_type, expiry_date = access_manager.has_access(user_id)
    
    # Команды, доступные без проверки доступа
    allowed_commands = ['start', 'help', 'support', 'contacts', 'myid']
    
    # Получаем команду из сообщения
    command = None
    if hasattr(message, 'text'):
        if message.text and message.text.startswith('/'):
            command = message.text.split(' ')[0][1:].split('@')[0]
    
    # Разрешаем доступ к определенным командам без проверки
    if command in allowed_commands:
        return await handler(event, data)
    
    # Разрешаем доступ администраторам
    if access_manager.is_admin(user_id):
        return await handler(event, data)
    
    # Если нет доступа
    if not has_access:
        # Получаем имя пользователя
        user_name = message.from_user.first_name or "Пользователь"
        
        # Формируем сообщение о необходимости доступа
        access_message = f"""
🔒 <b>Доступ ограничен</b>

Привет, {user_name}!

Для получения доступа к курсу необходимо связаться с администратором.

<b>📋 Как получить доступ:</b>

1️⃣ <b>Оплатить курс</b>
   Стоимость полного курса: <b>{ACCESS_CONFIG['price_per_course']} руб.</b>

2️⃣ <b>Связаться с администратором</b>
   Напишите администратору для получения доступа

3️⃣ <b>Предоставить информацию</b>
   • Ваш ID: <code>{user_id}</code>
   • Имя в Telegram
   • Username (если есть)

<b>👨‍💼 Контакты администратора:</b>
Для связи с администратором нажмите /support

<b>🎯 Что включено в курс:</b>
• 6 модулей с теорией и практикой
• Аудио сопровождение к каждому уроку
• Практические задания
• Финальный тест с сертификатом
• Готовый чек-лист для работы
• Поддержка 24/7

Для связи с администратором нажмите /support
        """
        
        # Создаем клавиатуру
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="👨‍💼 Связаться с администратором")],
                [KeyboardButton(text="ℹ️ Узнать мой ID")],
                [KeyboardButton(text="💰 Стоимость курса")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        # Отправляем сообщение
        try:
            await message.answer(access_message, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        except:
            pass
        
        # Прерываем обработку
        return
    
    # Если доступ есть, продолжаем обработку
    return await handler(event, data)

# Регистрируем мидлварь
dp.update.middleware(check_access_middleware)

# ФИКСИРОВАННАЯ КЛАВИАТУРА ДЛЯ ОСНОВНЫХ ДЕЙСТВИЙ
def get_main_keyboard(user_id: int = None) -> ReplyKeyboardMarkup:
    """
    Создает фиксированную клавиатуру, которая всегда показывается внизу
    с учетом прав доступа
    """
    # Проверяем, является ли пользователь администратором
    is_admin = access_manager.is_admin(user_id) if user_id else False
    
    if is_admin:
        # Клавиатура для администратора
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                # Первый ряд - административные функции
                [
                    KeyboardButton(text="👑 Админ панель"),
                    KeyboardButton(text="📊 Статистика"),
                ],
                # Второй ряд - обычные функции
                [
                    KeyboardButton(text="📚 Меню курса"),
                    KeyboardButton(text="🎧 Аудио уроки"),
                ],
                # Третий ряд
                [
                    KeyboardButton(text="📊 Мой прогресс"),
                    KeyboardButton(text="📞 Контакты"),
                ],
                # Четвертый ряд
                [
                    KeyboardButton(text="🔗 Полезные ссылки"),
                    KeyboardButton(text="🆘 Помощь"),
                ],
                # Пятый ряд
                [
                    KeyboardButton(text="📝 Пройти тест"),
                    KeyboardButton(text="🏆 Результаты теста")
                ],
                # Шестой ряд
                [
                    KeyboardButton(text="✅ Отметить все модули"),
                    KeyboardButton(text="📥 Скачать чек-лист")
                ]
            ],
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="Выберите действие..."
        )
    else:
        # Клавиатура для обычного пользователя
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                # Первый ряд
                [
                    KeyboardButton(text="📚 Меню курса"),
                    KeyboardButton(text="🎧 Аудио уроки"),
                ],
                # Второй ряд
                [
                    KeyboardButton(text="📊 Мой прогресс"),
                    KeyboardButton(text="📞 Контакты"),
                ],
                # Третий ряд
                [
                    KeyboardButton(text="🔗 Полезные ссылки"),
                    KeyboardButton(text="🆘 Помощь"),
                ],
                # Четвертый ряд
                [
                    KeyboardButton(text="📝 Пройти тест"),
                    KeyboardButton(text="🏆 Результаты теста")
                ],
                # Пятый ряд
                [
                    KeyboardButton(text="✅ Отметить все модули"),
                    KeyboardButton(text="📥 Скачать чек-лист")
                ]
            ],
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="Выберите действие..."
        )
    
    return keyboard

# Клавиатура для навигации по урокам
def get_lesson_navigation_keyboard(current_index: int, total_modules: int) -> ReplyKeyboardMarkup:
    """
    Создает клавиатуру для навигации по урокам
    """
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            # Первый ряд - навигация
            [
                KeyboardButton(text="⬅️ Предыдущий урок"),
                KeyboardButton(text=f"📖 {current_index+1}/{total_modules}"),
                KeyboardButton(text="Следующий урок ➡️"),
            ],
            # Второй ряд - действия с уроком
            [
                KeyboardButton(text="🎧 Прослушать аудио"),
                KeyboardButton(text="✅ Отметить пройденным"),
            ],
            # Третий ряд - возврат
            [
                KeyboardButton(text="📚 Меню курса"),
                KeyboardButton(text="📊 Мой прогресс"),
                KeyboardButton(text="🔙 Главное меню")
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Управление уроком..."
    )
    return keyboard

# Клавиатура для теста
def get_test_keyboard(question_num: int, total_questions: int) -> ReplyKeyboardMarkup:
    """
    Создает клавиатуру для прохождения теста
    """
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            # Варианты ответов
            [
                KeyboardButton(text="а"),
                KeyboardButton(text="б"),
            ],
            [
                KeyboardButton(text="в"),
                KeyboardButton(text="г"),
            ],
            # Навигация
            [
                KeyboardButton(text="⏭ Пропустить"),
                KeyboardButton(text=f"📝 {question_num}/{total_questions}"),
                KeyboardButton(text="🏁 Завершить тест")
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Выберите вариант ответа..."
    )
    return keyboard

# Клавиатура администратора
def get_admin_keyboard() -> ReplyKeyboardMarkup:
    """
    Клавиатура для администратора
    """
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="👥 Список пользователей"),
                KeyboardButton(text="➕ Выдать доступ"),
            ],
            [
                KeyboardButton(text="➖ Забрать доступ"),
                KeyboardButton(text="📊 Статистика"),
            ],
            [
                KeyboardButton(text="🔍 Найти пользователя"),
                KeyboardButton(text="📢 Рассылка"),
            ],
            [
                KeyboardButton(text="🔙 Главное меню"),
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Админ панель..."
    )
    return keyboard

# Клавиатура после теста
def get_after_test_keyboard(user_id: int = None) -> ReplyKeyboardMarkup:
    """
    Создает клавиатуру после завершения теста
    """
    is_admin = access_manager.is_admin(user_id) if user_id else False
    
    if is_admin:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [
                    KeyboardButton(text="👑 Админ панель"),
                    KeyboardButton(text="📊 Статистика")
                ],
                [
                    KeyboardButton(text="📚 Меню курса"),
                    KeyboardButton(text="🔙 Главное меню")
                ]
            ],
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="Выберите действие..."
        )
    else:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [
                    KeyboardButton(text="📊 Мой прогресс"),
                    KeyboardButton(text="🏆 Результаты теста")
                ],
                [
                    KeyboardButton(text="📚 Меню курса"),
                    KeyboardButton(text="🔙 Главное меню")
                ]
            ],
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="Выберите действие..."
        )
    return keyboard

# Вспомогательные функции для работы с аудио
class AudioManager:
    """Менеджер для работы с аудиофайлами"""
    
    @staticmethod
    def get_audio_path(module_index: int) -> Optional[str]:
        """Получить путь к аудиофайлу модуля"""
        if 0 <= module_index < len(MODULES):
            module = MODULES[module_index]
            audio_file = module.get("audio_file")
            if audio_file:
                audio_path = os.path.join(AUDIO_CONFIG["base_path"], audio_file)
                # Проверяем существование файла
                if os.path.exists(audio_path):
                    return audio_path
                else:
                    logger.warning(f"Audio file not found: {audio_path}")
        return None
    
    @staticmethod
    def audio_exists(module_index: int) -> bool:
        """Проверить существование аудиофайла"""
        return AudioManager.get_audio_path(module_index) is not None
    
    @staticmethod
    def get_audio_info(module_index: int) -> Dict:
        """Получить информацию об аудио модуля"""
        if 0 <= module_index < len(MODULES):
            module = MODULES[module_index]
            return {
                "file": module.get("audio_file"),
                "duration": module.get("audio_duration", 0),
                "title": module.get("audio_title", ""),
                "exists": AudioManager.audio_exists(module_index),
                "has_audio": module.get("has_audio", False)
            }
        return {}
    
    @staticmethod
    async def send_module_audio(chat_id: int, module_index: int) -> bool:
        """Отправить аудио сопровождение для модуля"""
        try:
            audio_path = AudioManager.get_audio_path(module_index)
            if not audio_path:
                logger.warning(f"No audio for module {module_index}")
                return False
            
            module = MODULES[module_index]
            audio_info = AudioManager.get_audio_info(module_index)
            
            # Создаем объект файла
            audio_file = FSInputFile(audio_path)
            
            # Формируем описание
            caption = f"🎧 <b>{module['emoji']} Аудио-сопровождение к модулю {module_index + 1}</b>\n"
            caption += f"<b>{module['title']}</b>\n\n"
            caption += f"⏱ <b>Длительность:</b> {audio_info['duration']//60}:{audio_info['duration']%60:02d}\n"
            caption += f"📚 <b>Описание:</b> {audio_info['title']}\n\n"
            caption += "<i>Рекомендуем прослушать аудио для лучшего усвоения материала</i>"
            
            # Отправляем аудио
            await bot.send_audio(
                chat_id=chat_id,
                audio=audio_file,
                caption=caption,
                parse_mode=ParseMode.HTML
            )
            
            logger.info(f"Audio sent for module {module_index + 1} to chat {chat_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending audio for module {module_index}: {e}")
            return False

# Функция отображения списка уроков
def get_lessons_list_keyboard() -> ReplyKeyboardMarkup:
    """
    Создает клавиатуру со списком всех уроков
    """
    keyboard_rows = []
    
    # Добавляем уроки по одному в ряд
    for module in MODULES:
        audio_icon = "🎧 " if module.get("has_audio", False) else ""
        keyboard_rows.append([
            KeyboardButton(text=f"{module['emoji']} {audio_icon}День {module['day']}: {module['title'][:20]}")
        ])
    
    # Добавляем кнопки возврата
    keyboard_rows.append([
        KeyboardButton(text="📊 Мой прогресс"),
        KeyboardButton(text="🔙 Назад в главное меню")
    ])
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=keyboard_rows,
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Выберите урок..."
    )
    return keyboard

# Функция отображения модуля
async def show_module(message: Message, module_index: int, state: FSMContext):
    """
    Показывает выбранный модуль и автоматически отправляет аудио сопровождение
    """
    module = MODULES[module_index]
    user_id = message.from_user.id
    
    # Проверяем доступ
    has_access, access_type, expiry_date = access_manager.has_access(user_id)
    if not has_access:
        await message.answer("У вас нет доступа к этому модулю. Для получения доступа свяжитесь с администратором: /support")
        return
    
    # Обновляем состояние
    await state.set_state(UserState.viewing_module)
    await state.update_data(current_module=module_index)
    
    # Обновляем последний просмотренный модуль
    if user_id in user_progress:
        user_progress[user_id]['last_module'] = module_index
    
    # Формируем сообщение
    module_text = f"{module['content']}\n\n"
    module_text += f"<b>📝 Практическое задание:</b> {module['task']}"
    
    # Проверяем, отмечен ли модуль как пройденный
    is_completed = False
    if user_id in user_progress:
        is_completed = (module_index + 1) in user_progress[user_id].get('completed_modules', [])
    
    if not is_completed:
        module_text += "\n\n✅ <b>Не забудьте отметить модуль как пройденный после изучения!</b>"
    
    # Отправляем текст модуля с клавиатурой навигации
    await message.answer(
        module_text,
        reply_markup=get_lesson_navigation_keyboard(module_index, len(MODULES)),
        parse_mode=ParseMode.HTML
    )
    
    # Автоматически отправляем аудио сопровождение
    audio_sent = await AudioManager.send_module_audio(message.chat.id, module_index)
    
    if not audio_sent and module.get("has_audio", False):
        await message.answer(
            "❌ Аудио сопровождение временно недоступно. Попробуйте позже.",
            parse_mode=ParseMode.HTML
        )

# Функции для тестирования
async def start_test_internal(message: Message, state: FSMContext):
    """
    Внутренняя функция запуска теста
    """
    user_id = message.from_user.id
    
    # Проверяем доступ
    has_access, access_type, expiry_date = access_manager.has_access(user_id)
    if not has_access:
        await message.answer("У вас нет доступа к тесту. Для получения доступа свяжитесь с администратором: /support")
        return
    
    # Инициализируем данные теста
    test_data = {
        "current_question": 0,
        "answers": {},  # вопрос_id -> ответ
        "start_time": datetime.now().isoformat(),
        "completed": False,
        "skipped": []
    }
    
    await state.set_state(UserState.taking_test)
    await state.update_data(test_data=test_data)
    
    # Отправляем первый вопрос
    await send_test_question(message, state, 0)

async def send_test_question(message: Message, state: FSMContext, question_index: int = None):
    """
    Отправляет вопрос теста
    """
    data = await state.get_data()
    test_data = data.get("test_data", {})
    
    if question_index is None:
        question_index = test_data.get("current_question", 0)
    
    if question_index >= len(TEST_QUESTIONS):
        await finish_test(message, state)
        return
    
    question = TEST_QUESTIONS[question_index]
    
    # Формируем текст вопроса
    question_text = f"<b>📝 Вопрос {question_index + 1} из {len(TEST_QUESTIONS)}</b>\n\n"
    question_text += f"{question['question']}\n\n"
    
    # Добавляем варианты ответов
    for option_key, option_text in question["options"].items():
        question_text += f"<b>{option_key})</b> {option_text}\n"
    
    question_text += "\n<i>Выберите вариант ответа (а, б, в, г)</i>"
    
    # Обновляем текущий вопрос в состоянии
    test_data["current_question"] = question_index
    await state.update_data(test_data=test_data)
    
    await message.answer(
        question_text,
        reply_markup=get_test_keyboard(question_index + 1, len(TEST_QUESTIONS)),
        parse_mode=ParseMode.HTML
    )

async def process_test_answer(message: Message, state: FSMContext, answer: str):
    """
    Обрабатывает ответ на вопрос теста
    """
    data = await state.get_data()
    test_data = data.get("test_data", {})
    current_question = test_data.get("current_question", 0)
    
    if current_question >= len(TEST_QUESTIONS):
        return
    
    # Сохраняем ответ
    question = TEST_QUESTIONS[current_question]
    test_data["answers"][question["id"]] = answer
    await state.update_data(test_data=test_data)
    
    # Переходим к следующему вопросу
    next_question = current_question + 1
    
    if next_question < len(TEST_QUESTIONS):
        await send_test_question(message, state, next_question)
    else:
        await finish_test(message, state)

async def send_final_summary(message: Message):
    """
    Отправляет финальное аудио и итоги курса после теста
    """
    # Отправляем финальное аудио (модуль 6)
    final_audio_sent = await AudioManager.send_module_audio(message.chat.id, 5)  # 5 = index 5 = module 6
    
    # Формируем итоги курса
    course_summary = """<b>✅ Итоги курса:</b>

После прохождения вы знаете:
1. Разницу между 44-ФЗ, 223-ФЗ и коммерческими закупками
2. Основные шаги для участия
3. Где искать информацию и тендеры
4. Практический план действий

<b>Ваш следующий шаг — ДЕЙСТВИЕ!</b>

<b>🎯 Теперь ваша очередь действовать! Первый шаг — самый важный!</b>"""
    
    # Отправляем итоги курса
    await message.answer(
        course_summary,
        parse_mode=ParseMode.HTML
    )
    
    # Если аудио не удалось отправить, сообщаем об этом
    if not final_audio_sent:
        await message.answer(
            "🎧 <b>Примечание:</b> Финальное аудио с итогами курса временно недоступно. Вы можете прослушать его позже через меню курса.",
            parse_mode=ParseMode.HTML
        )

async def finish_test(message: Message, state: FSMContext):
    """
    Завершает тест и показывает результаты
    """
    data = await state.get_data()
    test_data = data.get("test_data", {})
    user_id = message.from_user.id
    
    # Вычисляем результаты
    correct_answers = 0
    total_questions = len(TEST_QUESTIONS)
    results = []
    
    for question in TEST_QUESTIONS:
        question_id = question["id"]
        user_answer = test_data.get("answers", {}).get(question_id)
        correct_answer = question["correct"]
        
        is_correct = user_answer == correct_answer
        if is_correct:
            correct_answers += 1
        
        results.append({
            "question_id": question_id,
            "question": question["question"][:50] + "...",
            "user_answer": user_answer,
            "correct_answer": correct_answer,
            "correct_text": question["correct_text"],
            "is_correct": is_correct
        })
    
    # Вычисляем процент
    percentage = (correct_answers / total_questions) * 100 if total_questions > 0 else 0
    
    # Определяем оценку
    if correct_answers >= 1:  # Упрощенная логика для примера
        grade = "Отлично! Вы прекрасно усвоили материал курса и готовы к первым шагам в мире тендеров."
    else:
        grade = "Не переживайте! Вернитесь к материалам экспресс-курса и уделите внимание основам."
    
    # Сохраняем результаты в прогресс пользователя
    if user_id not in user_progress:
        user_progress[user_id] = {}
    
    test_result = {
        "date": datetime.now().isoformat(),
        "correct_answers": correct_answers,
        "total_questions": total_questions,
        "percentage": percentage,
        "grade": grade,
        "results": results
    }
    
    user_progress[user_id]["test_results"] = user_progress[user_id].get("test_results", [])
    user_progress[user_id]["test_results"].append(test_result)
    
    # Формируем текст результатов
    result_text = f"""
<b>🏆 Результаты теста</b>

✅ <b>Правильных ответов:</b> {correct_answers} из {total_questions}
📊 <b>Процент выполнения:</b> {percentage:.1f}%
⭐ <b>Оценка:</b> {correct_answers}/{total_questions}

<b>{grade}</b>

<b>📋 Детальные результаты:</b>
"""
    
    for i, result in enumerate(results, 1):
        status = "✅" if result["is_correct"] else "❌"
        result_text += f"\n{status} <b>Вопрос {i}:</b>"
        result_text += f"\nВаш ответ: <b>{result['user_answer'] if result['user_answer'] else 'нет ответа'}</b>"
        result_text += f"\nПравильный: <b>{result['correct_text']}</b>\n"
    
    result_text += f"\n<b>📅 Дата прохождения:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    result_text += "\n\n<b>🎯 Рекомендации:</b>"
    result_text += "\n• Повторите модули с вопросами, на которые ответили неправильно"
    result_text += "\n• Практикуйтесь на реальных тендерах"
    result_text += "\n• Задавайте вопросы в поддержку"
    
    # Отправляем результаты теста
    await message.answer(
        result_text,
        parse_mode=ParseMode.HTML
    )
    
    # Отправляем финальное аудио и итоги курса
    await send_final_summary(message)
    
    # Сбрасываем состояние теста
    await state.clear()

# ==================== ОСНОВНЫЕ КОМАНДЫ ====================

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """
    Обработчик команды /start
    """
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    username = message.from_user.username or ""
    
    # Проверяем доступ
    has_access, access_type, expiry_date = access_manager.has_access(user_id)
    
    # Инициализируем прогресс пользователя
    if user_id not in user_progress:
        user_progress[user_id] = {
            'start_date': datetime.now().isoformat(),
            'completed_modules': [],
            'last_module': 0,
            'name': user_name,
            'username': username,
            'audio_listened': [],
            'test_results': []
        }
    
    if not has_access:
        # Пользователь без доступа
        welcome_text = f"""
<b>👋 Привет, {user_name}!</b>

Добро пожаловать на <b>Экспресс-курс: "Тендеры с нуля"!</b>

🔒 <b>Для доступа к курсу необходима активация администратором.</b>

<b>💰 Стоимость курса:</b> {ACCESS_CONFIG['price_per_course']} руб. (единоразовый платеж)

<b>📋 Как получить доступ:</b>

1️⃣ <b>Оплатите курс</b>
   Стоимость: {ACCESS_CONFIG['price_per_course']} руб.

2️⃣ <b>Свяжитесь с администратором</b>
   Нажмите /support для связи

3️⃣ <b>Предоставьте информацию</b>
   • Ваш ID: <code>{user_id}</code>
   • Имя: {user_name}
   • Username: @{username if username else 'не указан'}

<b>🎯 Что вы получите:</b>
• 📚 6 модулей с теорией и практикой
• 🎧 Аудио-сопровождение к каждому уроку
• 📝 Практические задания
• 📊 Отслеживание прогресса
• 📝 Финальный тест
• 📥 Готовый чек-лист для работы
• 👨‍💼 Поддержка 24/7

<b>Для связи с администратором нажмите /support</b>
        """
        
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="👨‍💼 Связаться с администратором")],
                [KeyboardButton(text="ℹ️ Узнать мой ID")],
                [KeyboardButton(text="💰 Стоимость курса")]
            ],
            resize_keyboard=True
        )
        
        await message.answer(
            welcome_text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
    else:
        # Пользователь с доступом
        welcome_text = f"""
<b>👋 Добро пожаловать, {user_name}!</b>

✅ <b>Ваш доступ к курсу активен!</b>
<b>Тип доступа:</b> Постоянный

<b>🎯 Особенности курса:</b>
• 📚 6 модулей с теорией и практикой
• 🎧 <b>Аудио-сопровождение к каждому уроку</b>
• 📝 Практические задания
• 📊 Отслеживание прогресса
• <b>📝 Финальный тест</b> для проверки знаний

<b>🎧 Важно!</b> При выборе урока автоматически отправляется аудио-сопровождение в формата MP3.

<b>📝 После завершения всех модулей пройдите финальный тест для проверки знаний!</b>

<b>Используйте кнопки внизу для навигации:</b>
        """
        
        await message.answer(
            welcome_text,
            reply_markup=get_main_keyboard(user_id),
            parse_mode=ParseMode.HTML
        )
    
    await state.clear()

@dp.message(Command("myid"))
async def cmd_myid(message: Message):
    """
    Показать ID пользователя
    """
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    username = message.from_user.username or "не указан"
    
    id_text = f"""
<b>ℹ️ Ваша идентификационная информация:</b>

<b>👤 Имя:</b> {user_name}
<b>🆔 Ваш ID:</b> <code>{user_id}</code>
<b>🔗 Username:</b> @{username}

<b>📋 Для получения доступа:</b>
1. Оплатите курс: {ACCESS_CONFIG['price_per_course']} руб.
2. Свяжитесь с администратором: /support
3. Предоставьте эту информацию администратору

<b>Ваш ID необходим администратору для предоставления доступа.</b>
"""
    
    await message.answer(id_text, parse_mode=ParseMode.HTML)

@dp.message(Command("support"))
async def cmd_support(message: Message):
    """
    Связь с поддержкой/администратором
    """
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "Пользователь"
    username = message.from_user.username or "не указан"
    
    # Получаем информацию о доступе
    has_access, access_type, expiry_date = access_manager.has_access(user_id)
    
    if has_access:
        support_text = f"""
<b>👨‍💼 Служба поддержки</b>

✅ <b>У вас уже есть доступ к курсу!</b>

<b>📞 Контакты поддержки:</b>
Телефон: {ADDITIONAL_MATERIALS['contacts']['phone']}
Мобильный: {ADDITIONAL_MATERIALS['contacts']['mobile']}
Email: {ADDITIONAL_MATERIALS['contacts']['email']}

<b>🕒 Часы работы:</b>
Пн-Пт: 9:00-18:00 по МСК
Сб-Вс: 10:00-16:00 по МСК

<b>📋 По вопросам обучения:</b>
• Непонятные моменты в уроках
• Дополнительные материалы
• Советы по тендерам
• Технические проблемы с ботом

<b>Мы ответим вам в ближайшее время! ⏱</b>
        """
    else:
        support_text = f"""
<b>👨‍💼 Связь с администратором</b>

🔒 <b>У вас нет доступа к курсу</b>

<b>📋 Для получения доступа:</b>

1️⃣ <b>Оплатите курс</b>
   Стоимость: {ACCESS_CONFIG['price_per_course']} руб.

2️⃣ <b>Свяжитесь с администратором</b>
   • Телефон: {ADDITIONAL_MATERIALS['contacts']['phone']}
   • Мобильный: {ADDITIONAL_MATERIALS['contacts']['mobile']}
   • Email: {ADDITIONAL_MATERIALS['contacts']['email']}

3️⃣ <b>Предоставьте информацию:</b>
   • Ваш ID: <code>{user_id}</code>
   • Имя: {user_name}
   • Username: @{username}
   • Дата и сумма оплаты

<b>💰 Способы оплаты:</b>
• Банковский перевод
• Перевод на карту
• Другие способы (уточняйте у администратора)

<b>После оплаты и подтверждения администратор предоставит вам доступ к курсу.</b>

<b>🕒 Администратор работает:</b>
Пн-Пт: 9:00-18:00 по МСК
        """
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="ℹ️ Мой ID")],
            [KeyboardButton(text="💰 Стоимость курса")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )
    
    await message.answer(
        support_text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )

# ==================== АДМИНИСТРАТИВНЫЕ КОМАНДЫ ====================

@dp.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    """
    Административная панель
    """
    user_id = message.from_user.id
    
    if not access_manager.is_admin(user_id):
        await message.answer("❌ У вас нет прав администратора.")
        return
    
    await state.set_state(UserState.admin_menu)
    
    stats = access_manager.get_user_stats()
    
    admin_text = f"""
<b>👑 Административная панель</b>

<b>📊 Статистика:</b>
• Пользователей с доступом: {stats['total_paid']}
• Общий доход: {stats['total_income']} руб.
• Средний доход на пользователя: {stats['avg_income_per_user']:.2f} руб.

<b>🔧 Команды администрирования:</b>
• <code>/grant @username</code> - выдать доступ по username
• <code>/grant_id ID</code> - выдать доступ по ID
• <code>/revoke @username</code> - забрать доступ по username
• <code>/userinfo @username</code> - информация о пользователе
• <code>/broadcast текст</code> - рассылка сообщений

<b>Используйте кнопки ниже для управления:</b>
    """
    
    await message.answer(
        admin_text,
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "👑 Админ панель")
async def handle_admin_panel(message: Message, state: FSMContext):
    """
    Открыть админ панель
    """
    await cmd_admin(message, state)

@dp.message(F.text == "👥 Список пользователей", UserState.admin_menu)
async def handle_admin_users(message: Message):
    """
    Показать список пользователей с доступом
    """
    user_id = message.from_user.id
    
    if not access_manager.is_admin(user_id):
        return
    
    stats = access_manager.get_user_stats()
    
    users_text = f"""
<b>👥 Пользователи с доступом</b>

<b>Всего:</b> {stats['total_paid']}
<b>Общий доход:</b> {stats['total_income']} руб.

<b>📋 Последние 10 пользователей:</b>
"""
    
    # Покажем последних 10 пользователей
    count = 0
    for uid_str, user_data in list(access_manager.paid_users.items())[:10]:
        count += 1
        username = user_data.get('username', 'не указан')
        granted_date = user_data.get('granted_date', 'неизвестно')
        if granted_date != 'неизвестно':
            try:
                granted = datetime.fromisoformat(granted_date)
                granted_date = granted.strftime('%d.%m.%Y')
            except:
                pass
        
        users_text += f"\n{count}. @{username} (ID: {uid_str}) | Выдан: {granted_date}"
    
    if count == 0:
        users_text += "\n\n📭 Пользователей нет"
    
    users_text += "\n\n<b>🔍 Для поиска пользователя:</b>\n<code>/userinfo @username</code>"
    
    await message.answer(users_text, parse_mode=ParseMode.HTML)

@dp.message(F.text == "➕ Выдать доступ", UserState.admin_menu)
async def handle_grant_access(message: Message, state: FSMContext):
    """
    Выдать доступ пользователю
    """
    user_id = message.from_user.id
    
    if not access_manager.is_admin(user_id):
        return
    
    await state.set_state(UserState.admin_grant_access)
    
    await message.answer(
        "➕ <b>Выдача доступа пользователю</b>\n\n"
        "Отправьте username пользователя в формате:\n"
        "<code>@username</code> или <code>username</code>\n\n"
        "<b>Примеры:</b>\n"
        "<code>@ivanov</code>\n"
        "<code>ivanov</code>\n\n"
        "<b>ИЛИ</b>\n\n"
        "Отправьте ID пользователя:\n"
        "<code>id:123456789</code>\n\n"
        "Для отмены нажмите /cancel",
        parse_mode=ParseMode.HTML
    )

@dp.message(UserState.admin_grant_access)
async def process_grant_access(message: Message, state: FSMContext):
    """
    Обработка выдачи доступа
    """
    user_id = message.from_user.id
    
    if not access_manager.is_admin(user_id):
        return
    
    if message.text.lower() == '/cancel':
        await state.clear()
        await message.answer("❌ Выдача доступа отменена.", reply_markup=get_admin_keyboard())
        return
    
    input_text = message.text.strip()
    
    # Проверяем формат ввода
    if input_text.startswith('id:'):
        # Выдача доступа по ID
        try:
            target_user_id = int(input_text[3:].strip())
            
            # Проверяем, есть ли уже доступ
            if str(target_user_id) in access_manager.paid_users:
                await message.answer(
                    f"❌ Пользователь с ID {target_user_id} уже имеет доступ.",
                    reply_markup=get_admin_keyboard(),
                    parse_mode=ParseMode.HTML
                )
                await state.clear()
                return
            
            # Пытаемся получить информацию о пользователе
            try:
                user_chat = await bot.get_chat(target_user_id)
                username = user_chat.username or ""
                user_name = user_chat.first_name or "Пользователь"
            except Exception as e:
                username = ""
                user_name = "Пользователь"
                logger.warning(f"Could not get user info for {target_user_id}: {e}")
            
            # Выдаем доступ
            success = access_manager.grant_access_by_id(target_user_id, user_id, username)
            
            if success:
                await message.answer(
                    f"✅ <b>Доступ успешно выдан!</b>\n\n"
                    f"<b>Пользователь:</b> {user_name}\n"
                    f"<b>ID:</b> {target_user_id}\n"
                    f"<b>Username:</b> @{username if username else 'не указан'}\n"
                    f"<b>Выдал:</b> Администратор\n"
                    f"<b>Дата:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                    f"<b>👤 Уведомление отправлено пользователю.</b>",
                    reply_markup=get_admin_keyboard(),
                    parse_mode=ParseMode.HTML
                )
                
                # Отправляем уведомление пользователю
                try:
                    notification_text = f"""
✅ <b>Вам предоставлен доступ к курсу "Тендеры с нуля"!</b>

Администратор предоставил вам постоянный доступ ко всем материалам курса.

<b>🎯 Что теперь доступно:</b>
• 6 модулей с теорией и практикой
• Аудио сопровождение к каждому уроку
• Практические задания
• Финальный тест
• Чек-лист для скачивания

<b>Нажмите /start для начала обучения!</b>

Приятного обучения! 🚀
                    """
                    await bot.send_message(target_user_id, notification_text, parse_mode=ParseMode.HTML)
                except Exception as e:
                    logger.error(f"Failed to notify user {target_user_id}: {e}")
            else:
                await message.answer(
                    "❌ Не удалось выдать доступ. Попробуйте снова.",
                    reply_markup=get_admin_keyboard(),
                    parse_mode=ParseMode.HTML
                )
            
        except ValueError:
            await message.answer(
                "❌ Неверный формат ID. Используйте: <code>id:123456789</code>",
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.HTML
            )
    
    else:
        # Выдача доступа по username
        username = input_text.replace('@', '').strip()
        
        if not username:
            await message.answer(
                "❌ Неверный формат username. Используйте: <code>@username</code> или <code>username</code>",
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.HTML
            )
            return
        
        await message.answer(
            f"🔍 <b>Поиск пользователя @{username}...</b>\n\n"
            f"Для выдачи доступа по username необходимо знать ID пользователя.\n\n"
            f"<b>Попросите пользователя отправить команду:</b>\n"
            f"<code>/myid</code>\n\n"
            f"Затем выдайте доступ по ID:\n"
            f"<code>id:123456789</code>\n\n"
            f"<b>ИЛИ</b>\n\n"
            f"Попросите пользователя написать боту, затем выдайте доступ через список пользователей.",
            reply_markup=get_admin_keyboard(),
            parse_mode=ParseMode.HTML
        )
    
    await state.clear()

@dp.message(F.text == "➖ Забрать доступ", UserState.admin_menu)
async def handle_revoke_access(message: Message, state: FSMContext):
    """
    Забрать доступ у пользователя
    """
    user_id = message.from_user.id
    
    if not access_manager.is_admin(user_id):
        return
    
    await state.set_state(UserState.admin_revoke_access)
    
    await message.answer(
        "➖ <b>Забрать доступ у пользователя</b>\n\n"
        "Отправьте username пользователя в формате:\n"
        "<code>@username</code> или <code>username</code>\n\n"
        "<b>Примеры:</b>\n"
        "<code>@ivanov</code>\n"
        "<code>ivanov</code>\n\n"
        "<b>ИЛИ</b>\n\n"
        "Отправьте ID пользователя:\n"
        "<code>id:123456789</code>\n\n"
        "Для отмены нажмите /cancel",
        parse_mode=ParseMode.HTML
    )

@dp.message(UserState.admin_revoke_access)
async def process_revoke_access(message: Message, state: FSMContext):
    """
    Обработка отзыва доступа
    """
    user_id = message.from_user.id
    
    if not access_manager.is_admin(user_id):
        return
    
    if message.text.lower() == '/cancel':
        await state.clear()
        await message.answer("❌ Отзыв доступа отменен.", reply_markup=get_admin_keyboard())
        return
    
    input_text = message.text.strip()
    
    # Проверяем формат ввода
    if input_text.startswith('id:'):
        # Отзыв доступа по ID
        try:
            target_user_id = int(input_text[3:].strip())
            
            # Проверяем, есть ли доступ
            if str(target_user_id) not in access_manager.paid_users:
                await message.answer(
                    f"❌ Пользователь с ID {target_user_id} не имеет доступа.",
                    reply_markup=get_admin_keyboard(),
                    parse_mode=ParseMode.HTML
                )
                await state.clear()
                return
            
            # Забираем доступ
            success = access_manager.revoke_access(target_user_id)
            
            if success:
                await message.answer(
                    f"✅ <b>Доступ успешно отозван!</b>\n\n"
                    f"<b>Пользователь:</b> ID {target_user_id}\n"
                    f"<b>Отозвал:</b> Администратор\n"
                    f"<b>Дата:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                    f"<b>👤 Уведомление отправлено пользователю.</b>",
                    reply_markup=get_admin_keyboard(),
                    parse_mode=ParseMode.HTML
                )
                
                # Отправляем уведомление пользователю
                try:
                    notification_text = f"""
❌ <b>Ваш доступ к курсу "Тендеры с нуля" отозван!</b>

Администратор отозвал ваш доступ ко всем материалам курса.

Если это произошло по ошибке, свяжитесь с администратором: /support
                    """
                    await bot.send_message(target_user_id, notification_text, parse_mode=ParseMode.HTML)
                except Exception as e:
                    logger.error(f"Failed to notify user {target_user_id}: {e}")
            else:
                await message.answer(
                    "❌ Не удалось отозвать доступ. Попробуйте снова.",
                    reply_markup=get_admin_keyboard(),
                    parse_mode=ParseMode.HTML
                )
            
        except ValueError:
            await message.answer(
                "❌ Неверный формат ID. Используйте: <code>id:123456789</code>",
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.HTML
            )
    
    else:
        # Отзыв доступа по username
        username = input_text.replace('@', '').strip()
        
        if not username:
            await message.answer(
                "❌ Неверный формат username. Используйте: <code>@username</code> или <code>username</code>",
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.HTML
            )
            return
        
        # Ищем пользователя по username
        user_info = access_manager.get_user_by_username(username)
        
        if not user_info:
            await message.answer(
                f"❌ Пользователь @{username} не найден или не имеет доступа.",
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.HTML
            )
            await state.clear()
            return
        
        # Забираем доступ
        success = access_manager.revoke_access(user_info["user_id"])
        
        if success:
            await message.answer(
                f"✅ <b>Доступ успешно отозван!</b>\n\n"
                f"<b>Пользователь:</b> @{username}\n"
                f"<b>ID:</b> {user_info['user_id']}\n"
                f"<b>Отозвал:</b> Администратор\n"
                f"<b>Дата:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                f"<b>👤 Уведомление отправлено пользователю.</b>",
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.HTML
            )
            
            # Отправляем уведомление пользователю
            try:
                notification_text = f"""
❌ <b>Ваш доступ к курсу "Тендеры с нуля" отозван!</b>

Администратор отозвал ваш доступ ко всем материалам курса.

Если это произошло по ошибке, свяжитесь с администратором: /support
                """
                await bot.send_message(user_info["user_id"], notification_text, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.error(f"Failed to notify user {user_info['user_id']}: {e}")
        else:
            await message.answer(
                "❌ Не удалось отозвать доступ. Попробуйте снова.",
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.HTML
            )
    
    await state.clear()

@dp.message(F.text == "📊 Статистика", UserState.admin_menu)
async def handle_admin_stats(message: Message):
    """
    Детальная статистика
    """
    user_id = message.from_user.id
    
    if not access_manager.is_admin(user_id):
        return
    
    stats = access_manager.get_user_stats()
    
    # Собираем дополнительную статистику
    today = datetime.now().date()
    users_today = 0
    users_this_month = 0
    
    for user_data in access_manager.paid_users.values():
        granted_date_str = user_data.get("granted_date")
        if granted_date_str:
            try:
                granted_date = datetime.fromisoformat(granted_date_str).date()
                if granted_date == today:
                    users_today += 1
                if granted_date.month == today.month and granted_date.year == today.year:
                    users_this_month += 1
            except:
                pass
    
    stats_text = f"""
<b>📊 Детальная статистика</b>

<b>👥 Пользователи:</b>
• Всего с доступом: {stats['total_paid']}
• Добавлено сегодня: {users_today}
• Добавлено в этом месяце: {users_this_month}

<b>💰 Финансы:</b>
• Общий доход: {stats['total_income']} руб.
• Средний доход на пользователя: {stats['avg_income_per_user']:.2f} руб.
• Потенциальный доход (если все заплатят): {stats['total_paid'] * ACCESS_CONFIG['price_per_course']} руб.

<b>📈 Активность:</b>
• Всего пользователей в боте: {len(user_progress)}
• Прошли тест: {sum(1 for uid, data in user_progress.items() if data.get('test_results'))}
• Завершили все модули: {sum(1 for uid, data in user_progress.items() if len(data.get('completed_modules', [])) == len(MODULES))}

<b>📅 Последние 5 пользователей:</b>
"""
    
    # Покажем последних 5 пользователей
    count = 0
    for uid_str, user_data in list(access_manager.paid_users.items())[:5]:
        count += 1
        username = user_data.get('username', 'не указан')
        granted_date = user_data.get('granted_date', 'неизвестно')
        if granted_date != 'неизвестно':
            try:
                granted = datetime.fromisoformat(granted_date)
                granted_date = granted.strftime('%d.%m.%Y')
            except:
                pass
        
        # Проверяем активность
        has_progress = int(uid_str) in user_progress
        modules_completed = len(user_progress.get(int(uid_str), {}).get('completed_modules', [])) if has_progress else 0
        
        stats_text += f"\n{count}. @{username}"
        stats_text += f" | Модулей: {modules_completed}/{len(MODULES)}"
        stats_text += f" | С {granted_date}"
    
    await message.answer(stats_text, parse_mode=ParseMode.HTML)

@dp.message(Command("grant"))
async def cmd_grant(message: Message, command: CommandObject):
    """
    Выдать доступ по username (командная версия)
    """
    user_id = message.from_user.id
    
    if not access_manager.is_admin(user_id):
        await message.answer("❌ У вас нет прав администратора.")
        return
    
    if not command.args:
        await message.answer(
            "Использование: <code>/grant @username</code>\n\n"
            "Пример: <code>/grant @ivanov</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    username = command.args.replace('@', '').strip()
    
    await message.answer(
        f"🔍 <b>Поиск пользователя @{username}...</b>\n\n"
        f"Для выдачи доступа по username необходимо знать ID пользователя.\n\n"
        f"<b>Попросите пользователя отправить команду:</b>\n"
        f"<code>/myid</code>\n\n"
        f"Затем выдайте доступ по ID:\n"
        f"<code>/grant_id ID_пользователя</code>\n\n"
        f"<b>ИЛИ</b>\n\n"
        f"Попросите пользователя написать боту, затем выдайте доступ через админ панель.",
        parse_mode=ParseMode.HTML
    )

@dp.message(Command("grant_id"))
async def cmd_grant_id(message: Message, command: CommandObject):
    """
    Выдать доступ по ID (командная версия)
    """
    user_id = message.from_user.id
    
    if not access_manager.is_admin(user_id):
        await message.answer("❌ У вас нет прав администратора.")
        return
    
    if not command.args:
        await message.answer(
            "Использование: <code>/grant_id ID_пользователя</code>\n\n"
            "Пример: <code>/grant_id 123456789</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    try:
        target_user_id = int(command.args.strip())
        
        # Проверяем, есть ли уже доступ
        if str(target_user_id) in access_manager.paid_users:
            await message.answer(
                f"❌ Пользователь с ID {target_user_id} уже имеет доступ.",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Пытаемся получить информацию о пользователе
        try:
            user_chat = await bot.get_chat(target_user_id)
            username = user_chat.username or ""
            user_name = user_chat.first_name or "Пользователь"
        except Exception as e:
            username = ""
            user_name = "Пользователь"
            logger.warning(f"Could not get user info for {target_user_id}: {e}")
        
        # Выдаем доступ
        success = access_manager.grant_access_by_id(target_user_id, user_id, username)
        
        if success:
            await message.answer(
                f"✅ <b>Доступ успешно выдан!</b>\n\n"
                f"<b>Пользователь:</b> {user_name}\n"
                f"<b>ID:</b> {target_user_id}\n"
                f"<b>Username:</b> @{username if username else 'не указан'}\n"
                f"<b>Выдал:</b> Администратор\n"
                f"<b>Дата:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                f"<b>👤 Уведомление отправлено пользователю.</b>",
                parse_mode=ParseMode.HTML
            )
            
            # Отправляем уведомление пользователю
            try:
                notification_text = f"""
✅ <b>Вам предоставлен доступ к курсу "Тендеры с нуля"!</b>

Администратор предоставил вам постоянный доступ ко всем материалам курса.

<b>🎯 Что теперь доступно:</b>
• 6 модулей с теорией и практикой
• Аудио сопровождение к каждому уроку
• Практические задания
• Финальный тест
• Чек-лист для скачивания

<b>Нажмите /start для начала обучения!</b>

Приятного обучения! 🚀
                """
                await bot.send_message(target_user_id, notification_text, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.error(f"Failed to notify user {target_user_id}: {e}")
        else:
            await message.answer(
                "❌ Не удалось выдать доступ. Попробуйте снова.",
                parse_mode=ParseMode.HTML
            )
        
    except ValueError:
        await message.answer(
            "❌ Неверный формат ID. Используйте: <code>/grant_id 123456789</code>",
            parse_mode=ParseMode.HTML
        )

@dp.message(Command("revoke"))
async def cmd_revoke(message: Message, command: CommandObject):
    """
    Забрать доступ по username (командная версия)
    """
    user_id = message.from_user.id
    
    if not access_manager.is_admin(user_id):
        await message.answer("❌ У вас нет прав администратора.")
        return
    
    if not command.args:
        await message.answer(
            "Использование: <code>/revoke @username</code>\n\n"
            "Пример: <code>/revoke @ivanov</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    username = command.args.replace('@', '').strip()
    
    # Ищем пользователя по username
    user_info = access_manager.get_user_by_username(username)
    
    if not user_info:
        await message.answer(
            f"❌ Пользователь @{username} не найден или не имеет доступа.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Забираем доступ
    success = access_manager.revoke_access(user_info["user_id"])
    
    if success:
        await message.answer(
            f"✅ <b>Доступ успешно отозван!</b>\n\n"
            f"<b>Пользователь:</b> @{username}\n"
            f"<b>ID:</b> {user_info['user_id']}\n"
            f"<b>Отозвал:</b> Администратор\n"
            f"<b>Дата:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"<b>👤 Уведомление отправлено пользователю.</b>",
            parse_mode=ParseMode.HTML
        )
        
        # Отправляем уведомление пользователю
        try:
            notification_text = f"""
❌ <b>Ваш доступ к курсу "Тендеры с нуля" отозван!</b>

Администратор отозвал ваш доступ ко всем материалам курса.

Если это произошло по ошибке, свяжитесь с администратором: /support
            """
            await bot.send_message(user_info["user_id"], notification_text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"Failed to notify user {user_info['user_id']}: {e}")
    else:
        await message.answer(
            "❌ Не удалось отозвать доступ. Попробуйте снова.",
            parse_mode=ParseMode.HTML
        )

@dp.message(Command("userinfo"))
async def cmd_userinfo(message: Message, command: CommandObject):
    """
    Информация о пользователе
    """
    user_id = message.from_user.id
    
    if not access_manager.is_admin(user_id):
        await message.answer("❌ У вас нет прав администратора.")
        return
    
    if not command.args:
        await message.answer(
            "Использование: <code>/userinfo @username</code> или <code>/userinfo id:123456789</code>\n\n"
            "Примеры:\n"
            "<code>/userinfo @ivanov</code>\n"
            "<code>/userinfo id:123456789</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    input_text = command.args.strip()
    
    if input_text.startswith('id:'):
        # Поиск по ID
        try:
            target_user_id = int(input_text[3:].strip())
            user_info = access_manager.get_user_info(target_user_id)
            
            if not user_info.get("has_access"):
                await message.answer(
                    f"❌ Пользователь с ID {target_user_id} не имеет доступа.",
                    parse_mode=ParseMode.HTML
                )
                return
            
            info_text = f"""
<b>👤 Информация о пользователе</b>

<b>ID:</b> {target_user_id}
<b>Доступ:</b> ✅ Есть
<b>Тип доступа:</b> {user_info['access_type']}
<b>Дата выдачи:</b> {user_info.get('granted_date', 'Неизвестно')}
<b>Выдал:</b> {user_info.get('granted_by', 'Неизвестно')}
<b>Username:</b> @{user_info.get('username', 'не указан')}
<b>Цена:</b> {user_info.get('price', ACCESS_CONFIG['price_per_course'])} руб.
"""
            
            # Проверяем прогресс пользователя
            if target_user_id in user_progress:
                progress = user_progress[target_user_id]
                info_text += f"\n<b>📚 Прогресс обучения:</b>"
                info_text += f"\nНачал: {progress.get('start_date', 'Неизвестно')}"
                info_text += f"\nПройдено модулей: {len(progress.get('completed_modules', []))}/{len(MODULES)}"
                info_text += f"\nПройдено тестов: {len(progress.get('test_results', []))}"
                info_text += f"\nПрослушано аудио: {len(progress.get('audio_listened', []))}"
            
            await message.answer(info_text, parse_mode=ParseMode.HTML)
            
        except ValueError:
            await message.answer(
                "❌ Неверный формат ID. Используйте: <code>/userinfo id:123456789</code>",
                parse_mode=ParseMode.HTML
            )
    else:
        # Поиск по username
        username = input_text.replace('@', '').strip()
        user_info = access_manager.get_user_by_username(username)
        
        if not user_info:
            await message.answer(
                f"❌ Пользователь @{username} не найден или не имеет доступа.",
                parse_mode=ParseMode.HTML
            )
            return
        
        info_text = f"""
<b>👤 Информация о пользователе</b>

<b>Username:</b> @{username}
<b>ID:</b> {user_info['user_id']}
<b>Доступ:</b> ✅ Есть
<b>Тип доступа:</b> {user_info.get('access_type', 'paid')}
<b>Дата выдачи:</b> {user_info.get('granted_date', 'Неизвестно')}
<b>Выдал:</b> {user_info.get('granted_by', 'Неизвестно')}
<b>Цена:</b> {user_info.get('price', ACCESS_CONFIG['price_per_course'])} руб.
"""
        
        # Проверяем прогресс пользователя
        if user_info['user_id'] in user_progress:
            progress = user_progress[user_info['user_id']]
            info_text += f"\n<b>📚 Прогресс обучения:</b>"
            info_text += f"\nНачал: {progress.get('start_date', 'Неизвестно')}"
            info_text += f"\nПройдено модулей: {len(progress.get('completed_modules', []))}/{len(MODULES)}"
            info_text += f"\nПройдено тестов: {len(progress.get('test_results', []))}"
            info_text += f"\nПрослушано аудио: {len(progress.get('audio_listened', []))}"
        
        await message.answer(info_text, parse_mode=ParseMode.HTML)

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message, command: CommandObject):
    """
    Рассылка сообщений пользователям
    """
    user_id = message.from_user.id
    
    if not access_manager.is_admin(user_id):
        await message.answer("❌ У вас нет прав администратора.")
        return
    
    if not command.args:
        await message.answer(
            "📢 <b>Рассылка сообщений</b>\n\n"
            "Использование: <code>/broadcast текст_сообщения</code>\n\n"
            "<b>Пример:</b>\n"
            "<code>/broadcast Всем привет! Новое обновление курса!</code>\n\n"
            "<b>⚠️ Будьте осторожны! Сообщение будет отправлено всем пользователям с доступом.</b>",
            parse_mode=ParseMode.HTML
        )
        return
    
    broadcast_text = command.args
    total_users = len(access_manager.paid_users)
    sent = 0
    failed = 0
    
    # Отправляем подтверждение
    await message.answer(
        f"📢 <b>Начинаю рассылку...</b>\n\n"
        f"Получателей: {total_users}\n"
        f"Текст: {broadcast_text[:100]}...\n\n"
        f"<i>Это займет некоторое время...</i>",
        parse_mode=ParseMode.HTML
    )
    
    # Рассылка пользователям с доступом
    for user_id_str in access_manager.paid_users.keys():
        try:
            await bot.send_message(int(user_id_str), broadcast_text, parse_mode=ParseMode.HTML)
            sent += 1
            await asyncio.sleep(0.1)  # Чтобы не превысить лимиты Telegram
        except Exception as e:
            failed += 1
            logger.error(f"Failed to send broadcast to {user_id_str}: {e}")
    
    # Отправляем отчет
    await message.answer(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📊 <b>Результаты:</b>\n"
        f"• Всего получателей: {total_users}\n"
        f"• Успешно отправлено: {sent}\n"
        f"• Не удалось отправить: {failed}\n"
        f"• Процент доставки: {sent/total_users*100:.1f}% если total_users > 0 else 0%\n\n"
        f"<i>Пользователи, которые заблокировали бота или удалили его, не получили сообщение.</i>",
        parse_mode=ParseMode.HTML
    )

# ==================== ОСНОВНЫЕ ОБРАБОТЧИКИ ====================

# Обработчик скачивания чек-листа
@dp.message(F.text == "📥 Скачать чек-лист")
async def handle_download_checklist(message: Message):
    """
    Обработчик кнопки "📥 Скачать чек-лист"
    """
    try:
        # Проверяем доступ
        user_id = message.from_user.id
        has_access, access_type, expiry_date = access_manager.has_access(user_id)
        if not has_access:
            await message.answer("У вас нет доступа к чек-листу. Для получения доступа свяжитесь с администратором: /support")
            return
        
        # Путь к файлу чек-листа
        checklist_path = "Чек-лист -Первые 10 шагов в тендерах-.docx"
        
        if not os.path.exists(checklist_path):
            # Если файла нет локально
            await message.answer(
                "❌ Файл чек-листа временно недоступен.\n\n"
                "Вы можете использовать текстовую версию чек-листа из 6 модуля курса.",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Отправляем файл как документ
        document = FSInputFile(checklist_path)
        
        caption = """✅ <b>Чек-лист "Первые 10 шагов в тендерах"</b>

📋 <b>Что внутри:</b>
• Пошаговый план для старта в течение недели
• 10 практических шагов от анализа до первой заявки
• Конкретные инструкции и ссылки
• Полезные советы для новичков

💡 <b>Рекомендации:</b>
1. Сохраните файл на устройство
2. Распечатайте или держите открытым на экране
3. Отмечайте выполненные шаги
4. Не пытайтесь сделать все за один день!

<b>У вас все получится! Этот чек-лист — ваш надежный проводник в мире тендеров.</b>"""
        
        await message.answer_document(
            document=document,
            caption=caption,
            parse_mode=ParseMode.HTML
        )
        
        logger.info(f"Checklist sent to user {message.from_user.id}")
        
    except Exception as e:
        logger.error(f"Error sending checklist: {e}")
        await message.answer(
            "❌ Произошла ошибка при отправке файла.\n"
            "Попробуйте позже или используйте текстовую версию из 6 модуля.",
            parse_mode=ParseMode.HTML
        )

# Обработчики кнопок главного меню
@dp.message(F.text == "📚 Меню курса")
async def handle_course_menu(message: Message):
    """
    Показывает меню курса со списком уроков
    """
    lessons_text = "<b>📚 Выберите урок для изучения:</b>\n\n"
    
    for i, module in enumerate(MODULES, 1):
        audio_icon = "🎧 " if module.get("has_audio", False) else ""
        lessons_text += f"{module['emoji']} {audio_icon}<b>День {module['day']}:</b> {module['title']}\n"
        
        # Проверяем прогресс
        user_id = message.from_user.id
        if user_id in user_progress:
            if i in user_progress[user_id].get('completed_modules', []):
                lessons_text += "   ✅ Пройден\n"
            else:
                lessons_text += "   ⏳ Не пройден\n"
        
        lessons_text += "\n"
    
    await message.answer(
        lessons_text,
        reply_markup=get_lessons_list_keyboard(),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "🎧 Аудио уроки")
async def handle_audio_lessons(message: Message):
    """
    Показывает все доступные аудио-уроки
    """
    audio_list = "<b>🎧 Все аудио-уроки курса:</b>\n\n"
    
    for i, module in enumerate(MODULES, 1):
        audio_info = AudioManager.get_audio_info(i-1)
        if audio_info.get("exists"):
            duration_min = audio_info['duration'] // 60
            duration_sec = audio_info['duration'] % 60
            audio_list += f"🎧 <b>День {module['day']}:</b> {module['title']}\n"
            audio_list += f"   ⏱ {duration_min}:{duration_sec:02d}\n"
            audio_list += f"   📝 {audio_info['title']}\n\n"
    
    if audio_list == "<b>🎧 Все аудио-уроки курса:</b>\n\n":
        audio_list += "❌ Аудио-уроки пока не добавлены"
    else:
        audio_list += "<i>Аудио автоматически отправляется при выборе урока</i>"
    
    await message.answer(
        audio_list,
        reply_markup=get_main_keyboard(message.from_user.id),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "📊 Мой прогресс")
async def handle_my_progress(message: Message):
    """
    Показывает прогресс пользователя
    """
    user_id = message.from_user.id
    
    if user_id not in user_progress:
        await message.answer(
            "❌ Вы еще не начали обучение.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    progress = user_progress[user_id]
    completed = len(progress.get('completed_modules', []))
    total = len(MODULES)
    percentage = (completed / total) * 100 if total > 0 else 0
    
    # Аудио статистика
    audio_listened = len(progress.get('audio_listened', []))
    audio_total = sum(1 for module in MODULES if module.get("has_audio", False))
    audio_percentage = (audio_listened / audio_total * 100) if audio_total > 0 else 0
    
    # Статистика тестов
    test_results = progress.get('test_results', [])
    last_test = test_results[-1] if test_results else None
    
    progress_text = f"""
<b>📊 Ваш прогресс в курсе:</b>

👤 <b>Имя:</b> {progress.get('name', 'Не указано')}
📅 <b>Дата начала:</b> {progress['start_date'][:10]}
🎯 <b>Последний урок:</b> {progress.get('last_module', 0) + 1}/{total}

<b>Статистика:</b>
✅ <b>Пройдено уроков:</b> {completed}/{total} ({percentage:.1f}%)
🎧 <b>Прослушано аудио:</b> {audio_listened}/{audio_total} ({audio_percentage:.1f}%)
📝 <b>Пройдено тестов:</b> {len(test_results)}
"""
    
    if last_test:
        progress_text += f"🏆 <b>Последний тест:</b> {last_test['correct_answers']}/{last_test['total_questions']} ({last_test['percentage']:.1f}%)\n"
    
    progress_text += "\n<b>Статус уроков:</b>\n"
    
    for i in range(1, total + 1):
        module = MODULES[i-1]
        if i in progress.get('completed_modules', []):
            audio_icon = "🎧" if i in progress.get('audio_listened', []) else ""
            progress_text += f"✅ {audio_icon} День {module['day']}: {module['title'][:25]}\n"
        else:
            progress_text += f"⏳ День {module['day']}: {module['title'][:25]}\n"
    
    # Проверяем, пройдены ли все модули
    all_modules_completed = completed == total
    
    if all_modules_completed:
        if len(test_results) == 0:
            progress_text += "\n🎉 <b>Все модули пройдены! Вы готовы к тесту!</b>"
            progress_text += "\n📝 <b>Нажмите '📝 Пройти тест' для проверки знаний.</b>"
        else:
            best_result = max(test_results, key=lambda x: x['percentage'])
            progress_text += f"\n🏆 <b>Лучший результат теста:</b> {best_result['correct_answers']}/{best_result['total_questions']} ({best_result['percentage']:.1f}%)"
    else:
        progress_text += f"\n\n⚠️ <b>Для доступа к тесту необходимо пройти все модули.</b>"
        progress_text += f"\n✅ <b>Вы можете отметить все модули как пройденные кнопкой ниже.</b>"
        
        # Добавляем клавиатуру с быстрыми действиями
        quick_actions = ReplyKeyboardMarkup(
            keyboard=[
                [
                    KeyboardButton(text="✅ Отметить все модули как пройденные"),
                    KeyboardButton(text="📥 Скачать чек-лист")
                ],
                [
                    KeyboardButton(text="📚 Меню курса"),
                    KeyboardButton(text="📝 Пройти тест все равно")
                ]
            ],
            resize_keyboard=True
        )
        
        await message.answer(
            progress_text,
            reply_markup=quick_actions,
            parse_mode=ParseMode.HTML
        )
        return
    
    progress_text += "\n<b>Продолжайте обучение! 💪</b>"
    
    await message.answer(
        progress_text,
        reply_markup=get_main_keyboard(user_id),
        parse_mode=ParseMode.HTML
    )

# Обработчик выбора урока из списка
@dp.message(F.text.startswith(("📚", "🏛️", "🏢", "💼", "🚀", "🏆")))
async def handle_lesson_selection(message: Message, state: FSMContext):
    """
    Обработчик выбора урока из списка
    """
    try:
        # Ищем модуль по тексту кнопки
        for i, module in enumerate(MODULES):
            audio_icon = "🎧 " if module.get("has_audio", False) else ""
            button_text = f"{module['emoji']} {audio_icon}День {module['day']}: {module['title'][:20]}"
            
            if message.text.startswith(module['emoji']) or button_text in message.text:
                await show_module(message, i, state)
                return
        
        # Если урок не найден
        await message.answer(
            "❌ Урок не найден. Выберите урок из списка.",
            reply_markup=get_lessons_list_keyboard()
        )
    except Exception as e:
        logger.error(f"Lesson selection error: {e}")
        await message.answer(
            "❌ Ошибка выбора урока. Попробуйте снова.",
            reply_markup=get_main_keyboard()
        )

# Обработчики кнопок навигации в уроке
@dp.message(F.text == "⬅️ Предыдущий урок")
async def handle_prev_lesson(message: Message, state: FSMContext):
    """
    Переход к предыдущему уроку
    """
    data = await state.get_data()
    current_module = data.get("current_module", 0)
    
    if current_module > 0:
        await show_module(message, current_module - 1, state)
    else:
        await message.answer(
            "❌ Это первый урок. Предыдущего урока нет.",
            reply_markup=get_lesson_navigation_keyboard(current_module, len(MODULES))
        )

@dp.message(F.text == "Следующий урок ➡️")
async def handle_next_lesson(message: Message, state: FSMContext):
    """
    Переход к следующему уроку
    """
    data = await state.get_data()
    current_module = data.get("current_module", 0)
    
    if current_module < len(MODULES) - 1:
        await show_module(message, current_module + 1, state)
    else:
        await message.answer(
            "✅ Это последний урок курса! Поздравляем с завершением!\n\n"
            "📝 <b>Теперь вы можете пройти финальный тест для проверки знаний!</b>\n"
            "Нажмите кнопку '📝 Пройти тест' в главном меню.",
            reply_markup=get_lesson_navigation_keyboard(current_module, len(MODULES)),
            parse_mode=ParseMode.HTML
        )

@dp.message(F.text == "🎧 Прослушать аудио")
async def handle_listen_audio(message: Message, state: FSMContext):
    """
    Повторное прослушивание аудио к текущему уроку
    """
    data = await state.get_data()
    current_module = data.get("current_module", 0)
    
    if current_module is not None:
        audio_sent = await AudioManager.send_module_audio(message.chat.id, current_module)
        
        if audio_sent:
            # Отмечаем аудио как прослушанное
            user_id = message.from_user.id
            if user_id in user_progress:
                if current_module + 1 not in user_progress[user_id].get('audio_listened', []):
                    user_progress[user_id].setdefault('audio_listened', []).append(current_module + 1)
            
            await message.answer(
                "🎧 Аудио отправлено!",
                reply_markup=get_lesson_navigation_keyboard(current_module, len(MODULES))
            )
        else:
            await message.answer(
                "❌ Аудио временно недоступно. Попробуйте позже.",
                reply_markup=get_lesson_navigation_keyboard(current_module, len(MODULES))
            )
    else:
        await message.answer(
            "❌ Вы не находитесь в уроке. Выберите урок из меню.",
            reply_markup=get_main_keyboard()
        )

@dp.message(F.text == "✅ Отметить пройденным")
async def handle_complete_lesson(message: Message, state: FSMContext):
    """
    Отметка текущего урока как пройденного
    """
    data = await state.get_data()
    current_module = data.get("current_module", 0)
    user_id = message.from_user.id
    
    if current_module is not None:
        if user_id not in user_progress:
            user_progress[user_id] = {
                'start_date': datetime.now().isoformat(),
                'completed_modules': [],
                'last_module': current_module,
                'name': message.from_user.first_name,
                'username': message.from_user.username or "",
                'audio_listened': [],
                'test_results': []
            }
        
        module_num = current_module + 1
        if module_num not in user_progress[user_id]['completed_modules']:
            user_progress[user_id]['completed_modules'].append(module_num)
            await message.answer(
                f"✅ Урок {module_num} отмечен как пройденный!",
                reply_markup=get_lesson_navigation_keyboard(current_module, len(MODULES))
            )
            
            # Проверяем, пройдены ли все модули
            completed = len(user_progress[user_id]['completed_modules'])
            total = len(MODULES)
            
            if completed == total:
                await message.answer(
                    "🎉 <b>Поздравляем! Вы завершили все модули курса!</b>\n\n"
                    "📝 <b>Теперь вы можете пройти финальный тест:</b>\n"
                    "1. Проверить свои знания\n"
                    "2. Получить оценку\n"
                    "3. Увидеть рекомендации по улучшению\n\n"
                    "Нажмите кнопку '📝 Пройти тест' в главном меню!",
                    reply_markup=get_main_keyboard(user_id),
                    parse_mode=ParseMode.HTML
                )
        else:
            await message.answer(
                "ℹ️ Этот урок уже отмечен как пройденный",
                reply_markup=get_lesson_navigation_keyboard(current_module, len(MODULES))
            )
    else:
        await message.answer(
            "❌ Вы не находитесь в уроке. Выберите урок из меню.",
            reply_markup=get_main_keyboard()
        )

# Обработчики для теста
@dp.message(F.text == "📝 Пройти тест")
async def handle_start_test(message: Message, state: FSMContext):
    """
    Запускает тестирование
    """
    user_id = message.from_user.id
    
    # Проверяем доступ
    has_access, access_type, expiry_date = access_manager.has_access(user_id)
    if not has_access:
        await message.answer("У вас нет доступа к тесту. Для получения доступа свяжитесь с администратором: /support")
        return
    
    # Проверяем, прошел ли пользователь все модули
    if user_id in user_progress:
        completed = len(user_progress[user_id].get('completed_modules', []))
        total = len(MODULES)
        
        if completed < total:
            # Создаем клавиатуру с опциями
            keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [
                        KeyboardButton(text="✅ Отметить все модули как пройденные"),
                        KeyboardButton(text="📝 Пройти тест все равно")
                    ],
                    [
                        KeyboardButton(text="📚 Вернуться к обучению"),
                        KeyboardButton(text="📊 Мой прогресс")
                    ]
                ],
                resize_keyboard=True
            )
            
            await message.answer(
                f"⚠️ <b>Внимание!</b>\n\n"
                f"Вы прошли {completed} из {total} модулей.\n\n"
                f"<b>Рекомендуемые варианты:</b>\n"
                f"1️⃣ <b>Продолжить обучение</b> - завершить все модули\n"
                f"2️⃣ <b>Отметить все модули</b> - если вы уже изучили материал\n"
                f"3️⃣ <b>Пройти тест все равно</b> - начать тест сейчас\n\n"
                f"<i>Для успешного прохождения теста рекомендуется завершить все модули.</i>",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
            return
    
    # Если все модули пройдены или пользователь выбрал "Пройти тест все равно"
    await start_test_internal(message, state)

# Обработчики ответов на тест
@dp.message(F.text.in_({"а", "б", "в", "г"}), UserState.taking_test)
async def handle_test_answer(message: Message, state: FSMContext):
    """
    Обрабатывает ответ на вопрос теста
    """
    await process_test_answer(message, state, message.text)

@dp.message(F.text == "⏭ Пропустить", UserState.taking_test)
async def handle_skip_question(message: Message, state: FSMContext):
    """
    Пропускает текущий вопрос
    """
    data = await state.get_data()
    test_data = data.get("test_data", {})
    current_question = test_data.get("current_question", 0)
    
    # Переходим к следующему вопросу
    next_question = current_question + 1
    
    if next_question < len(TEST_QUESTIONS):
        await message.answer(
            f"⏭ Вопрос {current_question + 1} пропущен.",
            parse_mode=ParseMode.HTML
        )
        await send_test_question(message, state, next_question)
    else:
        await finish_test(message, state)

@dp.message(F.text == "🏁 Завершить тест", UserState.taking_test)
async def handle_finish_test_early(message: Message, state: FSMContext):
    """
    Завершает тест досрочно
    """
    await message.answer(
        "📝 <b>Тест завершен досрочно.</b>\n\n"
        "Вы можете пройти тест снова в любое время.",
        parse_mode=ParseMode.HTML
    )
    await finish_test(message, state)

@dp.message(F.text == "✅ Отметить все модули")
async def handle_mark_all_modules(message: Message):
    """
    Обработчик кнопки "Отметить все модули" из главного меню
    """
    user_id = message.from_user.id
    
    if user_id not in user_progress:
        user_progress[user_id] = {
            'start_date': datetime.now().isoformat(),
            'completed_modules': [],
            'last_module': 0,
            'name': message.from_user.first_name,
            'username': message.from_user.username or "",
            'audio_listened': [],
            'test_results': []
        }
    
    # Отмечаем все модули как пройденные
    user_progress[user_id]['completed_modules'] = list(range(1, len(MODULES) + 1))
    
    # Отмечаем все аудио как прослушанные
    for i in range(1, len(MODULES) + 1):
        if i not in user_progress[user_id].get('audio_listened', []):
            user_progress[user_id].setdefault('audio_listened', []).append(i)
    
    await message.answer(
        f"✅ Все {len(MODULES)} модуля отмечены как пройденные!\n\n"
        "🎉 Теперь вы можете пройти финальный тест.\n"
        "Нажмите кнопку '📝 Пройти тест' для начала тестирования.",
        reply_markup=get_main_keyboard(user_id),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "🏆 Результаты теста")
async def handle_test_results(message: Message):
    """
    Показывает результаты тестов пользователя
    """
    user_id = message.from_user.id
    
    if user_id not in user_progress:
        await message.answer(
            "❌ Вы еще не проходили тестирование.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    test_results = user_progress[user_id].get('test_results', [])
    
    if not test_results:
        await message.answer(
            "📝 <b>У вас еще нет результатов тестирования.</b>\n\n"
            "Пройти тест можно после изучения всех модулей курса.\n"
            "Нажмите кнопку '📝 Пройти тест' для начала.",
            reply_markup=get_main_keyboard(user_id),
            parse_mode=ParseMode.HTML
        )
        return
    
    # Показываем последний результат
    last_test = test_results[-1]
    
    result_text = f"""
<b>🏆 Результаты последнего теста:</b>

📅 <b>Дата:</b> {datetime.fromisoformat(last_test['date']).strftime('%d.%m.%Y %H:%M')}
✅ <b>Правильных ответов:</b> {last_test['correct_answers']} из {last_test['total_questions']}
📊 <b>Процент выполнения:</b> {last_test['percentage']:.1f}%
⭐ <b>Оценка:</b> {last_test['correct_answers']}/{last_test['total_questions']}

<b>📋 Детальные результаты:</b>
"""
    
    for i, result in enumerate(last_test['results'], 1):
        status = "✅" if result["is_correct"] else "❌"
        result_text += f"\n{status} <b>Вопрос {i}:</b>"
        result_text += f"\nВаш ответ: <b>{result['user_answer'] if result['user_answer'] else 'нет ответа'}</b>"
        result_text += f"\nПравильный: <b>{result['correct_text']}</b>\n"
    
    # Показываем историю
    if len(test_results) > 1:
        result_text += f"\n<b>📊 История тестов:</b> {len(test_results)} попыток"
        for i, test in enumerate(test_results[-5:], 1):  # Последние 5 попыток
            date_str = datetime.fromisoformat(test['date']).strftime('%d.%m')
            result_text += f"\n{i}. {date_str}: {test['correct_answers']}/{test['total_questions']} ({test['percentage']:.1f}%)"
    
    result_text += "\n\n<b>🎯 Совет:</b> Для улучшения результатов повторите модули с ошибками."
    
    await message.answer(
        result_text,
        reply_markup=get_main_keyboard(user_id),
        parse_mode=ParseMode.HTML
    )

# Обработчики возврата в меню
@dp.message(F.text == "🔙 Назад в главное меню")
async def handle_back_to_main(message: Message):
    """
    Возврат в главное меню
    """
    user_id = message.from_user.id
    await message.answer(
        "<b>📋 Главное меню:</b>\n\nВы вернулись в главное меню.",
        reply_markup=get_main_keyboard(user_id),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "🔙 Главное меню")
async def handle_back_to_main_from_test(message: Message):
    """
    Возврат в главное меню из результатов теста
    """
    user_id = message.from_user.id
    await message.answer(
        "<b>📋 Главное меню:</b>\n\nВы вернулись в главное меню.",
        reply_markup=get_main_keyboard(user_id),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "🔙 Назад")
async def handle_back(message: Message):
    """
    Возврат назад
    """
    user_id = message.from_user.id
    await message.answer(
        "Возвращаюсь...",
        reply_markup=get_main_keyboard(user_id)
    )

# Обработчик команды /help
@dp.message(Command("help"))
async def cmd_help(message: Message):
    """
    Обработчик команды /help
    """
    user_id = message.from_user.id
    help_text = """
<b>🆘 Справка по использованию бота:</b>

<b>🎧 Аудио сопровождение:</b>
• При выборе урока автоматически отправляется аудио-пояснение
• Для повторного прослушивания нажмите "🎧 Прослушать аудио"

<b>📚 Навигация по курсу:</b>
• <b>📚 Меню курса</b> - список всех уроков
• В уроке используйте кнопки "⬅️ Предыдущий урок" и "Следующий урок ➡️"
• "✅ Отметить пройденным" - отмечайте пройденные уроки

<b>📝 Финальный тест:</b>
• <b>📝 Пройти тест</b> - запуск финального теста
• Выберите вариант ответа (а, б, в, г)
• Можно пропустить вопрос
• Результаты сохраняются

<b>📥 Скачивание чек-листа:</b>
• <b>📥 Скачать чек-лист</b> - скачать готовый чек-лист

<b>📊 Отслеживание прогресса:</b>
• В "📊 Моем прогрессе" видна статистика

<b>🔒 Получение доступа:</b>
• Доступ предоставляется администратором
• Для получения доступа нажмите /support
• Узнайте свой ID: /myid

<b>📞 Контакты поддержки:</b>
• Телефон: +7(4922)223-222
• Email: info@tritika.ru
    """
    
    await message.answer(
        help_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard(user_id)
    )

@dp.message(Command("contacts"))
async def cmd_contacts(message: Message):
    """
    Показывает контактную информацию
    """
    contacts_text = f"""
<b>📞 Контакты для связи:</b>

📧 <b>Email:</b> {ADDITIONAL_MATERIALS['contacts']['email']}
📱 <b>Телефон:</b> {ADDITIONAL_MATERIALS['contacts']['phone']}
📲 <b>Мобильный:</b> {ADDITIONAL_MATERIALS['contacts']['mobile']}

🌐 <b>Сайт:</b> https://tritika.ru

<b>📅 Часы работы поддержки:</b>
Пн-Пт: 9:00-18:00 по МСК
Сб-Вс: выходной

<b>✉️ Пишите нам по любым вопросам:</b>
• Получение доступа к курсу
• Технические проблемы с ботом
• Вопросы по курсу
• Консультации по тендерам
    """
    
    await message.answer(
        contacts_text,
        reply_markup=get_main_keyboard(message.from_user.id),
        parse_mode=ParseMode.HTML
    )

# Обработчик всех остальных сообщений
@dp.message()
async def handle_other_messages(message: Message):
    """
    Обработчик всех прочих сообщений
    """
    if message.content_type == ContentType.TEXT:
        user_id = message.from_user.id
        
        # Проверяем, является ли это ответом на кнопки доступа
        if message.text == "👨‍💼 Связаться с администратором":
            await cmd_support(message)
        elif message.text == "ℹ️ Узнать мой ID":
            await cmd_myid(message)
        elif message.text == "💰 Стоимость курса":
            await message.answer(
                f"💰 <b>Стоимость курса:</b> {ACCESS_CONFIG['price_per_course']} руб.\n\n"
                f"Для получения доступа свяжитесь с администратором: /support",
                parse_mode=ParseMode.HTML
            )
        elif message.text == "✅ Отметить все модули как пройденные":
            await handle_mark_all_modules(message)
        elif message.text == "📝 Пройти тест все равно":
            await start_test_internal(message, dp.current_state(user=user_id))
        elif message.text == "📚 Вернуться к обучению":
            await handle_course_menu(message)
        else:
            # Если сообщение не обработано другими хендлерами
            await message.answer(
                "🤖 Я бот для обучения тендерам с аудио сопровождением!\n\n"
                "Используйте кнопки внизу для навигации или команды:\n"
                "/start - Начать работу с ботом\n"
                "/myid - Узнать свой ID\n"
                "/support - Связаться с администратором\n"
                "/help - Помощь\n\n"
                "🔒 <b>Доступ к курсу предоставляется администратором после оплаты.</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_keyboard(user_id)
            )

# ==================== ФУНКЦИИ ДЛЯ ЗАПУСКА ====================

# Функция проверки аудио файлов при запуске
async def check_audio_files():
    """
    Проверяет наличие всех аудио файлов при запуске бота
    """
    logger.info("Проверяем аудио файлы...")
    
    missing_files = []
    
    for i, module in enumerate(MODULES):
        audio_file = module.get("audio_file")
        if audio_file:
            audio_path = os.path.join(AUDIO_CONFIG["base_path"], audio_file)
            if os.path.exists(audio_path):
                file_size = os.path.getsize(audio_path) / (1024 * 1024)  # в МБ
                logger.info(f"✓ Аудио для урока {i+1}: {audio_file} ({file_size:.2f} МБ)")
            else:
                logger.warning(f"✗ Аудио для урока {i+1} не найдено: {audio_file}")
                missing_files.append((i+1, audio_file))
        else:
            logger.warning(f"✗ Урок {i+1} не имеет указанного аудио файла")
    
    if missing_files:
        logger.error(f"Отсутствуют аудио файлы: {missing_files}")
    else:
        logger.info("✓ Все аудио файлы на месте")
    
    return len(missing_files) == 0

# Функция проверки файла чек-листа
async def check_checklist_file():
    """
    Проверяет наличие файла чек-листа
    """
    checklist_path = "Чек-лист -Первые 10 шагов в тендерах-.docx"
    
    if os.path.exists(checklist_path):
        file_size = os.path.getsize(checklist_path) / 1024  # в КБ
        logger.info(f"✓ Чек-лист найден: {checklist_path} ({file_size:.1f} КБ)")
        return True
    else:
        logger.warning(f"✗ Чек-лист не найден: {checklist_path}")
        logger.warning("Кнопка '📥 Скачать чек-лист' будет недоступна")
        return False

# HTTP сервер для мониторинга
async def health_check(request):
    """Обработчик для health check"""
    stats = access_manager.get_user_stats()
    
    return web.json_response({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "paid_users": stats["total_paid"],
        "total_income": stats["total_income"],
        "modules": len(MODULES),
        "restarts": restart_count,
        "checklist_available": os.path.exists("Чек-лист -Первые 10 шагов в тендерах-.docx"),
        "admin_count": len(ACCESS_CONFIG["admin_ids"])
    })

async def start_http_server():
    """Запуск HTTP сервера для мониторинга"""
    app = web.Application()
    app.router.add_get('/health', health_check)
    app.router.add_get('/', lambda request: web.Response(text="Telegram Bot with Admin Access System is running!"))
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    
    logger.info(f"HTTP сервер запущен на порту {PORT}")
    return runner

# Функция для запуска бота с повторными попытками
async def run_bot_with_retries():
    """
    Запускает бота с повторными попытками при сбоях
    """
    global bot_instance, dp_instance, shutdown_flag, restart_count
    
    bot_instance = bot
    dp_instance = dp
    
    while not shutdown_flag and restart_count < max_restarts:
        try:
            logger.info(f"🚀 Запуск бота (попытка {restart_count + 1}/{max_restarts})...")
            logger.info(f"Порт для HTTP: {PORT}")
            
            # Проверяем аудио файлы
            await check_audio_files()
            
            # Проверяем файл чек-листа
            checklist_available = await check_checklist_file()
            
            # Запускаем HTTP сервер
            http_runner = await start_http_server()
            
            # Проверяем токен и подключаемся к Telegram
            try:
                bot_info = await bot.get_me()
                logger.info(f"✅ Бот запущен: @{bot_info.username} (ID: {bot_info.id})")
                logger.info(f"✅ Система доступа: Только через администратора")
                logger.info(f"✅ Администраторов: {len(ACCESS_CONFIG['admin_ids'])}")
                logger.info(f"✅ Пользователей с доступом: {len(access_manager.paid_users)}")
                logger.info(f"✅ Стоимость курса: {ACCESS_CONFIG['price_per_course']} руб.")
                logger.info(f"✅ Аудио сопровождение: {sum(1 for m in MODULES if m.get('has_audio'))}/{len(MODULES)} уроков")
                logger.info(f"✅ Чек-лист доступен: {'Да' if checklist_available else 'Нет'}")
                logger.info(f"✅ HTTP сервер запущен на порту {PORT}")
            except Exception as e:
                logger.error(f"❌ Не удалось подключиться к Telegram API: {e}")
                logger.error("Проверьте ваш BOT_TOKEN и подключение к интернету")
                restart_count += 1
                if not shutdown_flag:
                    logger.info(f"⏳ Повторная попытка через {restart_delay} секунд...")
                    await asyncio.sleep(restart_delay)
                continue
            
            # Запускаем поллинг с обработкой ошибок
            try:
                logger.info("🔄 Начинаем polling...")
                await dp.start_polling(bot, skip_updates=True)
            except asyncio.CancelledError:
                logger.info("✅ Polling отменен (graceful shutdown)")
                break
            except Exception as e:
                logger.error(f"❌ Ошибка polling: {e}")
                logger.error(f"Трассировка ошибки: {traceback.format_exc()}")
                
                restart_count += 1
                if not shutdown_flag and restart_count < max_restarts:
                    logger.info(f"🔄 Перезапуск через {restart_delay} секунд (попытка {restart_count}/{max_restarts})...")
                    await asyncio.sleep(restart_delay)
                else:
                    logger.error(f"❌ Достигнут лимит перезапусков ({max_restarts}). Бот остановлен.")
                    break
                    
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка в основном цикле: {e}")
            logger.error(f"Трассировка ошибки: {traceback.format_exc()}")
            
            restart_count += 1
            if not shutdown_flag and restart_count < max_restarts:
                logger.info(f"🔄 Перезапуск через {restart_delay * 2} секунд (попытка {restart_count}/{max_restarts})...")
                await asyncio.sleep(restart_delay * 2)
            else:
                logger.error(f"❌ Достигнут лимит перезапусков ({max_restarts}). Бот остановлен.")
                break
    
    logger.info("🛑 Бот окончательно остановлен.")
    
    # Сохраняем данные
    access_manager.save_data("paid_users", access_manager.paid_users)
    
    # Закрываем сессию
    try:
        await bot.session.close()
        logger.info("✅ Сессия бота закрыта")
    except:
        pass

# Основная функция запуска с обработкой ошибок
async def main():
    """
    Основная функция запуска бота с обработкой ошибок и graceful shutdown
    """
    global shutdown_flag
    
    # Создаем задачу для запуска бота
    bot_task = asyncio.create_task(run_bot_with_retries())
    
    try:
        # Ждем завершения задачи
        await bot_task
    except KeyboardInterrupt:
        logger.info("✅ Получен KeyboardInterrupt, инициируем shutdown...")
        shutdown_flag = True
        await shutdown()
    except Exception as e:
        logger.error(f"❌ Необработанное исключение в main: {e}")
        logger.error(f"Трассировка ошибки: {traceback.format_exc()}")
    finally:
        # Гарантируем корректное завершение
        if not bot_task.done():
            bot_task.cancel()
            try:
                await bot_task
            except asyncio.CancelledError:
                pass

# Точка входа с обработкой исключений
if __name__ == "__main__":
    try:
        # Выводим информацию о запуске
        print("=" * 60)
        print("🤖 Бот обучения тендерам с доступом через администратора")
        print("=" * 60)
        print(f"📅 Время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🔄 Максимальное количество перезапусков: {max_restarts}")
        print(f"💰 Стоимость курса: {ACCESS_CONFIG['price_per_course']} руб.")
        print(f"👑 Администраторов: {len(ACCESS_CONFIG['admin_ids'])}")
        print(f"👥 Пользователей с доступом: {len(access_manager.paid_users)}")
        print(f"📚 Количество модулей: {len(MODULES)}")
        print(f"🎧 Аудио файлов: {sum(1 for m in MODULES if m.get('has_audio'))}")
        print(f"📝 Вопросов в тесте: {len(TEST_QUESTIONS)}")
        print(f"📥 Чек-лист: {'Присутствует' if os.path.exists('Чек-лист -Первые 10 шагов в тендерах-.docx') else 'Отсутствует'}")
        print(f"🌐 HTTP порт: {PORT}")
        print("=" * 60)
        print("Основные команды:")
        print("/start - Начать работу с ботом")
        print("/myid - Узнать свой ID")
        print("/support - Связаться с администратором")
        print("/help - Помощь")
        print("=" * 60)
        print("Команды администратора:")
        print("/admin - Админ панель")
        print("/grant @username - Выдать доступ")
        print("/grant_id ID - Выдать доступ по ID")
        print("/revoke @username - Забрать доступ")
        print("/userinfo @username - Информация о пользователе")
        print("/broadcast текст - Рассылка")
        print("=" * 60)
        
        # Запускаем основную функцию
        asyncio.run(main())
        
    except KeyboardInterrupt:
        print("\n\n✅ Бот остановлен пользователем (Ctrl+C)")
        logger.info("Бот остановлен пользователем (KeyboardInterrupt)")
    except Exception as e:
        print(f"\n\n❌ Критическая ошибка: {e}")
        logger.error(f"Критическая ошибка при запуске: {e}")
        logger.error(f"Трассировка ошибки: {traceback.format_exc()}")
        sys.exit(1)
