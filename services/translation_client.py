import aiohttp
import logging
import re
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

class TranslationClient:
    """
    Назначение:
        Асинхронный клиент автоперевода Any-to-Any с локальным определением языка источника.
    """

    @staticmethod
    def detect_source_language(text: str) -> str:
        """
        Назначение:
            Сверхбыстрое локальное определение языка источника по Unicode-диапазонам без сетевых запросов.
        Входные параметры:
            text (str): Входящий текст на любом языке.
        Возвращаемое значение:
            str: Двухбуквенный ISO-код языка ('ru', 'zh', 'ar', 'en'...).
        """
        # Проверка на китайские / японские иероглифы (CJK Unified Ideographs)
        if re.search(r"[\u4e00-\u9fff]", text):
            return "zh"
        # Проверка на кириллицу (русский, белорусский, украинский)
        if re.search(r"[А-Яа-яЁёІіЇїЎў]", text):
            return "ru"
        # Проверка на арабскую вязь
        if re.search(r"[\u0600-\u06FF]", text):
            return "ar"
        # По умолчанию для латиницы считаем английский
        return "en"

    @classmethod
    async def translate(cls, text: str, target_lang: str, src_lang: Optional[str] = None) -> Tuple[str, str]:
        """
        Назначение:
            Асинхронный перевод строки на целевой язык через публичный шлюз Google Translate.
        Входные параметры:
            text (str): Исходный текст для перевода.
            target_lang (str): Код целевого языка ('en', 'es', 'zh', 'ru'...).
            src_lang (str, optional): Код языка источника. Если не указан — определяется автоматически.
        Возвращаемое значение:
            Tuple[str, str]: (Переведенный текст, Определенный язык источника).
        """
        clean_text = text.strip()
        if not clean_text:
            return text, "en"

        detected_src = src_lang or cls.detect_source_language(clean_text)

        # Если исходный язык совпадает с целевым — перевод не требуется
        if detected_src.lower() == target_lang.lower():
            return clean_text, detected_src

        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": detected_src,
            "tl": target_lang,
            "dt": "t",
            "q": clean_text
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=3.5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        # Google Translate API возвращает список сегментов [[['Hello', 'Привет', ...]]]
                        translated_parts = [segment[0] for segment in data[0] if segment and segment[0]]
                        full_translation = "".join(translated_parts)
                        return full_translation, detected_src
        except Exception as e:
            logger.warning(f"Сбой сети при автопереводе '{clean_text[:20]}...' на '{target_lang}': {e}")

        # Фолбэк: если интернет упал, возвращаем оригинальный текст без краша бота
        return clean_text, detected_src