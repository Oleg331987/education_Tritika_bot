import os
import sys
import logging
import asyncio
import signal
import time
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Set
import traceback
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

# =========== СИСТЕМА ДОСТУПА И АДМИНИСТРИРОВАНИЯ ===========
class AccessControl:
    """Класс для управления доступом и администраторами"""
    
    def __init__(self):
        self.admins_file = "admins.json"
        self.paid_users_file = "paid_users.json"
        self.admins: Set[int] = set()
        self.paid_users: Set[int] = set()
        self.load_data()
    
    def load_data(self):
        """Загружает данные об администраторах и оплативших пользователях"""
        try:
            # Загружаем администраторов
            if os.path.exists(self.admins_file):
                with open(self.admins_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.admins = set(data.get("admins", []))
                    logger.info(f"Загружено {len(self.admins)} администраторов")
            
            # Загружаем оплативших пользователей
            if os.path.exists(self.paid_users_file):
                with open(self.paid_users_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.paid_users = set(data.get("paid_users", []))
                    logger.info(f"Загружено {len(self.paid_users)} оплативших пользователей")
                    
        except Exception as e:
            logger.error(f"Ошибка загрузки данных доступа: {e}")
            self.admins = set()
            self.paid_users = set()
    
    def save_admins(self):
        """Сохраняет список администраторов"""
        try:
            with open(self.admins_file, 'w', encoding='utf-8') as f:
                json.dump({"admins": list(self.admins)}, f, ensure_ascii=False, indent=2)
            logger.info(f"Сохранено {len(self.admins)} администраторов")
        except Exception as e:
            logger.error(f"Ошибка сохранения администраторов: {e}")
    
    def save_paid_users(self):
        """Сохраняет список оплативших пользователей"""
        try:
            with open(self.paid_users_file, 'w', encoding='utf-8') as f:
                json.dump({"paid_users": list(self.paid_users)}, f, ensure_ascii=False, indent=2)
            logger.info(f"Сохранено {len(self.paid_users)} оплативших пользователей")
        except Exception as e:
            logger.error(f"Ошибка сохранения оплативших пользователей: {e}")
    
    def is_admin(self, user_id: int) -> bool:
        """Проверяет, является ли пользователь администратором"""
        return user_id in self.admins
    
    def is_paid_user(self, user_id: int) -> bool:
        """Проверяет, есть ли у пользователя доступ"""
        return user_id in self.paid_users or user_id in self.admins
    
    def add_admin(self, user_id: int) -> bool:
        """Добавляет администратора"""
        if user_id not in self.admins:
            self.admins.add(user_id)
            self.save_admins()
            return True
        return False
    
    def remove_admin(self, user_id: int) -> bool:
        """Удаляет администратора"""
        if user_id in self.admins:
            self.admins.remove(user_id)
            self.save_admins()
            return True
        return False
    
    def add_paid_user(self, user_id: int) -> bool:
        """Добавляет оплатившего пользователя"""
        if user_id not in self.paid_users:
            self.paid_users.add(user_id)
            self.save_paid_users()
            return True
        return False
    
    def remove_paid_user(self, user_id: int) -> bool:
        """Удаляет оплатившего пользователя"""
        if user_id in self.paid_users:
            self.paid_users.remove(user_id)
            self.save_paid_users()
            return True
        return False
    
    def get_all_admins(self) -> List[int]:
        """Возвращает список всех администраторов"""
        return list(self.admins)
    
    def get_all_paid_users(self) -> List[int]:
        """Возвращает список всех оплативших пользователей"""
        return list(self.paid_users)
    
    def get_user_info(self, user_id: int) -> Dict:
        """Возвращает информацию о пользователе"""
        return {
            "is_admin": self.is_admin(user_id),
            "is_paid": self.is_paid_user(user_id),
            "user_id": user_id
        }

# Инициализируем систему контроля доступа
access_control = AccessControl()

# Инициализация начальных администраторов из переменной окружения
def init_admins():
    """Инициализирует администраторов из переменной окружения"""
    initial_admins = os.getenv('INITIAL_ADMINS', '')
    if initial_admins:
        admin_ids = [int(id.strip()) for id in initial_admins.split(',') if id.strip().isdigit()]
        for admin_id in admin_ids:
            access_control.add_admin(admin_id)
        logger.info(f"Инициализированы администраторы: {admin_ids}")

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
    admin_add_user = State()
    admin_remove_user = State()

# =========== ФИЛЬТРЫ ДЛЯ ПРОВЕРКИ ДОСТУПА ===========
class AccessFilter:
    """Фильтр для проверки доступа пользователя"""
    
    @staticmethod
    async def check_access(message: Message) -> bool:
        """Проверяет, есть ли у пользователя доступ к контенту"""
        user_id = message.from_user.id
        return access_control.is_paid_user(user_id)
    
    @staticmethod
    async def check_admin(message: Message) -> bool:
        """Проверяет, является ли пользователь администратором"""
        user_id = message.from_user.id
        return access_control.is_admin(user_id)

# Конфигурация аудиофайлов
AUDIO_CONFIG = {
    "base_path": "audio/",
    "default_format": ".mp3",
}

# Данные курса с аудио (остаются без изменений)
MODULES = [
    # ... (ваши модули остаются без изменений)
    {
        "id": 1,
        "day": 1,
        "title": "Основы мира тендеров",
        "emoji": "📚",
        "content": """<b>📚 День 1 | Модуль 1: Основы мира тендеров</b>

✅ <b>Что такое тендер?</b>
Это конкурентная форма размещения заказов на поставку товаров, выполнение работ или оказание услуг, при которой заказчик выбирает исполнителя на основе заранее объявленных критериев.

Проще говоря, это процедура, где несколько компаний (поставщиков) предлагают свои условия (в первую очередь цену) для победы в контракте, а заказчик выбирает самое выгодное для себя предложение.

✅ <b>Участники системы:</b>
• <b>Заказчик</b> — государство, госкомпания, бизнес
• <b>Поставщик</b> — компания (Вы)

✅ <b>Основные законы:</b>
• <b>44-ФЗ</b> — жесткие правила для госзаказчиков
• <b>223-ФЗ</b> — гибкие правила для госкорпораций
• <b>Коммерческие тендеры</b> — правила устанавливает компания

🔗 <b>Полезные ссылки:</b>
• 44-ФЗ: https://www.consultant.ru/document/cons_doc_LAW_144624/
• 223-ФЗ: https://www.consultant.ru/document/cons_doc_LAW_116964/
• ЕИС: https://zakupki.gov.ru

📝 <b>Практическое задание:</b>
Найдите 2-3 тендера в вашей сфере: один по 44-ФЗ, один по 223-ФЗ на сайте zakupki.gov.ru

1. Перейдите в раздел «Закупки»
2. Установите параметры поиска: 44-ФЗ, 223-ФЗ
3. Введите наименование интересующей вас закупки
4. Нажмите «Применить»

<code>Пример поиска: Поставка офисной мебели</code>""",
        "task": "Найти и изучить 2 тендера в вашей сфере деятельности",
        "audio_file": "module1.mp3",
        "audio_duration": 120,
        "audio_title": "Основы тендерной системы",
        "has_audio": True
    },
    # ... (остальные модули без изменений)
]

# Тестовые вопросы (остаются без изменений)
TEST_QUESTIONS = [
    # ... (ваши вопросы без изменений)
]

# Дополнительные материалы (остаются без изменений)
ADDITIONAL_MATERIALS = {
    "links": {
        "ЕИС": "https://zakupki.gov.ru",
        "Госуслуги": "https://www.gosuslugi.ru",
        "B2B-Center": "https://www.b2b-center.ru",
        "КонсультантПлюс 44-ФЗ": "https://www.consultant.ru/document/cons_doc_LAW_144624/",
        "Удостоверяющий центр": "https://uc-itcom.ru",
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

# =========== КЛАВИАТУРЫ ===========
def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """
    Создает фиксированную клавиатуру в зависимости от статуса пользователя
    """
    is_paid = access_control.is_paid_user(user_id)
    
    if is_paid:
        # Полная клавиатура для оплативших пользователей
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
    else:
        # Ограниченная клавиатура для неоплативших
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [
                    KeyboardButton(text="🔓 Получить доступ"),
                    KeyboardButton(text="📞 Контакты"),
                ],
                [
                    KeyboardButton(text="🆘 Помощь"),
                    KeyboardButton(text="ℹ️ О курсе"),
                ]
            ],
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="Для доступа к курсу оплатите подписку..."
        )
    
    return keyboard

def get_admin_keyboard() -> ReplyKeyboardMarkup:
    """
    Клавиатура для администраторов
    """
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="👥 Управление доступом"),
                KeyboardButton(text="📊 Статистика"),
            ],
            [
                KeyboardButton(text="📢 Рассылка"),
                KeyboardButton(text="⚙️ Настройки"),
            ],
            [
                KeyboardButton(text="🔙 Главное меню"),
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

def get_access_management_keyboard() -> ReplyKeyboardMarkup:
    """
    Клавиатура для управления доступом
    """
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="➕ Добавить пользователя"),
                KeyboardButton(text="➖ Удалить пользователя"),
            ],
            [
                KeyboardButton(text="📋 Список пользователей"),
                KeyboardButton(text="👑 Управление админами"),
            ],
            [
                KeyboardButton(text="🔙 Назад в админку"),
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

def get_admin_management_keyboard() -> ReplyKeyboardMarkup:
    """
    Клавиатура для управления администраторами
    """
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="👑 Добавить администратора"),
                KeyboardButton(text="🗑️ Удалить администратора"),
            ],
            [
                KeyboardButton(text="📋 Список администраторов"),
                KeyboardButton(text="🔙 Назад"),
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

# Клавиатура для навигации по урокам (только для оплативших)
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

# Клавиатура для теста (только для оплативших)
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
            ],
            [
                KeyboardButton(text="🔙 Главное меню"),
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Выберите вариант ответа..."
    )
    return keyboard

