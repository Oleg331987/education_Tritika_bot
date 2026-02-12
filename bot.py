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
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

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
        self.init_admins_from_env()
    
    def load_data(self):
        """Загружает данные об администраторах и оплативших пользователях"""
        try:
            if os.path.exists(self.admins_file):
                with open(self.admins_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.admins = set(data.get("admins", []))
                    logger.info(f"Загружено {len(self.admins)} администраторов из файла")
            
            if os.path.exists(self.paid_users_file):
                with open(self.paid_users_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.paid_users = set(data.get("paid_users", []))
                    logger.info(f"Загружено {len(self.paid_users)} оплативших пользователей из файла")
                    
        except Exception as e:
            logger.error(f"Ошибка загрузки данных доступа: {e}")
            self.admins = set()
            self.paid_users = set()
    
    def init_admins_from_env(self):
        """Инициализирует администраторов из переменной окружения"""
        try:
            initial_admins = os.getenv('INITIAL_ADMINS', '')
            logger.info(f"Переменная INITIAL_ADMINS из .env: '{initial_admins}'")
            
            if initial_admins:
                admin_ids = []
                for admin_str in initial_admins.split(','):
                    admin_str = admin_str.strip()
                    if admin_str:
                        try:
                            admin_id = int(admin_str)
                            admin_ids.append(admin_id)
                        except ValueError:
                            logger.warning(f"Некорректный ID администратора: {admin_str}")
                
                logger.info(f"Найдены ID администраторов из .env: {admin_ids}")
                
                added_count = 0
                for admin_id in admin_ids:
                    if self.add_admin(admin_id):
                        added_count += 1
                        logger.info(f"Добавлен администратор из .env: {admin_id}")
                    else:
                        logger.info(f"Администратор {admin_id} уже существует")
                
                logger.info(f"Всего добавлено администраторов из .env: {added_count}")
            else:
                logger.warning("Переменная INITIAL_ADMINS не установлена в .env файле")
                
        except Exception as e:
            logger.error(f"Ошибка при инициализации администраторов из .env: {e}")
    
    def save_admins(self):
        """Сохраняет список администраторов"""
        try:
            with open(self.admins_file, 'w', encoding='utf-8') as f:
                json.dump({"admins": list(self.admins)}, f, ensure_ascii=False, indent=2)
            logger.info(f"Сохранено {len(self.admins)} администраторов в файл")
        except Exception as e:
            logger.error(f"Ошибка сохранения администраторов: {e}")
    
    def save_paid_users(self):
        """Сохраняет список оплативших пользователей"""
        try:
            with open(self.paid_users_file, 'w', encoding='utf-8') as f:
                json.dump({"paid_users": list(self.paid_users)}, f, ensure_ascii=False, indent=2)
            logger.info(f"Сохранено {len(self.paid_users)} оплативших пользователей в файл")
        except Exception as e:
            logger.error(f"Ошибка сохранения оплативших пользователей: {e}")
    
    def is_admin(self, user_id: int) -> bool:
        """Проверяет, является ли пользователь администратором"""
        result = user_id in self.admins
        logger.debug(f"Проверка прав администратора для {user_id}: {result}")
        return result
    
    def is_paid_user(self, user_id: int) -> bool:
        """Проверяет, есть ли у пользователя доступ"""
        # Администраторы автоматически получают доступ к курсу
        result = user_id in self.paid_users or user_id in self.admins
        logger.debug(f"Проверка доступа для {user_id}: {result}")
        return result
    
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

# Функции для работы с прогрессом пользователей
USER_PROGRESS_FILE = "user_progress.json"

def load_user_progress():
    """Загружает прогресс пользователей из файла"""
    try:
        if os.path.exists(USER_PROGRESS_FILE):
            with open(USER_PROGRESS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Преобразуем ключи из строк в целые числа (ID пользователей)
                return {int(k): v for k, v in data.items()}
        return {}
    except Exception as e:
        logger.error(f"Ошибка загрузки прогресса пользователей: {e}")
        return {}

def save_user_progress():
    """Сохраняет прогресс пользователей в файл"""
    try:
        with open(USER_PROGRESS_FILE, 'w', encoding='utf-8') as f:
            json.dump(user_progress, f, ensure_ascii=False, indent=2)
        logger.info(f"Сохранен прогресс для {len(user_progress)} пользователей")
    except Exception as e:
        logger.error(f"Ошибка сохранения прогресса пользователей: {e}")

# Загружаем прогресс пользователей при запуске и периодически сохраняем
user_progress = load_user_progress()

# Автоматическое сохранение прогресса каждые 5 минут
async def auto_save_progress():
    """Периодически сохраняет прогресс пользователей"""
    while not shutdown_flag:
        await asyncio.sleep(300)  # 5 минут
        try:
            save_user_progress()
            logger.info("Автосохранение прогресса пользователей")
        except Exception as e:
            logger.error(f"Ошибка при автосохранении прогресса: {e}")

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
        # Сохраняем прогресс перед завершением
        save_user_progress()
        logger.info("Прогресс пользователей сохранен перед завершением")
        
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
        sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

# =========== ИНИЦИАЛИЗАЦИЯ БОТА ===========
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    logger.error("BOT_TOKEN не установлен! Установите переменную окружения в .env файле.")
    sys.exit(1)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class UserState(StatesGroup):
    viewing_module = State()
    waiting_feedback = State()
    taking_test = State()
    test_question = State()
    admin_add_user = State()
    admin_remove_user = State()

AUDIO_CONFIG = {
    "base_path": "audio/",
    "default_format": ".mp3",
}

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
        "title": "44-ФЗ",
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
10. 📑 Обеспечение гарантийных обязательств (при необходимости)
11. 📝 Электронное актирование

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
        "title": "223-ФЗ",
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
2. 📊 Требуется предоставить релевантный опыт работы и квалификацию
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
• Конкурсы

<b>Неконкурентные:</b>
• Прямые закупки у единственного поставщика
• Уникальные товары/услуги
• Срочные закупки

✅ <b>Где искать закупки:</b>
1. 🌐 Корпоративные порталы компаний (разделы «Закупки», «Для поставщиков»)
2. 🏪 Специализированные площадки:
   • B2B-Center: https://www.b2b-center.ru
   • Bidzaar: https://bidzaar.com
   • Tender PRO: https://www.tender.pro
   • СберB2B: https:/sberb2b.ru
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
        "task": "Составить список потенциальных заказчиков и зарегистрироваться на B2B-Center",
        "audio_file": "module4.mp3",
        "audio_duration": 165,
        "audio_title": "Стратегии работы с коммерческими заказчиками",
        "has_audio": True
    },
    {
        "id": 5,
        "day": 5,
        "title": "Банковские гарантии в тендерах",
        "emoji": "🏦",
        "content": """<b>🏦 День 5 | Модуль 5: Банковские гарантии в тендерах</b>

✅ <b>Что такое банковская гарантия (БГ)?</b>
Это документ, подтверждающий готовность банка отвечать за исполнение взятых на себя обязательств одной из сторон договора. Гарантия выдаётся по просьбе исполнителя. Если поставщик нарушает условия, указанные в БГ, банк выплатит заказчику договорную сумму.

Проще говоря: Банк выступает вашим поручителем перед заказчиком.

✅ <b>Зачем нужна банковская гарантия в тендерах?</b>

1. <b>Обеспечение заявки</b> — сумма, которая выступает в роли гарантии для участия в тендере.

2. <b>Обеспечение исполнения контракта</b> — гарантия выполнения обязательств по договору.

3. <b>Обеспечение гарантийных обязательств</b> — обеспечивает качество товара, работ или услуг и распространяется на весь гарантийный период.

Обеспечение заявки требуется на этапе подачи заявки и обычно составляет 0,5–5% от начальной цены контракта (НМЦК). Действует до подписания контракта.

Обеспечение исполнения контракта же требуется после победы в тендере и составляет 5–30% от цены контракта. Действует до полного выполнения контракта.

✅ <b>Кто может выдавать банковские гарантии?</b>
Только банки, включённые в Перечень Минфина. Актуальный список можно найти на сайте Минфина.

✅ <b>Как получить банковскую гарантию?</b>

1. Обратитесь в компанию 
ООО "БИЗНЕС-ПОДДЕРЖКА":
сайт - банк-гарантия.рф
телефон: 8 800 600 04 60
e-mail: garant@bzgarant.com
   
Приглашаем к сотрудничеству! Вы с нами оформляете БГ и получаете вознаграждение по каждой сделке. 
Пишите «% за БГ» в ТГ @malkovabzgarant и мы расскажем как.

2. Пришлите необходимые документы для подачи заявки

3. Получите гарантию в электронном виде.

✅ <b>Ключевые требования к банковской гарантии:</b>

1. Безотзывная
2. Содержит все обязательные условия (сумма, срок, реквизиты сторон)
3. Внесена в реестр банковских гарантий
4. Соответствует установленной форме.

🔗 <b>Полезные ссылки:</b>
• Перечень банков на сайте Минфина: https://minfin.gov.ru/ru/perfomance/tender/banks/
• ЕИС: https://zakupki.gov.ru""",
        "task": "Найдите в ЕИС (zakupki.gov.ru) 2-3 тендера, где требуется обеспечение заявки или обеспечение исполнения контракта. Изучите, в какой форме требуется обеспечение (деньги или БГ). Ознакомьтесь с примером банковской гарантии на сайте Минфина или в личном кабинете банка (например, Сбер, ВТБ, Тинькофф).",
        "audio_file": "module5.mp3",
        "audio_duration": 180,
        "audio_title": "Банковские гарантии в тендерах: как снизить риски",
        "has_audio": True
    },
    {
        "id": 6,
        "day": 6,
        "title": "Практический старт",
        "emoji": "🚀",
        "content": """<b>🚀 День 6 | Модуль 6: Практический старт</b>

✅ <b>Пошаговый план действий:</b>

1. <b>Получите ЭЦП:</b>
   • Для ООО/ИП — в Налоговом органе
   • Для ФЛ - в аккредитованном УЦ (https://uc-itcom.ru)
   • оформить УКЭП физлица и машиночитаемую доверенность (МЧД) на сотрудника компании

2. <b>Настройте рабочее место:</b>
   • Установите КриптоПРО CSP
   • Настройте браузер Chromium-Gost
   • Установите Рутокен Драйвер
   • Установите плагины КриптоПро ЭЦП Browser plug-in, плагин ГИС НР, плагин ГосУслуг

3. <b>Зарегистрируйтесь в системах:</b>
   • Госуслуги (ЕИА): https://www.gosuslugi.ru - добавьте организацию
   • ЕИС: https://zakupki.gov.ru - зарегистрируйте организацию
   
4. <b>Откройте спецсчет</b> для обеспечения заявок

5. <b>Настройте поиск</b> по вашим товарам/услугам

✅ <b>Начните с малого:</b>
1. Выберите 1-2 простых тендера
2. Изучите ВСЮ документации
3. Подготовьте заявку строго по требованиям
4. Не бойтесь писать запросы на разъяснения заказчику

❌ <b>Ключевые ошибки новичков:</b>
1. Пропустить требование в документации
2. Неправильно заполнить заявку
3. Опоздать с подачей
4. Не внести обеспечение заявки на участие
5. Бояться писать запросы заказчику

🎯 <b>Ваш первый тендер — это ценный опыт, даже если не победите!</b>""",
        "task": "Составить пошаговый план действий",
        "audio_file": "module6.mp3",
        "audio_duration": 210,
        "audio_title": "Практический план: первые шаги в тендерах",
        "has_audio": True
    },
    {
        "id": 7,
        "day": 7,
        "title": "Итоги курса",
        "emoji": "🏆",
        "content": """<b>🏆 День 7 | Модуль 7: Итоги курса</b>

✅ <b>Итоги курса:</b>

После прохождения вы знаете:
1. Разницу между 44-ФЗ, 223-ФЗ и коммерческими закупками
2. Основные шаги для участия
3. Где искать информацию и тендеры
4. Практический план действий

🎯 <b>Ваш следующий шаг — ДЕЙСТВИЕ!</b>

✅ <b>Чек-лист "Первые 10 шагов в тендерах"</b>

Ваш пошаговый план для старта в течение недели:

<b>✅ Шаг 1: Анализ возможностей</b>
1. Определили, какие свои товары/услуги вы можете предлагать через тендеры.
2. Выяснили коды ОКПД2/ОКВЭД2 для своего вида деятельности.

<b>✅ Шаг 2: Изучение рынка</b>
1. Провели разведку на zakupki.gov.ru: посмотрели, какие закупки есть по вашим товарам/работам/услугам, кто основные заказчики и конкуренты.
2. Проанализировали итоговые цены участников и процент снижения.

<b>✅ Шаг 3: Подготовка документов компании, открытие спецсчета</b>
1. Проверили, что все учредительные документы (Устав, выписка из ЕГРЮЛ/ЕГРИП и др.) актуальны.
2. Открыли спецсчет для обеспечения заявки.
3. Подготовили необходимые документы.

<b>✅ Шаг 4: Получение электронной цифровой подписи (ЭЦП), установка ПО, регистрация в ЕСИА</b>
1. Получили квалифицированную электронную цифровую подпись (КЭП).
2. Если на порталах действует сотрудник от своего имени, оформили на него КЭП физлица и машиночитаемую доверенность (МЧД).
3. Зарегистрировали участника на сайте госуслуг (в ЕСИА).
4. Установили ПО (КриптоПРО CSP, плагин КриптоПро, плагин ГИС НР, рутокен драйвер, браузер Chromium-Gost).

<b>✅ Шаг 5: Аккредитация на электронных торговых площадках (ЭТП)</b>
1. Подали заявку на аккредитацию в личном кабинете участника ЕИС.
2. Дождались подтверждения аккредитации (обычно до 5 рабочих дней).

<b>✅ Шаг 6: Выбор первой закупки</b>
1. Нашли на zakupki.gov.ru подходящую закупку по 44-ФЗ (например, "Запрос котировок"), 223-ФЗ с небольшим объемом и простыми требованиями или коммерческий тендер.
2. Внесли ее в свой план-календарь, отметив дату и время окончания подачи заявок.

<b>✅ Шаг 7: Детальное изучение документации</b>
1. Скачали и внимательно прочитали всю документацию по выбранной закупке.
2. Выделили цветом ключевые разделы: техническое задание, требования к участникам, критерии оценки, информационная карта.

<b>✅ Шаг 8: Подготовка и подача заявки</b>
1. Собрали все документы, требуемые в заявке (по перечню из документации).
2. Заполнили все формы на электронной площадке.
3. Внесли денежные средства на спецсчет или подали заявку на получение банковской гарантии (БГ) для обеспечения заявки.
4. Отправили заявки ЗАРАНЕЕ, минимум за 1 день до окончания срока.

<b>✅ Шаг 9: Участие в процедуре</b>
1. Если это аукцион, изучили инструкцию площадки и приняли в нем участие в установленное время.
2. Следили за протоколами на ЭТП и на zakupki.gov.ru.

<b>✅ Шаг 10: Работа с итогами</b>
1. В случае победы: получили проект контракта от заказчика, проверили его, внесли денежные средства или оформили банковскую гарантию (БГ) на обеспечение исполнения контракта. Приложили необходимые документы, подписали контракт и приступили к исполнению.
2. В случае проигрыша: проанализировали протоколы, чтобы понять, кто победил, по какой цене и почему. Сделали выводы для подготовки следующей заявки.

<b>Важно:</b> Не пытайтесь сделать все шаги за один день! Разбейте план на 5-7 рабочих дней. Главное — начать и пройти весь путь от выбора закупки до подачи заявки.

📥 <b>ДОПОЛНИТЕЛЬНЫЙ МАТЕРИАЛ:</b>

Мы подготовили для вас <b>готовый чек-лист в формате Word</b>, который вы можете:
• 📁 Сохранить на компьютер
• 🖨️ Распечатать и отмечать шаги
• 📱 Держать открытым на телефоне или планшете
• 📎 Использовать как памятку при работе

<b>Чтобы скачать чек-лист, нажмите кнопку "📥 Скачать чек-лист" в главном меню!</b>

Файл содержит те же 10 шагов, но в удобном для работы формате с возможностью делать пометки.

🎁 <b>А в следующем, 8-м модуле, вас ждут специальные подарки и бонусы для выпускников курса!</b>""",
        "task": "Составить план действий на первую неделю по чек-листу",
        "audio_file": "module7.mp3",
        "audio_duration": 180,
        "audio_title": "Итоги курса: чек-лист первых шагов и план действий",
        "has_audio": True
    },
    {
        "id": 8,
        "day": 8,
        "title": "Подарки",
        "emoji": "🎁",
        "content": """<b>🎁 День 8 | Модуль 8: Подарки для наших выпускников</b>

Поздравляем с завершением курса «Тендеры с нуля»! Вы сделали важный шаг к новым победам. Мы в «Тритике» ценим наших учеников и подготовили для вас специальные бонусы и выгодные предложения, которые помогут применить знания на практике с максимальной эффективностью.

Чтобы поддержать вас на старте, мы предоставляем эксклюзивную <b>скидку 10% на первую услугу из следующего списка</b>:

<b>🎯 Услуга: Сопровождение одного конкретного тендера</b>
<b>✅ Ваша выгода:</b> Скидка на первое сопровождение
<b>📋 Краткое описание:</b> Идеально для старта. Вы выбираете тендер, а наши эксперты помогут подготовить и подать заявку «под ключ», избегая ошибок.

<b>🎯 Услуга: Консультация по стратегии участия</b>
<b>✅ Ваша выгода:</b> Бесплатно в течение 30 дней после завершения курса
<b>📋 Краткое описание:</b> Обсудите с нашим специалистом первые шаги, выбор тендеров и план действий для вашей компании.

<b>📞 Как воспользоваться:</b>
Свяжитесь с нами по телефону <b>+7 (4922) 223-222</b> или напишите на <b>info@tritika.ru</b>, указав в теме письма <b>«Выпускник экспресс-курса, ФИО»</b>.

<b>💡 Теперь у вас есть знания, поддержка и выгодные условия для первых побед. Мы будем рады помочь вам в этом!</b>

<b>🏆 Команда «Тритики» желает вам успешных тендеров и выгодных контрактов!</b>

<b>📌 Контакты для связи:</b>
• Телефон: +7 (4922) 223-222
• Мобильный: +7-904-653-69-87
• Email: info@tritika.ru
• Сайт: https://tritika.ru
• Телеграм: @tritikaru

<b>🎯 Не откладывайте на завтра то, что можно сделать сегодня! Ваш первый тендер ждет вас!</b>""",
        "task": "Связаться с нами для получения подарков по контактам выше",
        "audio_file": "module8.mp3",
        "audio_duration": 150,
        "audio_title": "Подарки для выпускников курса",
        "has_audio": True
    }
]

TEST_QUESTIONS = [
    {
        "id": 1,
        "question": "Какой федеральный закон регулирует закупки государственных бюджетных учреждений (например, администрации города, больницы, школы) и характеризуется принципом максимальной экономии и прозрачности?",
        "options": {
            "а": "223-ФЗ",
            "б": "Гражданский кодекс РФ",
            "в": "44-ФЗ",
            "г": "94-ФЗ"
        },
        "correct": "в",
        "correct_text": "в) 44-ФЗ"
    },
    {
        "id": 2,
        "question": "Основное отличие закупок по 223-ФЗ от закупок по 44-ФЗ заключается в том, что:",
        "options": {
            "а": "У каждого заказчика по 223-ФЗ есть собственное Положение о закупке, которое нужно изучать в первую очередь.",
            "б": "Закупки по 223-ФЗ всегда проводятся в виде аукциона.",
            "в": "Для участия в закупках по 223-ФЗ не требуется электронная подпись.",
            "г": "Закупки по 223-ФЗ не размещаются на официальных сайтах."
        },
        "correct": "а",
        "correct_text": "а) У каждого заказчика по 223-ФЗ есть собственное Положение о закупке, которое нужно изучать в первую очередь."
    },
    {
        "id": 3,
        "question": "Какой способ закупки по 44-ФЗ является самым популярным, где побеждает участник, предложивший самую низкую цену?",
        "options": {
            "а": "Открытый конкурс",
            "б": "Запрос котировок",
            "в": "Электронный аукцион",
            "г": "Закрытый конкурс"
        },
        "correct": "в",
        "correct_text": "в) Электронный аукцион"
    },
    {
        "id": 4,
        "question": "Каков правильный порядок первоначальных шагов для начала участия в электронных торгах по 44-ФЗ и 223-ФЗ?",
        "options": {
            "а": "Подать заявку на тендер → Изучить документацию → Получить электронную подпись",
            "б": "Получить электронную подпись → Пройти аккредитацию на электронных торговых площадках (ЭТП) → Найти закупку",
            "в": "Найти закупку → Заключить контракт → Внести обеспечение заявки",
            "г": "Аккредитоваться на ЭТП → Участвовать в аукционе → Получить электронную подпись"
        },
        "correct": "б",
        "correct_text": "б) Получить электронную подпись → Пройти аккредитацию на электронных торговых площадках (ЭТП) → Найти закупку"
    },
    {
        "id": 5,
        "question": "Какая из перечисленных ошибок является самой типичной для новичка в тендерах?",
        "options": {
            "а": "Слишком детальное изучение технического задания.",
            "б": "Задать уточняющий вопрос заказчику.",
            "в": "Пропустить мелкое требование в документации или не вовремя подать заявку.",
            "г": "Анализ результатов прошлых закупок."
        },
        "correct": "в",
        "correct_text": "в) Пропустить мелкое требование в документации или не вовремя подать заявку."
    },
    {
        "id": 6,
        "question": "Для коммерческие тендеры (например, закупки крупной частной компании) характерно:",
        "options": {
            "а": "Строгое регулирование по 44-ФЗ.",
            "б": "Главный и единственный критерий победы — самая низкая цена.",
            "в": "Правила устанавливает сама компания-заказчик, сильно ценится репутация.",
            "г": "Все результаты и процедуры всегда публичны и не могут быть оспорены."
        },
        "correct": "в",
        "correct_text": "в) Правила устанавливает сама компания-заказчик, сильно ценится репутация."
    },
    {
        "id": 7,
        "question": "Какой официальный сайт является единой точкой для поиска информации о закупки по 44-ФЗ и 223-ФЗ?",
        "options": {
            "а": "b2b-center.ru",
            "б": "sberbank-ast.ru",
            "в": "zakupki.gov.ru",
            "г": "roseltorg.ru"
        },
        "correct": "в",
        "correct_text": "в) zakupki.gov.ru"
    },
    {
        "id": 8,
        "question": "Рекомендуемая стратегия для первых шагов в тендерах — это:",
        "options": {
            "а": "Сразу участвовать в 10 крупных конкурсах.",
            "б": "Выбрать 1-2 простых тендера с минимальными требованиями для получения опыта.",
            "в": "Ждать, пока заказчик сам найдет вас и предложит контракт.",
            "г": "Участвовать только в коммерческих тендерах, игнорируя государственные."
        },
        "correct": "б",
        "correct_text": "б) Выбрать 1-2 простых тендера с минимальными требованиями для получения опыта."
    }
]

ADDITIONAL_MATERIALS = {
    "links": {
        "ЕИС": "https://zakupki.gov.ru",
        "Госуслуги": "https://www.gosuslugi.ru",
        "B2B-Center": "https://www.b2b-center.ru",
        "КонсультантПлюс 44-ФЗ": "https://www.consultant.ru/document/cons_doc_LAW_144624/",
        "Удостоверяющий центр": "https://uc-itcom.ru",
        "Техподдержка курса": "https://tritika.ru",
        "Политика конфиденциальности": "https://tritika.ru/privacy-policy/"
    },
    "contacts": {
        "email": "info@tritika.ru",
        "phone": "+7(4922)223-222",
        "mobile": "+7-904-653-69-87",
        "website": "https://tritika.ru",
        "telegram": "@tritikaru"
    }
}

# =========== КЛАВИАТУРЫ ===========
def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """
    Создает фиксированную клавиатуру в зависимости от статуса пользователя
    """
    is_paid = access_control.is_paid_user(user_id)
    
    if is_paid:
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
        
        if access_control.is_admin(user_id):
            keyboard.keyboard.append([KeyboardButton(text="👥 Управление доступом")])
    else:
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

def get_lesson_navigation_keyboard(current_index: int, total_modules: int) -> ReplyKeyboardMarkup:
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

def get_lessons_list_keyboard() -> ReplyKeyboardMarkup:
    keyboard_rows = []
    
    for module in MODULES:
        audio_icon = "🎧 " if module.get("has_audio", False) else ""
        keyboard_rows.append([
            KeyboardButton(text=f"{module['emoji']} {audio_icon}День {module['day']}: {module['title'][:20]}")
        ])
    
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

def get_after_test_keyboard() -> ReplyKeyboardMarkup:
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

# =========== АУДИО МЕНЕДЖЕР ===========
class AudioManager:
    """Менеджер для работы с аудиофайлами"""
    
    def __init__(self, bot: Bot):
        self.bot = bot
    
    @staticmethod
    def get_audio_path(module_index: int) -> Optional[str]:
        """Получить путь к аудиофайлу модуля"""
        if 0 <= module_index < len(MODULES):
            module = MODULES[module_index]
            audio_file = module.get("audio_file")
            if audio_file:
                audio_path = os.path.join(AUDIO_CONFIG["base_path"], audio_file)
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
    
    async def send_module_audio(self, chat_id: int, module_index: int, user_id: int) -> bool:
        """Отправить аудио сопровождение для модуля с inline-кнопкой для отметки"""
        try:
            audio_path = AudioManager.get_audio_path(module_index)
            if not audio_path:
                logger.warning(f"No audio for module {module_index}")
                return False
            
            module = MODULES[module_index]
            audio_info = AudioManager.get_audio_info(module_index)
            
            audio_file = FSInputFile(audio_path)
            
            caption = f"🎧 <b>{module['emoji']} Аудио-сопровождение к модулю {module_index + 1}</b>\n"
            caption += f"<b>{module['title']}</b>\n\n"
            caption += f"⏱ <b>Длительность:</b> {audio_info['duration']//60}:{audio_info['duration']%60:02d}\n"
            caption += f"📚 <b>Описание:</b> {audio_info['title']}\n\n"
            
            is_completed = False
            if user_id in user_progress:
                is_completed = (module_index + 1) in user_progress[user_id].get('completed_modules', [])
            
            if is_completed:
                caption += "✅ <b>Этот модуль уже отмечен как пройденный</b>\n\n"
            else:
                caption += "🔘 <b>Нажмите кнопку ниже, чтобы отметить модуль как пройденный после прослушивания:</b>\n\n"
            
            caption += "<i>Рекомендуем прослушать аудио для лучшего усвоения материала</i>"
            
            inline_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="✅ Отметить модуль как пройденный", 
                    callback_data=f"done_{module_index}"
                )]
            ])
            
            await self.bot.send_audio(
                chat_id=chat_id,
                audio=audio_file,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=inline_kb
            )
            
            logger.info(f"Audio sent for module {module_index + 1} to chat {chat_id} with inline button")
            return True
            
        except Exception as e:
            logger.error(f"Error sending audio for module {module_index}: {e}")
            return False

