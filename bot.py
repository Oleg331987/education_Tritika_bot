import os
import sys
import logging
import asyncio
import signal
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import json
import traceback

import aiohttp
from aiohttp import web

# Импорты aiogram
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ContentType
from aiogram.filters.state import StateFilter

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
    "admin_ids": [],  # Заполняется из env
    "price_per_course": 2990,  # рублей за полный курс
}

# Файлы для хранения данных
DATA_FILES = {
    "paid_users": "paid_users.json",
}

# Класс для управления доступом
class AccessManager:
    """Менеджер доступа к боту"""
    
    def __init__(self):
        self.paid_users = self.load_data("paid_users")
        
        # Загружаем admin_ids из переменных окружения
        admin_ids_str = os.getenv('ADMIN_IDS', '')
        if admin_ids_str:
            try:
                ACCESS_CONFIG["admin_ids"] = [int(id.strip()) for id in admin_ids_str.split(',') if id.strip().isdigit()]
                logger.info(f"Загружены ID администраторов: {ACCESS_CONFIG['admin_ids']}")
            except Exception as e:
                logger.error(f"Ошибка загрузки ADMIN_IDS: {e}")
    
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
    
    def has_access(self, user_id: int) -> Tuple[bool, str]:
        """
        Проверить доступ пользователя
        
        Returns:
            Tuple[has_access, access_type]
        """
        user_id_str = str(user_id)
        
        # Проверка администратора
        if self.is_admin(user_id):
            return True, "admin"
        
        # Проверка платного доступа
        if user_id_str in self.paid_users:
            return True, "paid"
        
        return False, "none"
    
    def grant_access_by_id(self, user_id: int, admin_id: int, username: str = "") -> bool:
        """Предоставить доступ пользователю по ID"""
        user_id_str = str(user_id)
        
        if user_id_str in self.paid_users:
            return False
        
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
        total_income = sum(user_data.get("price", 0) for user_data in self.paid_users.values())
        
        return {
            "total_paid": total_paid,
            "total_income": total_income,
            "avg_income_per_user": total_income / total_paid if total_paid > 0 else 0
        }
    
    def get_user_info(self, user_id: int) -> Dict:
        """Получить информацию о пользователе"""
        user_id_str = str(user_id)
        has_access, access_type = self.has_access(user_id)
        
        info = {
            "user_id": user_id,
            "has_access": has_access,
            "access_type": access_type,
        }
        
        if user_id_str in self.paid_users:
            info.update(self.paid_users[user_id_str])
        
        return info

# Инициализация менеджера доступа
access_manager = AccessManager()

# Проверка токена бота
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    logger.error("BOT_TOKEN не установлен! Установите переменную окружения.")
    sys.exit(1)

# Инициализация бота
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
    taking_test = State()
    admin_menu = State()
    admin_grant_access = State()
    admin_revoke_access = State()

# Данные курса с аудио
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

# Тестовые вопросы
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
        "question": "Основное отличие закупок по 223-ФЗ от закупок по 44-FZ заключается в том, что:",
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

# ==================== МИДЛВАРЬ ДЛЯ ПРОВЕРКИ ДОСТУПА ====================

