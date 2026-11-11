import asyncio
import logging
from typing import Callable, Awaitable, Any, List
from aiogram import Bot, Dispatcher, Router
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from sqlalchemy import select

from core.config import settings
from database.session import engine
from database.models.base import Base
from core.worker import DynamicWorkerPool, task_registry, TaskHandler
from middlewares import ThrottlingMiddleware, AuthAndDBSessionMiddleware
from handlers import register_all_handlers
from services.retention_service import RetentionService
from services.scheduler_service import SchedulerService
import services.mailing_executor  # Регистрирует хэндлер TASK_DISPATCH_MAILING в task_registry

logger = logging.getLogger("CoreSDK")


class BotApplication:
    """
    Назначение:
        Главный оркестратор ядра (SDK). Управляет жизненным циклом базы данных,
        фоновых воркеров, обработчиков Telegram и сторонних плагинов.
    """

    def __init__(self) -> None:
        """
        Назначение: Инициализация компонентов бота и диспетчера с корпоративным SSL фиксом.
        Входные параметры: Нет.
        Возвращаемое значение: None.
        """
        session = AiohttpSession()
        session._connector_init = {"ssl": False}

        self.bot = Bot(
            token=settings.BOT_TOKEN,
            session=session,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        self.dp = Dispatcher()
        self.workers = DynamicWorkerPool(bot=self.bot)
        self._custom_routers: List[Router] = []
        self._retention_task: asyncio.Task | None = None

    def register_task_handler(self, task_code: str) -> Callable[[TaskHandler], TaskHandler]:
        """
        Назначение:
            Декоратор для регистрации функций-исполнителей фоновых задач из внешних проектов.
        Входные параметры:
            task_code (str): Уникальный строковый код задачи.
        Возвращаемое значение:
            Callable[[TaskHandler], TaskHandler]: Обернутый декоратор.
        """

        def decorator(func: TaskHandler) -> TaskHandler:
            task_registry.register(task_code)(func)
            return func

        return decorator

    async def _seed_default_permissions(self) -> None:
        """
        Назначение: Автоматическое создание базовых прав (системных и пользовательских) при старте.
        """
        from database.models.permission import Permission
        from database.session import AsyncSessionLocal

        default_perms = [
            # Пользовательские права (is_system=False) — именно они отображаются в ACL!
            {"code": "TASK_SYSTEM_CALC", "desc": "Запуск тяжелых вычислений", "is_system": False},
            {"code": "EXPORT_PERSONAL_DATA", "desc": "Экспорт своих данных", "is_system": False},
            {"code": "PRIORITY_QUEUE", "desc": "Приоритетная очередь задач", "is_system": False},
            # Системные права (is_system=True) — только для SuperAdmin
            {"code": "MANAGE_ADMINS", "desc": "Назначение администраторов", "is_system": True},
            {"code": "VIEW_SYSTEM_LOGS", "desc": "Просмотр системного аудита", "is_system": True},
        ]

        async with AsyncSessionLocal() as session:
            for p in default_perms:
                stmt = select(Permission).where(Permission.code == p["code"])
                exists = (await session.execute(stmt)).scalar_one_or_none()
                if not exists:
                    new_perm = Permission(
                        code=p["code"],
                        description=p["desc"],
                        is_system=p["is_system"]
                    )
                    session.add(new_perm)
            await session.commit()

    def include_plugin_router(self, router: Router) -> None:
        """
        Назначение:
            Подключение кастомных пользовательских роутеров от внешних ботов к ядру.
        Входные параметры:
            router (Router): Роутер библиотеки Aiogram с готовыми хэндлерами.
        Возвращаемое значение: None.
        """
        self._custom_routers.append(router)

    async def _setup_middlewares(self) -> None:
        """
        Назначение: Подключение системных слоев проверки (Антифлуд, Сессия БД, Права).
        Входные параметры: Нет.
        Возвращаемое значение: None.
        """
        throttling = ThrottlingMiddleware()
        self.dp.message.outer_middleware(throttling)
        self.dp.callback_query.outer_middleware(throttling)
        self.dp.message.outer_middleware(AuthAndDBSessionMiddleware())
        self.dp.callback_query.outer_middleware(AuthAndDBSessionMiddleware())

    async def _setup_routes(self) -> None:
        """
        Назначение: Регистрация системных роутеров ядра и внешних кастомных роутеров.
        Входные параметры: Нет.
        Возвращаемое значение: None.
        """
        # Системные роуты (регистрация, профиль, админка)
        register_all_handlers(self.dp)

        # Подключение плагинов внешних ботов
        for r in self._custom_routers:
            self.dp.include_router(r)

    async def run(self) -> None:
        """
        Назначение:
            Точка входа запуска системы: проверка схемы БД, запуск пула воркеров,
            фоновой очистки устаревших данных и поллинга Telegram.
        Входные параметры: Нет.
        Возвращаемое значение: None.
        """
        logger.info("Инициализация инфраструктуры ядра...")

        # 1. Автоматическая проверка БД
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # 2. Настройка конвейера обработки
        await self._setup_middlewares()
        await self._setup_routes()

        await self._seed_default_permissions()
        # 3. Старт воркеров
        await self.workers.start()

        # 4. Старт сервиса очистки мусора (Retention)
        self._retention_task = asyncio.create_task(RetentionService.start_periodic_cleanup())
        # 5. Старт фонового планировщика рассылок
        self._scheduler_task = asyncio.create_task(SchedulerService.start_scheduler_loop())

        try:
            logger.info("Запуск Telegram Polling...")
            await self.bot.delete_webhook(drop_pending_updates=True)
            await self.dp.start_polling(self.bot)
        finally:
            logger.info("Завершение процессов ядра...")
            if self._retention_task:
                self._retention_task.cancel()
            if hasattr(self, "_scheduler_task") and self._scheduler_task:
                self._scheduler_task.cancel()
            await self.workers.stop()
            await self.bot.session.close()
            await engine.dispose()
            logger.info("Все подсистемы остановлены.")
