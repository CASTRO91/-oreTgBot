import asyncio
import logging
import time
from typing import Callable, Dict, Awaitable, Any, Set
from aiogram import Bot

from database.session import AsyncSessionLocal
from database.models.queue import QueueTask, TaskStatus
from core.queue import QueueManager
from core.config import settings
from services.alert_service import AlertService
from sqlalchemy import select, func

logger = logging.getLogger(__name__)

TaskHandler = Callable[[QueueTask, Bot], Awaitable[Any]]


class TaskRegistry:
    def __init__(self):
        self._handlers: Dict[str, TaskHandler] = {}

    def register(self, task_code: str):
        def decorator(func: TaskHandler):
            self._handlers[task_code] = func
            return func

        return decorator

    def get(self, task_code: str) -> TaskHandler | None:
        return self._handlers.get(task_code)


task_registry = TaskRegistry()


class DynamicWorkerPool:
    """
    Продвинутый пул воркеров с:
    - Автомасштабированием (от min до max)
    - Откисанием лишних при простое (Scale-Down)
    - Защитой от утечек памяти (Worker Recycling)
    """

    def __init__(
            self,
            bot: Bot,
            min_workers: int = settings.MIN_WORKERS,
            max_workers: int = settings.MAX_WORKERS,
            idle_timeout: float = settings.WORKER_IDLE_TIMEOUT,
            max_tasks_per_worker: int = settings.MAX_TASKS_PER_WORKER,
            max_worker_lifetime: float = settings.MAX_WORKER_LIFETIME
    ):
        self.bot = bot
        self.min_workers = min_workers
        self.max_workers = max_workers
        self.idle_timeout = idle_timeout
        self.max_tasks_per_worker = max_tasks_per_worker
        self.max_worker_lifetime = max_worker_lifetime

        self.is_running = False
        self._worker_id_counter = 0
        self._active_workers: Set[asyncio.Task] = set()
        self._busy_workers_count = 0
        self._scaler_task: asyncio.Task | None = None

    async def _worker_loop(self, worker_id: int, is_core: bool):
        logger.info(f"👷 [Воркер #{worker_id}] Запущен ({'Базовый' if is_core else 'Динамический'}).")

        tasks_processed = 0
        created_at = time.time()
        last_busy_time = time.time()
        current_sleep = settings.POLL_MIN_INTERVAL
        
        # Индивидуальное событие воркера для предотвращения Race Condition
        worker_event = asyncio.Event()
        QueueManager.register_listener(worker_event)

        try:
            while self.is_running:
                try:
                    # 1. Проверка рециркуляции памяти (TTL / Лимит задач)
                    lifetime = time.time() - created_at
                    if tasks_processed >= self.max_tasks_per_worker or lifetime >= self.max_worker_lifetime:
                        logger.info(
                            f"♻️ [Воркер #{worker_id}] Рециркуляция памяти (задач: {tasks_processed}, аптайм: {int(lifetime)}с). Перезапуск."
                        )
                        break

                    # 2. Пытаемся захватить задачу
                    task = None
                    async with AsyncSessionLocal() as session:
                        task = await QueueManager.claim_task(session)

                    # 3. ЕСЛИ ЗАДАЧ НЕТ — ВКЛЮЧАЕТСЯ УМНЫЙ СОН
                    if not task:
                        idle_time = time.time() - last_busy_time

                        # Откисание динамического воркера
                        if not is_core and idle_time >= self.idle_timeout:
                            logger.info(f"🍂 [Воркер #{worker_id}] Простаивал {int(idle_time)}с. Откисает (Scale-Down).")
                            break

                        # Сбрасываем персональный флаг перед ожиданием
                        worker_event.clear()

                        # Спим с возможностью мгновенного пробуждения
                        try:
                            # Ждем либо наступления персонального события новой задачи, либо истечения current_sleep
                            await asyncio.wait_for(worker_event.wait(), timeout=current_sleep)
                            # Если проснулись по событию — сбрасываем сон на минимум
                            current_sleep = settings.POLL_MIN_INTERVAL
                        except asyncio.TimeoutError:
                            # Если вышли по таймауту (события не было) — увеличиваем интервал сна (Backoff)
                            current_sleep = min(
                                current_sleep * settings.POLL_BACKOFF_FACTOR,
                                settings.POLL_MAX_INTERVAL
                            )

                        continue

                    # 4. ЗАДАЧА ЕСТЬ — ВЫПОЛНЯЕМ
                    current_sleep = settings.POLL_MIN_INTERVAL  # Сброс сна
                    self._busy_workers_count += 1
                    last_busy_time = time.time()
                    tasks_processed += 1
                    logger.info(f"👷 [Воркер #{worker_id}] Взял задачу #{task.id} [{task.task_code}]")

                    async with AsyncSessionLocal() as session:
                        handler = task_registry.get(task.task_code)
                        if not handler:
                            err_msg = f"Хэндлер задачи '{task.task_code}' не найден!"
                            logger.error(err_msg)
                            if await QueueManager.fail_task(session, task, err_msg):
                                await AlertService.notify_task_failed(self.bot, task.id, task.task_code, task.user_id,
                                                                      err_msg, task.attempts)
                        else:
                            try:
                                await handler(task, self.bot)
                                await QueueManager.complete_task(session, task.id)
                                logger.info(f"✅ [Воркер #{worker_id}] Успешно завершил задачу #{task.id}")
                            except Exception as e:
                                logger.exception(f"❌ [Воркер #{worker_id}] Ошибка задачи #{task.id}: {e}")
                                if await QueueManager.fail_task(session, task, str(e)):
                                    await AlertService.notify_task_failed(self.bot, task.id, task.task_code, task.user_id,
                                                                          str(e), task.attempts)

                    self._busy_workers_count = max(0, self._busy_workers_count - 1)

                except Exception as e:
                    logger.error(f"Сбой в воркере #{worker_id}: {e}")
                    self._busy_workers_count = max(0, self._busy_workers_count - 1)
                    await asyncio.sleep(settings.POLL_MIN_INTERVAL)
        finally:
            QueueManager.unregister_listener(worker_event)
            logger.info(f"🛑 [Воркер #{worker_id}] Остановлен.")

    def _spawn_worker(self, is_core: bool):
        """Создание нового асинхронного воркера."""
        self._worker_id_counter += 1
        w_id = self._worker_id_counter
        t = asyncio.create_task(self._worker_loop(w_id, is_core))
        self._active_workers.add(t)
        t.add_done_callback(self._active_workers.discard)

    async def _autoscaler_loop(self):
        """Диспетчер автомасштабирования (Scaler Daemon)."""
        logger.info("📈 Диспетчер масштабирования запущен.")
        while self.is_running:
            try:
                # Очищаем уже завершившиеся таски
                self._active_workers = {t for t in self._active_workers if not t.done()}
                current_count = len(self._active_workers)

                # 1. Всегда гарантируем наличие MIN_WORKERS
                if current_count < self.min_workers:
                    needed = self.min_workers - current_count
                    for _ in range(needed):
                        self._spawn_worker(is_core=True)

                # 2. Проверяем нагрузку в БД (сколько задач ждет)
                async with AsyncSessionLocal() as session:
                    stmt = select(func.count(QueueTask.id)).where(QueueTask.status == TaskStatus.PENDING)
                    pending_count = (await session.execute(stmt)).scalar() or 0

                # 3. Решение о Scale-Up:
                # Если висящих задач больше, чем свободных воркеров прямо сейчас
                free_workers = current_count - self._busy_workers_count
                if pending_count > free_workers and current_count < self.max_workers:
                    logger.info(
                        f"⚡️ Нагрузка растет! Задач в очереди: {pending_count}, Свободно воркеров: {free_workers}. "
                        f"Поднимаем доп. воркера ({current_count + 1}/{self.max_workers})"
                    )
                    self._spawn_worker(is_core=False)

                await asyncio.sleep(2.0)  # Цикл оценки нагрузки каждые 2 сек

            except Exception as e:
                logger.error(f"Ошибка диспетчера масштабирования: {e}")
                await asyncio.sleep(2.0)

    async def start(self):
        self.is_running = True
        # Запускаем начальные дежурные воркеры
        for _ in range(self.min_workers):
            self._spawn_worker(is_core=True)
        # Запускаем фоновый диспетчер
        self._scaler_task = asyncio.create_task(self._autoscaler_loop())

    async def stop(self):
        logger.info("Остановка пула воркеров...")
        self.is_running = False
        if self._scaler_task:
            self._scaler_task.cancel()

        for t in list(self._active_workers):
            t.cancel()

        await asyncio.gather(*self._active_workers, return_exceptions=True)
        logger.info("Все воркеры корректно остановлены.")


# Для обратной совместимости импорта в main.py
WorkerPool = DynamicWorkerPool