async def check_access_middleware(handler, event, data):
    """Проверка доступа пользователя"""
    if hasattr(event, 'message'):
        message = event.message
    elif hasattr(event, 'callback_query'):
        message = event.call_query.message
    else:
        return await handler(event, data)
    
    user_id = message.from_user.id
    
    # Проверяем, является ли пользователь администратором
    if access_manager.is_admin(user_id):
        return await handler(event, data)
    
    # Команды, доступные без проверки доступа
    allowed_commands = ['start', 'help', 'support', 'contacts', 'myid', 'admin']
    
    # Получаем команду из сообщения
    command = None
    if hasattr(message, 'text') and message.text:
        if message.text.startswith('/'):
            command = message.text.split(' ')[0][1:].split('@')[0]
    
    # Разрешаем доступ к определенным командам без проверки
    if command in allowed_commands:
        return await handler(event, data)
    
    # Проверяем доступ к контенту
    has_access, access_type = access_manager.has_access(user_id)
    
    if not has_access:
        # Формируем сообщение о необходимости доступа
        access_message = f"""
🔒 <b>Доступ ограничен</b>

Для получения доступа к курсу необходимо связаться с администратором.

<b>📋 Как получить доступ:</b>

1️⃣ <b>Оплатить курс</b>
   Стоимость полного курса: <b>{ACCESS_CONFIG['price_per_course']} руб.</b>

2️⃣ <b>Связаться с администратором</b>
   Нажмите /support для связи

3️⃣ <b>Предоставить информацию</b>
   • Ваш ID: <code>{user_id}</code>
   • Имя в Telegram
   • Username (если есть)

<b>Для связи с администратором нажмите /support</b>
        """
        
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="👨‍💼 Связаться с администратором")],
                [KeyboardButton(text="ℹ️ Узнать мой ID")],
                [KeyboardButton(text="💰 Стоимость курса")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        try:
            await message.answer(access_message, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения о доступе: {e}")
        
        return
    
    return await handler(event, data)

# Применяем мидлварь
dp.message.middleware(check_access_middleware)

# ==================== ФИКСИРОВАННЫЕ КЛАВИАТУРЫ ====================

def get_main_keyboard(user_id: int = None) -> ReplyKeyboardMarkup:
    """
    Создает фиксированную клавиатуру, которая всегда показывается внизу
    с учетом прав доступа
    """
    is_admin = access_manager.is_admin(user_id) if user_id else False
    
    if is_admin:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [
                    KeyboardButton(text="👑 Админ панель"),
                    KeyboardButton(text="📊 Статистика"),
                ],
                [
                    KeyboardButton(text="📚 Меню курса"),
                    KeyboardButton(text="🎧 Аудио уроки"),
                ],
                [
                    KeyboardButton(text="📊 Мой прогресс"),
                    KeyboardButton(text="📞 Контакты"),
                ],
                [
                    KeyboardButton(text="🔗 Полезные ссылки"),
                    KeyboardButton(text="🆘 Помощь"),
                ],
                [
                    KeyboardButton(text="📝 Пройти тест"),
                    KeyboardButton(text="🏆 Результаты теста")
                ],
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
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [
                    KeyboardButton(text="📚 Меню курса"),
                    KeyboardButton(text="🎧 Аудио уроки"),
                ],
                [
                    KeyboardButton(text="📊 Мой прогресс"),
                    KeyboardButton(text="📞 Контакты"),
                ],
                [
                    KeyboardButton(text="🔗 Полезные ссылки"),
                    KeyboardButton(text="🆘 Помощь"),
                ],
                [
                    KeyboardButton(text="📝 Пройти тест"),
                    KeyboardButton(text="🏆 Результаты теста")
                ],
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

def get_lesson_navigation_keyboard(current_index: int, total_modules: int) -> ReplyKeyboardMarkup:
    """
    Создает клавиатуру для навигации по урокам
    """
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="⬅️ Предыдущий урок"),
                KeyboardButton(text=f"📖 {current_index+1}/{total_modules}"),
                KeyboardButton(text="Следующий урок ➡️"),
            ],
            [
                KeyboardButton(text="🎧 Прослушать аудио"),
                KeyboardButton(text="✅ Отметить пройденным"),
            ],
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

def get_test_keyboard(question_num: int, total_questions: int) -> ReplyKeyboardMarkup:
    """
    Создает клавиатуру для прохождения теста
    """
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="а"),
                KeyboardButton(text="б"),
            ],
            [
                KeyboardButton(text="в"),
                KeyboardButton(text="г"),
            ],
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

def get_lessons_list_keyboard() -> ReplyKeyboardMarkup:
    """
    Создает клавиатуру со списком всех уроков
    """
    keyboard_rows = []
    
    for module in MODULES:
        audio_icon = "🎧 " if module.get("has_audio", False) else ""
        keyboard_rows.append([
            KeyboardButton(text=f"{module['emoji']} {audio_icon}День {module['day']}: {module['title'][:20]}")
        ])
    
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

# ==================== ОСНОВНЫЕ КОМАНДЫ ====================

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """
    Обработчик команды /start
    """
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    username = message.from_user.username or ""
    
    await state.clear()
    
    has_access, access_type = access_manager.has_access(user_id)
    
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
    
    has_access, access_type = access_manager.has_access(user_id)
    
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
async def handle_admin_panel_button(message: Message, state: FSMContext):
    """
    Обработчик кнопки "Админ панель"
    """
    user_id = message.from_user.id
    
    if not access_manager.is_admin(user_id):
        await message.answer("❌ У вас нет прав администратора.")
        return
    
    await cmd_admin(message, state)