audio_manager = AudioManager(bot)

# =========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===========
async def show_module(message: Message, module_index: int, state: FSMContext):
    """
    Показывает выбранный модуль и автоматически отправляет аудио сопровождение
    """
    module = MODULES[module_index]
    user_id = message.from_user.id
    
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к этому модулю. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
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
        module_text += "\n<i>После прослушивания аудио нажмите кнопку в аудио-сообщении выше</i>"
    
    await message.answer(
        module_text,
        reply_markup=get_lesson_navigation_keyboard(module_index, len(MODULES)),
        parse_mode=ParseMode.HTML
    )
    
    audio_sent = await audio_manager.send_module_audio(message.chat.id, module_index, user_id)
    
    if not audio_sent and module.get("has_audio", False):
        await message.answer(
            "❌ Аудио сопровождение временно недоступно. Попробуйте позже.",
            parse_mode=ParseMode.HTML
        )

async def start_test_internal(message: Message, state: FSMContext):
    """
    Внутренняя функция запуска теста
    """
    user_id = message.from_user.id
    
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к тесту. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
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

async def process_test_answer(message: Message, state: FSMContext, answer: str):
    """
    Обрабатывает ответ на вопрос теста
    """
    user_id = message.from_user.id
    
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к тесту. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    data = await state.get_data()
    test_data = data.get("test_data", {})
    current_question = test_data.get("current_question", 0)
    
    if current_question >= len(TEST_QUESTIONS):
        return
    
    question = TEST_QUESTIONS[current_question]
    test_data["answers"][question["id"]] = answer
    await state.update_data(test_data=test_data)
    
    next_question = current_question + 1
    
    if next_question < len(TEST_QUESTIONS):
        await send_test_question(message, state, next_question)
    else:
        await finish_test(message, state)

