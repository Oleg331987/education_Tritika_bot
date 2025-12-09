import os
import sys
import logging
import asyncio
import signal
from datetime import datetime
from typing import Optional, Dict

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
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Глобальные переменные для graceful shutdown
bot_instance = None
dp_instance = None

# Обработчики сигналов для graceful shutdown
def signal_handler(sig, frame):
    """Обработчик сигналов для graceful shutdown"""
    logger.info(f"Received signal {sig}, initiating graceful shutdown...")
    
    if bot_instance and dp_instance:
        asyncio.create_task(shutdown())
    else:
        sys.exit(0)

async def shutdown():
    """Корректное завершение работы бота"""
    logger.info("Starting graceful shutdown...")
    
    try:
        # Останавливаем polling
        if dp_instance:
            await dp_instance.stop_polling()
            logger.info("Polling stopped successfully")
        
        # Закрываем сессию бота
        if bot_instance:
            await bot_instance.session.close()
            logger.info("Bot session closed successfully")
            
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
    finally:
        logger.info("Shutdown completed")
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

# Конфигурация аудиофайлов
AUDIO_CONFIG = {
    "base_path": "audio/",
    "default_format": ".mp3",
}

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

🎧 <b>Аудио сопровождение:</b> В этом аудио мы подробно разберем основы тендерной системы и расскажем, с чего начать новичку.

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
    {
        "id": 2,
        "day": 2,
        "title": "44-ФЗ — Главный 'коридор' для старта",
        "emoji": "🏛️",
        "content": """<b>🏛️ День 2 | Модуль 2: 44-ФЗ</b>

✅ <b>Ключевые способы закупок:</b>

<b>Конкурентные закупки:</b>
• Аукцион в электронной форме (побеждает самый дешевый)
• Конкурс в электронной форме (лучшие условия)
• Электронный запрос котировок (быстро, для небольших сумм)

<b>Неконкурентные:</b>
• Закупка у единственного поставщика
• Малые закупки до 600 тыс. руб.

✅ <b>Этапы участия:</b>
1. 📝 Электронная подпись (ЭП)
2. 🏢 Аккредитация на ЭТП
3. 🔍 Поиск закупки
4. 📄 Изучение документации
5. 💰 Обеспечение заявки (спецсчет или банковская гарантия)
6. 📤 Подача заявки
7. 🎯 Участие в процедуре
8. 🤝 Обеспечение контракта
9. ✍️ Заключение контракта

🎧 <b>Аудио сопровождение:</b> В аудио мы детально разберем каждый этап участия в закупках по 44-ФЗ и дадим практические рекомендации.

📝 <b>Практическое задание:</b>
Выберите простой аукцион по 44-ФЗ и изучите документацию:

1. Откройте zakupki.gov.ru
2. Выберите раздел «Закупки»
3. Установите фильтр «44-ФЗ»
4. Найдите закупку на сумму до 500 тыс. руб.
5. Скачайте и изучите документацию""",
        "task": "Изучить документацию к одному аукциону по 44-ФЗ",
        "audio_file": "module2.mp3",
        "audio_duration": 180,
        "audio_title": "Работа с 44-ФЗ: практическое руководство",
        "has_audio": True
    },
    {
        "id": 3,
        "day": 3,
        "title": "223-ФЗ — Мир возможностей и гибкости",
        "emoji": "🏢",
        "content": """<b>🏢 День 3 | Модуль 3: 223-ФЗ</b>

✅ <b>Главное отличие:</b>
1. У каждого заказчика своё <b>Положение о закупке</b>
2. Регулирует корпоративные закупки — заказы госкорпораций и крупного бизнеса

✅ <b>Способы закупок:</b>
• Любые (аукцион, запрос котировок, конкурс, запрос предложений)
• Правила определяет сам заказчик

✅ <b>Особенности:</b>
1. 🔍 Больше внимания качеству и репутации
2. 📊 Требуется предоставить релевантный опыт работы
3. 💵 Цена — не всегда решающий фактор
4. 🤝 Больше возможностей для переговоров

🔗 <b>Полезные ссылки:</b>
• Статья о 223-ФЗ: https://zakupki.kontur.ru/site/articles/22556-223fz2

🎧 <b>Аудио сопровождение:</b> Мы расскажем, как эффективно работать с госкорпорациями и какие возможности открывает 223-ФЗ.

📝 <b>Практическое задание:</b>
Найдите закупку по 223-ФЗ от крупной госкомпании:

1. Откройте zakupki.gov.ru
2. Перейдите в раздел «Планирование»
3. Выберите «Положения о закупке 223-ФЗ»
4. Найдите закупку от компаний: РЖД, Ростелеком, Газпром
5. Изучите Положение о закупке""",
        "task": "Найти и изучить Положение о закупке компании по 223-ФЗ",
        "audio_file": "module3.mp3",
        "audio_duration": 150,
        "audio_title": "Корпоративные закупки по 223-ФЗ",
        "has_audio": True
    },
    {
        "id": 4,
        "day": 4,
        "title": "Коммерческие тендеры — Работа с бизнесом",
        "emoji": "💼",
        "content": """<b>💼 День 4 | Модуль 4: Коммерческие тендеры</b>

✅ <b>Ключевые способы закупок:</b>

<b>Конкурентные:</b>
• Запрос предложений
• Аукционы
• Конкурсы

<b>Неконкурентные:</b>
• Прямые закупки у единственного поставщика
• Уникальные товары/услуги
• Срочные закупки

✅ <b>Где искать закупки:</b>
1. 🌐 Корпоративные порталы компаний (разделы «Закупки», «Для поставщиков»)
2. 🏪 Специализированные площадки:
   • B2B-Center: https://www.b2b-center.ru
   • СберАСТ: https://sberbank-ast.ru
   • РТС-тендер: https://www.rts-tender.ru
3. 🤝 Прямые контакты с отделом закупок

✅ <b>Особенности:</b>
1. ⭐ Ценится репутация и надежность
2. 💬 Больше переговоров и обсуждений
3. 📝 Меньше формальностей
4. ⚖️ Нет обязанности заключать контракт с победителем

🎧 <b>Аудио сопровождение:</b> Узнайте, как выигрывать коммерческие тендеры и строить долгосрочные отношения с бизнес-заказчиками.

📝 <b>Практическое задание:</b>
1. Составьте список из 5-10 компаний вашей отрасли
2. Найдите на их сайтах разделы закупок
3. Зарегистрируйтесь на B2B-Center
4. Найдите 3 интересующие вас закупки""",
        "task": "Составить список потенциальных заказчиков и зарегистрироваться на B2B-Center",
        "audio_file": "module4.mp3",
        "audio_duration": 165,
        "audio_title": "Стратегии работы с коммерческими заказчиками",
        "has_audio": True
    },
    {
        "id": 5,
        "day": 5,
        "title": "Практический старт — План на первые шаги",
        "emoji": "🚀",
        "content": """<b>🚀 День 5 | Модуль 5: Практический старт</b>

✅ <b>Пошаговый план действий:</b>

1. <b>Получите ЭЦП:</b>
   • Для ООО/ИП — в аккредитованном УЦ (https://uc-itcom.ru)
   • Стоимость: от 2 000 руб./год

2. <b>Настройте рабочее место:</b>
   • Установите КриптоПРО CSP
   • Настройте браузер Chromium-Gost
   • Приобретите Рутокен

3. <b>Зарегистрируйтесь в системах:</b>
   • Госуслуги (ЕИА): https://www.gosuslugi.ru
   • ЕИС: https://zakupki.gov.ru
   • 5-8 электронных торговых площадок

4. <b>Откройте спецсчет</b> для обеспечения заявок

5. <b>Настройте поиск</b> по вашим товарам/услугам

✅ <b>Начните с малого:</b>
1. Выберите 1-2 простых тендера (до 500 тыс. руб.)
2. Изучите ВСЮ документацию
3. Подготовьте заявку строго по требованиям
4. Не бойтесь задавать вопросы заказчику

❌ <b>Ключевые ошибки новичков:</b>
1. Пропустить требование в документации
2. Неправильно заполнить заявку
3. Опоздать с подачей
4. Не внести обеспечение
5. Бояться задавать вопросы

🎧 <b>Аудио сопровождение:</b> Практический план действий на первые 30 дней и разбор частых ошибок.

🎯 <b>Ваш первый тендер — это ценный опыт, даже если не победите!</b>""",
        "task": "Составить личный план действий на первые 30 дней",
        "audio_file": "module5.mp3",
        "audio_duration": 210,
        "audio_title": "Практический план: первые шаги в тендерах",
        "has_audio": True
    }
]