@dp.message(F.text == "👥 Список пользователей")
async def handle_admin_users(message: Message, state: FSMContext):
    """
    Показать список пользователей с доступом
    """
    user_id = message.from_user.id
    
    current_state = await state.get_state()
    if current_state != UserState.admin_menu:
        await message.answer("Сначала откройте админ панель: /admin")
        return
    
    if not access_manager.is_admin(user_id):
        return
    
    stats = access_manager.get_user_stats()
    
    users_text = f"""
<b>👥 Пользователи с доступом</b>

<b>Всего:</b> {stats['total_paid']}
<b>Общий доход:</b> {stats['total_income']} руб.

<b>📋 Последние 10 пользователей:</b>
"""
    
    count = 0
    paid_users_list = list(access_manager.paid_users.items())
    
    if not paid_users_list:
        users_text += "\n\n📭 Пользователей с доступом нет"
    else:
        for uid_str, user_data in paid_users_list[:10]:
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
    
    users_text += "\n\n<b>🔍 Для поиска пользователя:</b>\n<code>/userinfo @username</code>"
    
    await message.answer(users_text, parse_mode=ParseMode.HTML)

@dp.message(F.text == "📊 Статистика")
async def handle_admin_stats(message: Message, state: FSMContext):
    """
    Детальная статистика
    """
    user_id = message.from_user.id
    
    current_state = await state.get_state()
    if current_state != UserState.admin_menu:
        await message.answer("Сначала откройте админ панель: /admin")
        return
    
    if not access_manager.is_admin(user_id):
        return
    
    stats = access_manager.get_user_stats()
    
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
"""
    
    count = 0
    paid_users_list = list(access_manager.paid_users.items())
    
    if paid_users_list:
        stats_text += "\n\n<b>📅 Последние 5 пользователей:</b>"
        
        for uid_str, user_data in paid_users_list[:5]:
            count += 1
            username = user_data.get('username', 'не указан')
            granted_date = user_data.get('granted_date', 'неизвестно')
            if granted_date != 'неизвестно':
                try:
                    granted = datetime.fromisoformat(granted_date)
                    granted_date = granted.strftime('%d.%m.%Y')
                except:
                    pass
            
            has_progress = int(uid_str) in user_progress
            modules_completed = len(user_progress.get(int(uid_str), {}).get('completed_modules', [])) if has_progress else 0
            
            stats_text += f"\n{count}. @{username}"
            stats_text += f" | Модулей: {modules_completed}/{len(MODULES)}"
            stats_text += f" | С {granted_date}"
    
    await message.answer(stats_text, parse_mode=ParseMode.HTML)

@dp.message(F.text == "➕ Выдать доступ")
async def handle_grant_access_button(message: Message, state: FSMContext):
    """
    Выдать доступ пользователю
    """
    user_id = message.from_user.id
    
    current_state = await state.get_state()
    if current_state != UserState.admin_menu:
        await message.answer("Сначала откройте админ панель: /admin")
        return
    
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

@dp.message(StateFilter(UserState.admin_grant_access))
async def process_grant_access(message: Message, state: FSMContext):
    """
    Обработка выдачи доступа
    """
    user_id = message.from_user.id
    
    if not access_manager.is_admin(user_id):
        return
    
    if message.text.lower() == '/cancel':
        await state.set_state(UserState.admin_menu)
        await message.answer("❌ Выдача доступа отменена.", reply_markup=get_admin_keyboard())
        return
    
    input_text = message.text.strip()
    
    if input_text.startswith('id:'):
        try:
            target_user_id = int(input_text[3:].strip())
            
            if str(target_user_id) in access_manager.paid_users:
                await message.answer(
                    f"❌ Пользователь с ID {target_user_id} уже имеет доступ.",
                    reply_markup=get_admin_keyboard(),
                    parse_mode=ParseMode.HTML
                )
                await state.set_state(UserState.admin_menu)
                return
            
            try:
                user_chat = await bot.get_chat(target_user_id)
                username = user_chat.username or ""
                user_name = user_chat.first_name or "Пользователь"
            except Exception as e:
                username = ""
                user_name = "Пользователь"
                logger.warning(f"Не удалось получить информацию о пользователе {target_user_id}: {e}")
            
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
                    logger.error(f"Не удалось отправить уведомление пользователю {target_user_id}: {e}")
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
    
    await state.set_state(UserState.admin_menu)

@dp.message(F.text == "➖ Забрать доступ")
async def handle_revoke_access_button(message: Message, state: FSMContext):
    """
    Забрать доступ у пользователя
    """
    user_id = message.from_user.id
    
    current_state = await state.get_state()
    if current_state != UserState.admin_menu:
        await message.answer("Сначала откройте админ панель: /admin")
        return
    
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

@dp.message(StateFilter(UserState.admin_revoke_access))
async def process_revoke_access(message: Message, state: FSMContext):
    """
    Обработка отзыва доступа
    """
    user_id = message.from_user.id
    
    if not access_manager.is_admin(user_id):
        return
    
    if message.text.lower() == '/cancel':
        await state.set_state(UserState.admin_menu)
        await message.answer("❌ Отзыв доступа отменен.", reply_markup=get_admin_keyboard())
        return
    
    input_text = message.text.strip()
    
    if input_text.startswith('id:'):
        try:
            target_user_id = int(input_text[3:].strip())
            
            if str(target_user_id) not in access_manager.paid_users:
                await message.answer(
                    f"❌ Пользователь с ID {target_user_id} не имеет доступа.",
                    reply_markup=get_admin_keyboard(),
                    parse_mode=ParseMode.HTML
                )
                await state.set_state(UserState.admin_menu)
                return
            
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
                
                try:
                    notification_text = f"""
