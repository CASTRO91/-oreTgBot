import enum
from datetime import datetime
from sqlalchemy import BigInteger, String, Boolean, DateTime, Enum, Text, Float, JSON, Integer, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database.models.base import Base, utc_now
from core.config import settings


class UserRole(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"  # Назначенные админы
    USER = "USER"  # Обычные пользователи


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    first_name: Mapped[str] = mapped_column(String(128), index=True)
    last_name: Mapped[str] = mapped_column(String(128), index=True)
    address: Mapped[str] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Локализация, часовой пояс и координаты
    language_code: Mapped[str] = mapped_column(String(8), default=settings.DEFAULT_LANGUAGE, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default=settings.DEFAULT_TIMEZONE, nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.USER, nullable=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    # Расширяемый профиль для плагинов (магазины, недвижимость, фильтры, корзины, баллы)
    extra_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )

    # Связи
    permissions = relationship("UserPermission", back_populates="user", cascade="all, delete-orphan")
    group_memberships = relationship("UserGroupMembership", back_populates="user", cascade="all, delete-orphan")
    extra_data_history = relationship(
        "UserExtraDataHistory",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="desc(UserExtraDataHistory.id)"
    )


class UserExtraDataHistory(Base):
    """
    Назначение:
        Хранение хронологической истории изменений extra_data пользователя.
        Фиксирует:
        - user_id: ID пользователя
        - applied_at: момент вступления состояния в силу
        - archived_at: момент замены состояния новым и перемещения в архив
        - snapshot: снимок состояния extra_data на тот период
        - source: модуль/плагин (например, 'shop', 'real_estate', 'admin', 'system')
        - reason: причина или описание операции
    """
    __tablename__ = "user_extra_data_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False, index=True
    )
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    archived_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user = relationship("User", back_populates="extra_data_history")

    __table_args__ = (
        Index("ix_extra_data_history_user_archived", "user_id", "archived_at"),
    )