async def send_final_summary(message: Message):
    """
    Отправляет финальное аудио и итоги курса после теста
    """
    user_id = message.from_user.id
    
    if not access_control.is_paid_user(user_id):
        return
    
    # Отправляем аудио 8-го модуля (подарки)
    final_audio_sent = await audio_manager.send_module_audio(message.chat.id, 7, user_id)
    
    # Отправляем содержание 8-го модуля
    module = MODULES[7]
    module_text = module['content']
    
    await message.answer(
        module_text,
        parse_mode=ParseMode.HTML
    )
    
    if not final_audio_sent:
        await message.answer(
            "🎧 <b>Примечание:</b> Аудио сопровождение временно недоступно. Вы можете прослушать его позже через меню курса.",
            parse_mode=ParseMode.HTML
        )

async def finish_test(message: Message, state: FSMContext):
    """
    Завершает тест и показывает результаты
    """
    user_id = message.from_user.id
    
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к тесту. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    data = await state.get_data()
    test_data = data.get("test_data", {})
    
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
    
    if correct_answers >= 7:
        grade = "Отлично! Вы прекрасно усвоили материал курса и готовы к первым шагам в мире тендеров."
    elif correct_answers >= 5:
        grade = "Хорошо. Вы поняли основные принципы, но рекомендуем еще раз повторить модули, где были допущены ошибки."
    else:
        grade = "Не переживайте! Вернитесь к материалам экспресс-курса и уделите внимание основам (модули 1-3). Практика и повторение — ключ к успеху!"
    
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
    
    save_user_progress()
    
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
    
    if correct_answers >= 5:
        result_text += "\n\n🎉 <b>ПОЗДРАВЛЯЕМ С УСПЕШНЫМ ПРОХОЖДЕНИЕМ КУРСА И ТЕСТА!</b> 🎉"
        result_text += "\n\n✅ Вы освоили основы тендерной системы"
        result_text += "\n✅ Вы готовы к первым шагам в мире тендеров"
        result_text += "\n✅ У вас есть практический план действий"
        result_text += "\n✅ Вы знаете, где искать закупки и как участвовать"
        result_text += "\n\n<b>Теперь ваша очередь действовать! Первый шаг — самый важный!</b>"
    
    await message.answer(
        result_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_after_test_keyboard()
    )
    
    await state.clear()

# =========== ОБРАБОТЧИКИ CALLBACK QUERY ===========
@dp.callback_query(lambda c: c.data.startswith('done_'))
async def handle_mark_completed_callback(callback_query: CallbackQuery, state: FSMContext):
    """
    Обрабатывает нажатие на кнопку "✅ Отметить модуль как пройденный" в аудио-сообщении
    """
    user_id = callback_query.from_user.id
    
    if not access_control.is_paid_user(user_id):
        await callback_query.answer(
            "❌ У вас нет доступа к курсу. Для получения доступа оплатите подписку.",
            show_alert=True
        )
        return
    
    try:
        module_index = int(callback_query.data.split('_')[-1])
    except ValueError:
        await callback_query.answer(
            "❌ Ошибка при обработке запроса.",
            show_alert=True
        )
        return
    
    if module_index < 0 or module_index >= len(MODULES):
        await callback_query.answer(
            "❌ Неверный номер модуля.",
            show_alert=True
        )
        return
    
    if user_id not in user_progress:
        user_progress[user_id] = {
            'start_date': datetime.now().isoformat(),
            'completed_modules': [],
            'last_module': module_index,
            'name': callback_query.from_user.first_name,
            'audio_listened': [],
            'test_results': []
        }
    
    module_num = module_index + 1
    
    if module_num in user_progress[user_id]['completed_modules']:
        await callback_query.answer(
            "ℹ️ Этот модуль уже отмечен как пройденный!",
            show_alert=True
        )
        return
    
    user_progress[user_id]['completed_modules'].append(module_num)
    
    if module_num not in user_progress[user_id].get('audio_listened', []):
        user_progress[user_id].setdefault('audio_listened', []).append(module_num)
    
    user_progress[user_id]['last_module'] = module_index
    
    save_user_progress()
    
    await callback_query.answer(
        f"✅ Модуль {module_num} успешно отмечен как пройденный!",
        show_alert=True
    )
    
    try:
        module = MODULES[module_index]
        audio_info = AudioManager.get_audio_info(module_index)
        
        updated_caption = f"🎧 <b>{module['emoji']} Аудио-сопровождение к модулю {module_index + 1}</b>\n"
        updated_caption += f"<b>{module['title']}</b>\n\n"
        updated_caption += f"⏱ <b>Длительность:</b> {audio_info['duration']//60}:{audio_info['duration']%60:02d}\n"
        updated_caption += f"📚 <b>Описание:</b> {audio_info['title']}\n\n"
        updated_caption += "✅ <b>Этот модуль отмечен как пройденный!</b>\n\n"
        updated_caption += "<i>Вы можете прослушать аудио еще раз для повторения</i>"
        
        await callback_query.message.edit_caption(
            caption=updated_caption,
            parse_mode=ParseMode.HTML,
            reply_markup=None
        )
        
    except Exception as e:
        logger.error(f"Error updating audio message: {e}")
    
    completed = len(user_progress[user_id]['completed_modules'])
    total = len(MODULES)
    
    if completed >= 7 and not user_progress[user_id].get('test_results'):
        try:
            await callback_query.message.answer(
                "🎉 <b>Поздравляем! Вы завершили основные модули курса!</b>\n\n"
                "📝 <b>Теперь вы можете пройти финальный тест для проверки знаний:</b>\n"
                "1. Проверить свои знания\n"
                "2. Получить оценку\n"
                "3. Увидеть рекомендации по улучшению\n\n"
                "Нажмите кнопку '📝 Пройти тест' в главном меню!",
                parse_mode=ParseMode.HTML
            )
        except:
            pass
    elif completed == total:
        try:
            await callback_query.message.answer(
                "🎉 <b>Поздравляем! Вы завершили все модули курса, включая бонусный!</b>\n\n"
                "📝 <b>Если вы еще не проходили финальный тест, нажмите кнопку '📝 Пройти тест' в главном меню!</b>\n"
                "🎁 <b>А если уже прошли, то надеемся, что вам понравились подарки в 8 дне!</b>",
                parse_mode=ParseMode.HTML
            )
        except:
            pass

