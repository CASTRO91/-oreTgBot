from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from database.session import AsyncSessionLocal
from services.user_service import UserService
from utils.states import RegistrationStates
from services.i18n_service import I18nService

class AuthAndDBSessionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # 1. Извлекаем пользователя из события
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        # 2. Оборачиваем весь пайплайн в сессию SQLAlchemy
        async with AsyncSessionLocal() as session:
            data["session"] = session

            # Ищем пользователя в БД
            db_user = await UserService.get_by_id(session, user.id)

            # 3. ПРОВЕРКА БАНА: если забанен — прерываем цепочку
            if db_user and db_user.is_banned:
                ban_text = await I18nService.tr("⛔️ Ваш аккаунт заблокирован администратором.", db_user.language_code)
                if isinstance(event, Message):
                    await event.answer(ban_text)
                elif isinstance(event, CallbackQuery):
                    await event.answer(ban_text, show_alert=True)
                return None

            # 4. ПРОВЕРКА РЕГИСТРАЦИИ:
            # Если юзера нет в БД, разрешаем ТОЛЬКО /start и шаги FSM-регистрации
            if not db_user:
                state: FSMContext = data.get("state")
                current_state = await state.get_state() if state else None

                is_registering = current_state in [
                    RegistrationStates.waiting_for_first_name.state,
                    RegistrationStates.waiting_for_last_name.state,
                    RegistrationStates.waiting_for_address.state,
                    RegistrationStates.waiting_for_phone.state,
                ]

                # Проверяем команду /start
                is_start_cmd = isinstance(event, Message) and event.text and event.text.startswith("/start")

                if not is_registering and not is_start_cmd:
                    tg_lang = user.language_code or "ru"
                    req_reg_text = await I18nService.tr(
                        "⚠️ Вы не зарегистрированы. Пожалуйста, отправьте команду /start для регистрации.",
                        tg_lang
                    )
                    if isinstance(event, Message):
                        await event.answer(req_reg_text)
                    elif isinstance(event, CallbackQuery):
                        await event.answer(req_reg_text, show_alert=True)
                    return None

            # Прокидываем пользователя в данные хэндлера
            data["db_user"] = db_user
            return await handler(event, data)