import asyncio
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

# Импортируем конфиг и базу нашего ядра
from core.config import settings
from database.models.base import Base
# Обязательно импортируем все модели, чтобы Alembic их увидел в метаданных
from database.models import User, Permission, UserPermission, QueueTask, ActionLog

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """
    Назначение: Запуск миграций в оффлайн-режиме (без активного подключения к БД).
    Входные параметры: Нет.
    Возвращаемое значение: None.
    """
    url = settings.DB_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection: Connection) -> None:
    """
    Назначение: Выполнение миграций внутри переданного синхронного соединения.
    Входные параметры:
        connection (Connection): Объект соединения SQLAlchemy.
    Возвращаемое значение: None.
    """
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations() -> None:
    """
    Назначение: Создание асинхронного движка и запуск миграций в онлайн-режиме.
    Входные параметры: Нет.
    Возвращаемое значение: None.
    """
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = settings.DB_URL

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()

def run_migrations_online() -> None:
    """
    Назначение: Точка входа для онлайн-миграций.
    Входные параметры: Нет.
    Возвращаемое значение: None.
    """
    asyncio.run(run_async_migrations())

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()