import os
import logging
import asyncio
from typing import Optional
from datetime import datetime

# Импорты aiogram
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

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

# Проверка токена бота
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    logger.error("BOT_TOKEN не установлен! Установите переменную окружения.")
    exit(1)

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
    viewing_module = State()  # Состояние просмотра модуля
    waiting_feedback = State()  # Состояние ожидания отзыва

# Данные курса (модули)
MODULES = [
    {
        "id": 1,
        "day": 1,
        "title": "Основы мира тендеров",
        "emoji": "📚",
        "content": """<b>📚 День 1 | Модуль 1: Основы мира тендеров</b>

✅ <b>Что такое тендер?</b>
Это конкурентная форма размещения заказов на поставку товаров, выполнение работ или оказание услуг, при которой заказчик выбирает исполнителя на основе заранее объявленных критериев.

✅ <b>Участники системы:</b>
• Заказчик — государство, госкомпания, бизнес
• Поставщик — компания (Вы)

✅ <b>Основные законы:</b>
• <b>44-ФЗ</b> — жесткие правила для госзаказчиков
• <b>223-ФЗ</b> — гибкие правила для госкомпаний
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
        "task": "Найти и изучить 2 тендера в вашей сфере деятельности"
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

📝 <b>Практическое задание:</b>
Выберите простой аукцион по 44-ФЗ и изучите документацию:

1. Откройте zakupki.gov.ru
2. Выберите раздел «Закупки»
3. Установите фильтр «44-ФЗ»
4. Найдите закупку на сумму до 500 тыс. руб.
5. Скачайте и изучите документацию""",
        "task": "Изучить документацию к одному аукциону по 44-ФЗ"
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

📝 <b>Практическое задание:</b>
Найдите закупку по 223-ФЗ от крупной госкомпании:

1. Откройте zakupki.gov.ru
2. Перейдите в раздел «Планирование»
3. Выберите «Положения о закупке 223-ФЗ»
4. Найдите закупку от компаний: РЖД, Ростелеком, Газпром
5. Изучите Положение о закупке""",
        "task": "Найти и изучить Положение о закупке компании по 223-ФЗ"
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

📝 <b>Практическое задание:</b>
1. Составьте список из 5-10 компаний вашей отрасли
2. Найдите на их сайтах разделы закупок
3. Зарегистрируйтесь на B2B-Center
4. Найдите 3 интересующие вас закупки""",
        "task": "Составить список потенциальных заказчиков и зарегистрироваться на B2B-Center"
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
   • Госуслуги (ЕСИА): https://www.gosuslugi.ru
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

🎯 <b>Ваш первый тендер — это ценный опыт, даже если не победите!</b>""",
        "task": "Составить личный план действий на первые 30 дней"
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

# Словарь для хранения прогресса пользователей (в реальном проекте используйте БД)
user_progress = {}

# Функция создания клавиатуры навигации
def get_navigation_keyboard(current_index: int, total_modules: int, user_id: int = None) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для навигации по модулям
    """
    builder = InlineKeyboardBuilder()
    
    # Кнопки навигации
    if current_index > 0:
        builder.button(text="⬅️ Назад", callback_data=f"prev_{current_index-1}")
    
    # Информация о прогрессе
    if user_id and user_id in user_progress:
        completed = user_progress[user_id].get('completed_modules', [])
        if current_index + 1 in completed:
            status = "✅"
        else:
            status = "📖"
    else:
        status = "📖"
    
    builder.button(text=f"{status} {current_index+1}/{total_modules}", callback_data="show_progress")
    
    if current_index < total_modules - 1:
        builder.button(text="Вперед ➡️", callback_data=f"next_{current_index+1}")
    
    builder.adjust(3)
    
    # Дополнительные кнопки
    builder.row(
        InlineKeyboardButton(text="📋 Меню курса", callback_data="course_menu"),
        InlineKeyboardButton(text="✅ Отметить пройденным", callback_data=f"complete_{current_index}")
    )
    
    builder.row(
        InlineKeyboardButton(text="🔗 Полезные ссылки", callback_data="useful_links"),
        InlineKeyboardButton(text="📞 Контакты", callback_data="contacts")
    )
    
    return builder.as_markup()

# Клавиатура главного меню
def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Создает главное меню курса
    """
    builder = InlineKeyboardBuilder()
    
    for module in MODULES:
        builder.button(
            text=f"{module['emoji']} День {module['day']}: {module['title'][:20]}...",
            callback_data=f"module_{module['id']-1}"
        )
    
    builder.adjust(1)
    
    # Дополнительные кнопки
    builder.row(
        InlineKeyboardButton(text="📊 Мой прогресс", callback_data="my_progress"),
        InlineKeyboardButton(text="⭐ Оставить отзыв", callback_data="leave_feedback")
    )
    
    builder.row(
        InlineKeyboardButton(text="🆘 Помощь", callback_data="help"),
        InlineKeyboardButton(text="ℹ️ О курсе", callback_data="about")
    )
    
    return builder.as_markup()

# Хендлер команды /start
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
            'name': user_name
        }
    
    # Приветственное сообщение
    welcome_text = f"""
<b>👋 Привет, {user_name}!</b>

Добро пожаловать на <b>Экспресс-курс: "Тендеры с нуля"</b>!

🎯 <b>Цель курса:</b> Дать системное понимание работы в сфере госзакупок и коммерческих тендеров.

📅 <b>Формат:</b> 5 дней, 1 модуль в день + практические задания
👥 <b>Уровень:</b> Начинающий → Практик

<b>Выберите действие:</b>
    """
    
    await message.answer(
        welcome_text,
        reply_markup=get_main_menu_keyboard(),
        parse_mode=ParseMode.HTML
    )
    
    # Сбрасываем состояние
    await state.clear()

# Хендлер команды /help
@dp.message(Command("help"))
async def cmd_help(message: Message):
    """
    Обработчик команды /help
    """
    help_text = """
<b>🆘 Помощь по использованию бота:</b>

<b>Основные команды:</b>
/start - Начать работу с ботом
/help - Получить справку
/menu - Открыть главное меню
/progress - Посмотреть свой прогресс
/module [номер] - Перейти к конкретному модулю

<b>Навигация:</b>
• Используйте кнопки "Вперед"/"Назад" для перехода между модулями
• "Меню курса" - выбор любого модуля
• "Отметить пройденным" - отметить текущий модуль как завершенный

<b>Техническая поддержка:</b>
По всем вопросам пишите на: info@tritika.ru
Или звоните: +7(4922)223-222
    """
    
    await message.answer(help_text, parse_mode=ParseMode.HTML)

# Хендлер команды /menu
@dp.message(Command("menu"))
async def cmd_menu(message: Message):
    """
    Обработчик команды /menu
    """
    await message.answer(
        "<b>📋 Главное меню курса:</b>",
        reply_markup=get_main_menu_keyboard(),
        parse_mode=ParseMode.HTML
    )

# Хендлер команды /progress
@dp.message(Command("progress"))
async def cmd_progress(message: Message):
    """
    Обработчик команды /progress
    """
    user_id = message.from_user.id
    
    if user_id not in user_progress:
        await message.answer("❌ Вы еще не начали обучение. Введите /start")
        return
    
    progress = user_progress[user_id]
    completed = len(progress.get('completed_modules', []))
    total = len(MODULES)
    percentage = (completed / total) * 100 if total > 0 else 0
    
    progress_text = f"""
<b>📊 Ваш прогресс:</b>

🎓 <b>Пройдено модулей:</b> {completed}/{total} ({percentage:.1f}%)
📅 <b>Дата начала:</b> {progress['start_date'][:10]}
👤 <b>Имя:</b> {progress.get('name', 'Не указано')}

<b>Модули:</b>
"""
    
    for i, module in enumerate(MODULES, 1):
        status = "✅" if i in progress.get('completed_modules', []) else "⏳"
        progress_text += f"{status} День {module['day']}: {module['title']}\n"
    
    progress_text += "\n<b>Продолжайте в том же духе! 💪</b>"
    
    await message.answer(progress_text, parse_mode=ParseMode.HTML)

# Хендлер команды /module
@dp.message(Command("module"))
async def cmd_module(message: Message, command: CommandObject, state: FSMContext):
    """
    Обработчик команды /module [номер]
    """
    try:
        if not command.args:
            await message.answer("Укажите номер модуля: /module 1")
            return
        
        module_num = int(command.args)
        if 1 <= module_num <= len(MODULES):
            await show_module(message, module_num - 1, state)
        else:
            await message.answer(f"❌ Модуль {module_num} не найден. Доступные модули: 1-{len(MODULES)}")
    except ValueError:
        await message.answer("❌ Неверный формат номера модуля. Используйте: /module 1")

# Функция отображения модуля
async def show_module(message: Message, module_index: int, state: FSMContext):
    """
    Показывает выбранный модуль
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
    
    # Отправляем сообщение
    if isinstance(message, CallbackQuery):
        await message.message.edit_text(
            module_text,
            reply_markup=get_navigation_keyboard(module_index, len(MODULES), user_id),
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer(
            module_text,
            reply_markup=get_navigation_keyboard(module_index, len(MODULES), user_id),
            parse_mode=ParseMode.HTML
        )

# Обработчик нажатия кнопок навигации
@dp.callback_query(F.data.startswith(("prev_", "next_", "module_")))
async def handle_navigation(callback: CallbackQuery, state: FSMContext):
    """
    Обработчик навигационных кнопок
    """
    try:
        if callback.data.startswith("prev_"):
            module_index = int(callback.data.split("_")[1])
        elif callback.data.startswith("next_"):
            module_index = int(callback.data.split("_")[1])
        elif callback.data.startswith("module_"):
            module_index = int(callback.data.split("_")[1])
        else:
            module_index = 0
        
        await show_module(callback, module_index, state)
        await callback.answer()
        
    except (ValueError, IndexError) as e:
        logger.error(f"Navigation error: {e}")
        await callback.answer("❌ Ошибка навигации", show_alert=True)

# Обработчик кнопки "Меню курса"
@dp.callback_query(F.data == "course_menu")
async def handle_course_menu(callback: CallbackQuery):
    """
    Показывает меню курса
    """
    await callback.message.edit_text(
        "<b>📋 Выберите модуль для изучения:</b>",
        reply_markup=get_main_menu_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

# Обработчик кнопки "Отметить пройденным"
@dp.callback_query(F.data.startswith("complete_"))
async def handle_complete_module(callback: CallbackQuery):
    """
    Отмечает модуль как пройденный
    """
    try:
        module_index = int(callback.data.split("_")[1])
        module_num = module_index + 1
        user_id = callback.from_user.id
        
        if user_id not in user_progress:
            user_progress[user_id] = {
                'start_date': datetime.now().isoformat(),
                'completed_modules': [],
                'last_module': module_index,
                'name': callback.from_user.first_name
            }
        
        if module_num not in user_progress[user_id]['completed_modules']:
            user_progress[user_id]['completed_modules'].append(module_num)
            await callback.answer(f"✅ Модуль {module_num} отмечен как пройденный!")
        else:
            await callback.answer("ℹ️ Этот модуль уже пройден")
        
        # Обновляем клавиатуру
        await callback.message.edit_reply_markup(
            reply_markup=get_navigation_keyboard(module_index, len(MODULES), user_id)
        )
        
    except Exception as e:
        logger.error(f"Complete module error: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

# Обработчик кнопки "Полезные ссылки"
@dp.callback_query(F.data == "useful_links")
async def handle_useful_links(callback: CallbackQuery):
    """
    Показывает полезные ссылки
    """
    links_text = "<b>🔗 Полезные ссылки:</b>\n\n"
    
    for name, url in ADDITIONAL_MATERIALS['links'].items():
        links_text += f"• <a href='{url}'>{name}</a>\n"
    
    await callback.message.answer(
        links_text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )
    await callback.answer()

# Обработчик кнопки "Контакты"
@dp.callback_query(F.data == "contacts")
async def handle_contacts(callback: CallbackQuery):
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
Пн-Пт: 9:00-18:00
Сб-Вс: выходной
    """
    
    await callback.message.answer(contacts_text, parse_mode=ParseMode.HTML)
    await callback.answer()

# Обработчик кнопки "Мой прогресс"
@dp.callback_query(F.data == "my_progress")
async def handle_my_progress(callback: CallbackQuery):
    """
    Показывает прогресс пользователя
    """
    user_id = callback.from_user.id
    
    if user_id not in user_progress:
        await callback.answer("❌ Вы еще не начали обучение", show_alert=True)
        return
    
    progress = user_progress[user_id]
    completed = len(progress.get('completed_modules', []))
    total = len(MODULES)
    
    progress_text = f"""
<b>📊 Ваш прогресс:</b>

✅ <b>Пройдено:</b> {completed}/{total} модулей
📈 <b>Процент завершения:</b> {completed/total*100:.1f}%

<b>Статус модулей:</b>
"""
    
    for i in range(1, total + 1):
        if i in progress.get('completed_modules', []):
            progress_text += f"✅ День {i}: {MODULES[i-1]['title']}\n"
        else:
            progress_text += f"⏳ День {i}: {MODULES[i-1]['title']}\n"
    
    await callback.message.answer(progress_text, parse_mode=ParseMode.HTML)
    await callback.answer()

# Обработчик кнопки "О курсе"
@dp.callback_query(F.data == "about")
async def handle_about(callback: CallbackQuery):
    """
    Показывает информацию о курсе
    """
    about_text = """
<b>ℹ️ О курсе "Тендеры с нуля":</b>

🎯 <b>Цель:</b> Подготовить участников к успешному участию в государственных и коммерческих тендерах.

<b>📅 Формат:</b>
• 5 дней интенсивного обучения
• 5 модулей с теорией и практикой
• Пошаговые инструкции
• Практические задания

<b>👥 Для кого:</b>
• Начинающие предприниматели
• Специалисты по закупкам
• Фрилансеры
• Все, кто хочет начать работать с госзаказом

<b>📚 Что вы получите:</b>
1. Системное понимание тендеров
2. Практические навыки участия
3. Шаблоны документов
4. Доступ к полезным ресурсам
5. План действий на 30 дней

<b>Авторы:</b> Команда экспертов с многолетним опытом в госзакупках
    """
    
    await callback.message.answer(about_text, parse_mode=ParseMode.HTML)
    await callback.answer()

# Обработчик кнопки "Оставить отзыв"
@dp.callback_query(F.data == "leave_feedback")
async def handle_leave_feedback(callback: CallbackQuery, state: FSMContext):
    """
    Начинает процесс оставления отзыва
    """
    await state.set_state(UserState.waiting_feedback)
    await callback.message.answer(
        "📝 Пожалуйста, напишите ваш отзыв о курсе:\n\n"
        "• Что понравилось?\n"
        "• Что можно улучшить?\n"
        "• Ваши пожелания\n\n"
        "<i>Отзыв будет отправлен разработчикам курса</i>",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

# Обработчик текстовых сообщений (для отзывов)
@dp.message(UserState.waiting_feedback)
async def handle_feedback_message(message: Message, state: FSMContext):
    """
    Обрабатывает отзыв пользователя
    """
    feedback = message.text
    user_name = message.from_user.full_name
    user_id = message.from_user.id
    
    # Здесь можно сохранить отзыв в базу данных или отправить на email
    # В данном примере просто логируем
    
    logger.info(f"Feedback from {user_name} (ID: {user_id}): {feedback}")
    
    await message.answer(
        "✅ Спасибо за ваш отзыв! Он очень важен для нас.\n\n"
        "Мы учтем ваши пожелания для улучшения курса!",
        reply_markup=get_main_menu_keyboard()
    )
    
    # Сбрасываем состояние
    await state.clear()

# Обработчик всех остальных сообщений
@dp.message()
async def handle_other_messages(message: Message):
    """
    Обработчик всех прочих сообщений
    """
    await message.answer(
        "🤖 Я бот для обучения тендерам!\n\n"
        "Используйте команды:\n"
        "/start - Начать обучение\n"
        "/menu - Открыть меню\n"
        "/help - Помощь\n"
        "/progress - Ваш прогресс",
        reply_markup=get_main_menu_keyboard()
    )

# Функция запуска бота
async def main():
    """
    Основная функция запуска бота
    """
    logger.info("Starting tender bot...")
    
    # Проверяем токен
    try:
        bot_info = await bot.get_me()
        logger.info(f"Bot started: @{bot_info.username}")
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        return
    
    # Запускаем поллинг
    await dp.start_polling(bot)

# Точка входа
if __name__ == "__main__":
    asyncio.run(main())