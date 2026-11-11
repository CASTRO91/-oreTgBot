from typing import List, Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from database.models.group import Group, UserGroupMembership
from database.models.user import User
from sqlalchemy import func

class GroupService:
    """
    Назначение: Управление пользовательскими группами (сегментами) для таргетированных рассылок.
    """

    @staticmethod
    async def create_group(
        session: AsyncSession,
        name: str,
        created_by: int,
        description: Optional[str] = None
    ) -> Group:
        """
        Назначение: Создание новой группы пользователей.
        Входные параметры:
            session (AsyncSession): Сессия БД.
            name (str): Название группы.
            created_by (int): Telegram ID администратора.
            description (str, optional): Описание группы.
        Возвращаемое значение:
            Group: Созданная группа.
        """
        group = Group(name=name, description=description, created_by=created_by)
        session.add(group)
        await session.commit()
        await session.refresh(group)
        return group

    @staticmethod
    async def get_all_groups(session: AsyncSession) -> List[Group]:
        """
        Назначение: Получение списка всех доступных групп.
        Входные параметры:
            session (AsyncSession): Сессия БД.
        Возвращаемое значение:
            List[Group]: Список групп.
        """
        stmt = select(Group).order_by(Group.name.asc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def add_user_to_group(
        session: AsyncSession,
        user_id: int,
        group_id: int,
        added_by: int
    ) -> bool:
        """
        Назначение: Добавление пользователя в группу.
        Входные параметры:
            session (AsyncSession): Сессия БД.
            user_id (int): Telegram ID пользователя.
            group_id (int): ID группы.
            added_by (int): Telegram ID админа.
        Возвращаемое значение:
            bool: True если добавлен, False если уже состоял.
        """
        check_stmt = select(UserGroupMembership).where(
            UserGroupMembership.user_id == user_id,
            UserGroupMembership.group_id == group_id
        )
        existing = (await session.execute(check_stmt)).scalar_one_or_none()
        if existing:
            return False

        membership = UserGroupMembership(
            user_id=user_id,
            group_id=group_id,
            added_by=added_by
        )
        session.add(membership)
        await session.commit()
        return True

    @staticmethod
    async def remove_user_from_group(
        session: AsyncSession,
        user_id: int,
        group_id: int
    ) -> None:
        """
        Назначение: Исключение пользователя из группы.
        Входные параметры:
            session (AsyncSession): Сессия БД.
            user_id (int): Telegram ID пользователя.
            group_id (int): ID группы.
        Возвращаемое значение: None.
        """
        stmt = delete(UserGroupMembership).where(
            UserGroupMembership.user_id == user_id,
            UserGroupMembership.group_id == group_id
        )
        await session.execute(stmt)
        await session.commit()

    @staticmethod
    async def get_user_groups(session: AsyncSession, user_id: int) -> List[Group]:
        """
        Назначение: Получение списка групп, в которых состоит пользователь.
        Входные параметры:
            session (AsyncSession): Сессия БД.
            user_id (int): Telegram ID пользователя.
        Возвращаемое значение:
            List[Group]: Список групп.
        """
        stmt = (
            select(Group)
            .join(UserGroupMembership, UserGroupMembership.group_id == Group.id)
            .where(UserGroupMembership.user_id == user_id)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_group_member_ids(session: AsyncSession, group_id: int) -> List[int]:
        """
        Назначение: Получение списка Telegram ID всех участников группы.
        Входные параметры:
            session (AsyncSession): Сессия БД.
            group_id (int): ID группы.
        Возвращаемое значение:
            List[int]: Список Telegram ID.
        """
        stmt = (
            select(UserGroupMembership.user_id)
            .where(UserGroupMembership.group_id == group_id)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_group_by_id(session: AsyncSession, group_id: int) -> Optional[Group]:
        """
        Назначение: Получение объекта группы по ID.
        """
        stmt = select(Group).where(Group.id == group_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def count_group_members(session: AsyncSession, group_id: int) -> int:
        """
        Назначение: Подсчет точного количества участников в группе.
        Входные параметры:
            session (AsyncSession): Сессия БД.
            group_id (int): ID группы.
        Возвращаемое значение:
            int: Число пользователей в группе.
        """
        stmt = select(func.count(UserGroupMembership.id)).where(UserGroupMembership.group_id == group_id)
        result = await session.execute(stmt)
        return result.scalar() or 0

    @staticmethod
    async def delete_group(session: AsyncSession, group_id: int) -> None:
        """
        Назначение: Каскадное удаление группы и всех связей с пользователями.
        """
        # Сначала чистим связку участников
        await session.execute(delete(UserGroupMembership).where(UserGroupMembership.group_id == group_id))
        # Удаляем саму группу
        await session.execute(delete(Group).where(Group.id == group_id))
        await session.commit()