# Дополнительные материалы
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

# ФИКСИРОВАННАЯ КЛАВИАТУРА ДЛЯ ОСНОВНЫХ ДЕЙСТВИЙ
def get_main_keyboard() -> ReplyKeyboardMarkup:
    """
    Создает фиксированную клавиатуру, которая всегда показывается внизу
    """
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
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Управление уроком..."
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
    
    # Обновляем состояние
    await state.set_state(UserState.viewing_module)
    await state.update_data(current_module=module_index)
    
    # Обновляем последний просмотренный модуль
    if user_id in user_progress:
        user_progress[user_id]['last_module'] = module_index
    
    # Формируем сообщение
    module_text = f"{module['content']}\n\n"
    module_text += f"<b>📝 Практическое задание:</b> {module['task']}"
    
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

# Обработчики команд
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
            'audio_listened': []
        }
    
    welcome_text = f"""
<b>👋 Привет, {user_name}!</b>

Добро пожаловать на <b>Экспресс-курс: "Тендеры с нуля"</b>!

🎯 <b>Особенности курса:</b>
• 📚 5 модулей с теорией и практикой
• 🎧 <b>Аудио-сопровождение к каждому уроку</b>
• 📝 Практические задания
• 📊 Отслеживание прогресса

<b>🎧 Важно!</b> При выборе урока автоматически отправляется аудио-сопровождение в формате MP3.

<b>Используйте кнопки внизу для навигации:</b>
• <b>📚 Меню курса</b> - список всех уроков
• <b>🎧 Аудио уроки</b> - все доступные аудио
• <b>📊 Мой прогресс</b> - статистика обучения
• <b>📞 Контакты</b> - связь с поддержкой
• <b>🔗 Полезные ссылки</b> - важные ресурсы
• <b>🆘 Помощь</b> - инструкция по использованию
    """
    
    await message.answer(
        welcome_text,
        reply_markup=get_main_keyboard(),
        parse_mode=ParseMode.HTML
    )
    
    await state.clear()

