import enum
from datetime import datetime
from sqlalchemy import Integer, BigInteger, String, Text, DateTime, Enum, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column
from database.models.base import Base, utc_now


class ScheduleType(str, enum.Enum):
    ONCE = "ONCE"  # Разовое отправление
    RECURRENT = "RECURRENT"  # Циклическое (по Cron-правилу)


class TargetType(str, enum.Enum):
    ALL = "ALL"  # Всем пользователям
    USER = "USER"  # Одному конкретному пользователю
    GROUP = "GROUP"  # Определенной группе пользователей


class MediaType(str, enum.Enum):
    NONE = "NONE"  # Только текст
    PHOTO = "PHOTO"  # Фотография с текстом
    VIDEO = "VIDEO"  # Видеозапись с текстом
    DOCUMENT = "DOCUMENT"  # Документ/файл с текстом


class ScheduledMailing(Base):
    """
    Назначение: Модель запланированных и циклических рассылок с медиа-вложениями.
    """
    __tablename__ = "scheduled_mailings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)  # Текст с поддержкой {first_name} и HTML

    # Медиа-вложения
    media_type: Mapped[MediaType] = mapped_column(Enum(MediaType), default=MediaType.NONE, nullable=False)
    media_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Таргетинг
    target_type: Mapped[TargetType] = mapped_column(Enum(TargetType), nullable=False)
    target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # ID юзера или ID группы

    # Расписание
    schedule_type: Mapped[ScheduleType] = mapped_column(Enum(ScheduleType), nullable=False)
    cron_rule: Mapped[str | None] = mapped_column(String(64), nullable=True)  # Для RECURRENT
    target_time: Mapped[str | None] = mapped_column(String(5),
                                                    nullable=True)  # "10:00" - желаемое локальное время юзера

    # Статус и тайминги
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_active_next_run", "is_active", "next_run_at"),
    )