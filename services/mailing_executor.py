import asyncio
import logging
from datetime import datetime
import pytz
from aiogram import Bot
from sqlalchemy import select

from database.session import AsyncSessionLocal
from database.models.mailing import ScheduledMailing, TargetType, MediaType
from database.models.user import User
from database.models.queue import QueueTask
from core.worker import task_registry
from core.config import settings
from services.group_service import GroupService
from database.models.mailing_log import MailingDeliveryLog
from services.i18n_service import I18nService

logger = logging.getLogger(__name__)

class MailingExecutor:
    """
    Назначение: Исполнение рассылки сообщений воркером с защитой от тихих часов и шаблонизацией.
    """

    @staticmethod
    def is_quiet_hour(user_timezone: str) -> bool:
        """
        Назначение: Проверка, находится ли пользователь сейчас в 'тихих часах' (ночь).
        Входные параметры:
            user_timezone (str): IANA часовой пояс пользователя.
        Возвращаемое значение:
            bool: True если сейчас ночь и слать нельзя, иначе False.
        """
        try:
            tz = pytz.timezone(user_timezone)
            user_now = datetime.now(tz)
            current_hour = user_now.hour

            if settings.QUIET_HOURS_START > settings.QUIET_HOURS_END:
                # Например, с 22:00 до 09:00
                return current_hour >= settings.QUIET_HOURS_START or current_hour < settings.QUIET_HOURS_END
            else:
                return settings.QUIET_HOURS_START <= current_hour < settings.QUIET_HOURS_END
        except Exception:
            return False

    @staticmethod
    def render_template(text: str, user: User) -> str:
        """
        Назначение: Безопасная подстановка переменных {first_name}, {last_name}, {username}, {address} в текст.
        Не падает с ошибками KeyError/ValueError при наличии любых других фигурных скобок или JSON.
        Входные параметры:
            text (str): Шаблон текста.
            user (User): Объект пользователя.
        Возвращаемое значение:
            str: Сформированный персонализированный текст.
        """
        if not text:
            return ""

        uname = f"@{user.username}" if user.username else (user.first_name or "")
        replacements = {
            "{first_name}": user.first_name or "",
            "{last_name}": user.last_name or "",
            "{username}": uname,
            "{address}": user.address or "",
        }

        result = text
        for placeholder, val in replacements.items():
            result = result.replace(placeholder, str(val))
        return result

    @classmethod
    async def send_media_message(cls, bot: Bot, user_id: int, text: str, media_type: MediaType, file_id: str | None) -> None:
        """
        Назначение: Отправка сообщения с учетом типа медиа-вложения (фото, видео, документ или текст).
        """
        if media_type == MediaType.PHOTO and file_id:
            await bot.send_photo(chat_id=user_id, photo=file_id, caption=text, parse_mode="HTML")
        elif media_type == MediaType.VIDEO and file_id:
            await bot.send_video(chat_id=user_id, video=file_id, caption=text, parse_mode="HTML")
        elif media_type == MediaType.DOCUMENT and file_id:
            await bot.send_document(chat_id=user_id, document=file_id, caption=text, parse_mode="HTML")
        else:
            await bot.send_message(chat_id=user_id, text=text, parse_mode="HTML")


@task_registry.register("TASK_DISPATCH_MAILING")
async def handle_dispatch_mailing_task(task: QueueTask, bot: Bot) -> None:
    """
    Назначение: Обработчик очереди задач с рассылкой по локальному времени каждого пользователя.
    """
    mailing_id = task.payload.get("mailing_id")
    if not mailing_id:
        return

    async with AsyncSessionLocal() as session:
        mailing = await session.get(ScheduledMailing, mailing_id)
        if not mailing:
            return

        # 1. Получаем список ID получателей
        target_user_ids = []
        if mailing.target_type == TargetType.ALL:
            stmt = select(User.telegram_id).where(User.is_banned == False)
            target_user_ids = list((await session.execute(stmt)).scalars().all())
        elif mailing.target_type == TargetType.USER:
            if mailing.target_id:
                target_user_ids = [mailing.target_id]
        elif mailing.target_type == TargetType.GROUP:
            if mailing.target_id:
                target_user_ids = await GroupService.get_group_member_ids(session, int(mailing.target_id))

        success_count = 0
        skipped_quiet_hours = 0

        for uid in target_user_ids:
            user = await session.get(User, uid)
            if not user or user.is_banned:
                continue

            # 2. ПРОВЕРКА ТИХИХ ЧАСОВ ПО ЛОКАЛЬНОМУ ВРЕМЕНИ ЮЗЕРА
            if MailingExecutor.is_quiet_hour(user.timezone):
                skipped_quiet_hours += 1
                logger.info(f"🌙 Пользователь {uid} сейчас спит ({user.timezone}). Пропуск отправки.")
                continue

            # 3. Отправка сообщения
            try:
                # Персонализация текста
                personalized_text = MailingExecutor.render_template(mailing.text, user)

                # Переводим текст на родной язык этого юзера!
                translated_text = await I18nService.tr(personalized_text, user.language_code)

                await MailingExecutor.send_media_message(
                    bot=bot,
                    user_id=uid,
                    text=translated_text,
                    media_type=mailing.media_type,
                    file_id=mailing.media_file_id
                )

                # Фиксируем лог доставки
                session.add(MailingDeliveryLog(mailing_id=mailing.id, user_id=uid))
                success_count += 1
                await asyncio.sleep(0.05)  # Лимиты Telegram
            except Exception as e:
                logger.warning(f"Не удалось доставить рассылку юзеру {uid}: {e}")

        await session.commit()
        logger.info(
            f"📢 Рассылка #{mailing.id} обработана: успешно {success_count}, "
            f"ночной режим пропустил {skipped_quiet_hours}."
        )