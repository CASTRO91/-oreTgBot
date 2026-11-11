import asyncio
from datetime import datetime
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from database.models.queue import QueueTask, TaskStatus
from database.models.base import utc_now
from core.config import settings


class QueueManager:
    # Системное событие (для обратной совместимости)
    _new_task_event = asyncio.Event()
    # Реестр индивидуальных событий воркеров для предотвращения Race Condition
    _listeners: set[asyncio.Event] = set()

    @classmethod
    def register_listener(cls, event: asyncio.Event) -> None:
        """Регистрация индивидуального события воркера."""
        cls._listeners.add(event)

    @classmethod
    def unregister_listener(cls, event: asyncio.Event) -> None:
        """Удаление индивидуального события воркера при его остановке."""
        cls._listeners.discard(event)

    @classmethod
    def get_event(cls) -> asyncio.Event:
        return cls._new_task_event

    @classmethod
    def trigger_wake_up(cls) -> None:
        """Мгновенно будит ВСЕХ спящих воркеров без взаимного сброса сигналов."""
        cls._new_task_event.set()
        for event in list(cls._listeners):
            event.set()

    @classmethod
    async def enqueue(
            cls,
            session: AsyncSession,
            task_code: str,
            user_id: int,
            payload: dict,
            max_attempts: int = settings.DEFAULT_MAX_ATTEMPTS
    ) -> QueueTask:
        """Постановка задачи в очередь + моментальное пробуждение воркеров."""
        task = QueueTask(
            task_code=task_code,
            user_id=user_id,
            payload=payload,
            status=TaskStatus.PENDING,
            max_attempts=max_attempts
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)

        # ПИНАЕМ ВОРКЕРОВ: задача создана, хватит спать!
        cls.trigger_wake_up()
        return task

    @staticmethod
    async def claim_task(session: AsyncSession) -> QueueTask | None:
        """Атомарный захват задачи (Fetch-and-Lock)."""
        async with session.begin():
            subquery = (
                select(QueueTask.id)
                .where(QueueTask.status == TaskStatus.PENDING)
                .order_by(QueueTask.id.asc())
                .limit(1)
                .scalar_subquery()
            )

            stmt = (
                update(QueueTask)
                .where(
                    QueueTask.id == subquery,
                    QueueTask.status == TaskStatus.PENDING
                )
                .values(
                    status=TaskStatus.PROCESSING,
                    attempts=QueueTask.attempts + 1
                )
                .returning(QueueTask)
            )

            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    @staticmethod
    async def complete_task(session: AsyncSession, task_id: int):
        stmt = (
            update(QueueTask)
            .where(QueueTask.id == task_id)
            .values(
                status=TaskStatus.COMPLETED,
                processed_at=utc_now()
            )
        )
        await session.execute(stmt)
        await session.commit()

    @staticmethod
    async def fail_task(session: AsyncSession, task: QueueTask, error: str) -> bool:
        is_fatal = task.attempts >= task.max_attempts
        new_status = TaskStatus.FAILED if is_fatal else TaskStatus.PENDING

        stmt = (
            update(QueueTask)
            .where(QueueTask.id == task.id)
            .values(
                status=new_status,
                error_message=error,
                processed_at=utc_now() if is_fatal else None
            )
        )
        await session.execute(stmt)
        await session.commit()

        # Если задача вернулась в PENDING — снова будим пул для новой попытки
        if not is_fatal:
            QueueManager.trigger_wake_up()

        return is_fatal