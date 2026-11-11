import logging
from typing import Optional, Tuple
from aiogram import Bot, types

logger = logging.getLogger(__name__)


class MediaRelayService:
    """
    Назначение:
        Универсальный сервис пересылки медиаконтента и сообщений в ядре бота.
        Позволяет пересылать текст, фото, видео, аудиофайлы, голосовые сообщения,
        видеокружочки (video_note) и документы между любыми пользователями и чатами
        без потери качества и с опциональным добавлением заголовка и инлайн-кнопок.
    """

    CAPTION_MAX_LEN = 1024
    TEXT_MAX_LEN = 4096

    @classmethod
    def extract_media_info(cls, message: types.Message) -> Tuple[str, Optional[str]]:
        """
        Назначение: Извлечение типа медиа и его уникального file_id из входящего сообщения.
        Возвращает: (media_type, file_id)
        """
        if message.photo:
            # Берем фото в максимальном разрешении (последний элемент в списке)
            return "PHOTO", message.photo[-1].file_id
        elif message.video:
            return "VIDEO", message.video.file_id
        elif message.audio:
            return "AUDIO", message.audio.file_id
        elif message.voice:
            return "VOICE", message.voice.file_id
        elif message.video_note:
            return "VIDEO_NOTE", message.video_note.file_id
        elif message.document:
            return "DOCUMENT", message.document.file_id
        elif message.animation:
            return "ANIMATION", message.animation.file_id
        elif message.sticker:
            return "STICKER", message.sticker.file_id
        return "TEXT", None

    @classmethod
    async def relay_message(
        cls,
        bot: Bot,
        message: types.Message,
        target_chat_id: int,
        header_text: Optional[str] = None,
        reply_markup: Optional[types.InlineKeyboardMarkup] = None
    ) -> bool:
        """
        Назначение:
            Надежная пересылка сообщения любого типа адресату.
            Использует нативный механизм copy_message / copy_to Telegram Bot API.
        Входные параметры:
            bot (Bot): Экземпляр бота.
            message (types.Message): Исходное входящее сообщение с медиа или текстом.
            target_chat_id (int): Telegram ID получателя.
            header_text (str, optional): Шапка сообщения (например: "✉️ Сообщение от администрации:").
            reply_markup (InlineKeyboardMarkup, optional): Инлайн-кнопки (например: "Ответить").
        Возвращаемое значение:
            bool: True в случае успешной доставки, False при ошибке.
        """
        media_type, _ = cls.extract_media_info(message)

        try:
            # 1. Текстовое сообщение
            if media_type == "TEXT":
                raw_text = message.text or ""
                final_text = f"{header_text}\n\n{raw_text}".strip() if header_text else raw_text
                await bot.send_message(
                    chat_id=target_chat_id,
                    text=final_text[:cls.TEXT_MAX_LEN],
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
                return True

            # 2. Медиа без поддержки подписи (Видеокружочки и Стикеры)
            if media_type in ("VIDEO_NOTE", "STICKER"):
                if header_text:
                    await bot.send_message(chat_id=target_chat_id, text=header_text, parse_mode="HTML")
                await message.copy_to(
                    chat_id=target_chat_id,
                    reply_markup=reply_markup
                )
                return True

            # 3. Медиа с поддержкой подписи (Фото, Видео, Аудио, Голосовые, Документы, Анимации)
            orig_caption = message.caption or ""
            if header_text:
                combined_caption = f"{header_text}\n\n{orig_caption}".strip()
            else:
                combined_caption = orig_caption

            # Если комбинированная подпись укладывается в лимит Telegram (1024 символа)
            if len(combined_caption) <= cls.CAPTION_MAX_LEN:
                await message.copy_to(
                    chat_id=target_chat_id,
                    caption=combined_caption if combined_caption else None,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
            else:
                # Если подпись слишком длинная — отправляем шапку отдельно, затем сам медиафайл
                if header_text:
                    await bot.send_message(chat_id=target_chat_id, text=header_text, parse_mode="HTML")
                await message.copy_to(
                    chat_id=target_chat_id,
                    caption=orig_caption[:cls.CAPTION_MAX_LEN] if orig_caption else None,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )

            return True

        except Exception as e:
            logger.error(f"Ошибка пересылки медиасообщения ({media_type}) для chat_id={target_chat_id}: {e}")
            return False
