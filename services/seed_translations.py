import asyncio
import logging
from database.session import engine
from database.models.base import Base
from services.i18n_service import I18nService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SeedTranslations")

# Ключевые системные фразы ядра
CORE_PHRASES = [
    "👋 С возвращением, {first_name}!",
    "Используйте /profile для просмотра профиля.",
    "👋 Добро пожаловать в систему!",
    "Для начала работы необходимо зарегистрироваться.",
    "Введите ваше Имя:",
    "Отлично! Теперь введите вашу Фамилию:",
    "Введите ваш Адрес (город, улица, дом) или нажмите кнопку 📍 Поделиться геопозицией ниже:",
    "Остался последний шаг. Отправьте ваш номер телефона с помощью кнопки ниже или нажмите «Пропустить шаг»:",
    "🎉 Регистрация успешно завершена!",
    "Ваш Профиль",
    "Справочник доступных вам команд:",
    "Команды Администратора:",
    "Функции Создателя (SuperAdmin):",
    "Панель управления и фоновые рассылки",
    "Быстрый поиск пользователя",
    "Показать последних зарегистрированных",
    "Конструктор умных рассылок",
    "Управление группами",
    "Статистика очереди",
    "Изменить Имя",
    "Изменить Фамилию",
    "Изменить Адрес",
    "Изменить Телефон",
    "Сменить язык",
    "Сменить часовой пояс",
    "Назад к пользователю",
    "Заблокировать",
    "Разблокировать",
    "Настроить права (ACL)"
]


async def seed_all_languages():
    logger.info("🚀 Начинаем прогрев базы данных переводами на все поддерживаемые языки...")

    # Создаем таблицы если их нет
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    target_languages = [lang for lang in I18nService.LANGUAGES.keys() if lang != "ru"]

    total = len(CORE_PHRASES) * len(target_languages)
    counter = 0

    for phrase in CORE_PHRASES:
        for lang in target_languages:
            # Метод tr() сам переведет и сохранит в localization_cache
            await I18nService.tr(phrase, target_lang=lang)
            counter += 1
            if counter % 10 == 0:
                logger.info(f"Прогрето {counter}/{total} фраз...")
            await asyncio.sleep(0.05)  # Небольшая пауза для вежливости к API

    logger.info("✅ База данных успешно наполнена переводами!")


if __name__ == "__main__":
    asyncio.run(seed_all_languages())