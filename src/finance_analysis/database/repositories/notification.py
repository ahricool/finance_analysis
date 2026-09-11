"""Message persistence and mandatory current-user read scope."""

from sqlalchemy import func, or_, select

from finance_analysis.core.time import coerce_aware_utc
from finance_analysis.database.models.notification import Notification
from finance_analysis.database.session import DatabaseManager


class NotificationRepository:
    def __init__(self, db=None):
        self.db = db or DatabaseManager.get_instance()

    def create(self, *, uid, title, content, route_type, severity) -> int:
        def write(session):
            row = Notification(uid=uid, title=title, content=content, route_type=route_type, severity=severity)
            session.add(row)
            session.flush()
            return row.id

        return self.db._run_write_transaction("notification.create", write)

    @staticmethod
    def _scope(uid: int):
        if uid is None:
            raise ValueError("An authenticated uid is required")
        return or_(Notification.uid == uid, Notification.uid.is_(None))

    def list_messages(
        self,
        *,
        uid: int,
        page=1,
        page_size=20,
        keyword=None,
        route_type=None,
        severity=None,
        start_time=None,
        end_time=None,
    ):
        filters = [self._scope(uid)]
        if keyword:
            pattern = "%" + keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            filters.append(
                or_(Notification.title.ilike(pattern, escape="\\"), Notification.content.ilike(pattern, escape="\\"))
            )
        if route_type:
            filters.append(Notification.route_type == route_type)
        if severity:
            filters.append(Notification.severity == severity)
        if start_time:
            filters.append(Notification.created_at >= coerce_aware_utc(start_time))
        if end_time:
            filters.append(Notification.created_at <= coerce_aware_utc(end_time))
        with self.db.get_session() as session:
            total = session.scalar(select(func.count()).select_from(Notification).where(*filters))
            rows = (
                session.execute(
                    select(
                        Notification.id,
                        Notification.uid,
                        Notification.title,
                        func.substr(Notification.content, 1, 240).label("content_preview"),
                        Notification.route_type,
                        Notification.severity,
                        Notification.created_at,
                    )
                    .where(*filters)
                    .order_by(Notification.created_at.desc(), Notification.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
                .mappings()
                .all()
            )
            return {"items": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}

    def get_message(self, notification_id: int, *, uid: int):
        with self.db.get_session() as session:
            row = session.scalar(
                select(Notification).where(
                    Notification.id == notification_id,
                    self._scope(uid),
                )
            )
            if row is not None:
                session.expunge(row)
            return row