@dp.message(Command("menu"))
async def cmd_menu(message: Message):
    """
    Обработчик команды /menu
    """
    await message.answer(
        "<b>📋 Главное меню:</b>\n\nИспользуйте кнопки внизу для навигации.",
        reply_markup=get_main_keyboard(),
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
        reply_markup=get_main_keyboard(),
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
            "❌ Вы еще не начали обучение. Нажмите /start",
            reply_markup=get_main_keyboard()
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
    
    progress_text = f"""
<b>📊 Ваш прогресс в курсе:</b>

👤 <b>Имя:</b> {progress.get('name', 'Не указано')}
📅 <b>Дата начала:</b> {progress['start_date'][:10]}
🎯 <b>Последний урок:</b> {progress.get('last_module', 0) + 1}/{total}

<b>Статистика:</b>
✅ <b>Пройдено уроков:</b> {completed}/{total} ({percentage:.1f}%)
🎧 <b>Прослушано аудио:</b> {audio_listened}/{audio_total} ({audio_percentage:.1f}%)

<b>Статус уроков:</b>
"""
    
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
        reply_markup=get_main_keyboard(),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "📞 Контакты")
async def handle_contacts(message: Message):
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
• Технические проблемы с ботом
• Вопросы по курсу
• Консультации по тендерам
• Предложения по сотрудничеству
    """
    
    await message.answer(
        contacts_text,
        reply_markup=get_main_keyboard(),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "🔗 Полезные ссылки")
async def handle_useful_links(message: Message):
    """
    Показывает полезные ссылки
    """
    links_text = "<b>🔗 Полезные ссылки и ресурсы:</b>\n\n"
    
    for name, url in ADDITIONAL_MATERIALS['links'].items():
        links_text += f"• <a href='{url}'>{name}</a>\n"
    
    links_text += "\n<b>📱 Контакты поддержки:</b>\n"
    links_text += f"📧 Email: {ADDITIONAL_MATERIALS['contacts']['email']}\n"
    links_text += f"📞 Телефон: {ADDITIONAL_MATERIALS['contacts']['phone']}\n"
    links_text += f"📲 Мобильный: {ADDITIONAL_MATERIALS['contacts']['mobile']}"
    
    await message.answer(
        links_text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "🆘 Помощь")
async def handle_help(message: Message):
    """
    Показывает справку
    """
    help_text = """