# =========== КОМАНДЫ ===========
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """
    Обработчик команды /start - ОСНОВНОЙ
    """
    try:
        user_id = message.from_user.id
        user_name = message.from_user.first_name or "Пользователь"
        
        logger.info(f"📱 /start от пользователя {user_id} ({user_name})")
        
        # Инициализируем прогресс, если пользователь новый
        if user_id not in user_progress:
            user_progress[user_id] = {
                'start_date': datetime.now().isoformat(),
                'completed_modules': [],
                'last_module': 0,
                'name': user_name,
                'audio_listened': [],
                'test_results': []
            }
            save_user_progress()
            logger.info(f"✅ Создан новый профиль для {user_id}")
        
        # Проверяем права доступа
        is_admin = access_control.is_admin(user_id)
        is_paid = access_control.is_paid_user(user_id)
        
        logger.info(f"🔑 Права пользователя {user_id}: admin={is_admin}, paid={is_paid}")
        
        # Очищаем состояние
        await state.clear()
        
        # Формируем приветственное сообщение
        if is_admin:
            # Администратор
            admin_text = f"""
<b>👑 Привет, Администратор {user_name}!</b>

Добро пожаловать в панель управления ботом!

<b>Ваши права:</b>
• Полный доступ ко всем {len(MODULES)} урокам курса
• Управление доступом пользователей
• Добавление/удаление администраторов
• Просмотр статистики
• Рассылка сообщений

<b>Используйте кнопки внизу для навигации!</b>
"""
            await message.answer(admin_text, 
                               reply_markup=get_admin_keyboard(),
                               parse_mode=ParseMode.HTML)
            
        elif is_paid:
            # Оплативший пользователь
            paid_text = f"""
<b>👋 Привет, {user_name}!</b>

Добро пожаловать на <b>Экспресс-курс: "Тендеры с нуля"</b>!

✅ <b>Ваш доступ активирован!</b>

<b>Доступные функции:</b>
• 📚 {len(MODULES)} модулей с аудио-сопровождением
• 🎧 Аудио-уроки с кнопкой для отметки прогресса
• 📝 Практические задания
• 📊 Отслеживание прогресса
• 🏆 Финальный тест
• 📥 Чек-лист для скачивания
• 📞 Контакты поддержки

<b>🎧 Важно!</b> При выборе урока автоматически отправляется аудио-сопровождение <b>с кнопкой для отметки модуля как пройденного</b>.

<b>Используйте кнопки внизу для навигации!</b>
"""
            await message.answer(paid_text,
                               reply_markup=get_main_keyboard(user_id),
                               parse_mode=ParseMode.HTML)
            
        else:
            # Новый пользователь без доступа
            new_user_text = f"""
<b>👋 Привет, {user_name}!</b>

Добро пожаловать на <b>Экспресс-курс: "Тендеры с нуля"</b>!

🚀 <b>Курс включает:</b>
• {len(MODULES)} модулей с аудио-сопровождением
• Практические задания
• Финальный тест
• Чек-лист для работы
• 🎁 Подарки для выпускников

🔒 <b>Для получения доступа необходимо:</b>
1. Оплатить подписку
2. Обратиться к администратору

💰 <b>Стоимость:</b> 
   <s>5 000 руб.</s> 
   
📞 <b>Контакты для оплаты:</b>
Телефон: {ADDITIONAL_MATERIALS['contacts']['mobile']}
Email: {ADDITIONAL_MATERIALS['contacts']['email']}
Телеграм: {ADDITIONAL_MATERIALS['contacts']['telegram']}

<b>Нажмите "🔓 Получить доступ" для оплаты!</b>

🆔 <b>Ваш ID:</b> <code>{user_id}</code>
"""
            await message.answer(new_user_text,
                               reply_markup=get_main_keyboard(user_id),
                               parse_mode=ParseMode.HTML)
            
        logger.info(f"✅ Приветственное сообщение отправлено пользователю {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка в cmd_start: {e}")
        try:
            await message.answer(
                "Привет! Я бот для обучения тендерам. "
                "Пожалуйста, попробуйте отправить /start еще раз.",
                parse_mode=ParseMode.HTML
            )
        except:
            pass

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
• Модулей в курсе: {len(MODULES)}

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

# =========== ДОБАВЛЯЕМ КОМАНДУ ДЛЯ ТЕСТИРОВАНИЯ ===========
@dp.message(Command("ping"))
async def cmd_ping(message: Message):
    """Проверка работы бота"""
    await message.answer("🏓 pong! Бот работает.")

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
    
    users_text = "<b>📋 Пользователи с доступом:</b>\n\n"
    
    for i, user_id in enumerate(paid_users[:50], 1):
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
<b>👑 Управление администраторов</b>

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
    
    total_users = len(user_progress)
    paid_users = len(access_control.get_all_paid_users())
    admins = len(access_control.get_all_admins())
    
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
• Модулей в курсе: {len(MODULES)}

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
• Модулей в курсе: {len(MODULES)}

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
    
    data = await state.get_data()
    is_adding_admin = data.get('is_admin', False)
    
    try:
        target_id = None
        
        if target.isdigit():
            target_id = int(target)
        elif target.startswith('@'):
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
            if access_control.add_admin(target_id):
                await message.answer(
                    f"✅ Пользователь ID: <code>{target_id}</code> назначен администратором!",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_admin_management_keyboard()
                )
                
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
            if access_control.add_paid_user(target_id):
                await message.answer(
                    f"✅ Пользователю ID: <code>{target_id}</code> предоставлен доступ к курсу!",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_access_management_keyboard()
                )
                
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
    
    data = await state.get_data()
    is_removing_admin = data.get('is_admin', False)
    
    try:
        target_id = None
        
        if target.isdigit():
            target_id = int(target)
        elif target.startswith('@'):
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

