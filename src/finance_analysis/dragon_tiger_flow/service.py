"""Bounded close/backfill ingestion; network requests precede the publication transaction."""

from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.dragon_tiger_flow import DragonTigerFlowRepository
from finance_analysis.integrations.market_data.service import MarketDataService
from finance_analysis.integrations.market_data.providers.fuyao import FuyaoError
from .calendar import expected_date, sessions_through, validate_day
from .config import BOARDS, MAX_BACKFILL_DAYS


class DragonTigerReadinessError(RuntimeError):
    pass


class DragonTigerFlowService:
    def __init__(self, repository=None, market_data=None):
        self.repository = repository or DragonTigerFlowRepository()
        self.market_data = market_data or MarketDataService()

    def collect(self, day):
        validate_day(day)
        started = utc_now()
        sources, errors = {}, {}
        for board in BOARDS:
            try:
                sources[board] = self.market_data.get_dragon_tiger_board(day, board)
            except (FuyaoError, TimeoutError, ValueError) as exc:
                if board == "all":
                    raise DragonTigerReadinessError("龙虎榜核心数据未就绪；保留旧批次") from None
                errors[board] = type(exc).__name__
        try:
            return self.repository.publish(day, sources, errors, started)
        except ValueError:
            raise DragonTigerReadinessError("龙虎榜质量检查未通过；保留旧批次") from None

    def run(self, trade_date=None, backfill_days=None, missing_only=True):
        if trade_date is not None and backfill_days is not None:
            raise ValueError("trade_date 与 backfill_days 不能同时提供")
        day = trade_date or expected_date()
        validate_day(day)
        if backfill_days is None:
            result = self.collect(day)
            if result["status"] == "partial":
                raise DragonTigerReadinessError("辅助榜单未就绪；已发布有效核心，等待重试")
            return result
        if type(backfill_days) is not int or not 1 <= backfill_days <= MAX_BACKFILL_DAYS:
            raise ValueError("backfill_days 必须在1..31")
        outcomes = []
        for target in sessions_through(day, backfill_days):
            if missing_only and self.repository.has_complete(target):
                outcomes.append({"trade_date": target.isoformat(), "status": "existing"})
                continue
            try:
                outcomes.append(self.collect(target))
            except DragonTigerReadinessError:
                outcomes.append({"trade_date": target.isoformat(), "status": "failed"})
        return {
            "status": "partial" if any(r["status"] in ("partial", "failed") for r in outcomes) else "completed",
            "days": outcomes,
        }
