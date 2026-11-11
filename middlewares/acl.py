from typing import Optional
from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import AsyncSessionLocal
from database.models.user import User, UserRole
from services.access_service import AccessService
from services.user_service import UserService
from services.i18n_service import I18nService
from core.config import settings


class AdminRoleFilter(BaseFilter):
    """
    Фильтр проверки прав администратора:
    Разрешает доступ только SUPER_ADMIN и ADMIN.
    """

    async def __call__(self, event: TelegramObject, db_user: Optional[User] = None) -> bool:
        user = getattr(event, "from_user", None)
        if not user:
            return False

        # 1. Главный предохранитель: SUPER_ADMIN из конфига всегда имеет доступ
        if user.id == settings.ADMIN_ID:
            return True

        # 2. Проверка роли из переданного объекта пользователя (от outer_middleware)
        if db_user:
            return db_user.role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]

        # 3. Фолбэк на случай вызова вне контекста outer_middleware
        async with AsyncSessionLocal() as session:
            found_user = await UserService.get_by_id(session, user.id)
            return bool(found_user and found_user.role in [UserRole.ADMIN, UserRole.SUPER_ADMIN])


class PermissionFilter(BaseFilter):
    """
    Назначение:
        Автономный фильтр проверки прав доступа (ACL/RBAC).
        Если сессия не прокинута мидлварью — создает свою безопасную сессию на лету.
    """

    def __init__(self, permission_code: str):
        self.permission_code = permission_code

    async def __call__(self, event: TelegramObject, session: Optional[AsyncSession] = None) -> bool:
        user = getattr(event, "from_user", None)
        if not user:
            return False

        # Если сессия уже есть в data — используем её, иначе открываем новую
        if session:
            has_access = await AccessService.check_access(
                session=session,
                user_id=user.id,
                perm_code=self.permission_code
            )
        else:
            async with AsyncSessionLocal() as local_session:
                has_access = await AccessService.check_access(
                    session=local_session,
                    user_id=user.id,
                    perm_code=self.permission_code
                )

        if not has_access:
            if hasattr(event, "answer"):
                lang = getattr(user, "language_code", "ru") or "ru"
                denied_msg = await I18nService.tr("⛔️ У вас нет прав на выполнение этого действия.", lang)
                await event.answer(denied_msg)
            return False

        return True


class SuperAdminFilter(BaseFilter):
    """
    Фильтр жесткого ограничения: только для константного SUPER_ADMIN.
    Использование для команд назначения админов.
    """

    async def __call__(self, event: TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        if not user:
            return False
        return AccessService.is_super_admin(user.id)