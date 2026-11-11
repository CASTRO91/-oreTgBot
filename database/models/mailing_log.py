from datetime import datetime
from sqlalchemy import Integer, BigInteger, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from database.models.base import Base

class MailingDeliveryLog(Base):
    """
    Назначение: Фиксация факта доставки рассылки конкретному пользователю за конкретную дату.
    """
    __tablename__ = "mailing_delivery_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mailing_id: Mapped[int] = mapped_column(Integer, ForeignKey("scheduled_mailings.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False)
    delivered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("mailing_id", "user_id", "delivered_at", name="uq_mailing_user_delivery"),
        Index("ix_delivery_lookup", "mailing_id", "user_id"),
    )