# =========== ОБРАБОТЧИК ДЛЯ ПОЛУЧЕНИЯ ДОСТУПА С QR-КОДОМ ===========
@dp.message(F.text == "🔓 Получить доступ")
async def handle_get_access(message: Message):
    """
    Информация о получении доступа с QR-кодом для оплаты
    """
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    username = message.from_user.username or "не указан"
    
    if access_control.is_paid_user(user_id):
        await message.answer(
            "✅ У вас уже есть доступ к курсу!",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    access_info = f"""
<b>🔓 ПОЛУЧЕНИЕ ДОСТУПА К КУРСУ</b>

✨ <b>Стоимость доступа к курсу<s>5 000 руб.</s>
---
<b>📋 ЧТО ВХОДИТ В КУРС:</b>

✅ <b>{len(MODULES)} модулей с аудио-сопровождением:</b>
   • 📚 Основы мира тендеров
   • 🏛️ Работа с 44-ФЗ
   • 🏢 Корпоративные закупки (223-ФЗ)
   • 💼 Коммерческие тендеры
   • 🏦 Банковские гарантии в тендерах
   • 🚀 Практический старт
   • 🏆 Итоги курса
   • 🎁 Подарки для выпускников

✅ <b>Уникальные преимущества:</b>
   • 🎧 Аудио-пояснения к каждому уроку
   • 📝 Практические задания
   • ✅ Кнопки для отметки прогресса
   • 📊 Автоматическое отслеживание прогресса
   • 🏆 Финальный тест с оценкой знаний
   • 📥 Готовый чек-лист
   • 🎁 Специальные подарки после завершения

---
<b>📝 СОГЛАСИЕ НА ОБРАБОТКУ ПЕРСОНАЛЬНЫХ ДАННЫХ:</b>

Нажимая кнопку "🔓 Получить доступ", вы подтверждаете, что:
1. Ознакомились с Политикой конфиденциальности
2. Соглашаетесь на обработку Ваших персональных данных
3. Принимаете условия оказания услуг

📄 <a href="https://tritika.ru/privacy-policy/">Политика конфиденциальности tritika.ru</a>
---
<b>💳 СПОСОБ ОПЛАТЫ:</b>

1. <b>Перевод по QR-коду</b> (сканируйте код ниже)
---
<b>🤝 ПОСЛЕ ОПЛАТЫ:</b>

1. Сохраните чек об оплате
2. Напишите нам в Telegram или на email
3. Укажите ваш ID: <code>{user_id}</code>
4. Мы активируем ваш доступ в течение 24 часов

<b>📞 КОНТАКТЫ:</b>
Телефон: {ADDITIONAL_MATERIALS['contacts']['mobile']}
Email: {ADDITIONAL_MATERIALS['contacts']['email']}
Сайт: {ADDITIONAL_MATERIALS['contacts']['website']}
Телеграм: {ADDITIONAL_MATERIALS['contacts']['telegram']}

<b>🆔 Ваш ID для связи: <code>{user_id}</code></b>

<b>📱 КАК НАЖАТЬ КНОПКУ:</b>
Внизу экрана найдите кнопку <b>"🔓 Получить доступ"</b> и нажмите на нее для получения подробной информации об оплате.
"""
    
    await message.answer(
        access_info,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=get_main_keyboard(user_id)
    )
    
    qr_code_path = "qr_code.png"
    if os.path.exists(qr_code_path):
        try:
            photo = FSInputFile(qr_code_path)
            caption = "<b>📱 QR-код для оплаты 3 999 руб.</b>\n\n"
            caption += "1. Откройте приложение вашего банка\n"
            caption += "2. Нажмите «Оплатить по QR-коду»\n"
            caption += "3. Наведите камеру на код\n"
            caption += "4. Проверьте сумму: <b>3 999 руб.</b>\n"
            caption += "5. Подтвердите платеж\n\n"
            caption += "✅ После оплаты отправьте чек на почту info@tritika.ru"
            
            await message.answer_photo(
                photo=photo,
                caption=caption,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Error sending QR code: {e}")
            await message.answer(
                "❌ Не удалось отправить QR-код. Пожалуйста, свяжитесь с администратором для получения реквизитов.",
                parse_mode=ParseMode.HTML
            )
    else:
        await message.answer(
            "<b>💳 РЕКВИЗИТЫ ДЛЯ ОПЛАТЫ:</b>\n\n"
            "<b>Сумма:</b> 3 999 руб.\n\n"
            "<b>Получатель:</b> ООО «Тритика»\n"
            "<b>ИНН:</b> 3304023510\n"
            "<b>Банк:</b> ПАО Сбербанк\n"
            "<b>БИК:</b> 044525225\n"
            "<b>Счет:</b> 40702810012345678901\n"
            "<b>Корр. счет:</b> 30101810400000000225\n\n"
            "<b>Назначение платежа:</b> Оплата курса «Тендеры с нуля»\n\n"
            "<b>Контакты для связи после оплаты:</b>\n"
            f"Телеграм: {ADDITIONAL_MATERIALS['contacts']['telegram']}\n"
            f"Email: {ADDITIONAL_MATERIALS['contacts']['email']}\n"
            f"Телефон: {ADDITIONAL_MATERIALS['contacts']['mobile']}\n\n"
            "✅ После оплаты отправьте скриншот чека в этот чат",
            parse_mode=ParseMode.HTML
        )
    
    admins = access_control.get_all_admins()
    notification_sent = False
    
    for admin_id in admins:
        try:
            admin_message = f"""
🔔 <b>НОВЫЙ ЗАПРОС НА ДОСТУП</b>

👤 <b>Информация о пользователе:</b>
• ID: <code>{user_id}</code>
• Имя: {user_name}
• Никнейм: @{username}
• Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

💰 <b>Тип доступа:</b> Полный курс 5 000 руб.
📋 <b>Статус:</b> Ожидает оплаты

<b>Действия:</b>
1. Дождитесь подтверждения оплаты от пользователя
2. Добавьте пользователя через панель администратора
3. Уведомите пользователя об активации доступа

<b>Для добавления пользователя:</b>
Нажмите «👥 Управление доступом» → «➕ Добавить пользователя» → Введите ID: <code>{user_id}</code>
"""
            await bot.send_message(admin_id, admin_message, parse_mode=ParseMode.HTML)
            notification_sent = True
            logger.info(f"Уведомление отправлено администратору {admin_id}")
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление администратору {admin_id}: {e}")
    
    if notification_sent:
        await message.answer(
            "✅ <b>Ваш запрос отправлен администраторам!</b>\n\n"
            "Они уведомлены о вашем желании получить доступ к курсу.\n\n"
            "📞 <b>Что делать дальше:</b>\n"
            "1. Произведите оплату по QR-коду\n"
            "2. Сохраните чек/скриншот оплаты\n"
            "3. Отправьте чек в этот чат\n"
            "4. Ожидайте активации доступа (до 24 часов)\n\n"
            "⌛ <b>Обычно доступ активируется в течение 1-2 часов</b>",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer(
            "⚠️ <b>Не удалось отправить уведомление администраторам</b>\n\n"
            "Пожалуйста, свяжитесь с нами напрямую:\n"
            f"Телефон: {ADDITIONAL_MATERIALS['contacts']['mobile']}\n"
            f"Email: {ADDITIONAL_MATERIALS['contacts']['email']}\n"
            f"Сайт: {ADDITIONAL_MATERIALS['contacts']['website']}\n"
            f"Телеграм: {ADDITIONAL_MATERIALS['contacts']['telegram']}\n\n"
            "Сообщите ваш ID для получения доступа:\n"
            f"<code>{user_id}</code>",
            parse_mode=ParseMode.HTML
        )

@dp.message(F.text == "ℹ️ О курсе")
async def handle_about_course(message: Message):
    """
    Информация о курсе
    """
    user_id = message.from_user.id
    
    about_text = f"""
<b>🎓 ЭКСПРЕСС-КУРС «ТЕНДЕРЫ С НУЛЯ»</b>

<b>🎯 ЦЕЛЬ КУРСА:</b>
Научить начинающих предпринимателей и специалистов участвовать в тендерах с нуля до первой победы.

<b>📚 ЧТО ВЫ ПОЛУЧИТЕ:</b>

✅ <b>{len(MODULES)} структурированных модулей:</b>
1. 📚 Основы мира тендеров
2. 🏛️ Работа с 44-ФЗ (госзакупки)
3. 🏢 Корпоративные закупки (223-ФЗ)
4. 💼 Коммерческие тендеры
5. 🏦 Банковские гарантии в тендерах
6. 🚀 Практический старт
7. 🏆 Итоги курса
8. 🎁 Подарки для выпускников

✅ <b>Уникальные форматы обучения:</b>
• 🎧 Аудио-сопровождение к каждому уроку
• ✅ Inline-кнопки для отметки прогресса
• 📝 Практические задания после каждого модуля
• 📊 Автоматическое отслеживание прогресса
• 🏆 Финальный тест с оценкой знаний
• 📥 Готовый чек-лист в Word-формате
• 🎁 Специальные подарки после завершения

✅ <b>Практические результаты:</b>
• Понимание разницы между 44-ФЗ, 223-ФЗ и коммерческими тендерами
• Знание где и как искать тендеры
• Умение изучать документацию
• Понимание банковских гарантий в тендерах
• Практический план первых шагов
• Чек-лист из 10 конкретных действий
• Специальные бонусы для выпускников

<b>👥 ДЛЯ КОГО ЭТОТ КУРС:</b>
• 🚀 Начинающие предприниматели
• 💼 Владельцы малого и среднего бизнеса
• 👨‍💼 Специалисты по закупкам
• 📈 Менеджеры по продажам
• 🎓 Выпускники экономических вузов
• 🔄 Все, кто хочет освоить новую профессию

<b>💰 СТОИМОСТЬ:</b>

✨ <b>Стоимость 5 000 р.</b>

<b>📞 КОНТАКТЫ:</b>
Телефон: {ADDITIONAL_MATERIALS['contacts']['mobile']}
Email: {ADDITIONAL_MATERIALS['contacts']['email']}
Сайт: {ADDITIONAL_MATERIALS['contacts']['website']}
Телеграм: {ADDITIONAL_MATERIALS['contacts']['telegram']}

<b>🔓 Для получения доступа нажмите "🔓 Получить доступ"</b>
"""
    
    await message.answer(
        about_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard(user_id)
    )

# =========== ОБРАБОТЧИКИ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ С ДОСТУПОМ ===========
@dp.message(F.text == "📚 Меню курса")
async def handle_course_menu(message: Message):
    """
    Показывает меню курса со списком уроков
    """
    user_id = message.from_user.id
    
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к курсу. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    lessons_text = f"<b>📚 Выберите урок для изучения ({len(MODULES)} модулей):</b>\n\n"
    
    for i, module in enumerate(MODULES, 1):
        audio_icon = "🎧 " if module.get("has_audio", False) else ""
        lessons_text += f"{module['emoji']} {audio_icon}<b>День {module['day']}:</b> {module['title']}\n"
        
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
    
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к аудио урокам. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    audio_list = f"<b>🎧 Все аудио-уроки курса ({len(MODULES)} модулей):</b>\n\n"
    
    for i, module in enumerate(MODULES, 1):
        audio_info = AudioManager.get_audio_info(i-1)
        if audio_info.get("exists"):
            duration_min = audio_info['duration'] // 60
            duration_sec = audio_info['duration'] % 60
            audio_list += f"🎧 <b>День {module['day']}:</b> {module['title']}\n"
            audio_list += f"   ⏱ {duration_min}:{duration_sec:02d}\n"
            audio_list += f"   📝 {audio_info['title']}\n\n"
    
    if audio_list == f"<b>🎧 Все аудио-уроки курса ({len(MODULES)} модулей):</b>\n\n":
        audio_list += "❌ Аудио-уроки пока не добавлены"
    else:
        audio_list += "<i>Аудио автоматически отправляется при выборе урока <b>с кнопкой для отметки пройденного</b></i>"
    
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
    
    audio_listened = len(progress.get('audio_listened', []))
    audio_total = sum(1 for module in MODULES if module.get("has_audio", False))
    audio_percentage = (audio_listened / audio_total * 100) if audio_total > 0 else 0
    
    test_results = progress.get('test_results', [])
    last_test = test_results[-1] if test_results else None
    
    admin_badge = " 👑" if access_control.is_admin(user_id) else ""
    
    progress_text = f"""
<b>📊 Ваш прогресс в курсе{admin_badge}:</b>

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

@dp.message(F.text == "📞 Контакты")
async def handle_contacts(message: Message):
    """
    Показывает контактную информацию
    """
    user_id = message.from_user.id
    contacts_text = f"""
<b>📞 Контакты для связи:</b>

📧 <b>Email:</b> {ADDITIONAL_MATERIALS['contacts']['email']}
📱 <b>Телефон:</b> {ADDITIONAL_MATERIALS['contacts']['phone']}
📲 <b>Мобильный:</b> {ADDITIONAL_MATERIALS['contacts']['mobile']}
<b>Телеграм:</b> {ADDITIONAL_MATERIALS['contacts']['telegram']}

🌐 <b>Сайт:</b> {ADDITIONAL_MATERIALS['contacts']['website']}
📄 <b>Политика конфиденциальности:</b> https://tritika.ru/privacy-policy/

<b>📅 Часы работы поддержки:</b>
Пн-Пт: 8:30-17:30 по МСК
Сб-Вс: выходной

<b>✉️ Пишите нам по любым вопросам:</b>
• Технические проблемы с ботом
• Вопросы по курсу
• Консультации по тендерам
• Предложения по сотрудничеству
• Вопросы по оплате и доступу
    """
    
    await message.answer(
        contacts_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard(user_id)
    )

@dp.message(F.text == "🔗 Полезные ссылки")
async def handle_useful_links(message: Message):
    """
    Показывает полезные ссылки
    """
    user_id = message.from_user.id
    links_text = "<b>🔗 Полезные ссылки и ресурсы:</b>\n\n"
    
    for name, url in ADDITIONAL_MATERIALS['links'].items():
        links_text += f"• <a href='{url}'>{name}</a>\n"
    
    links_text += "\n<b>📱 Контакты поддержки:</b>\n"
    links_text += f"📧 Email: {ADDITIONAL_MATERIALS['contacts']['email']}\n"
    links_text += f"📞 Телефон: {ADDITIONAL_MATERIALS['contacts']['phone']}\n"
    links_text += f"📲 Мобильный: {ADDITIONAL_MATERIALS['contacts']['mobile']}\n"
    links_text += f"🌐 Сайт: {ADDITIONAL_MATERIALS['contacts']['website']}\n"
    links_text += f"📢 Телеграм: {ADDITIONAL_MATERIALS['contacts']['telegram']}"
    
    await message.answer(
        links_text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=get_main_keyboard(user_id)
    )

@dp.message(F.text == "🆘 Помощь")
async def handle_help(message: Message):
    """
    Показывает справку
    """
    user_id = message.from_user.id
    help_text = f"""
<b>🆘 Справка по использованию бота:</b>

<b>🎧 Аудио сопровождение:</b>
• При выборе урока автоматически отправляется аудио-пояснение <b>с кнопкой для отметки модуля как пройденного</b>
• Для повторного прослушивания нажмите "🎧 Прослушать аудио"
• Все аудио в формате MP3, совместимы с любыми устройствами

<b>📚 Навигация по курсу:</b>
• <b>📚 Меню курса</b> - список всех {len(MODULES)} уроков
• В уроке используйте кнопки "⬅️ Предыдущий урок" и "Следующий урок ➡️"
• <b>✅ Отметить пройденным в аудио-сообщении</b> - отмечайте пройденные уроки прямо в аудио
• "🔙 Назад в главное меню" - возврат к основным кнопкам

<b>📝 Финальный тест:</b>
• <b>📝 Пройти тест</b> - запуск финального теста (8 вопросов)
• Выберите вариант ответа (а, б, в, г)
• Можно пропустить вопрос ("⏭ Пропучить")
• Результаты сохраняются в вашем прогрессе

<b>📥 Скачивание чек-листа:</b>
• <b>📥 Скачать чек-лист</b> - скачать готовый чек-лист в формате Word
• Чек-лист содержит 10 практических шагов для старта в тендерах
• Сохраните файл для работы в течение недели

<b>🚀 Быстрые действия:</b>
• <b>✅ Отметить все модули</b> - быстро отмечает все модули как пройденные

<b>📊 Отслеживание прогресса:</b>
• В "📊 Моем прогрессе" видна статистика по пройденным урокам и прослушанным аудио
• Процент завершения курса обновляется автоматически
• <b>🏆 Результаты теста</b> - история пройденных тестов

<b>🔧 Технические проблемы:</b>
• Если аудио не приходит, попробуйте кнопку "🎧 Прослушать аудио"
• При проблемах с ботом перезапустите его командой /start
• Для сброса прогресса напишите в поддержку

<b>💰 Оплата и доступ:</b>
• <b>🔓 Получить доступ</b>
• После оплаты отправьте чек в чат
• Доступ активируется в течение 24 часов

<b>📞 Контакты поддержки:</b>
• Email: {ADDITIONAL_MATERIALS['contacts']['email']}
• Телефон: {ADDITIONAL_MATERIALS['contacts']['phone']}
• Сайт: {ADDITIONAL_MATERIALS['contacts']['website']}
• Телеграм: {ADDITIONAL_MATERIALS['contacts']['telegram']}

<b>🕒 Часы работы поддержки:</b>
Пн-Пт: 8:30-17:30 по МСК
    """
    
    await message.answer(
        help_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard(user_id)
    )

# =========== ТЕСТ ===========
@dp.message(F.text == "📝 Пройти тест")
async def handle_start_test(message: Message, state: FSMContext):
    """
    Запускает тестирование
    """
    user_id = message.from_user.id
    
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к тесту. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    # Проверяем, пройдены ли первые 7 модулей (основные)
    if user_id in user_progress:
        completed = len(user_progress[user_id].get('completed_modules', []))
        total = len(MODULES)
        
        if completed < 7:
            keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [
                        KeyboardButton(text="✅ Отметить все модули"),
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
                f"<b>Рекомендуется завершить первые 7 основных модулей перед тестом.</b>\n\n"
                f"<b>Варианты:</b>\n"
                f"1️⃣ <b>Продолжить обучение</b> - завершить основные модули\n"
                f"2️⃣ <b>Отметить все модули</b> - если вы уже изучили материал\n"
                f"3️⃣ <b>Пройти тест все равно</b> - начать тест сейчас\n\n"
                f"<i>Для успешного прохождения теста рекомендуется завершить первые 7 модулей.</i>",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
            return
    
    await start_test_confirm(message)

async def start_test_confirm(message: Message):
    """
    Подтверждение начала теста
    """
    user_id = message.from_user.id
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="✅ Начать тест"),
                KeyboardButton(text="📥 Скачать чек-лист")
            ],
            [
                KeyboardButton(text="❌ Отмена"),
                KeyboardButton(text="📊 Мой прогресс")
            ]
        ],
        resize_keyboard=True
    )
    
    test_info = f"""
<b>📝 Информация о тесте:</b>

🔢 <b>Количество вопросов:</b> {len(TEST_QUESTIONS)}
⏱ <b>Рекомендуемое время:</b> 10-15 минут
📊 <b>Проходной балл:</b> 5 из 8 правильных ответов
🔄 <b>Повторные попытки:</b> Да, неограниченно

<b>📋 Формат теста:</b>
• Каждый вопрос имеет 4 варианта ответа (а, б, в, г)
• Выберите один правильный ответ
• Можно пропускать вопросы
• Результаты сохраняются автоматически

<b>🎯 Советы:</b>
• Внимательно читайте вопросы
• Исключайте заведомо неправильные варианты
• Не торопитесь с ответами
• Используйте знания из пройденных модулей

<b>Готовы начать тест?</b>
"""
    
    await message.answer(
        test_info,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "✅ Начать тест")
async def handle_confirm_start_test(message: Message, state: FSMContext):
    """
    Подтверждение начала теста - ПРЯМОЙ ЗАПУСК
    """
    await start_test_internal(message, state)

@dp.message(F.text == "📝 Пройти тест все равно")
async def handle_force_start_test(message: Message, state: FSMContext):
    """
    Принудительный запуск теста без проверки модулей
    """
    user_id = message.from_user.id
    
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к тесту. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    await message.answer(
        "⚠️ <b>Вы начинаете тест, не завершив все основные модули.</b>\n\n"
        "<i>Рекомендуем вернуться к изучению пропущенных модулей после теста.</i>",
        parse_mode=ParseMode.HTML
    )
    await start_test_confirm(message)

@dp.message(F.text == "✅ Отметить все модули")
async def handle_mark_all_modules(message: Message):
    """
    Обработчик кнопки "Отметить все модули" из главного меню
    """
    user_id = message.from_user.id
    
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к курсу. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    if user_id not in user_progress:
        user_progress[user_id] = {
            'start_date': datetime.now().isoformat(),
            'completed_modules': [],
            'last_module': 0,
            'name': message.from_user.first_name,
            'audio_listened': [],
            'test_results': []
        }
    
    user_progress[user_id]['completed_modules'] = list(range(1, len(MODULES) + 1))
    
    for i in range(1, len(MODULES) + 1):
        if i not in user_progress[user_id].get('audio_listened', []):
            user_progress[user_id].setdefault('audio_listened', []).append(i)
    
    save_user_progress()
    
    test_results = user_progress[user_id].get('test_results', [])
    
    if not test_results:
        await message.answer(
            f"✅ Все {len(MODULES)} модулей отмечены как пройденные!\n\n"
            "🎉 Теперь вы можете пройти финальный тест.\n"
            "Нажмите кнопку '📝 Пройти тест' для начала тестирования.",
            reply_markup=get_main_keyboard(user_id),
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer(
            f"✅ Все {len(MODULES)} модулей отмечены как пройденные!\n\n"
            "🎉 Вы уже проходили тест. Результаты сохранены.\n"
            "🎁 Не забудьте воспользоваться подарками в 8 дне курса!",
            reply_markup=get_main_keyboard(user_id),
            parse_mode=ParseMode.HTML
        )

@dp.message(F.text == "🏆 Результаты теста")
async def handle_test_results(message: Message):
    """
    Показывает результаты тестов пользователя
    """
    user_id = message.from_user.id
    
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к результатам теста. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    if user_id not in user_progress:
        await message.answer(
            "❌ Вы еще не проходили тестирование. Начните обучение с /start",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    test_results = user_progress[user_id].get('test_results', [])
    
    if not test_results:
        await message.answer(
            "📝 <b>У вас еще нет результатов тестирования.</b>\n\n"
            "Пройти тест можно после изучения основных модулей курса.\n"
            "Нажмите кнопку '📝 Пройти тест' для начала.",
            reply_markup=get_main_keyboard(user_id),
            parse_mode=ParseMode.HTML
        )
        return
    
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
    
    if len(test_results) > 1:
        result_text += f"\n<b>📊 История тестов:</b> {len(test_results)} попыток"
        for i, test in enumerate(test_results[-5:], 1):
            date_str = datetime.fromisoformat(test['date']).strftime('%d.%m')
            result_text += f"\n{i}. {date_str}: {test['correct_answers']}/{test['total_questions']} ({test['percentage']:.1f}%)"
    
    result_text += "\n\n<b>🎯 Совет:</b> Для улучшения результатов повторите модули с ошибками."
    
    if last_test['correct_answers'] >= 5:
        result_text += "\n\n🎉 <b>ПОЗДРАВЛЯЕМ С УСПЕШНЫМ ПРОХОЖДЕНИЕМ КУРСА И ТЕСТА!</b> 🎉"
        result_text += "\n\n✅ Вы освоили основы тендерной системы"
        result_text += "\n✅ Вы готовы к первым шагам в мире тендеров"
        result_text += "\n✅ У вас есть практический план действий"
        result_text += "\n✅ Вы знаете, где искать закупки и как участвовать"
        result_text += "\n🎁 <b>Не забудьте воспользоваться подарками в 8 дне курса!</b>"
        result_text += "\n\n<b>Теперь ваша очередь действовать! Первый шаг — самый важный!</b>"
    
    await message.answer(
        result_text,
        reply_markup=get_main_keyboard(user_id),
        parse_mode=ParseMode.HTML
    )

# =========== ОТВЕТЫ НА ТЕСТ ===========
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
    user_id = message.from_user.id
    
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к тесту. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    data = await state.get_data()
    test_data = data.get("test_data", {})
    current_question = test_data.get("current_question", 0)
    
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
    user_id = message.from_user.id
    
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к тесту. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    await message.answer(
        "📝 <b>Тест завершен досрочно.</b>\n\n"
        "Вы можете пройти тест снова в любое время.",
        parse_mode=ParseMode.HTML
    )
    await finish_test(message, state)

@dp.message(F.text == "❌ Отмена")
async def handle_cancel_test(message: Message):
    """
    Отмена начала теста
    """
    user_id = message.from_user.id
    await message.answer(
        "❌ Начало теста отменено.",
        reply_markup=get_main_keyboard(user_id)
    )

@dp.message(F.text == "📚 Вернуться к обучению")
async def handle_back_to_learning(message: Message):
    """
    Возврат к обучению
    """
    user_id = message.from_user.id
    await message.answer(
        "<b>📚 Возвращаемся к обучению...</b>",
        reply_markup=get_main_keyboard(user_id),
        parse_mode=ParseMode.HTML
    )

# =========== СКАЧИВАНИЕ ЧЕК-ЛИСТА ===========
@dp.message(F.text == "📥 Скачать чек-лист")
async def handle_download_checklist(message: Message):
    """
    Обработчик кнопки "📥 Скачать чек-лист"
    """
    user_id = message.from_user.id
    
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к чек-листу. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    try:
        checklist_path = "Чек-лист -Первые 10 шагов в тендерах-.docx"
        
        if not os.path.exists(checklist_path):
            await message.answer(
                "❌ Файл чек-листа временно недоступен.\n\n"
                "Вы можете использовать текстовую версию чек-листа из 7 модуля курса.",
                parse_mode=ParseMode.HTML
            )
            return
        
        document = FSInputFile(checklist_path)
        
        admin_badge = " (Администратор)" if access_control.is_admin(user_id) else ""
        
        caption = f"""✅ <b>Чек-лист "Первые 10 шагов в тендерах"{admin_badge}</b>

📋 <b>Что внутри:</b>
• Пошаговый план для старта в течение недели
• 10 практических шагов от анализа до первой заявки
• Конкретные инструкции и ссылки
• Полезные советы

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
            "Попробуйте позже или используйте текстовую версию из 7 модуля.",
            parse_mode=ParseMode.HTML
        )

# =========== ВЫБОР УРОКА ===========
@dp.message(F.text.startswith(("📚", "🏛️", "🏢", "💼", "🏦", "🚀", "🏆", "🎁")))
async def handle_lesson_selection(message: Message, state: FSMContext):
    """
    Обработчик выбора урока из списка
    """
    user_id = message.from_user.id
    
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к урокам. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
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
            reply_markup=get_main_keyboard(user_id)
        )

# =========== НАВИГАЦИЯ В УРОКЕ ===========
@dp.message(F.text == "⬅️ Предыдущий урок")
async def handle_prev_lesson(message: Message, state: FSMContext):
    """
    Переход к предыдущему уроку
    """
    user_id = message.from_user.id
    
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к урокам. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
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
    user_id = message.from_user.id
    
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к урокам. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    data = await state.get_data()
    current_module = data.get("current_module", 0)
    
    if current_module < len(MODULES) - 1:
        await show_module(message, current_module + 1, state)
    else:
        # Это последний урок (8 день)
        await message.answer(
            "🎉 <b>Поздравляем с завершением курса!</b>\n\n"
            "Вы прошли все уроки и получили полный набор знаний и инструментов для старта в тендерах.\n\n"
            "📝 <b>Если вы еще не проходили финальный тест, нажмите кнопку '📝 Пройти тест' в главном меню!</b>\n"
            "🎁 <b>А если уже прошли, то надеемся, что вам понравились подарки в 8 дне!</b>",
            reply_markup=get_lesson_navigation_keyboard(current_module, len(MODULES)),
            parse_mode=ParseMode.HTML
        )

@dp.message(F.text == "🎧 Прослушать аудио")
async def handle_listen_audio(message: Message, state: FSMContext):
    """
    Повторное прослушивание аудио к текущему уроку
    """
    user_id = message.from_user.id
    
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к аудио урокам. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    data = await state.get_data()
    current_module = data.get("current_module", 0)
    
    if current_module is not None:
        audio_sent = await audio_manager.send_module_audio(message.chat.id, current_module, user_id)
        
        if audio_sent:
            if user_id in user_progress:
                if current_module + 1 not in user_progress[user_id].get('audio_listened', []):
                    user_progress[user_id].setdefault('audio_listened', []).append(current_module + 1)
                    save_user_progress()
            
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
            reply_markup=get_main_keyboard(user_id)
        )

