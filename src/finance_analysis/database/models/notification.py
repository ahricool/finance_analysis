"""Messages produced by the system, independent of external delivery."""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base


class Notification(Base):
    __tablename__ = "notification"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(Integer, ForeignKey("users.id"), nullable=True)
    title = Column(String(300), nullable=False)
    content = Column(Text, nullable=False)
    route_type = Column(String(32), nullable=False)
    severity = Column(String(16), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        Index("ix_notification_created_at", "created_at"),
        Index("ix_notification_uid_created_at", "uid", "created_at"),
        Index("ix_notification_route_type_created_at", "route_type", "created_at"),
        Index("ix_notification_severity_created_at", "severity", "created_at"),
    )
