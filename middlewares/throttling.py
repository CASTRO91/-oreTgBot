import time
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from core.config import settings


class ThrottlingMiddleware(BaseMiddleware):
    """
    In-Memory Rate Limiter с защитой от спама и автоматической очисткой устаревших записей (защита от утечки памяти).
    Поддерживает как обычные текстовые сообщения, так и CallbackQuery (нажатия инлайн-кнопок).
    """

    def __init__(self, limit: float = settings.RATE_LIMIT_DELAY, max_cache_size: int = 10000):
        self.limit = limit
        self.max_cache_size = max_cache_size
        self.users: Dict[int, float] = {}
        self._last_cleanup = time.time()

    def _cleanup_expired(self, current_time: float) -> None:
        """Очистка устаревших записей для предотвращения утечки оперативной памяти."""
        if (current_time - self._last_cleanup < 60.0) and (len(self.users) < self.max_cache_size):
            return

        cutoff = current_time - (self.limit * 5.0)
        self.users = {uid: ts for uid, ts in self.users.items() if ts > cutoff}
        self._last_cleanup = current_time

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user") or getattr(event, "from_user", None)
        if not user:
            return await handler(event, data)

        user_id = user.id
        current_time = time.time()
        self._cleanup_expired(current_time)

        if user_id in self.users:
            delta = current_time - self.users[user_id]
            if delta < self.limit:
                # Превышен лимит запросов — глушим
                if isinstance(event, CallbackQuery):
                    try:
                        await event.answer()
                    except Exception:
                        pass
                return None

        self.users[user_id] = current_time
        return await handler(event, data)
