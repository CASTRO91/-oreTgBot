import logging
from aiogram import Bot
from core.config import settings

logger = logging.getLogger(__name__)

class AlertService:
    @staticmethod
    async def notify_task_failed(bot: Bot, task_id: int, task_code: str, user_id: int, error: str, attempts: int):
        """Отправка алерта Главному Админу при критическом падении задачи."""
        text = (
            f"🚨 <b>Критическая ошибка задачи!</b>\n\n"
            f"▫️ <b>ID задачи:</b> <code>#{task_id}</code>\n"
            f"▫️ <b>Код:</b> <code>{task_code}</code>\n"
            f"▫️ <b>Инициатор (TG ID):</b> <code>{user_id}</code>\n"
            f"▫️ <b>Количество попыток:</b> {attempts}\n"
            f"▫️ <b>Ошибка:</b> <code>{error}</code>"
        )
        try:
            await bot.send_message(chat_id=settings.ADMIN_ID, text=text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Не удалось отправить алерт главному админу: {e}")