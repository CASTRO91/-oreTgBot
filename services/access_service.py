from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from database.models.user import User, UserRole
from database.models.permission import Permission, UserPermission
from services.user_service import UserService
from core.config import settings

class AccessService:
    @staticmethod
    def is_super_admin(user_id: int) -> bool:
        """Супер-админ только один — зашит в конфиге."""
        return user_id == settings.ADMIN_ID

    @classmethod
    async def promote_to_admin(cls, session: AsyncSession, initiator_id: int, target_id: int) -> bool:
        """
        Назначение админа.
        ПРЕДОХРАНИТЕЛЬ: Только SUPER_ADMIN может создавать других админов!
        """
        if not cls.is_super_admin(initiator_id):
            raise PermissionError("ТОЛЬКО Главный Админ (SUPER_ADMIN) может назначать других администраторов!")

        target_user = await UserService.get_by_id(session, target_id)
        if not target_user:
            return False

        target_user.role = UserRole.ADMIN
        await session.commit()
        await UserService.log_action(session, initiator_id, "ADMIN_PROMOTED", {"target_id": target_id})
        return True

    @classmethod
    async def demote_admin(cls, session: AsyncSession, initiator_id: int, target_id: int) -> bool:
        """Разжалование админа (также только для SUPER_ADMIN)."""
        if not cls.is_super_admin(initiator_id):
            raise PermissionError("ТОЛЬКО Главный Админ может разжаловать администраторов!")

        if target_id == settings.ADMIN_ID:
            raise ValueError("Нельзя разжаловать Главного Админа.")

        target_user = await UserService.get_by_id(session, target_id)
        if not target_user:
            return False

        target_user.role = UserRole.USER
        await session.commit()
        await UserService.log_action(session, initiator_id, "ADMIN_DEMOTED", {"target_id": target_id})
        return True

    @classmethod
    async def grant_permission(
        cls, session: AsyncSession, initiator_id: int, target_id: int, perm_code: str
    ) -> bool:
        """
        Выдача индивидуального права пользователю.
        ПРЕДОХРАНИТЕЛЬ: Права с флагом is_system=True НЕЛЬЗЯ выдать никому!
        """
        # Ищем само право
        stmt = select(Permission).where(Permission.code == perm_code)
        result = await session.execute(stmt)
        perm = result.scalar_one_or_none()

        if not perm:
            raise ValueError(f"Право с кодом '{perm_code}' не существует!")

        # ПРОВЕРКА ЗАЩИТЫ
        if perm.is_system:
            raise PermissionError(f"Право '{perm_code}' является системным. Его нельзя выдать через ACL!")

        # Проверяем, не выдано ли уже
        check_stmt = select(UserPermission).where(
            UserPermission.user_id == target_id,
            UserPermission.permission_id == perm.id
        )
        existing = await session.execute(check_stmt)
        if existing.scalar_one_or_none():
            return False  # Уже выдано

        new_perm = UserPermission(
            user_id=target_id,
            permission_id=perm.id,
            granted_by=initiator_id
        )
        session.add(new_perm)
        await session.commit()

        await UserService.log_action(
            session, initiator_id, "PERMISSION_GRANTED",
            {"target_id": target_id, "permission": perm_code}
        )
        return True

    @classmethod
    async def revoke_permission(cls, session: AsyncSession, initiator_id: int, target_id: int, perm_code: str):
        """Отзыв индивидуального права."""
        stmt = (
            delete(UserPermission)
            .where(
                UserPermission.user_id == target_id,
                UserPermission.permission_id == select(Permission.id).where(Permission.code == perm_code).scalar_subquery()
            )
        )
        await session.execute(stmt)
        await session.commit()

        await UserService.log_action(
            session, initiator_id, "PERMISSION_REVOKED",
            {"target_id": target_id, "permission": perm_code}
        )

    @classmethod
    async def check_access(cls, session: AsyncSession, user_id: int, perm_code: str) -> bool:
        """
        Главная функция проверки доступа:
        1. Если SuperAdmin -> разрешено всё.
        2. Если Admin -> разрешено всё, кроме системных прав.
        3. Если User -> строго проверка по таблице user_permissions.
        """
        user = await UserService.get_by_id(session, user_id)
        if not user or user.is_banned:
            return False

        # 1. Super Admin константа
        if cls.is_super_admin(user_id):
            return True

        # Проверяем само запрашиваемое право
        perm_stmt = select(Permission).where(Permission.code == perm_code)
        perm = (await session.execute(perm_stmt)).scalar_one_or_none()

        # Если право системное, а юзер не SuperAdmin — отказ
        if perm and perm.is_system:
            return False

        # 2. Роль ADMIN имеет доступ ко всем не-системным командам
        if user.role == UserRole.ADMIN:
            return True

        # 3. Для роли USER — проверяем персональную выдачу
        if not perm:
            return False

        user_perm_stmt = select(UserPermission).where(
            UserPermission.user_id == user_id,
            UserPermission.permission_id == perm.id
        )
        has_perm = (await session.execute(user_perm_stmt)).scalar_one_or_none()
        return has_perm is not None