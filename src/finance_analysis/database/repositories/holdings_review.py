"""User-scoped review reads and atomic review/message completion."""

from copy import deepcopy

from sqlalchemy import select

from finance_analysis.core.time import utc_now
from finance_analysis.database.models.holdings_review import HoldingsReview
from finance_analysis.database.models.notification import Notification
from finance_analysis.database.models.portfolio import PortfolioAccount
from finance_analysis.database.session import DatabaseManager


def view(row):
    if row is None:
        return None
    snapshot = deepcopy(row.input_snapshot or {})
    proof = row.search_evidence or {}
    return {
        "id": row.id,
        "market": row.market,
        "trade_date": row.trade_date.isoformat(),
        "status": row.status,
        "decision": deepcopy(row.decision),
        "markdown": row.markdown,
        "error": row.error,
        "started_at": row.started_at.isoformat(),
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "as_of": snapshot.get("as_of"),
        "session_close": snapshot.get("session_close"),
        "portfolio": snapshot.get("portfolio", {}),
        "data_quality": snapshot.get("data_quality", []),
        "research": snapshot.get("research", {}),
        "indices": snapshot.get("indices", []),
        "holdings": [
            {k: v for k, v in p.items() if k not in {"daily_bars", "minute_bars", "recent_trades"}}
            for p in snapshot.get("holdings", [])
        ],
        "search_evidence": {
            "status": proof.get("status", "unavailable"),
            "requested": proof.get("requested", True),
            "citations": deepcopy(proof.get("citations", []))[:8],
        },
        "model": row.model,
    }


class HoldingsReviewRepository:
    def __init__(self, db=None):
        self.db = db or DatabaseManager.get_instance()

    def user_ids(self, market):
        with self.db.get_session() as session:
            return list(
                session.scalars(
                    select(PortfolioAccount.uid)
                    .where(
                        PortfolioAccount.market == market,
                    )
                    .distinct()
                    .order_by(PortfolioAccount.uid)
                )
            )

    @staticmethod
    def _query(uid, market, day):
        return select(HoldingsReview).where(
            HoldingsReview.uid == uid,
            HoldingsReview.market == market,
            HoldingsReview.trade_date == day,
        )

    def get(self, uid, market, day):
        with self.db.get_session() as session:
            return view(session.scalar(self._query(uid, market, day)))

    def dates(self, uid, market):
        with self.db.get_session() as session:
            return [
                {"trade_date": day.isoformat(), "status": status}
                for day, status in session.execute(
                    select(HoldingsReview.trade_date, HoldingsReview.status)
                    .where(
                        HoldingsReview.uid == uid,
                        HoldingsReview.market == market,
                    )
                    .order_by(HoldingsReview.trade_date.desc())
                    .limit(3660)
                )
            ]

    def start(self, uid, market, day, snapshot):
        with self.db.session_scope() as session:
            row = session.scalar(self._query(uid, market, day).with_for_update())
            if row is not None and row.status == "completed":
                return False
            if row is None:
                row = HoldingsReview(uid=uid, market=market, trade_date=day)
                session.add(row)
            row.status, row.input_snapshot, row.error = "processing", snapshot, None
            row.started_at, row.completed_at = utc_now(), None
        return True

    def save_input(self, uid, market, day, snapshot):
        with self.db.session_scope() as session:
            row = session.scalar(self._query(uid, market, day).with_for_update())
            if row is not None and row.status != "completed":
                row.input_snapshot = snapshot

    def fail(self, uid, market, day, error):
        with self.db.session_scope() as session:
            row = session.scalar(self._query(uid, market, day).with_for_update())
            if row is not None and row.status != "completed":
                row.status, row.error, row.completed_at = "failed", error[:500], utc_now()

    def complete(self, uid, market, day, decision, markdown, evidence, *, model=None, backend=None):
        with self.db.session_scope() as session:
            row = session.scalar(self._query(uid, market, day).with_for_update())
            if row is None or row.status == "completed":
                return None
            message = Notification(
                uid=uid,
                title=f"持仓复盘 · {market} · {day}",
                content=markdown,
                route_type="report",
                severity="warning" if any(r["severity"] == "HIGH" for r in decision["risks"]) else "info",
            )
            session.add(message)
            session.flush()
            row.status, row.decision, row.markdown = "completed", decision, markdown
            row.search_evidence, row.notification_id = evidence, message.id
            row.completed_at, row.error, row.model, row.backend = utc_now(), None, model, backend
            return message.id
