import enum
from datetime import datetime
from sqlalchemy import BigInteger, String, Integer, DateTime, Enum, JSON, Text, Index
from sqlalchemy.orm import Mapped, mapped_column
from database.models.base import Base
from core.config import settings


class TaskStatus(str, enum.Enum):
    PENDING = "PENDING"  # Ожидает воркера
    PROCESSING = "PROCESSING"  # Захвачено воркером
    COMPLETED = "COMPLETED"  # Успешно выполнено
    FAILED = "FAILED"  # Ошибка (попытки исчерпаны)


class QueueTask(Base):
    __tablename__ = "task_queue"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_code: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus), default=TaskStatus.PENDING, nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=settings.DEFAULT_MAX_ATTEMPTS, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # СОСТАВНОЙ ИНДЕКС ДЛЯ МГНОВЕННОГО ЗАХВАТА ЗАДАЧ ВОРКЕРАМИ
    __table_args__ = (
        Index("ix_task_queue_status_id", "status", "id"),
    )