# Вспомогательные функции для работы с аудио (остаются без изменений)
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

# Функция отображения списка уроков (только для оплативших)
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
        KeyboardButton(text="🔙 Главное меню")
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
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к этому модулю. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
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

# =========== ОСНОВНЫЕ ОБРАБОТЧИКИ КОМАНД ===========
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """
    Обработчик команды /start
    """
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    
    # Инициализируем прогресс пользователя
    if user_id not in user_progress:
        user_progress[user_id] = {
            'start_date': datetime.now().isoformat(),
            'completed_modules': [],
            'last_module': 0,
            'name': user_name,
            'audio_listened': [],
            'test_results': []
        }
    
    # Проверяем статус пользователя
    is_paid = access_control.is_paid_user(user_id)
    is_admin = access_control.is_admin(user_id)
    
    if is_admin:
        # Администратор
        welcome_text = f"""
<b>👑 Привет, Администратор {user_name}!</b>

Добро пожаловать в панель управления ботом!

<b>Ваши права:</b>
• Управление доступом пользователей
• Добавление/удаление администраторов
• Просмотр статистики
• Рассылка сообщений

<b>Используйте админ-панель для управления:</b>
"""
        await message.answer(
            welcome_text,
            reply_markup=get_admin_keyboard(),
            parse_mode=ParseMode.HTML
        )
        
    elif is_paid:
        # Оплативший пользователь
        welcome_text = f"""
<b>👋 Привет, {user_name}!</b>

Добро пожаловать на <b>Экспресс-курс: "Тендеры с нуля"</b>!

🎯 <b>Особенности курса:</b>
• 📚 6 модулей с теорией и практикой
• 🎧 <b>Аудио-сопровождение к каждому уроку</b>
• 📝 Практические задания
• 📊 Отслеживание прогресса
• <b>📝 Финальный тест</b> для проверки знаний

<b>🎧 Важно!</b> При выборе урока автоматически отправляется аудио-сопровождение.

<b>Используйте кнопки внизу для навигации!</b>
"""
        await message.answer(
            welcome_text,
            reply_markup=get_main_keyboard(user_id),
            parse_mode=ParseMode.HTML
        )
        
    else:
        # Неоплативший пользователь
        welcome_text = f"""
<b>👋 Привет, {user_name}!</b>

Добро пожаловать на <b>Экспресс-курс: "Тендеры с нуля"</b>!

🚀 <b>Курс включает:</b>
• 6 модулей с аудио-сопровождением
• Практические задания
• Финальный тест
• Чек-лист для работы

🔒 <b>Для получения доступа необходимо:</b>
1. Оплатить подписку
2. Обратиться к администратору

💰 <b>Стоимость:</b> Уточняйте у администратора

📞 <b>Контакты для оплаты:</b>
Телефон: {ADDITIONAL_MATERIALS['contacts']['mobile']}
Email: {ADDITIONAL_MATERIALS['contacts']['email']}

<b>После оплаты администратор добавит вас в систему!</b>
"""
        await message.answer(
            welcome_text,
            reply_markup=get_main_keyboard(user_id),
            parse_mode=ParseMode.HTML
        )
    
    await state.clear()

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    """
    Панель администратора
    """
    user_id = message.from_user.id
    
    if not access_control.is_admin(user_id):
        await message.answer(
            "❌ У вас нет прав администратора.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    admin_text = f"""
<b>👑 Панель администратора</b>

📊 <b>Статистика:</b>
• Администраторов: {len(access_control.get_all_admins())}
• Пользователей с доступом: {len(access_control.get_all_paid_users())}
• Всего пользователей бота: {len(user_progress)}

⚙️ <b>Доступные команды:</b>
• <b>Управление доступом</b> - добавление/удаление пользователей
• <b>Статистика</b> - подробная статистика
• <b>Рассылка</b> - отправка сообщений всем пользователям
• <b>Настройки</b> - настройки системы

<b>Выберите действие:</b>
"""
    
    await message.answer(
        admin_text,
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.HTML
    )

# =========== ОБРАБОТЧИКИ АДМИНИСТРАТОРА ===========
@dp.message(F.text == "👥 Управление доступом")
async def handle_access_management(message: Message):
    """
    Управление доступом пользователей
    """
    user_id = message.from_user.id
    
    if not access_control.is_admin(user_id):
        await message.answer(
            "❌ У вас нет прав администратора.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    access_text = f"""
<b>👥 Управление доступом</b>

📋 <b>Текущая статистика:</b>
• Всего пользователей с доступом: {len(access_control.get_all_paid_users())}
• Администраторов: {len(access_control.get_all_admins())}

🔧 <b>Доступные действия:</b>
• <b>Добавить пользователя</b> - предоставить доступ
• <b>Удалить пользователя</b> - отозвать доступ
• <b>Список пользователей</b> - просмотр всех пользователей
• <b>Управление админами</b> - добавление/удаление администраторов

<b>Выберите действие:</b>
"""
    
    await message.answer(
        access_text,
        reply_markup=get_access_management_keyboard(),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "➕ Добавить пользователя")
async def handle_add_user_start(message: Message, state: FSMContext):
    """
    Начало процесса добавления пользователя
    """
    user_id = message.from_user.id
    
    if not access_control.is_admin(user_id):
        await message.answer(
            "❌ У вас нет прав администратора.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    await state.set_state(UserState.admin_add_user)
    await message.answer(
        "<b>➕ Добавление пользователя</b>\n\n"
        "Отправьте мне <b>ID пользователя</b> или <b>@username</b> для предоставления доступа.\n\n"
        "<i>Для отмены нажмите /cancel</i>",
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "➖ Удалить пользователя")
async def handle_remove_user_start(message: Message, state: FSMContext):
    """
    Начало процесса удаления пользователя
    """
    user_id = message.from_user.id
    
    if not access_control.is_admin(user_id):
        await message.answer(
            "❌ У вас нет прав администратора.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    await state.set_state(UserState.admin_remove_user)
    await message.answer(
        "<b>➖ Удаление пользователя</b>\n\n"
        "Отправьте мне <b>ID пользователя</b> или <b>@username</b> для отзыва доступа.\n\n"
        "<i>Для отмены нажмите /cancel</i>",
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "📋 Список пользователей")
async def handle_list_users(message: Message):
    """
    Показывает список всех пользователей с доступом
    """
    user_id = message.from_user.id
    
    if not access_control.is_admin(user_id):
        await message.answer(
            "❌ У вас нет прав администратора.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    paid_users = access_control.get_all_paid_users()
    admins = access_control.get_all_admins()
    
    if not paid_users:
        await message.answer(
            "📋 <b>Список пользователей пуст.</b>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Формируем сообщение
    users_text = "<b>📋 Пользователи с доступом:</b>\n\n"
    
    for i, user_id in enumerate(paid_users[:50], 1):  # Показываем первые 50
        is_admin = user_id in admins
        admin_badge = " 👑" if is_admin else ""
        users_text += f"{i}. ID: <code>{user_id}</code>{admin_badge}\n"
    
    if len(paid_users) > 50:
        users_text += f"\n<i>... и еще {len(paid_users) - 50} пользователей</i>"
    
    users_text += f"\n\n<b>Всего: {len(paid_users)} пользователей</b>"
    
    await message.answer(
        users_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_access_management_keyboard()
    )

@dp.message(F.text == "👑 Управление админами")
async def handle_admin_management(message: Message):
    """
    Управление администраторами
    """
    user_id = message.from_user.id
    
    if not access_control.is_admin(user_id):
        await message.answer(
            "❌ У вас нет прав администратора.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    admins = access_control.get_all_admins()
    
    admin_text = f"""
<b>👑 Управление администраторами</b>

📋 <b>Текущие администраторы ({len(admins)}):</b>
"""
    
    for i, admin_id in enumerate(admins, 1):
        admin_text += f"{i}. ID: <code>{admin_id}</code>\n"
    
    admin_text += "\n<b>Доступные действия:</b>"
    
    await message.answer(
        admin_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_admin_management_keyboard()
    )

@dp.message(F.text == "👑 Добавить администратора")
async def handle_add_admin_start(message: Message, state: FSMContext):
    """
    Начало процесса добавления администратора
    """
    user_id = message.from_user.id
    
    if not access_control.is_admin(user_id):
        await message.answer(
            "❌ У вас нет прав администратора.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    await message.answer(
        "<b>👑 Добавление администратора</b>\n\n"
        "Отправьте мне <b>ID пользователя</b> для назначения администратором.\n\n"
        "<i>Внимание: Администратор получает полный доступ к управлению ботом!</i>\n\n"
        "<i>Для отмены нажмите /cancel</i>",
        parse_mode=ParseMode.HTML
    )
    
    # Сохраняем состояние для обработки следующего сообщения
    await state.set_state(UserState.admin_add_user)
    await state.update_data(is_admin=True)

@dp.message(F.text == "🗑️ Удалить администратора")
async def handle_remove_admin_start(message: Message, state: FSMContext):
    """
    Начало процесса удаления администратора
    """
    user_id = message.from_user.id
    
    if not access_control.is_admin(user_id):
        await message.answer(
            "❌ У вас нет прав администратора.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    admins = access_control.get_all_admins()
    
    if len(admins) <= 1:
        await message.answer(
            "❌ <b>Нельзя удалить последнего администратора!</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_admin_management_keyboard()
        )
        return
    
    await message.answer(
        "<b>🗑️ Удаление администратора</b>\n\n"
        "Отправьте мне <b>ID администратора</b> для удаления.\n\n"
        "<i>Внимание: После удаления пользователь потеряет права администратора!</i>\n\n"
        "<i>Для отмены нажмите /cancel</i>",
        parse_mode=ParseMode.HTML
    )
    
    # Сохраняем состояние для обработки следующего сообщения
    await state.set_state(UserState.admin_remove_user)
    await state.update_data(is_admin=True)

@dp.message(F.text == "📋 Список администраторов")
async def handle_list_admins(message: Message):
    """
    Показывает список всех администраторов
    """
    user_id = message.from_user.id
    
    if not access_control.is_admin(user_id):
        await message.answer(
            "❌ У вас нет прав администратора.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    admins = access_control.get_all_admins()
    
    admins_text = "<b>👑 Список администраторов:</b>\n\n"
    
    for i, admin_id in enumerate(admins, 1):
        admins_text += f"{i}. ID: <code>{admin_id}</code>\n"
    
    admins_text += f"\n<b>Всего: {len(admins)} администраторов</b>"
    
    await message.answer(
        admins_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_admin_management_keyboard()
    )

@dp.message(F.text == "📊 Статистика")
async def handle_statistics(message: Message):
    """
    Показывает статистику бота
    """
    user_id = message.from_user.id
    
    if not access_control.is_admin(user_id):
        await message.answer(
            "❌ У вас нет прав администратора.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    # Собираем статистику
    total_users = len(user_progress)
    paid_users = len(access_control.get_all_paid_users())
    admins = len(access_control.get_all_admins())
    
    # Статистика по прогрессу
    completed_courses = 0
    active_users = 0
    
    for user_data in user_progress.values():
        completed_modules = len(user_data.get('completed_modules', []))
        if completed_modules >= len(MODULES):
            completed_courses += 1
        if completed_modules > 0:
            active_users += 1
    
    stats_text = f"""
<b>📊 Статистика бота</b>

👥 <b>Пользователи:</b>
• Всего пользователей: {total_users}
• Пользователей с доступом: {paid_users}
• Администраторов: {admins}
• Активных пользователей: {active_users}

📚 <b>Прогресс обучения:</b>
• Завершили курс полностью: {completed_courses}
• Проходят обучение: {active_users - completed_courses}

🎯 <b>Курс:</b>
• Модулей: {len(MODULES)}
• Аудио уроков: {sum(1 for m in MODULES if m.get('has_audio'))}
• Вопросов в тесте: {len(TEST_QUESTIONS)}

📅 <b>Система:</b>
• Время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
• Перезапусков: {restart_count}
"""
    
    await message.answer(
        stats_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_admin_keyboard()
    )

@dp.message(F.text == "📢 Рассылка")
async def handle_broadcast_start(message: Message, state: FSMContext):
    """
    Начало создания рассылки
    """
    user_id = message.from_user.id
    
    if not access_control.is_admin(user_id):
        await message.answer(
            "❌ У вас нет прав администратора.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    await message.answer(
        "<b>📢 Создание рассылки</b>\n\n"
        "Отправьте мне сообщение, которое будет разослано всем пользователям с доступом.\n\n"
        "<i>Вы можете использовать HTML разметку для форматирования</i>\n\n"
        "<i>Для отмены нажмите /cancel</i>",
        parse_mode=ParseMode.HTML
    )
    
    # Сохраняем состояние для обработки следующего сообщения
    await state.update_data(broadcast=True)

@dp.message(F.text == "⚙️ Настройки")
async def handle_settings(message: Message):
    """
    Настройки системы
    """
    user_id = message.from_user.id
    
    if not access_control.is_admin(user_id):
        await message.answer(
            "❌ У вас нет прав администратора.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    settings_text = f"""
<b>⚙️ Настройки системы</b>

🔧 <b>Текущие настройки:</b>
• Максимальное количество перезапусков: {max_restarts}
• Задержка между перезапусками: {restart_delay} сек
• HTTP порт: {PORT}

📁 <b>Файлы данных:</b>
• Администраторы: {len(access_control.get_all_admins())} записей
• Пользователи: {len(access_control.get_all_paid_users())} записей
• Прогресс: {len(user_progress)} записей

🔄 <b>Действия:</b>
• /backup - Создать backup данных
• /restore - Восстановить из backup
• /cleanup - Очистить неактивных пользователей
"""
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🔙 Назад в админку"),
            ]
        ],
        resize_keyboard=True
    )
    
    await message.answer(
        settings_text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )

# =========== ОБРАБОТЧИКИ СОСТОЯНИЙ АДМИНИСТРАТОРА ===========
@dp.message(UserState.admin_add_user)
async def handle_admin_add_user_process(message: Message, state: FSMContext):
    """
    Обработка добавления пользователя/администратора
    """
    user_id = message.from_user.id
    target = message.text.strip()
    
    if not access_control.is_admin(user_id):
        await message.answer(
            "❌ У вас нет прав администратора.",
            reply_markup=get_main_keyboard(user_id)
        )
        await state.clear()
        return
    
    # Проверяем, является ли это добавлением администратора
    data = await state.get_data()
    is_adding_admin = data.get('is_admin', False)
    
    try:
        # Пробуем получить ID пользователя
        target_id = None
        
        if target.isdigit():
            # Если это числовой ID
            target_id = int(target)
        elif target.startswith('@'):
            # Если это username, пытаемся получить ID через бота
            try:
                user = await bot.get_chat(target)
                target_id = user.id
            except Exception as e:
                await message.answer(
                    f"❌ Не удалось найти пользователя {target}\n"
                    f"Ошибка: {str(e)}",
                    reply_markup=get_access_management_keyboard() if not is_adding_admin else get_admin_management_keyboard()
                )
                await state.clear()
                return
        else:
            await message.answer(
                "❌ Неверный формат. Отправьте ID пользователя (число) или @username",
                reply_markup=get_access_management_keyboard() if not is_adding_admin else get_admin_management_keyboard()
            )
            return
        
        if is_adding_admin:
            # Добавление администратора
            if access_control.add_admin(target_id):
                await message.answer(
                    f"✅ Пользователь ID: <code>{target_id}</code> назначен администратором!",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_admin_management_keyboard()
                )
                
                # Уведомляем нового администратора
                try:
                    await bot.send_message(
                        target_id,
                        "🎉 <b>Вас назначили администратором бота!</b>\n\n"
                        "Теперь у вас есть доступ к панели управления.\n"
                        "Используйте команду /admin для доступа к админ-панели.",
                        parse_mode=ParseMode.HTML
                    )
                except:
                    pass
            else:
                await message.answer(
                    f"ℹ️ Пользователь ID: <code>{target_id}</code> уже является администратором.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_admin_management_keyboard()
                )
        else:
            # Добавление обычного пользователя
            if access_control.add_paid_user(target_id):
                await message.answer(
                    f"✅ Пользователю ID: <code>{target_id}</code> предоставлен доступ к курсу!",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_access_management_keyboard()
                )
                
                # Уведомляем пользователя
                try:
                    await bot.send_message(
                        target_id,
                        "🎉 <b>Вам предоставлен доступ к курсу!</b>\n\n"
                        "Теперь вы можете начать обучение.\n"
                        "Используйте команду /start для начала работы с курсом.",
                        parse_mode=ParseMode.HTML
                    )
                except:
                    pass
            else:
                await message.answer(
                    f"ℹ️ Пользователь ID: <code>{target_id}</code> уже имеет доступ к курсу.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_access_management_keyboard()
                )
    
    except ValueError:
        await message.answer(
            "❌ Неверный формат ID. ID должен быть числом.",
            reply_markup=get_access_management_keyboard() if not is_adding_admin else get_admin_management_keyboard()
        )
    except Exception as e:
        logger.error(f"Error adding user: {e}")
        await message.answer(
            f"❌ Ошибка при добавлении пользователя: {str(e)}",
            reply_markup=get_access_management_keyboard() if not is_adding_admin else get_admin_management_keyboard()
        )
    
    await state.clear()

@dp.message(UserState.admin_remove_user)
async def handle_admin_remove_user_process(message: Message, state: FSMContext):
    """
    Обработка удаления пользователя/администратора
    """
    user_id = message.from_user.id
    target = message.text.strip()
    
    if not access_control.is_admin(user_id):
        await message.answer(
            "❌ У вас нет прав администратора.",
            reply_markup=get_main_keyboard(user_id)
        )
        await state.clear()
        return
    
    # Проверяем, является ли это удалением администратора
    data = await state.get_data()
    is_removing_admin = data.get('is_admin', False)
    
    try:
        # Пробуем получить ID пользователя
        target_id = None
        
        if target.isdigit():
            # Если это числовой ID
            target_id = int(target)
        elif target.startswith('@'):
            # Если это username, пытаемся получить ID через бота
            try:
                user = await bot.get_chat(target)
                target_id = user.id
            except Exception as e:
                await message.answer(
                    f"❌ Не удалось найти пользователя {target}\n"
                    f"Ошибка: {str(e)}",
                    reply_markup=get_access_management_keyboard() if not is_removing_admin else get_admin_management_keyboard()
                )
                await state.clear()
                return
        else:
            await message.answer(
                "❌ Неверный формат. Отправьте ID пользователя (число) или @username",
                reply_markup=get_access_management_keyboard() if not is_removing_admin else get_admin_management_keyboard()
            )
            return
        
        if is_removing_admin:
            # Удаление администратора
            if target_id == user_id:
                await message.answer(
                    "❌ <b>Вы не можете удалить себя из администраторов!</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_admin_management_keyboard()
                )
                return
            
            if access_control.remove_admin(target_id):
                await message.answer(
                    f"✅ Пользователь ID: <code>{target_id}</code> удален из администраторов!",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_admin_management_keyboard()
                )
            else:
                await message.answer(
                    f"ℹ️ Пользователь ID: <code>{target_id}</code> не является администратором.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_admin_management_keyboard()
                )
        else:
            # Удаление обычного пользователя
            if access_control.remove_paid_user(target_id):
                await message.answer(
                    f"✅ У пользователя ID: <code>{target_id}</code> отозван доступ к курсу!",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_access_management_keyboard()
                )
            else:
                await message.answer(
                    f"ℹ️ Пользователь ID: <code>{target_id}</code> не имеет доступа к курсу.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_access_management_keyboard()
                )
    
    except ValueError:
        await message.answer(
            "❌ Неверный формат ID. ID должен быть числом.",
            reply_markup=get_access_management_keyboard() if not is_removing_admin else get_admin_management_keyboard()
        )
    except Exception as e:
        logger.error(f"Error removing user: {e}")
        await message.answer(
            f"❌ Ошибка при удалении пользователя: {str(e)}",
            reply_markup=get_access_management_keyboard() if not is_removing_admin else get_admin_management_keyboard()
        )
    
    await state.clear()

# =========== ОБРАБОТЧИКИ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ===========
@dp.message(F.text == "🔓 Получить доступ")
async def handle_get_access(message: Message):
    """
    Информация о получении доступа
    """
    user_id = message.from_user.id
    
    access_info = f"""
<b>🔓 Получение доступа к курсу</b>

💰 <b>Стоимость подписки:</b>
• Полный доступ ко всем материалам
• Аудио сопровождение к каждому уроку
• Проверка знаний через тест
• Чек-лист для практической работы

📞 <b>Для оплаты свяжитесь с администратором:</b>
Телефон: {ADDITIONAL_MATERIALS['contacts']['mobile']}
Email: {ADDITIONAL_MATERIALS['contacts']['email']}

🤝 <b>После оплаты:</b>
1. Сообщите администратору ваш ID: <code>{user_id}</code>
2. Администратор добавит вас в систему
3. Вы получите уведомление о предоставлении доступа
4. Нажмите /start для начала обучения

<b>Ваш ID для связи с администратором:</b>
<code>{user_id}</code>
"""
    
    await message.answer(
        access_info,
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard(user_id)
    )

@dp.message(F.text == "ℹ️ О курсе")
async def handle_about_course(message: Message):
    """
    Информация о курсе
    """
    user_id = message.from_user.id
    
    about_text = f"""
<b>ℹ️ О курсе "Тендеры с нуля"</b>

🎯 <b>Цель курса:</b>
Дать практические навыки для участия в тендерах с нуля.

📚 <b>Что вы получите:</b>
• 6 модулей с теорией и практикой
• Аудио сопровождение к каждому уроку
• Практические задания
• Финальный тест для проверки знаний
• Чек-лист для первых шагов

👨‍🏫 <b>Для кого этот курс:</b>
• Начинающие предприниматели
• Специалисты по закупкам
• Владельцы малого бизнеса
• Все, кто хочет освоить тендеры

💰 <b>Стоимость:</b>
Уточняйте у администратора

📞 <b>Контакты:</b>
Телефон: {ADDITIONAL_MATERIALS['contacts']['mobile']}
Email: {ADDITIONAL_MATERIALS['contacts']['email']}

<b>Для получения доступа нажмите "🔓 Получить доступ"</b>
"""
    
    await message.answer(
        about_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard(user_id)
    )

# =========== ЗАЩИЩЕННЫЕ ОБРАБОТЧИКИ (только для оплативших) ===========
@dp.message(F.text == "📚 Меню курса")
async def handle_course_menu(message: Message):
    """
    Показывает меню курса со списком уроков
    """
    user_id = message.from_user.id
    
    # Проверяем доступ
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к курсу. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    lessons_text = "<b>📚 Выберите урок для изучения:</b>\n\n"
    
    for i, module in enumerate(MODULES, 1):
        audio_icon = "🎧 " if module.get("has_audio", False) else ""
        lessons_text += f"{module['emoji']} {audio_icon}<b>День {module['day']}:</b> {module['title']}\n"
        
        # Проверяем прогресс
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
    user_id = message.from_user.id
    
    # Проверяем доступ
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к аудио урокам. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
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
        reply_markup=get_main_keyboard(user_id),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "📊 Мой прогресс")
async def handle_my_progress(message: Message):
    """
    Показывает прогресс пользователя
    """
    user_id = message.from_user.id
    
    # Проверяем доступ
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к курсу. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    if user_id not in user_progress:
        await message.answer(
            "❌ Вы еще не начали обучение. Нажмите /start",
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
    
    progress_text += "\n<b>Продолжайте обучение! 💪</b>"
    
    await message.answer(
        progress_text,
        reply_markup=get_main_keyboard(user_id),
        parse_mode=ParseMode.HTML
    )

# ... (остальные обработчики для оплативших пользователей остаются без изменений,
# но должны начинаться с проверки доступа через access_control.is_paid_user(user_id))

# =========== КОМАНДА ОТМЕНЫ ===========
@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """
    Отмена текущего действия
    """
    user_id = message.from_user.id
    current_state = await state.get_state()
    
    if current_state:
        await state.clear()
        
        if access_control.is_admin(user_id):
            await message.answer(
                "❌ Действие отменено.",
                reply_markup=get_admin_keyboard()
            )
        elif access_control.is_paid_user(user_id):
            await message.answer(
                "❌ Действие отменено.",
                reply_markup=get_main_keyboard(user_id)
            )
        else:
            await message.answer(
                "❌ Действие отменено.",
                reply_markup=get_main_keyboard(user_id)
            )
    else:
        if access_control.is_admin(user_id):
            await message.answer(
                "Нет активных действий для отмены.",
                reply_markup=get_admin_keyboard()
            )
        else:
            await message.answer(
                "Нет активных действий для отмены.",
                reply_markup=get_main_keyboard(user_id)
            )

# =========== КОМАНДА НАЗАД ===========
@dp.message(F.text.in_({"🔙 Назад в админку", "🔙 Назад", "🔙 Главное меню"}))
async def handle_back(message: Message, state: FSMContext):
    """
    Возврат в главное меню
    """
    user_id = message.from_user.id
    await state.clear()
    
    if access_control.is_admin(user_id):
        await cmd_admin(message)
    elif access_control.is_paid_user(user_id):
        await cmd_start(message, state)
    else:
        await cmd_start(message, state)

# =========== ОБРАБОТЧИК ВСЕХ ОСТАЛЬНЫХ СООБЩЕНИЙ ===========
@dp.message()
async def handle_other_messages(message: Message, state: FSMContext):
    """
    Обработчик всех прочих сообщений
    """
    user_id = message.from_user.id
    
    # Проверяем, не является ли это сообщением для рассылки
    data = await state.get_data()
    if data.get('broadcast'):
        # Это сообщение для рассылки
        if access_control.is_admin(user_id):
            paid_users = access_control.get_all_paid_users()
            
            if not paid_users:
                await message.answer(
                    "❌ Нет пользователей для рассылки.",
                    reply_markup=get_admin_keyboard()
                )
                await state.clear()
                return
            
            await message.answer(
                f"📢 <b>Начинаю рассылку для {len(paid_users)} пользователей...</b>",
                parse_mode=ParseMode.HTML
            )
            
            success_count = 0
            fail_count = 0
            
            for target_id in paid_users:
                try:
                    await bot.copy_message(
                        chat_id=target_id,
                        from_chat_id=message.chat.id,
                        message_id=message.message_id,
                        parse_mode=ParseMode.HTML
                    )
                    success_count += 1
                except Exception as e:
                    logger.error(f"Failed to send broadcast to {target_id}: {e}")
                    fail_count += 1
            
            await message.answer(
                f"✅ <b>Рассылка завершена!</b>\n\n"
                f"• Успешно отправлено: {success_count}\n"
                f"• Не удалось отправить: {fail_count}\n"
                f"• Всего пользователей: {len(paid_users)}",
                parse_mode=ParseMode.HTML,
                reply_markup=get_admin_keyboard()
            )
        
        await state.clear()
        return
    
    # Проверяем доступ для остальных сообщений
    if message.content_type == ContentType.TEXT:
        # Проверяем, имеет ли пользователь доступ
        if access_control.is_paid_user(user_id):
            # Пользователь с доступом
            await message.answer(
                "🤖 Я бот для обучения тендерам с аудио сопровождением!\n\n"
                "Используйте кнопки внизу для навигации или команды:\n"
                "/start - Начать обучение\n"
                "/menu - Главное меню\n"
                "/help - Помощь\n"
                "/progress - Ваш прогресс\n"
                "/audio - Аудио уроки\n"
                "/test - Пройти финальный тест\n"
                "/status - Статус бота\n\n"
                "🎧 <b>Важно:</b> При выборе урока автоматически отправляется аудио-пояснение!\n"
                "📝 <b>После завершения курса пройдите финальный тест!</b>\n"
                "📥 <b>Скачайте готовый чек-лист для практической работы!</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_keyboard(user_id)
            )
        else:
            # Пользователь без доступа
            await message.answer(
                "🔒 <b>У вас нет доступа к полному функционалу бота</b>\n\n"
                "Для получения доступа к курсу:\n"
                "1. Оплатите подписку\n"
                "2. Свяжитесь с администратором\n"
                "3. Предоставьте ваш ID для добавления\n\n"
                f"<b>Ваш ID:</b> <code>{user_id}</code>\n\n"
                "📞 <b>Контакты:</b>\n"
                f"Телефон: {ADDITIONAL_MATERIALS['contacts']['mobile']}\n"
                f"Email: {ADDITIONAL_MATERIALS['contacts']['email']}\n\n"
                "Нажмите '🔓 Получить доступ' для подробной информации.",
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_keyboard(user_id)
            )

# =========== ФУНКЦИИ ПРОВЕРКИ ФАЙЛОВ ===========
async def check_audio_files():
    """Проверяет наличие всех аудио файлов при запуске бота"""
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

async def check_checklist_file():
    """Проверяет наличие файла чек-листа"""
    checklist_path = "Чек-лист -Первые 10 шагов в тендерах-.docx"
    
    if os.path.exists(checklist_path):
        file_size = os.path.getsize(checklist_path) / 1024  # в КБ
        logger.info(f"✓ Чек-лист найден: {checklist_path} ({file_size:.1f} КБ)")
        return True
    else:
        logger.warning(f"✗ Чек-лист не найден: {checklist_path}")
        logger.warning("Кнопка '📥 Скачать чек-лист' будет недоступна")
        return False

# =========== HTTP СЕРВЕР ДЛЯ МОНИТОРИНГА ===========
async def health_check(request):
    """Обработчик для health check"""
    return web.json_response({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "users": len(user_progress),
        "paid_users": len(access_control.get_all_paid_users()),
        "admins": len(access_control.get_all_admins()),
        "modules": len(MODULES),
        "restarts": restart_count,
        "checklist_available": os.path.exists("Чек-лист -Первые 10 шагов в тендерах-.docx")
    })

async def start_http_server():
    """Запуск HTTP сервера для мониторинга"""
    app = web.Application()
    app.router.add_get('/health', health_check)
    app.router.add_get('/', lambda request: web.Response(text="Telegram Bot is running!"))
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    
    logger.info(f"HTTP сервер запущен на порту {PORT}")
    return runner

# =========== ФУНКЦИЯ ДЛЯ ЗАПУСКА БОТА ===========
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
            
            # Инициализируем администраторов
            init_admins()
            
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
                logger.info(f"✅ Система доступа: {len(access_control.get_all_admins())} администраторов, {len(access_control.get_all_paid_users())} оплативших")
                logger.info(f"✅ Фиксированные кнопки: Автоматически адаптируются под статус пользователя")
                logger.info(f"✅ Аудио сопровождение: {sum(1 for m in MODULES if m.get('has_audio'))}/{len(MODULES)} уроков")
                logger.info(f"✅ HTTP сервер запущен на порту {PORT}")
            except Exception as e:
                logger.error(f"❌ Не удалось подключиться к Telegram API: {e}")
                logger.error("Проверьте ваш BOT_TOKEN и подключение к интернету")
                restart_count += 1
                if not shutdown_flag:
                    logger.info(f"⏳ Повторная попытка через {restart_delay} секунд...")
                    await asyncio.sleep(restart_delay)
                continue
            
            # Запускаем поллинг
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
    
    # Закрываем сессию
    try:
        await bot.session.close()
        logger.info("✅ Сессия бота закрыта")
    except:
        pass

# =========== ОСНОВНАЯ ФУНКЦИЯ ЗАПУСКА ===========
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

# =========== ТОЧКА ВХОДА ===========
if __name__ == "__main__":
    try:
        # Выводим информацию о запуске
        print("=" * 60)
        print("🤖 Бот обучения тендерам с системой контроля доступа")
        print("=" * 60)
        print(f"📅 Время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🔐 Система доступа: Включена")
        print(f"👑 Администраторов: {len(access_control.get_all_admins())}")
        print(f"👥 Пользователей с доступом: {len(access_control.get_all_paid_users())}")
        print(f"🔄 Максимальное количество перезапусков: {max_restarts}")
        print(f"⏱ Задержка между перезапусками: {restart_delay} сек")
        print(f"📚 Количество модулей: {len(MODULES)}")
        print(f"🎧 Аудио файлов: {sum(1 for m in MODULES if m.get('has_audio'))}")
        print(f"📝 Вопросов в тесте: {len(TEST_QUESTIONS)}")
        print(f"📥 Чек-лист: {'Присутствует' if os.path.exists('Чек-лист -Первые 10 шагов в тендерах-.docx') else 'Отсутствует'}")
        print(f"🌐 HTTP порт: {PORT}")
        print("=" * 60)
        print("🔐 Система администраторов:")
        print("• Админы могут добавлять/удалять пользователей")
        print("• Админы могут управлять другими админами")
        print("• Доступ к курсу только после оплаты")
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
