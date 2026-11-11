import hashlib
from datetime import datetime
from sqlalchemy import Integer, String, Text, Boolean, DateTime, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from database.models.base import Base, utc_now


class LocalizationCache(Base):
    """
    Назначение:
        Универсальная матрица кэширования переводов (Any-to-Any).
        Хранит переводы между любыми языковыми парами мира.
    """
    __tablename__ = "localization_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Уникальный MD5 хэш от: src_lang + ":" + target_lang + ":" + src_text
    cache_key: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)

    src_lang: Mapped[str] = mapped_column(String(8), nullable=False, index=True)  # Язык оригинала ('ru', 'zh', 'en'...)
    target_lang: Mapped[str] = mapped_column(String(8), nullable=False,
                                             index=True)  # Язык назначения ('en', 'es', 'it'...)

    src_text: Mapped[str] = mapped_column(Text, nullable=False)
    translated_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Флаг ручной правки через БД: если True, автопереводчик никогда не перезапишет этот текст
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now,
                                                 nullable=False)

    __table_args__ = (
        Index("ix_lang_pair_lookup", "src_lang", "target_lang", "cache_key"),
    )

    @staticmethod
    def generate_cache_key(src_lang: str, target_lang: str, text: str) -> str:
        """
        Назначение: Генерация MD5-хэша для быстрого поиска в БД за O(1).
        Входные параметры:
            src_lang (str): Язык оригинала.
            target_lang (str): Язык назначения.
            text (str): Исходный текст.
        Возвращаемое значение:
            str: 32-символьный хэш.
        """
        payload = f"{src_lang.lower().strip()}:{target_lang.lower().strip()}:{text.strip()}"
        return hashlib.md5(payload.encode("utf-8")).hexdigest()