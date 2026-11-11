import asyncio
import logging
import sys
from aiogram import Router, types, Bot
from aiogram.filters import Command
from middlewares.acl import PermissionFilter

from core.app import BotApplication
from database.models.queue import QueueTask
from core.queue import QueueManager
from database.session import AsyncSessionLocal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    stream=sys.stdout
)

# 1. Создаем экземпляр платформы
app = BotApplication()

# 2. Пример регистрации внешней задачи конкретного проекта
@app.register_task_handler("SAMPLE_EXTERNAL_TASK")
async def execute_sample_task(task: QueueTask, bot: Bot) -> None:
    """
    Назначение: Обработка внешней задачи из очереди.
    Входные параметры:
        task (QueueTask): Объект задачи из базы данных.
        bot (Bot): Экземпляр бота для отправки сообщений.
    Возвращаемое значение: None.
    """
    await asyncio.sleep(2)  # Эмуляция полезной нагрузки
    await bot.send_message(
        chat_id=task.user_id,
        text=f"✅ Ваша фоновая задача #{task.id} успешно выполнена внешним модулем!"
    )

# 3. Пример регистрации кастомного роутера внешнего проекта
custom_project_router = Router(name="custom_project_router")

# Команда доступна ТОЛЬКО тем, у кого есть право 'TASK_SYSTEM_CALC' (или Админам/SuperAdmin)
@custom_project_router.message(Command("do_work"), PermissionFilter("TASK_SYSTEM_CALC"))
async def cmd_do_work(message: types.Message) -> None:
    """
    Назначение: Запуск тестовой задачи с проверкой ACL прав.
    """
    async with AsyncSessionLocal() as session:
        task = await QueueManager.enqueue(
            session=session,
            task_code="SAMPLE_EXTERNAL_TASK",
            user_id=message.from_user.id,
            payload={"request_text": message.text}
        )
    await message.answer(f"⏳ Задача #{task.id} отправлена в фоновую очередь.")

app.include_plugin_router(custom_project_router)

# 4. Точка запуска
if __name__ == "__main__":
    try:
        asyncio.run(app.run())
    except (KeyboardInterrupt, SystemExit):
        logging.warning("Работа завершена пользователем.")