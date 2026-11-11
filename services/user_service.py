from datetime import datetime, timezone
from typing import List, Optional, Any, Dict
from sqlalchemy import select, or_, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.user import User, UserRole, UserExtraDataHistory
from database.models.audit import ActionLog
from database.models.base import utc_now
from core.config import settings


class UserService:
    """
    Назначение:
        Сервисный слой для управления пользователями, профилями,
        блокировками и аудитом действий.
    """

    @staticmethod
    async def log_action(
            session: AsyncSession,
            user_id: int,
            action: str,
            details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Назначение: Запись действия пользователя или администратора в таблицу аудита (ActionLog).
        Входные параметры:
            session (AsyncSession): Асинхронная сессия SQLAlchemy.
            user_id (int): Telegram ID инициатора действия.
            action (str): Текстовый код действия (например, 'USER_REGISTERED', 'USER_BANNED').
            details (dict, optional): Словарь с дополнительными метаданными.
        Возвращаемое значение: None.
        """
        log_entry = ActionLog(user_id=user_id, action=action, details=details)
        session.add(log_entry)
        await session.commit()

    @staticmethod
    async def get_by_id(
            session: AsyncSession,
            telegram_id: int
    ) -> Optional[User]:
        """
        Назначение: Получение объекта пользователя по его первичному ключу (Telegram ID).
        Входные параметры:
            session (AsyncSession): Асинхронная сессия SQLAlchemy.
            telegram_id (int): Telegram ID пользователя.
        Возвращаемое значение:
            Optional[User]: Объект модели User или None, если пользователь не найден.
        """
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @classmethod
    async def register_user(
            cls,
            session: AsyncSession,
            telegram_id: int,
            username: Optional[str],
            first_name: str,
            last_name: str,
            address: str,
            phone: Optional[str] = None,
            language_code: str = settings.DEFAULT_LANGUAGE,
            timezone: str = settings.DEFAULT_TIMEZONE,
            latitude: Optional[float] = None,
            longitude: Optional[float] = None,
            extra_data: Optional[dict] = None
    ) -> User:
        """
        Назначение: Регистрация нового пользователя с геоданными, языком и часовым поясом.
        Входные параметры:
            session (AsyncSession): Сессия SQLAlchemy.
            telegram_id (int): Telegram ID.
            username (str, optional): Юзернейм без '@'.
            first_name (str): Имя.
            last_name (str): Фамилия.
            address (str): Адрес.
            phone (str, optional): Номер телефона.
            language_code (str): Язык.
            timezone (str): IANA часовой пояс.
            latitude (float, optional): Широта.
            longitude (float, optional): Долгота.
        Возвращаемое значение: User.
        """
        role = UserRole.SUPER_ADMIN if telegram_id == settings.ADMIN_ID else UserRole.USER

        user = User(
            telegram_id=telegram_id,
            username=username.replace("@", "") if username else None,
            first_name=first_name,
            last_name=last_name,
            address=address,
            phone=phone,
            language_code=language_code,
            timezone=timezone,
            latitude=latitude,
            longitude=longitude,
            extra_data=extra_data or {},
            role=role,
            is_banned=False
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        await cls.log_action(
            session=session,
            user_id=telegram_id,
            action="USER_REGISTERED",
            details={"role": role.value, "timezone": timezone, "lang": language_code}
        )
        return user

    @staticmethod
    async def get_latest_users(
            session: AsyncSession,
            limit: int = 1
    ) -> List[User]:
        """
        Назначение: Получение списка последних зарегистрированных пользователей.
        Входные параметры:
            session (AsyncSession): Асинхронная сессия SQLAlchemy.
            limit (int): Количество пользователей для выборки (по умолчанию 1).
        Возвращаемое значение:
            List[User]: Список объектов User, отсортированных от новых к старым.
        """
        stmt = (
            select(User)
            .order_by(User.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @classmethod
    async def update_profile(
            cls,
            session: AsyncSession,
            telegram_id: int,
            **fields: Any
    ) -> Optional[User]:
        """
        Назначение: Динамическое обновление переданных полей профиля пользователя.
        Входные параметры:
            session (AsyncSession): Асинхронная сессия SQLAlchemy.
            telegram_id (int): Telegram ID пользователя для обновления.
            **fields: Произвольные именованные аргументы, соответствующие колонкам таблицы User.
        Возвращаемое значение:
            Optional[User]: Обновленный объект User или None, если пользователь не найден.
        """
        stmt = (
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(**fields, updated_at=datetime.now(timezone.utc))
            .returning(User)
        )
        result = await session.execute(stmt)
        await session.commit()
        updated_user = result.scalar_one_or_none()

        if updated_user:
            await cls.log_action(
                session=session,
                user_id=telegram_id,
                action="PROFILE_UPDATED",
                details={"updated_fields": list(fields.keys())}
            )
        return updated_user

    @staticmethod
    async def search_users(
            session: AsyncSession,
            query: str,
            limit: int = 10
    ) -> List[User]:
        """
        Назначение:
            Умный поиск пользователей с фильтрацией пробелов и спецсимволов.
            Поддерживает поиск по точному Telegram ID и регистронезависимый поиск по имени/фамилии/нику.
        Входные параметры:
            session (AsyncSession): Асинхронная сессия SQLAlchemy.
            query (str): Поисковая строка от пользователя.
            limit (int): Максимальное количество записей в ответе (по умолчанию 10).
        Возвращаемое значение:
            List[User]: Список найденных объектов пользователей.
        """
        clean_query = query.strip().lstrip("@").strip("[](){}<>\"'")

        if not clean_query:
            return []

        # Поиск по числовому Telegram ID
        if clean_query.isdigit():
            stmt = select(User).where(User.telegram_id == int(clean_query))
            result = await session.execute(stmt)
            return list(result.scalars().all())

        # Оптимизированный регистронезависимый поиск по текстовым полям
        search_pattern = f"%{clean_query.lower()}%"
        stmt = (
            select(User)
            .where(
                or_(
                    func.lower(User.username).like(search_pattern),
                    func.lower(User.first_name).like(search_pattern),
                    func.lower(User.last_name).like(search_pattern)
                )
            )
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @classmethod
    async def set_ban_status(
            cls,
            session: AsyncSession,
            admin_id: int,
            target_id: int,
            is_banned: bool
    ) -> None:
        """
        Назначение: Установка статуса блокировки пользователя с записью в ActionLog.
        Входные параметры:
            session (AsyncSession): Асинхронная сессия SQLAlchemy.
            admin_id (int): Telegram ID администратора, выполняющего операцию.
            target_id (int): Telegram ID целевого пользователя.
            is_banned (bool): True - заблокировать, False - снять блокировку.
        Возвращаемое значение: None.
        """
        stmt = (
            update(User)
            .where(User.telegram_id == target_id)
            .values(is_banned=is_banned, updated_at=datetime.now(timezone.utc))
        )
        await session.execute(stmt)
        await session.commit()

        action = "USER_BANNED" if is_banned else "USER_UNBANNED"
        await cls.log_action(
            session=session,
            user_id=admin_id,
            action=action,
            details={"target_id": target_id}
        )

    # --- МЕТОДЫ УПРАВЛЕНИЯ РАСШИРЯЕМЫМ ПРОФИЛЕМ (EXTRA_DATA) И ИСТОРИЕЙ ---

    @classmethod
    async def get_extra_data(cls, session: AsyncSession, user_id: int) -> dict:
        """
        Назначение: Получение текущего словаря extra_data пользователя.
        """
        user = await cls.get_by_id(session, user_id)
        if not user or not user.extra_data:
            return {}
        return dict(user.extra_data)

    @classmethod
    async def update_extra_data(
        cls,
        session: AsyncSession,
        user_id: int,
        new_data: dict,
        merge: bool = True,
        source: Optional[str] = None,
        reason: Optional[str] = None
    ) -> Optional[User]:
        """
        Назначение:
            Обновление расширенных данных пользователя с обязательной фиксацией истории:
            1. Создается исторический снимок предыдущего состояния с таймстемпами
               (когда применялось и когда снято).
            2. Применяется новое состояние (merge или полное замещение).
            3. Записывается аудит в ActionLog.
        Входные параметры:
            session (AsyncSession): Сессия SQLAlchemy.
            user_id (int): Telegram ID пользователя.
            new_data (dict): Новые данные для записи.
            merge (bool): True - объединить со старыми ключами, False - перезаписать целиком.
            source (str, optional): Источник изменений ('shop', 'real_estate', 'admin' и т.д.).
            reason (str, optional): Причина изменений или описание операции.
        Возвращаемое значение:
            User: Обновленный объект пользователя или None.
        """
        user = await cls.get_by_id(session, user_id)
        if not user:
            return None

        # Фиксируем временную метку перехода
        now = utc_now()
        prev_applied_at = user.updated_at or user.created_at or now
        prev_snapshot = dict(user.extra_data or {})

        # Сохраняем предыдущее состояние в архивную историю
        history_entry = UserExtraDataHistory(
            user_id=user.telegram_id,
            applied_at=prev_applied_at,
            archived_at=now,
            snapshot=prev_snapshot,
            source=source,
            reason=reason
        )
        session.add(history_entry)

        # Вычисляем новое актуальное состояние
        if merge:
            updated_data = dict(prev_snapshot)
            updated_data.update(new_data)
        else:
            updated_data = dict(new_data)

        user.extra_data = updated_data
        user.updated_at = now
        await session.commit()
        await session.refresh(user)

        await cls.log_action(
            session=session,
            user_id=user_id,
            action="EXTRA_DATA_UPDATED",
            details={
                "source": source,
                "reason": reason,
                "keys_updated": list(new_data.keys()),
                "history_id": history_entry.id
            }
        )
        return user

    @classmethod
    async def get_extra_data_history(
        cls,
        session: AsyncSession,
        user_id: int,
        limit: int = 50
    ) -> List[UserExtraDataHistory]:
        """
        Назначение: Получение хронологической истории снимков extra_data пользователя.
        """
        stmt = (
            select(UserExtraDataHistory)
            .where(UserExtraDataHistory.user_id == user_id)
            .order_by(UserExtraDataHistory.archived_at.desc(), UserExtraDataHistory.id.desc())
            .limit(limit)
        )
        return list((await session.execute(stmt)).scalars().all())

    @classmethod
    async def rollback_extra_data(
        cls,
        session: AsyncSession,
        user_id: int,
        history_id: int,
        source: Optional[str] = "rollback"
    ) -> Optional[User]:
        """
        Назначение: Откат extra_data пользователя к указанному историческому снимку по ID.
        """
        stmt = select(UserExtraDataHistory).where(
            UserExtraDataHistory.id == history_id,
            UserExtraDataHistory.user_id == user_id
        )
        history_record = (await session.execute(stmt)).scalar_one_or_none()
        if not history_record:
            return None

        return await cls.update_extra_data(
            session=session,
            user_id=user_id,
            new_data=history_record.snapshot,
            merge=False,
            source=source,
            reason=f"Откат к состоянию от {history_record.applied_at.strftime('%Y-%m-%d %H:%M:%S')}"
        )
