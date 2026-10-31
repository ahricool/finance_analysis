"""One daily review per user/market, no network calls inside business transactions."""

import logging

from finance_analysis.database.repositories.holdings_review import HoldingsReviewRepository
from finance_analysis.tasks.advisory_lock import PostgreSQLAdvisoryLock
from finance_analysis.tasks.lifecycle import TaskSkipped
from finance_analysis.market_review.trading_calendar import get_market_now

from .calendar import review_window
from .context import ReviewContextBuilder
from .decision import ReviewDecisionMaker
from .notification import push_review
from .report import render_markdown

logger = logging.getLogger(__name__)


class HoldingsReviewService:
    def __init__(self, *, repository=None, builder=None, maker=None, lock_factory=None, push=None):
        self.repo = repository or HoldingsReviewRepository()
        self.builder = builder or ReviewContextBuilder()
        self.maker = maker or ReviewDecisionMaker()
        self.lock_factory = lock_factory or (
            lambda uid, market: PostgreSQLAdvisoryLock(
                uid,
                db_manager=self.repo.db,
                namespace=20_261_101 if market == "CN" else 20_261_102,
            )
        )
        self.push = push or push_review

    def run(self, market, *, uid=None, now=None):
        window = review_window(market, now)
        if window is None:
            raise TaskSkipped("非交易日或不在收盘前50分钟复盘窗口")
        local, _, close = window
        users = [uid] if uid is not None else self.repo.user_ids(market)
        counts = {"completed": 0, "degraded": 0, "failed": 0, "already_completed": 0, "locked": 0}
        for owner in users:
            lock = self.lock_factory(owner, market)
            with lock:
                if not lock.acquired:
                    counts["locked"] += 1
                    continue
                existing = self.repo.get(owner, market, local.date())
                if existing and existing["status"] == "completed":
                    counts["already_completed"] += 1
                    continue
                if not self.repo.start(owner, market, local.date(), {}):
                    counts["already_completed"] += 1
                    continue
                try:
                    captured = get_market_now(market.lower(), now)
                    context = self.builder.build(owner, market, captured, close)
                    self.repo.save_input(owner, market, local.date(), context)
                    decision, evidence, metadata = self.maker.decide(owner, context)
                    markdown = render_markdown(context, decision, evidence)
                    notification_id = self.repo.complete(
                        owner,
                        market,
                        local.date(),
                        decision,
                        markdown,
                        evidence,
                        **metadata,
                    )
                except Exception as exc:
                    logger.exception("Holdings review failed market=%s", market)
                    self.repo.fail(owner, market, local.date(), f"复盘生成失败（{type(exc).__name__}）")
                    counts["failed"] += 1
                    continue
                counts["completed"] += 1
                counts["degraded"] += int(decision.get("degraded", False))
                if notification_id:
                    try:
                        self.push(owner, notification_id, market, local.date(), markdown)
                    except Exception:
                        logger.exception("Holdings review push failed after commit")
        return {"market": market, "trade_date": local.date().isoformat(), "user_count": len(users), **counts}
