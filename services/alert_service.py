import html
import logging
from aiogram import Bot
from core.config import settings

logger = logging.getLogger(__name__)


class AlertService:
    @staticmethod
    async def notify_task_failed(bot: Bot, task_id: int, task_code: str, user_id: int, error: str, attempts: int):
        """
        Отправка алерта Главному Админу при критическом падении задачи.
        Экранирует HTML и обрезает слишком длинный стек-трейс для надежной отправки.
        """
        safe_error = html.escape(str(error)[:1500])
        safe_code = html.escape(str(task_code))

        text = (
            f"🚨 <b>Критическая ошибка задачи!</b>\n\n"
            f"▫️ <b>ID задачи:</b> <code>#{task_id}</code>\n"
            f"▫️ <b>Код:</b> <code>{safe_code}</code>\n"
            f"▫️ <b>Инициатор (TG ID):</b> <code>{user_id}</code>\n"
            f"▫️ <b>Количество попыток:</b> {attempts}\n"
            f"▫️ <b>Ошибка:</b> <code>{safe_error}</code>"
        )
        try:
            await bot.send_message(chat_id=settings.ADMIN_ID, text=text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Не удалось отправить HTML-алерт главному админу: {e}")
            try:
                # Фолбэк на отправку чистым текстом без parse_mode при сбоях парсера
                plain_text = (
                    f"🚨 Критическая ошибка задачи #{task_id} [{task_code}]!\n"
                    f"Инициатор: {user_id}, Попыток: {attempts}\n"
                    f"Ошибка: {str(error)[:1500]}"
                )
                await bot.send_message(chat_id=settings.ADMIN_ID, text=plain_text)
            except Exception as ex_fallback:
                logger.error(f"Полный сбой отправки алерта: {ex_fallback}")