❌ <b>Ваш доступ к курсу "Тендеры с нуля" отозван!</b>

Администратор отозвал ваш доступ ко всем материалам курса.

Если это произошло по ошибке, свяжитесь с администратором: /support
                    """
                    await bot.send_message(target_user_id, notification_text, parse_mode=ParseMode.HTML)
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление пользователю {target_user_id}: {e}")
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
        username = input_text.replace('@', '').strip()
        
        if not username:
            await message.answer(
                "❌ Неверный формат username. Используйте: <code>@username</code> или <code>username</code>",
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.HTML
            )
            await state.set_state(UserState.admin_menu)
            return
        
        user_info = access_manager.get_user_by_username(username)
        
        if not user_info:
            await message.answer(
                f"❌ Пользователь @{username} не найден или не имеет доступа.",
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.HTML
            )
            await state.set_state(UserState.admin_menu)
            return
        
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
            
            try:
                notification_text = f"""
❌ <b>Ваш доступ к курсу "Тендеры с нуля" отозван!</b>

Администратор отозвал ваш доступ ко всем материалам курса.

Если это произошло по ошибке, свяжитесь с администратором: /support
                """
                await bot.send_message(user_info["user_id"], notification_text, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление пользователю {user_info['user_id']}: {e}")
        else:
            await message.answer(
                "❌ Не удалось отозвать доступ. Попробуйте снова.",
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.HTML
            )
    
    await state.set_state(UserState.admin_menu)

@dp.message(F.text == "🔙 Главное меню")
async def handle_back_to_main_menu(message: Message, state: FSMContext):
    """
    Возврат в главное меню из админ панели
    """
    user_id = message.from_user.id
    
    await state.clear()
    
    has_access, access_type = access_manager.has_access(user_id)
    
    if has_access:
        await message.answer(
            "<b>📋 Главное меню:</b>\n\nВы вернулись в главное меню.",
            reply_markup=get_main_keyboard(user_id),
            parse_mode=ParseMode.HTML
        )
    else:
        await cmd_start(message, state)

# ==================== КОМАНДНЫЕ АДМИН КОМАНДЫ ====================

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
        
        if str(target_user_id) in access_manager.paid_users:
            await message.answer(
                f"❌ Пользователь с ID {target_user_id} уже имеет доступ.",
                parse_mode=ParseMode.HTML
            )
            return
        
        try:
            user_chat = await bot.get_chat(target_user_id)
            username = user_chat.username or ""
            user_name = user_chat.first_name or "Пользователь"
        except Exception as e:
            username = ""
            user_name = "Пользователь"
            logger.warning(f"Не удалось получить информацию о пользователе {target_user_id}: {e}")
        
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
                logger.error(f"Не удалось отправить уведомление пользователю {target_user_id}: {e}")
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
    
    await message.answer(
        f"📢 <b>Начинаю рассылку...</b>\n\n"
        f"Получателей: {total_users}\n"
        f"Текст: {broadcast_text[:100]}...\n\n"
        f"<i>Это займет некоторое время...</i>",
        parse_mode=ParseMode.HTML
    )
    
    for user_id_str in access_manager.paid_users.keys():
        try:
            await bot.send_message(int(user_id_str), broadcast_text, parse_mode=ParseMode.HTML)
            sent += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            failed += 1
            logger.error(f"Failed to send broadcast to {user_id_str}: {e}")
    
    await message.answer(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📊 <b>Результаты:</b>\n"
        f"• Всего получателей: {total_users}\n"
        f"• Успешно отправлено: {sent}\n"
        f"• Не удалось отправить: {failed}\n"
        f"• Процент доставки: {(sent/total_users*100) if total_users > 0 else 0:.1f}%\n\n"
        f"<i>Пользователи, которые заблокировали бота или удалили его, не получили сообщение.</i>",
        parse_mode=ParseMode.HTML
    )

# ==================== ФУНКЦИИ ОБУЧЕНИЯ ====================

@dp.message(F.text == "📚 Меню курса")
async def handle_course_menu(message: Message):
    """
    Показывает меню курса со списком уроков
    """
    lessons_text = "<b>📚 Выберите урок для изучения:</b>\n\n"
    
    for i, module in enumerate(MODULES, 1):
        audio_icon = "🎧 " if module.get("has_audio", False) else ""
        lessons_text += f"{module['emoji']} {audio_icon}<b>День {module['day']}:</b> {module['title']}\n"
        
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

@dp.message(F.text.startswith(("📚", "🏛️", "🏢", "💼", "🚀", "🏆")))
async def handle_lesson_selection(message: Message, state: FSMContext):
    """
    Обработчик выбора урока из списка
    """
    try:
        for i, module in enumerate(MODULES):
            audio_icon = "🎧 " if module.get("has_audio", False) else ""
            button_text = f"{module['emoji']} {audio_icon}День {module['day']}: {module['title'][:20]}"
            
            if message.text.startswith(module['emoji']) or button_text in message.text:
                await show_module(message, i, state)
                return
        
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

async def show_module(message: Message, module_index: int, state: FSMContext):
    """
    Показывает выбранный модуль
    """
    user_id = message.from_user.id
    has_access, access_type = access_manager.has_access(user_id)
    if not has_access:
        await message.answer("У вас нет доступа к этому модулю. Для получения доступа свяжитесь с администратором: /support")
        return
    
    module = MODULES[module_index]
    
    await state.set_state(UserState.viewing_module)
    await state.update_data(current_module=module_index)
    
    if user_id in user_progress:
        user_progress[user_id]['last_module'] = module_index
    
    module_text = f"{module['content']}\n\n"
    module_text += f"<b>📝 Практическое задание:</b> {module['task']}"
    
    is_completed = False
    if user_id in user_progress:
        is_completed = (module_index + 1) in user_progress[user_id].get('completed_modules', [])
    
    if not is_completed:
        module_text += "\n\n✅ <b>Не забудьте отметить модуль как пройденный после изучения!</b>"
    
    await message.answer(
        module_text,
        reply_markup=get_lesson_navigation_keyboard(module_index, len(MODULES)),
        parse_mode=ParseMode.HTML
    )

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
    
    audio_listened = len(progress.get('audio_listened', []))
    audio_total = sum(1 for module in MODULES if module.get("has_audio", False))
    audio_percentage = (audio_listened / audio_total * 100) if audio_total > 0 else 0
    
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

@dp.message(F.text == "✅ Отметить все модули")
async def handle_mark_all_modules(message: Message):
    """
    Обработчик кнопки "Отметить все модули"
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
    
    user_progress[user_id]['completed_modules'] = list(range(1, len(MODULES) + 1))
    
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

