from datetime import datetime
from sqlalchemy import Integer, BigInteger, String, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database.models.base import Base

class Group(Base):
    """
    Назначение: Модель пользовательской группы/сегмента для таргетированных рассылок.
    """
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    members = relationship("UserGroupMembership", back_populates="group", cascade="all, delete-orphan")


class UserGroupMembership(Base):
    """
    Назначение: Таблица связи 'Многие-ко-Многим' между пользователями и группами.
    """
    __tablename__ = "user_group_membership"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False)
    group_id: Mapped[int] = mapped_column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    added_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="group_memberships")
    group = relationship("Group", back_populates="members")

    __table_args__ = (
        UniqueConstraint("user_id", "group_id", name="uq_user_group"),
        Index("ix_user_group_lookup", "user_id", "group_id"),
    )