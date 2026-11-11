from datetime import datetime
from sqlalchemy import Integer, BigInteger, String, DateTime, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column
from database.models.base import Base, utc_now

class ActionLog(Base):
    __tablename__ = "action_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (
        Index("ix_action_logs_user_date", "user_id", "created_at"),
    )