# ==================== ОСТАЛЬНЫЕ ОБРАБОТЧИКИ ====================

@dp.message()
async def handle_other_messages(message: Message, state: FSMContext):
    """
    Обработчик всех прочих сообщений
    """
    if message.content_type == ContentType.TEXT:
        user_id = message.from_user.id
        
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
            await start_test_internal(message, state)
        elif message.text == "📚 Вернуться к обучению":
            await handle_course_menu(message)
        else:
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

async def start_test_internal(message: Message, state: FSMContext):
    """
    Внутренняя функция запуска теста
    """
    user_id = message.from_user.id
    has_access, access_type = access_manager.has_access(user_id)
    if not has_access:
        await message.answer("У вас нет доступа к тесту. Для получения доступа свяжитесь с администратором: /support")
        return
    
    test_data = {
        "current_question": 0,
        "answers": {},
        "start_time": datetime.now().isoformat(),
        "completed": False,
        "skipped": []
    }
    
    await state.set_state(UserState.taking_test)
    await state.update_data(test_data=test_data)
    
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
    
    question_text = f"<b>📝 Вопрос {question_index + 1} из {len(TEST_QUESTIONS)}</b>\n\n"
    question_text += f"{question['question']}\n\n"
    
    for option_key, option_text in question["options"].items():
        question_text += f"<b>{option_key})</b> {option_text}\n"
    
    question_text += "\n<i>Выберите вариант ответа (а, б, в, г)</i>"
    
    test_data["current_question"] = question_index
    await state.update_data(test_data=test_data)
    
    await message.answer(
        question_text,
        reply_markup=get_test_keyboard(question_index + 1, len(TEST_QUESTIONS)),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text.in_(['а', 'б', 'в', 'г', '⏭ Пропустить', '🏁 Завершить тест']))