@dp.message(F.text == "✅ Отметить пройденным")
async def handle_complete_lesson(message: Message, state: FSMContext):
    """
    Отметка текущего урока как пройденного (через reply-клавиатуру)
    """
    user_id = message.from_user.id
    
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к курсу. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    data = await state.get_data()
    current_module = data.get("current_module", 0)
    
    if current_module is not None:
        if user_id not in user_progress:
            user_progress[user_id] = {
                'start_date': datetime.now().isoformat(),
                'completed_modules': [],
                'last_module': current_module,
                'name': message.from_user.first_name,
                'audio_listened': [],
                'test_results': []
            }
        
        module_num = current_module + 1
        if module_num not in user_progress[user_id]['completed_modules']:
            user_progress[user_id]['completed_modules'].append(module_num)
            save_user_progress()
            
            await message.answer(
                f"✅ Урок {module_num} отмечен как пройденный!\n\n"
                "<i>Вы также можете отметить модуль как пройденный через кнопку в аудио-сообщении выше.</i>",
                reply_markup=get_lesson_navigation_keyboard(current_module, len(MODULES)),
                parse_mode=ParseMode.HTML
            )
            
            completed = len(user_progress[user_id]['completed_modules'])
            total = len(MODULES)
            
            if completed >= 7 and not user_progress[user_id].get('test_results'):
                await message.answer(
                    "🎉 <b>Поздравляем! Вы завершили основные модули курса!</b>\n\n"
                    "📝 <b>Теперь вы можете пройти финальный тест:</b>\n"
                    "1. Проверить свои знания\n"
                    "2. Получить оценку\n"
                    "3. Увидеть рекомендации по улучшению\n\n"
                    "Нажмите кнопку '📝 Пройти тест' в главном меню!",
                    reply_markup=get_main_keyboard(user_id),
                    parse_mode=ParseMode.HTML
                )
            elif completed == total:
                await message.answer(
                    "🎉 <b>Поздравляем! Вы завершили все модули курса, включая бонусный!</b>\n\n"
                    "📝 <b>Если вы еще не проходили финальный тест, нажмите кнопку '📝 Пройти тест' в главном меню!</b>\n"
                    "🎁 <b>А если уже прошли, то надеемся, что вам понравились подарки в 8 дне!</b>",
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
            reply_markup=get_main_keyboard(user_id)
        )

