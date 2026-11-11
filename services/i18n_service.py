import logging
from typing import Dict, Any, Optional
from sqlalchemy import select
from database.session import AsyncSessionLocal
from database.models.localization import LocalizationCache
from services.translation_client import TranslationClient

logger = logging.getLogger(__name__)


class I18nService:
    """
    Назначение:
        Глобальный сервис динамической мультиязычности (Any-to-Any) с двухуровневым кэшированием (RAM + БД).
    """

    # Список официально поддерживаемых языков в интерфейсе бота
    LANGUAGES = {
        "ru": "🇷🇺 Русский",
        "en": "🇬🇧 English",
        "zh": "🇨🇳 中文",
        "be": "🇧🇾 Беларуская",
        "uk": "🇺🇦 Українська",
        "es": "🇪🇸 Español",
        "fr": "🇫🇷 Français",
        "it": "🇮🇹 Italiano",
        "de": "🇩🇪 Deutsch"
    }

    # Быстрый In-Memory кэш в оперативной памяти с контролем максимального размера
    _memory_cache: Dict[str, str] = {}
    _MAX_CACHE_SIZE: int = 5000

    @classmethod
    def _cache_set(cls, key: str, value: str) -> None:
        """Сохранение в RAM-кэш с ротацией для защиты от утечки памяти."""
        if len(cls._memory_cache) >= cls._MAX_CACHE_SIZE:
            # Очищаем 20% старых записей
            keys_to_purge = list(cls._memory_cache.keys())[:int(cls._MAX_CACHE_SIZE * 0.2)]
            for k in keys_to_purge:
                cls._memory_cache.pop(k, None)
        cls._memory_cache[key] = value

    @classmethod
    async def tr(cls, text: str, target_lang: str = "ru", **kwargs: Any) -> str:
        """
        Назначение:
            Главный метод перевода любой строки ядра с сохранением в базу данных.
        Входные параметры:
            text (str): Исходный текст (на любом языке).
            target_lang (str): Целевой язык пользователя.
            **kwargs: Переменные для подстановки после перевода ({name}, {address} и т.д.).
        Возвращаемое значение:
            str: Переведенный текст с подставленными переменными.
        """
        clean_text = text.strip()
        if not clean_text:
            return text

        # 1. Быстрое определение исходного языка
        src_lang = TranslationClient.detect_source_language(clean_text)

        # 2. Если языки совпадают — перевод не требуется
        if src_lang.lower() == target_lang.lower():
            return cls._apply_formatting(clean_text, kwargs)

        cache_key = LocalizationCache.generate_cache_key(src_lang, target_lang, clean_text)

        # 3. УРОВЕНЬ 1: Проверяем RAM-кэш (0 миллисекунд)
        if cache_key in cls._memory_cache:
            return cls._apply_formatting(cls._memory_cache[cache_key], kwargs)

        # 4. УРОВЕНЬ 2: Проверяем Базу Данных
        async with AsyncSessionLocal() as session:
            stmt = select(LocalizationCache).where(LocalizationCache.cache_key == cache_key)
            cached_record = (await session.execute(stmt)).scalar_one_or_none()

            if cached_record:
                cls._cache_set(cache_key, cached_record.translated_text)
                return cls._apply_formatting(cached_record.translated_text, kwargs)

            # 5. УРОВЕНЬ 3: Переводим через сеть и сохраняем в БД
            translated_text, detected_src = await TranslationClient.translate(
                text=clean_text,
                target_lang=target_lang,
                src_lang=src_lang
            )

            # Сохраняем в память
            cls._cache_set(cache_key, translated_text)

            # Сохраняем в БД для вечного использования
            try:
                new_entry = LocalizationCache(
                    cache_key=cache_key,
                    src_lang=detected_src,
                    target_lang=target_lang,
                    src_text=clean_text,
                    translated_text=translated_text,
                    is_manual=False
                )
                session.add(new_entry)
                await session.commit()
            except Exception as e:
                logger.error(f"Не удалось записать перевод в БД: {e}")

            return cls._apply_formatting(translated_text, kwargs)

    @classmethod
    def get_text(cls, key_or_text: str, lang: str = "ru", **kwargs: Any) -> str:
        """
        Назначение:
            Синхронный метод обратной совместимости.
            Если асинхронный вызов await tr() невозможен, пытается достать из памяти
            или возвращает читаемый текст по умолчанию.
        """
        # Если в памяти уже есть перевод — отдаем
        cache_key = LocalizationCache.generate_cache_key("ru", lang, key_or_text)
        if cache_key in cls._memory_cache:
            return cls._apply_formatting(cls._memory_cache[cache_key], kwargs)

        # Резервный словарь для критических системных шагов
        fallback_map = {
            "enter_last_name": "Отлично! Теперь введите вашу <b>Фамилию</b>:",
            "enter_address": "Введите ваш <b>Адрес</b> (город, улица, дом) или нажмите кнопку <b>📍 Поделиться геопозицией</b> ниже:",
            "enter_phone": "Остался последний шаг. Отправьте ваш <b>номер телефона</b> с помощью кнопки ниже или нажмите «Пропустить шаг»:",
            "reg_complete": "🎉 <b>Регистрация успешно завершена!</b>\n▫️ <b>Адрес:</b> {address}\n▫️ <b>Часовой пояс:</b> <code>{timezone}</code>",
            "btn_edit_name": "✏️ Изменить Имя",
            "btn_edit_last_name": "✏️ Изменить Фамилию",
            "btn_edit_address": "🏠 Изменить Адрес",
            "btn_edit_phone": "📱 Изменить Телефон",
            "btn_change_lang": "🌐 Сменить язык",
            "btn_change_tz": "🕒 Сменить часовой пояс",
            "select_tz": "Выберите ваш часовой пояс из списка:",
            "select_lang": "Выберите язык интерфейса:"
        }

        res = fallback_map.get(key_or_text, key_or_text)
        return cls._apply_formatting(res, kwargs)

    @staticmethod
    def _apply_formatting(text: str, kwargs: Dict[str, Any]) -> str:
        """Вспомогательный метод безопасного форматирования переменных."""
        if not kwargs:
            return text
        try:
            return text.format(**kwargs)
        except Exception:
            return text