async def handle_test_answer(message: Message, state: FSMContext):
    """
    Обработчик ответов на вопросы теста
    """
    data = await state.get_data()
    test_data = data.get("test_data", {})
    current_question = test_data.get("current_question", 0)
    
    if message.text == '🏁 Завершить тест':
        await finish_test(message, state)
        return
    elif message.text == '⏭ Пропустить':
        # Пропускаем вопрос
        if 'skipped' not in test_data:
            test_data['skipped'] = []
        test_data['skipped'].append(current_question + 1)
    elif message.text in ['а', 'б', 'в', 'г']:
        # Сохраняем ответ
        if 'answers' not in test_data:
            test_data['answers'] = {}
        
        question = TEST_QUESTIONS[current_question]
        test_data['answers'][question["id"]] = message.text
    
    # Переходим к следующему вопросу
    test_data['current_question'] += 1
    await state.update_data(test_data=test_data)
    
    if test_data['current_question'] < len(TEST_QUESTIONS):
        await send_test_question(message, state, test_data['current_question'])
    else:
        await finish_test(message, state)

async def finish_test(message: Message, state: FSMContext):
    """
    Завершает тест и показывает результаты
    """
    data = await state.get_data()
    test_data = data.get("test_data", {})
    user_id = message.from_user.id
    
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
    
    percentage = (correct_answers / total_questions) * 100 if total_questions > 0 else 0
    
    if correct_answers >= 1:
        grade = "Отлично! Вы прекрасно усвоили материал курса и готовы к первым шагам в мире тендеров."
    else:
        grade = "Не переживайте! Вернитесь к материалам экспресс-курса и уделите внимание основам."
    
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
    
    await message.answer(
        result_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard(user_id)
    )
    
    await state.clear()

# ==================== WEB SERVER FOR RENDER.COM ====================

async def web_handler(request):
    """Обработчик для веб-сервера Render.com"""
    return web.Response(text="🤖 Бот обучения тендерам работает!")

async def start_web_server():
    """Запуск веб-сервера для Render.com"""
    app = web.Application()
    app.router.add_get('/', web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"Веб-сервер запущен на порту {PORT}")
    return runner

# ==================== ОБРАБОТЧИКИ СИГНАЛОВ ====================

def signal_handler(sig, frame):
    """Обработчик сигналов для graceful shutdown"""
    global shutdown_flag
    logger.info(f"Получен сигнал {sig}, инициируется graceful shutdown...")
    shutdown_flag = True

async def shutdown():
    """Корректное завершение работы бота"""
    logger.info("Начинаем graceful shutdown...")
    
    try:
        access_manager.save_data("paid_users", access_manager.paid_users)
        
        if dp_instance:
            await dp_instance.stop_polling()
            logger.info("Polling успешно остановлен")
        
        if bot_instance:
            await bot_instance.session.close()
            logger.info("Сессия бота успешно закрыта")
            
    except Exception as e:
        logger.error(f"Ошибка при завершении: {e}")
    finally:
        logger.info("Shutdown завершен")

