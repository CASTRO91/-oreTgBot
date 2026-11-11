import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
from croniter import croniter
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import AsyncSessionLocal
from database.models.mailing import ScheduledMailing, ScheduleType
from core.queue import QueueManager
from core.config import settings
from database.models.mailing import ScheduledMailing, TargetType

logger = logging.getLogger(__name__)


class SchedulerService:
    """
    Назначение: Фоновый планировщик отложенных и периодических рассылок.
    """

    @staticmethod
    def calculate_next_cron_run(cron_rule: str, base_time: Optional[datetime] = None) -> datetime:
        """
        Назначение: Расчет следующей даты запуска по Cron-выражению.
        Входные параметры:
            cron_rule (str): Строка формата cron (например, '0 10 * * 1').
            base_time (datetime, optional): Базовое время отсчета.
        Возвращаемое значение:
            datetime: Следующее время запуска в UTC.
        """
        base = base_time or datetime.utcnow()
        iterator = croniter(cron_rule, base)
        return iterator.get_next(datetime)

    @classmethod
    async def poll_scheduled_mailings(cls) -> None:
        """
        Назначение: Проверка наступивших рассылок и передача их в очередь задач.
        Входные параметры: Нет.
        Возвращаемое значение: None.
        """
        now = datetime.utcnow()
        async with AsyncSessionLocal() as session:
            # Ищем активные рассылки, время которых наступило
            stmt = (
                select(ScheduledMailing)
                .where(
                    ScheduledMailing.is_active == True,
                    ScheduledMailing.next_run_at <= now
                )
            )
            mailings = list((await session.execute(stmt)).scalars().all())

            for mailing in mailings:
                logger.info(f"⏰ Наступило время рассылки #{mailing.id} '{mailing.title}'. Ставим задачу в очередь...")

                # 1. Отправляем в очередь ядра
                await QueueManager.enqueue(
                    session=session,
                    task_code="TASK_DISPATCH_MAILING",
                    user_id=mailing.created_by,
                    payload={"mailing_id": mailing.id}
                )

                # 2. Обновляем статус или высчитываем следующий цикл
                if mailing.schedule_type == ScheduleType.ONCE:
                    mailing.is_active = False
                    mailing.last_run_at = now
                else:
                    # Повторяющаяся рассылка (RECURRENT)
                    mailing.last_run_at = now
                    mailing.next_run_at = cls.calculate_next_cron_run(mailing.cron_rule, now)
                    logger.info(f"🔄 Рассылка #{mailing.id} запланирована на следующий цикл: {mailing.next_run_at}")

            await session.commit()

    @classmethod
    async def start_scheduler_loop(cls) -> None:
        """
        Назначение: Бесконечный фоновый цикл планировщика рассылок.
        Входные параметры: Нет.
        Возвращаемое значение: None.
        """
        logger.info("⏱ Планировщик отложенных рассылок запущен.")
        while True:
            try:
                await cls.poll_scheduled_mailings()
            except Exception as e:
                logger.error(f"Ошибка в цикле планировщика: {e}")
            await asyncio.sleep(settings.SCHEDULER_CHECK_INTERVAL)

    @staticmethod
    async def delete_mailings_by_target(
            session: AsyncSession,
            target_type: TargetType,
            target_id: Optional[int] = None
    ) -> int:
        """
        Назначение: Удаление рассылок по типу аудитории (Всем, Юзеру, конкретной Группе или всем Группам).
        Входные параметры:
            session (AsyncSession): Сессия БД.
            target_type (TargetType): ALL, USER или GROUP.
            target_id (int, optional): ID пользователя или ID группы.
        Возвращаемое значение:
            int: Количество удаленных рассылок.
        """
        stmt = delete(ScheduledMailing).where(ScheduledMailing.target_type == target_type)
        if target_id is not None:
            stmt = stmt.where(ScheduledMailing.target_id == target_id)

        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount

    @staticmethod
    async def delete_all_mailings(session: AsyncSession) -> int:
        """
        Назначение: Ультра-удаление абсолютно всех рассылок в системе.
        """
        stmt = delete(ScheduledMailing)
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount