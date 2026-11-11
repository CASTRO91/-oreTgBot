import enum
from datetime import datetime
from sqlalchemy import BigInteger, String, Boolean, DateTime, Enum, Text,Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database.models.base import Base, utc_now
from core.config import settings


class UserRole(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"  #
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

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )

    # Связи
    permissions = relationship("UserPermission", back_populates="user", cascade="all, delete-orphan")
    group_memberships = relationship("UserGroupMembership", back_populates="user", cascade="all, delete-orphan")