# =========== ВОЗВРАТ В ГЛАВНОЕ МЕНЮ ===========
@dp.message(F.text.in_({"🔙 Назад в главное меню", "🔙 Главное меню", "🔙 Назад в админку", "🔙 Назад"}))
async def handle_back_to_main(message: Message, state: FSMContext):
    """
    Возврат в главное меню
    """
    user_id = message.from_user.id
    await state.clear()
    
    if access_control.is_admin(user_id):
        await message.answer(
            "<b>👑 Возвращаемся в главное меню</b>\n\n"
            "Вы имеете полный доступ ко всем функциям бота как администратор.",
            reply_markup=get_main_keyboard(user_id),
            parse_mode=ParseMode.HTML
        )
    elif access_control.is_paid_user(user_id):
        await cmd_start(message, state)
    else:
        await cmd_start(message, state)

# =========== КОМАНДЫ ОТЛАДКИ ===========
@dp.message(Command("checkadmins"))
async def cmd_checkadmins(message: Message):
    """
    Проверка списка администраторов (для отладки)
    """
    user_id = message.from_user.id
    admins = access_control.get_all_admins()
    
    check_text = f"""
<b>🔍 Проверка администраторов:</b>

<b>Ваш ID:</b> <code>{user_id}</code>
<b>Вы администратор:</b> {'✅ Да' if access_control.is_admin(user_id) else '❌ Нет'}
<b>Вы имеете доступ к курсу:</b> {'✅ Да' if access_control.is_paid_user(user_id) else '❌ Нет'}

<b>Список всех администраторов:</b>
"""
    
    if admins:
        for i, admin_id in enumerate(admins, 1):
            check_text += f"{i}. <code>{admin_id}</code>\n"
    else:
        check_text += "❌ Список администраторов пуст\n"
    
    check_text += f"\n<b>Всего администраторов:</b> {len(admins)}"
    
    initial_admins_env = os.getenv('INITIAL_ADMINS', 'Не установлена')
    check_text += f"\n<b>INITIAL_ADMINS из .env:</b> {initial_admins_env}"
    
    await message.answer(
        check_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard(user_id)
    )

@dp.message(Command("debug"))
async def cmd_debug(message: Message):
    """
    Отладочная информация
    """
    user_id = message.from_user.id
    
    debug_text = f"""
<b>🛠 Отладочная информация:</b>

<b>Система:</b>
• ID пользователя: <code>{user_id}</code>
• Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
• Перезапусков: {restart_count}

<b>Доступ:</b>
• Администратор: {access_control.is_admin(user_id)}
• Оплативший/имеющий доступ: {access_control.is_paid_user(user_id)}

<b>Курс:</b>
• Всего модулей: {len(MODULES)}
• Из них с аудио: {sum(1 for m in MODULES if m.get('has_audio'))}
• Вопросов в тесте: {len(TEST_QUESTIONS)}

<b>Прогресс:</b>
• Пользователей в системе: {len(user_progress)}
• Ваш прогресс: {len(user_progress.get(user_id, {}).get('completed_modules', []))}/{len(MODULES)} модулей

<b>Переменные окружения:</b>
• BOT_TOKEN: {'✅ Установлен' if BOT_TOKEN else '❌ Не установлен'}
• INITIAL_ADMINS: {os.getenv('INITIAL_ADMINS', '❌ Не установлена')}
• PORT: {PORT}
"""
    
    await message.answer(
        debug_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard(user_id)
    )