<b>🆘 Справка по использованию бота:</b>

<b>🎧 Аудио сопровождение:</b>
• При выборе урока автоматически отправляется аудио-пояснение
• Для повторного прослушивания нажмите "🎧 Прослушать аудио"
• Все аудио в формате MP3, совместимы с любыми устройствами

<b>📚 Навигация по курсу:</b>
• <b>📚 Меню курса</b> - список всех уроков
• В уроке используйте кнопки "⬅️ Предыдущий урок" и "Следующий урок ➡️"
• "✅ Отметить пройденным" - отмечайте пройденные уроки
• "🔙 Назад в главное меню" - возврат к основным кнопкам

<b>📊 Отслеживание прогресса:</b>
• В "📊 Моем прогрессе" видна статистика по пройденным урокам и прослушанным аудио
• Процент завершения курса обновляется автоматически

<b>🔧 Технические проблемы:</b>
• Если аудио не приходит, попробуйте кнопку "🎧 Прослушать аудио"
• При проблемах с ботом перезапустите его командой /start
• Для сброса прогресса напишите в поддержку

<b>📞 Контакты поддержки:</b>
• Email: info@tritika.ru
• Телефон: +7(4922)223-222
• Сайт: https://tritika.ru

<b>🕒 Часы работы поддержки:</b>
Пн-Пт: 9:00-18:00 по МСК
    """
    
    await message.answer(
        help_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard()
    )

# Обработчик выбора урока из списка
@dp.message(F.text.startswith(("📚", "🏛️", "🏢", "💼", "🚀")))
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
            "✅ Это последний урок курса! Поздравляем с завершением!",
            reply_markup=get_lesson_navigation_keyboard(current_module, len(MODULES))
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
                'audio_listened': []
            }
        
        module_num = current_module + 1
        if module_num not in user_progress[user_id]['completed_modules']:
            user_progress[user_id]['completed_modules'].append(module_num)
            await message.answer(
                f"✅ Урок {module_num} отмечен как пройденный!",
                reply_markup=get_lesson_navigation_keyboard(current_module, len(MODULES))
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

@dp.message(F.text == "🔙 Назад в главное меню")
async def handle_back_to_main(message: Message, state: FSMContext):
    """
    Возврат в главное меню
    """
    await state.clear()
    await message.answer(
        "<b>📋 Главное меню:</b>\n\nВы вернулись в главное меню.",
        reply_markup=get_main_keyboard(),
        parse_mode=ParseMode.HTML
    )

# Обработчик команды /help
@dp.message(Command("help"))
async def cmd_help(message: Message):
    """
    Обработчик команды /help
    """
    await handle_help(message)

# Обработчик команды /progress
@dp.message(Command("progress"))
async def cmd_progress(message: Message):
    """
    Обработчик команды /progress
    """
    await handle_my_progress(message)

# Обработчик команды /audio
@dp.message(Command("audio"))
async def cmd_audio(message: Message, command: CommandObject):
    """
    Обработчик команды /audio [номер урока]
    """
    try:
        if not command.args:
            await handle_audio_lessons(message)
            return
        
        module_num = int(command.args)
        if 1 <= module_num <= len(MODULES):
            module_index = module_num - 1
            audio_sent = await AudioManager.send_module_audio(message.chat.id, module_index)
            
            if audio_sent:
                # Отмечаем аудио как прослушанное
                user_id = message.from_user.id
                if user_id in user_progress:
                    if module_num not in user_progress[user_id].get('audio_listened', []):
                        user_progress[user_id].setdefault('audio_listened', []).append(module_num)
                
                await message.answer(
                    f"🎧 Аудио к уроку {module_num} отправлено!",
                    reply_markup=get_main_keyboard()
                )
            else:
                await message.answer(
                    "❌ Аудио для этого урока не найдено",
                    reply_markup=get_main_keyboard()
                )
        else:
            await message.answer(
                f"❌ Урок {module_num} не найден. Доступные уроки: 1-{len(MODULES)}",
                reply_markup=get_main_keyboard()
            )
    except ValueError:
        await message.answer(
            "❌ Неверный формат. Используйте: /audio 1",
            reply_markup=get_main_keyboard()
        )

# Обработчик всех остальных сообщений
@dp.message()
async def handle_other_messages(message: Message):
    """
    Обработчик всех прочих сообщений
    """
    if message.content_type == ContentType.TEXT:
        # Если сообщение не обработано другими хендлерами
        await message.answer(
            "🤖 Я бот для обучения тендерам с аудио сопровождением!\n\n"
            "Используйте кнопки внизу для навигации или команды:\n"
            "/start - Начать обучение\n"
            "/menu - Главное меню\n"
            "/help - Помощь\n"
            "/progress - Ваш прогресс\n"
            "/audio - Аудио уроки\n\n"
            "🎧 <b>Важно:</b> При выборе урока автоматически отправляется аудио-пояснение!",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_keyboard()
        )

# Функция проверки аудио файлов при запуске
async def check_audio_files():
    """
    Проверяет наличие всех аудио файлов при запуске бота
    """
    logger.info("Checking audio files...")
    
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

# Основная функция запуска с обработкой ошибок
async def main():
    """
    Основная функция запуска бота с обработкой ошибок и graceful shutdown
    """
    global bot_instance, dp_instance
    bot_instance = bot
    dp_instance = dp
    
    logger.info("Starting tender bot with fixed bottom buttons...")
    logger.info("Registered SIGTERM and SIGINT handlers for graceful shutdown")
    
    # Проверяем аудио файлы
    await check_audio_files()
    
    # Проверяем токен и подключаемся к Telegram
    try:
        bot_info = await bot.get_me()
        logger.info(f"Bot started: @{bot_info.username} (ID: {bot_info.id})")
        logger.info(f"Fixed bottom buttons: 6 main buttons always visible")
        logger.info(f"Audio accompaniment: {sum(1 for m in MODULES if m.get('has_audio'))}/{len(MODULES)} lessons")
    except Exception as e:
        logger.error(f"Failed to connect to Telegram API: {e}")
        logger.error("Please check your BOT_TOKEN and internet connection")
        return
    
    # Запускаем поллинг с обработкой ошибок
    try:
        logger.info("Starting polling...")
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logger.info("Polling cancelled (graceful shutdown)")
    except Exception as e:
        logger.error(f"Polling error: {e}")
        logger.info("Attempting to restart in 5 seconds...")
        await asyncio.sleep(5)
        
        # Пробуем перезапустить
        try:
            await dp.start_polling(bot)
        except Exception as e2:
            logger.error(f"Failed to restart: {e2}")
            logger.error("Bot stopped")

# Точка входа с обработкой исключений
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        logger.error("Bot crashed unexpectedly")
