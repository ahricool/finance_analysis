"""Avatar bytes live separately from frequently queried user profiles."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, LargeBinary, String

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base


class UserAvatar(Base):
    __tablename__ = "user_avatar"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    data = Column(LargeBinary, nullable=False)
    version = Column(String(32), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