# =========== ДРУГИЕ КОМАНДЫ ===========
@dp.message(Command("menu"))
async def cmd_menu(message: Message):
    """
    Обработчик команды /menu
    """
    user_id = message.from_user.id
    await message.answer(
        "<b>📋 Главное меню:</b>\n\nИспользуйте кнопки внизу для навигации.",
        reply_markup=get_main_keyboard(user_id),
        parse_mode=ParseMode.HTML
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    """
    Обработчик команды /help
    """
    await handle_help(message)

@dp.message(Command("progress"))
async def cmd_progress(message: Message):
    """
    Обработчик команды /progress
    """
    await handle_my_progress(message)

@dp.message(Command("audio"))
async def cmd_audio(message: Message, command: CommandObject):
    """
    Обработчик команды /audio [номер урока]
    """
    user_id = message.from_user.id
    
    if not access_control.is_paid_user(user_id):
        await message.answer(
            "❌ У вас нет доступа к аудио урокам. Для получения доступа оплатите подписку.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    try:
        if not command.args:
            await handle_audio_lessons(message)
            return
        
        module_num = int(command.args)
        if 1 <= module_num <= len(MODULES):
            module_index = module_num - 1
            audio_sent = await audio_manager.send_module_audio(message.chat.id, module_index, user_id)
            
            if audio_sent:
                if module_num not in user_progress[user_id].get('audio_listened', []):
                    user_progress[user_id].setdefault('audio_listened', []).append(module_num)
                    save_user_progress()
                
                await message.answer(
                    f"🎧 Аудио к уроку {module_num} отправлено!",
                    reply_markup=get_main_keyboard(user_id)
                )
            else:
                await message.answer(
                    "❌ Аудио для этого урока не найдено",
                    reply_markup=get_main_keyboard(user_id)
                )
        else:
            await message.answer(
                f"❌ Урок {module_num} не найден. Доступные уроки: 1-{len(MODULES)}",
                reply_markup=get_main_keyboard(user_id)
            )
    except ValueError:
        await message.answer(
            "❌ Неверный формат. Используйте: /audio 1",
            reply_markup=get_main_keyboard(user_id)
        )

@dp.message(Command("test"))
async def cmd_test(message: Message, state: FSMContext):
    """
    Обработчик команды /test
    """
    await handle_start_test(message, state)

@dp.message(Command("status"))
async def cmd_status(message: Message):
    """
    Показывает статус бота
    """
    user_id = message.from_user.id
    status_text = f"""
<b>📊 Статус бота:</b>

🕒 <b>Время:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
👥 <b>Активных пользователей:</b> {len(user_progress)}
🔄 <b>Перезапусков:</b> {restart_count}/{max_restarts}
📚 <b>Модулей в курсе:</b> {len(MODULES)}
🎧 <b>Аудио уроков:</b> {sum(1 for m in MODULES if m.get('has_audio'))}
📝 <b>Вопросов в тесте:</b> {len(TEST_QUESTIONS)}
📥 <b>Чек-лист:</b> {"Доступен" if os.path.exists("Чек-лист -Первые 10 шагов в тендерах-.docx") else "Не найден"}
📱 <b>QR-код оплаты:</b> {"Доступен" if os.path.exists("qr_code.png") else "Не найден"}

<b>Система доступа:</b>
• Администраторов: {len(access_control.get_all_admins())}
• Пользователей с доступом: {len(access_control.get_all_paid_users())}

<b>💰 Цена курса:</b>
• Стоимость: 5 000 руб.

<b>✅ Бот работает стабильно</b>
"""
    
    await message.answer(
        status_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard(user_id)
    )

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

# =========== ОБРАБОТЧИК ВСЕХ ОСТАЛЬНЫХ СООБЩЕНИЙ ===========
@dp.message()
async def handle_other_messages(message: Message, state: FSMContext):
    """
    Обработчик всех прочих сообщений
    """
    user_id = message.from_user.id
    
    data = await state.get_data()
    if data.get('broadcast'):
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
    
    if message.content_type == ContentType.TEXT:
        if access_control.is_paid_user(user_id):
            await message.answer(
                f"🤖 Я бот для обучения тендерам с аудио сопровождением ({len(MODULES)} модулей)!\n\n"
                "Используйте кнопки внизу для навигации или команды:\n"
                "/start - Начать обучение\n"
                "/menu - Главное меню\n"
                "/help - Помощь\n"
                "/progress - Ваш прогресс\n"
                "/audio - Аудио уроки\n"
                "/test - Пройти финальный тест\n"
                "/status - Статус бота\n\n"
                "🎧 <b>Важно:</b> При выборе урока автоматически отправляется аудио-пояснение <b>с кнопкой для отметки пройденного!</b>\n"
                "📝 <b>После завершения курса пройдите финальный тест!</b>\n"
                "📥 <b>Скачайте готовый чек-лист для практической работы!</b>\n"
                "🎁 <b>После теста вас ждут специальные подарки для выпускников!</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_keyboard(user_id)
            )
        else:
            await message.answer(
                f"""🔒 <b>У ВАС НЕТ ДОСТУПА К ПОЛНОМУ ФУНКЦИОНАЛУ БОТА</b>

✨ <b>🎁 Стоимость 5 000 руб.</b>

<b>📋 ЧТО ВХОДИТ В КУРС ({len(MODULES)} модулей):</b>
• {len(MODULES)} модулей с аудио-сопровождением
• Практические задания после каждого урока
• Финальный тест для проверки знаний
• Готовый чек-лист
• Подарки для выпускников

<b>🎧 УНИКАЛЬНАЯ ФУНКЦИЯ:</b>
При выборе урока автоматически отправляется аудио-пояснение <b>с кнопкой для отметки модуля как пройденного</b>

<b>📱 КАК ПОЛУЧИТЬ ДОСТУП:</b>
1. Внизу экрана найдите кнопку <b>"🔓 Получить доступ"</b>
2. Нажмите на нее для получения подробной информации об оплате
3. Оплатите курс
4. Отправьте чек об оплате на почту info@tritika.ru
5. Мы активируем ваш доступ в течение 24 часов

<b>📞 КОНТАКТЫ:</b>
Телефон: {ADDITIONAL_MATERIALS['contacts']['mobile']}
Email: {ADDITIONAL_MATERIALS['contacts']['email']}
Сайт: {ADDITIONAL_MATERIALS['contacts']['website']}
Телеграм: {ADDITIONAL_MATERIALS['contacts']['telegram']}

<b>🆔 Ваш ID: <code>{user_id}</code></b>

<b>💳 Для оплаты нажмите кнопку "🔓 Получить доступ" внизу экрана!</b>""",
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_keyboard(user_id)
            )

# =========== ФУНКЦИИ ПРОВЕРКИ ФАЙЛОВ ===========
def create_audio_stubs():
    """Создает заглушки для аудио файлов, если они отсутствуют"""
    os.makedirs(AUDIO_CONFIG["base_path"], exist_ok=True)
    
    for module in MODULES:
        audio_file = module.get("audio_file")
        if audio_file:
            audio_path = os.path.join(AUDIO_CONFIG["base_path"], audio_file)
            if not os.path.exists(audio_path):
                try:
                    with open(audio_path, 'w', encoding='utf-8') as f:
                        f.write(f"Audio stub for module {module['id']}: {module['title']}\n")
                        f.write(f"Duration: {module.get('audio_duration', 120)} seconds\n")
                        f.write(f"File will be available after setup\n")
                    logger.info(f"Created audio stub: {audio_path}")
                except Exception as e:
                    logger.error(f"Failed to create audio stub: {e}")

async def check_audio_files():
    """Проверяет наличие всех аудио файлов при запуске бота"""
    logger.info("Проверяем аудио файлы...")
    
    os.makedirs(AUDIO_CONFIG["base_path"], exist_ok=True)
    
    missing_files = []
    
    for i, module in enumerate(MODULES):
        audio_file = module.get("audio_file")
        if audio_file:
            audio_path = os.path.join(AUDIO_CONFIG["base_path"], audio_file)
            if os.path.exists(audio_path):
                file_size = os.path.getsize(audio_path) / (1024 * 1024)
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
        file_size = os.path.getsize(checklist_path) / 1024
        logger.info(f"✓ Чек-лист найден: {checklist_path} ({file_size:.1f} КБ)")
        return True
    else:
        logger.warning(f"✗ Чек-лист не найден: {checklist_path}")
        logger.warning("Кнопка '📥 Скачать чек-лист' будет недоступна")
        return False

async def check_qr_code():
    """Проверяет наличие QR-кода для оплаты"""
    qr_code_path = "qr_code.png"
    
    if os.path.exists(qr_code_path):
        file_size = os.path.getsize(qr_code_path) / 1024
        logger.info(f"✓ QR-код найден: {qr_code_path} ({file_size:.1f} КБ)")
        return True
    else:
        logger.warning(f"✗ QR-код не найден: {qr_code_path}")
        logger.warning("Пользователям будут показываться только реквизиты")
        return False

async def check_required_files():
    """Проверяет наличие всех необходимых файлов"""
    logger.info("Проверяем необходимые файлы...")
    
    required_files = [
        "admins.json",
        "paid_users.json",
        USER_PROGRESS_FILE,
        "Чек-лист -Первые 10 шагов в тендерах-.docx"
    ]
    
    missing_files = []
    for file in required_files:
        if not os.path.exists(file):
            missing_files.append(file)
            logger.warning(f"Файл не найден: {file}")
    
    if not os.path.exists(AUDIO_CONFIG["base_path"]):
        os.makedirs(AUDIO_CONFIG["base_path"], exist_ok=True)
        logger.info(f"Создана папка: {AUDIO_CONFIG['base_path']}")
    
    audio_files = []
    for module in MODULES:
        audio_file = module.get("audio_file")
        if audio_file:
            audio_path = os.path.join(AUDIO_CONFIG["base_path"], audio_file)
            if not os.path.exists(audio_path):
                audio_files.append(audio_file)
    
    if missing_files:
        logger.error(f"Отсутствуют файлы: {missing_files}")
    else:
        logger.info("✓ Все необходимые файлы на месте")
    
    if audio_files:
        logger.warning(f"Отсутствуют аудио файлы: {len(audio_files)} из {sum(1 for m in MODULES if m.get('has_audio'))}")
    
    return len(missing_files) == 0 and len(audio_files) == 0

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
        "checklist_available": os.path.exists("Чек-лист -Первые 10 шагов в тендерах-.docx"),
        "qr_code_available": os.path.exists("qr_code.png"),
        "price": {
            "discount": 3999,
            "after_discount": 4999,
            "discount_valid_until": "2026-01-31"
        }
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

# =========== ИНИЦИАЛИЗАЦИЯ СИСТЕМЫ ===========
def initialize_system():
    """Инициализирует всю систему при запуске"""
    logger.info("🔧 Инициализация системы...")
    
    # Проверяем наличие администраторов
    admins = access_control.get_all_admins()
    if not admins:
        logger.warning("⚠️ В системе нет администраторов!")
        logger.warning("Добавьте администраторов через переменную окружения INITIAL_ADMINS")
    else:
        logger.info(f"✅ Загружено администраторов: {len(admins)}")
        for admin_id in admins:
            logger.info(f"   👑 Администратор ID: {admin_id}")
    
    # Проверяем пользователей с доступом
    paid_users = access_control.get_all_paid_users()
    logger.info(f"✅ Пользователей с доступом: {len(paid_users)}")
    
    # Проверяем прогресс пользователей
    logger.info(f"✅ Пользователей в системе: {len(user_progress)}")
    
    # Проверяем конфигурацию курса
    logger.info(f"✅ Модулей в курсе: {len(MODULES)}")
    logger.info(f"✅ Аудио уроков: {sum(1 for m in MODULES if m.get('has_audio'))}")
    
    return True

# =========== ФУНКЦИЯ ДЛЯ ЗАПУСКА БОТА ===========
async def run_bot_with_retries():
    """
    Запускает бота с повторными попытками при сбоях
    """
    global bot_instance, dp_instance, shutdown_flag, restart_count
    
    # Инициализируем систему
    initialize_system()
    
    # Проверяем файлы перед запуском
    files_ok = await check_required_files()
    if not files_ok:
        logger.warning("⚠️ Некоторые файлы отсутствуют. Бот продолжит работу, но некоторые функции могут быть недоступны.")
    
    # Создаем заглушки для аудио файлов перед запуском
    create_audio_stubs()
    
    bot_instance = bot
    dp_instance = dp
    
    while not shutdown_flag and restart_count < max_restarts:
        try:
            logger.info(f"🚀 Запуск бота (попытка {restart_count + 1}/{max_restarts})...")
            logger.info(f"Порт для HTTP: {PORT}")
            
            # Проверяем подключение к Telegram API
            try:
                bot_info = await bot.get_me()
                logger.info(f"✅ Бот авторизован: @{bot_info.username} (ID: {bot_info.id})")
            except Exception as e:
                logger.error(f"❌ Не удалось подключиться к Telegram API: {e}")
                logger.error("Проверьте ваш BOT_TOKEN и подключение к интернету")
                restart_count += 1
                if not shutdown_flag:
                    logger.info(f"⏳ Повторная попытка через {restart_delay} секунд...")
                    await asyncio.sleep(restart_delay)
                continue
            
            # Детальная информация о системе
            logger.info(f"✅ Система доступа: {len(access_control.get_all_admins())} администраторов, {len(access_control.get_all_paid_users())} оплативших")
            logger.info(f"✅ Фиксированные кнопки: Администраторы получают полный доступ")
            logger.info(f"✅ Аудио сопровождение с кнопкой: {sum(1 for m in MODULES if m.get('has_audio'))}/{len(MODULES)} уроков")
            logger.info(f"✅ QR-код оплаты: {'Доступен' if os.path.exists('qr_code.png') else 'Не найден'}")
            logger.info(f"✅ Сохранение прогресса: ВКЛЮЧЕНО ({USER_PROGRESS_FILE})")
            logger.info(f"✅ Автосохранение прогресса: ВКЛЮЧЕНО (каждые 5 минут)")
            
            await check_audio_files()
            await check_checklist_file()
            await check_qr_code()
            
            http_runner = await start_http_server()
            
            try:
                logger.info("🔄 Начинаем polling...")
                # Запускаем автосохранение прогресса
                auto_save_task = asyncio.create_task(auto_save_progress())
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
    
    bot_task = asyncio.create_task(run_bot_with_retries())
    
    try:
        await bot_task
    except KeyboardInterrupt:
        logger.info("✅ Получен KeyboardInterrupt, инициируем shutdown...")
        shutdown_flag = True
        await shutdown()
    except Exception as e:
        logger.error(f"❌ Необработанное исключение в main: {e}")
        logger.error(f"Трассировка ошибки: {traceback.format_exc()}")
    finally:
        if not bot_task.done():
            bot_task.cancel()
            try:
                await bot_task
            except asyncio.CancelledError:
                pass

# =========== ТОЧКА ВХОДА ===========
if __name__ == "__main__":
    try:
        print("=" * 60)
        print("🤖 БОТ ДЛЯ ОБУЧЕНИЯ ТЕНДЕРАМ")
        print("=" * 60)
        print(f"📅 Время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Проверяем токен бота
        if not BOT_TOKEN or BOT_TOKEN == "ваш_токен_бота":
            print("❌ ОШИБКА: BOT_TOKEN не установлен в .env файле!")
            print("Создайте файл .env и добавьте строку:")
            print("BOT_TOKEN=ваш_токен_от_BotFather")
            sys.exit(1)
        
        # Проверяем администраторов
        admins = access_control.get_all_admins()
        print(f"👑 Администраторов: {len(admins)}")
        if admins:
            print(f"   ID администраторов: {', '.join(map(str, admins))}")
        else:
            print("   ⚠️ Администраторы не найдены. Добавьте через INITIAL_ADMINS в .env")
        
        print(f"👥 Пользователей в системе: {len(user_progress)}")
        print(f"📚 Модулей в курсе: {len(MODULES)}")
        print(f"💰 Стоимость курса: 5 000 руб.")
                print(f"🌐 HTTP порт: {PORT}")
        print("=" * 60)
        print("✅ Бот запускается...")
        print("📱 Проверьте бота командой /ping")
        print("=" * 60)
        
        # Запускаем бота
        asyncio.run(main())
        
    except KeyboardInterrupt:
        print("\n\n✅ Бот остановлен пользователем (Ctrl+C)")
        logger.info("Бот остановлен пользователем (KeyboardInterrupt)")
    except Exception as e:
        print(f"\n\n❌ Критическая ошибка: {e}")
        logger.error(f"Критическая ошибка при запуске: {e}")
        logger.error(f"Трассировка ошибки: {traceback.format_exc()}")
        sys.exit(1)