# ==================== ФУНКЦИИ ДЛЯ ЗАПУСКА ====================

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
            
            try:
                bot_info = await bot.get_me()
                logger.info(f"✅ Бот запущен: @{bot_info.username} (ID: {bot_info.id})")
                logger.info(f"✅ Система доступа: Только через администратора")
                logger.info(f"✅ Администраторов: {len(ACCESS_CONFIG['admin_ids'])}")
                logger.info(f"✅ ID администраторов: {ACCESS_CONFIG['admin_ids']}")
                logger.info(f"✅ Пользователей с доступом: {len(access_manager.paid_users)}")
                logger.info(f"✅ Стоимость курса: {ACCESS_CONFIG['price_per_course']} руб.")
            except Exception as e:
                logger.error(f"❌ Не удалось подключиться к Telegram API: {e}")
                restart_count += 1
                if not shutdown_flag:
                    logger.info(f"⏳ Повторная попытка через {restart_delay} секунд...")
                    await asyncio.sleep(restart_delay)
                continue
            
            try:
                logger.info("🔄 Начинаем polling...")
                await dp.start_polling(bot, skip_updates=True)
            except asyncio.CancelledError:
                logger.info("✅ Polling отменен (graceful shutdown)")
                break
            except Exception as e:
                logger.error(f"❌ Ошибка polling: {e}")
                restart_count += 1
                if not shutdown_flag and restart_count < max_restarts:
                    logger.info(f"🔄 Перезапуск через {restart_delay} секунд (попытка {restart_count}/{max_restarts})...")
                    await asyncio.sleep(restart_delay)
                else:
                    logger.error(f"❌ Достигнут лимит перезапусков ({max_restarts}). Бот остановлен.")
                    break
                    
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка в основном цикле: {e}")
            restart_count += 1
            if not shutdown_flag and restart_count < max_restarts:
                logger.info(f"🔄 Перезапуск через {restart_delay * 2} секунд (попытка {restart_count}/{max_restarts})...")
                await asyncio.sleep(restart_delay * 2)
            else:
                logger.error(f"❌ Достигнут лимит перезапусков ({max_restarts}). Бот остановлен.")
                break
    
    logger.info("🛑 Бот окончательно остановлен.")
    
    access_manager.save_data("paid_users", access_manager.paid_users)
    
    try:
        await bot.session.close()
        logger.info("✅ Сессия бота закрыта")
    except:
        pass

async def main():
    """
    Основная функция запуска бота
    """
    global shutdown_flag
    
    # Устанавливаем обработчики сигналов
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Запускаем веб-сервер для Render.com
    runner = await start_web_server()
    
    # Запускаем бота в фоне
    bot_task = asyncio.create_task(run_bot_with_retries())
    
    try:
        # Ждем завершения задачи бота или сигнала завершения
        await bot_task
    except asyncio.CancelledError:
        logger.info("Задача бота отменена")
    except Exception as e:
        logger.error(f"Задача бота завершилась с ошибкой: {e}")
    finally:
        # Останавливаем веб-сервер
        await runner.cleanup()
        logger.info("Веб-сервер остановлен")
        
        # Вызываем shutdown для бота
        await shutdown()

if __name__ == "__main__":
    try:
        print("=" * 60)
        print("🤖 Бот обучения тендерам с доступом через администратора")
        print("=" * 60)
        print(f"💰 Стоимость курса: {ACCESS_CONFIG['price_per_course']} руб.")
        print(f"👑 Администраторов: {len(ACCESS_CONFIG['admin_ids'])}")
        print(f"👥 Пользователей с доступом: {len(access_manager.paid_users)}")
        print(f"🌐 Веб-сервер на порту: {PORT}")
        print("=" * 60)
        print("Основные команды:")
        print("/start - Начать работу с ботом")
        print("/myid - Узнать свой ID")
        print("/support - Связаться с администратором")
        print("/admin - Админ панель (только для админов)")
        print("=" * 60)
        
        asyncio.run(main())
        
    except KeyboardInterrupt:
        print("\n\n✅ Бот остановлен пользователем (Ctrl+C)")
    except Exception as e:
        print(f"\n\n❌ Критическая ошибка: {e}")
        traceback.print_exc()
        sys.exit(1)
