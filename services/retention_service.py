import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import delete
from database.session import AsyncSessionLocal
from database.models.queue import QueueTask, TaskStatus
from database.models.audit import ActionLog
from database.models.base import utc_now
from core.config import settings

logger = logging.getLogger(__name__)

class RetentionService:
    """Сервис фоновой очистки устаревших данных."""
    @staticmethod
    async def cleanup_old_data():
        logger.info("🧹 Запуск плановой очистки устаревших данных...")
        now = utc_now()
        task_cutoff = now - timedelta(days=settings.RETENTION_DAYS_TASKS)
        log_cutoff = now - timedelta(days=settings.RETENTION_DAYS_LOGS)

        async with AsyncSessionLocal() as session:
            try:
                # 1. Удаляем выполненные и ошибочные задачи старше N дней
                stmt_tasks = delete(QueueTask).where(
                    QueueTask.status.in_([TaskStatus.COMPLETED, TaskStatus.FAILED]),
                    QueueTask.created_at < task_cutoff
                )
                res_tasks = await session.execute(stmt_tasks)

                # 2. Удаляем старые логи аудита
                stmt_logs = delete(ActionLog).where(ActionLog.created_at < log_cutoff)
                res_logs = await session.execute(stmt_logs)

                await session.commit()
                logger.info(
                    f"🧹 Очистка завершена: удалено {res_tasks.rowcount} старых задач и "
                    f"{res_logs.rowcount} записей аудита."
                )
            except Exception as e:
                logger.error(f"Ошибка при очистке данных: {e}")

    @classmethod
    async def start_periodic_cleanup(cls):
        """Бесконечный фоновый цикл очистки."""
        interval_seconds = settings.CLEANUP_INTERVAL_HOURS * 3600
        while True:
            try:
                await cls.cleanup_old_data()
            except Exception as e:
                logger.error(f"Ошибка в цикле RetentionService: {e}")
            await asyncio.sleep(interval_seconds)