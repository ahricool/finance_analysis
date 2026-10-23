"""Read-only views and one bounded daily runner for every registered strategy."""

import logging
from datetime import datetime, timedelta, timezone
from time import monotonic

from finance_analysis.core.secret_redact import redact_secrets
from finance_analysis.market_review.trading_calendar import (
    get_completed_trading_days,
    get_effective_trading_date,
    get_market_now,
    get_market_session_bounds,
    get_trading_days_between,
)
from finance_analysis.stock_strategies.engine import advance
from finance_analysis.stock_strategies.features import DataNotReady
from finance_analysis.stock_strategies.registry import STRATEGIES, definition, parameters

logger = logging.getLogger(__name__)
MAX_CATCHUP_DAYS = 5
RUN_BUDGET_SECONDS = 180


class StockStrategyService:
    def __init__(self, repository=None, loader=None, definitions=STRATEGIES, lock_factory=None):
        if repository is None:
            from finance_analysis.database.repositories.stock_strategies import StockStrategyRepository

            repository = StockStrategyRepository()
        self.repo, self.loader, self.definitions = repository, loader, definitions
        self.lock_factory = lock_factory

    def overview(self, market):
        expected = get_effective_trading_date(market.lower())
        result = []
        for spec in self.definitions:
            if market not in spec.markets:
                continue
            latest, attempt, state, _ = self.repo.latest(spec, market)
            result.append(
                dict(
                    strategy=parameters(spec, market).describe(market),
                    latest=latest,
                    last_run=attempt,
                    start_date=state["start_date"] if state else None,
                    status=(
                        "catching_up"
                        if attempt and attempt["status"] == "success" and latest and latest["trade_date"] < expected
                        else attempt["status"] if attempt else "not_started"
                    ),
                )
            )
        return dict(market=market, expected_date=expected, items=result)

    def detail(self, key, market, before=None, limit=100):
        spec = definition(key, market)
        if spec is None:
            return None
        latest, attempt, state, universe = self.repo.latest(spec, market, include_universe=True)
        history = self.repo.history(spec, market, before=before, limit=limit)
        return dict(
            market=market,
            expected_date=get_effective_trading_date(market.lower()),
            strategy=parameters(spec, market).describe(market),
            latest=latest,
            last_run=attempt,
            start_date=state["start_date"] if state else None,
            universe=universe,
            curve=self.repo.curve(spec, market),
            days=history,
            next_before=history[-1]["trade_date"] if len(history) == limit else None,
        )

    def _lock(self, market):
        if self.lock_factory:
            return self.lock_factory(market)
        from finance_analysis.tasks.advisory_lock import PostgreSQLAdvisoryLock, TaskAdvisoryLockId

        return PostgreSQLAdvisoryLock(
            TaskAdvisoryLockId.STOCK_STRATEGIES_CN if market == "CN" else TaskAdvisoryLockId.STOCK_STRATEGIES_US,
            db_manager=self.repo.db,
        )

    def run(self, market=None, strategy_key=None, now=None):
        now = now or datetime.now(timezone.utc)
        markets = (market,) if market else ("CN", "US")
        if market not in (None, "CN", "US"):
            raise ValueError("market must be CN or US")
        if strategy_key and not any(
            s.key == strategy_key and any(m in s.markets for m in markets) for s in self.definitions
        ):
            raise ValueError("未知策略或策略不支持该市场")
        if self.loader is None:
            from finance_analysis.stock_strategies.inputs import InputLoader

            self.loader = InputLoader(db_manager=self.repo.db)
        results = []
        deadline = monotonic() + RUN_BUDGET_SECONDS
        for target in markets:
            local = get_market_now(target.lower(), now)
            # Before today's settlement window, recover only earlier closed sessions.
            # Manual runs must not be blocked after delayed inputs become available.
            hour = 19 if target == "CN" else 22
            if local.hour < hour:
                cutoff = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(microseconds=1)
                day = get_completed_trading_days(target.lower(), 1, cutoff)[-1]
            else:
                day = get_effective_trading_date(target.lower(), current_time=now)
            with self._lock(target) as lock:
                if not lock.acquired:
                    results.append(dict(market=target, status="busy"))
                    continue
                results.extend(self._market(target, day, strategy_key, now, deadline))
        failed = sum(r["status"] == "failed" for r in results)
        waiting = sum(r["status"] == "waiting" for r in results)
        success = sum(r["status"] == "success" for r in results)
        return dict(
            status="partial" if failed or waiting else "success",
            results=results,
            failed=failed,
            waiting=waiting,
            success=success,
        )

    def _market(self, market, end, key, now, deadline):
        specs = [parameters(s, market) for s in self.definitions if market in s.markets and (not key or s.key == key)]
        # The anchor persists before input checks, so late-ready strategies share the same starting session.
        try:
            launch, universe = self.repo.launch(end, market, lambda: self.loader.freeze(market))
        except DataNotReady as exc:
            for spec in specs:
                self.repo.attempt(spec, market, end, "waiting", str(exc))
            return [dict(market=market, status="waiting", reason=str(exc))]
        days = get_trading_days_between(market.lower(), launch, end)
        if not days:
            return []
        for spec in specs:
            self.repo.initialize(spec, market, days[0])
        progress, results = {}, []
        for spec in specs:
            row = self.repo.state(spec, market)
            remaining = [d for d in days if row["last_date"] is None or d > row["last_date"]]
            progress[spec.key] = dict(row=row, days=remaining[:MAX_CATCHUP_DAYS], failed=False)
        for day in sorted({d for p in progress.values() for d in p["days"]}):
            active = [s for s in specs if day in progress[s.key]["days"] and not progress[s.key]["failed"]]
            if not active:
                continue
            if monotonic() >= deadline:
                for spec in active:
                    self.repo.attempt(spec, market, day, "waiting", "达到本轮计算预算，下轮从未完成交易日继续")
                    progress[spec.key]["failed"] = True
                    results.append(
                        dict(strategy_key=spec.key, market=market, trade_date=day.isoformat(), status="waiting")
                    )
                continue
            try:
                anchors = {
                    p["mark_date"]
                    for spec in active
                    for p in progress[spec.key]["row"]["payload"]["positions"].values()
                }
                anchors.update(progress[spec.key]["row"]["payload"].get("benchmark_mark_date") for spec in active)
                data = self.loader.load(market, day, universe, anchor_dates=anchors)
            except Exception as exc:
                logger.exception("Stock strategy shared input failed: market=%s day=%s", market, day)
                status = "waiting" if isinstance(exc, DataNotReady) else "failed"
                reason = redact_secrets(str(exc))[:2000]
                for spec in active:
                    self.repo.attempt(spec, market, day, status, reason)
                    progress[spec.key]["failed"] = True
                    results.append(
                        dict(
                            strategy_key=spec.key,
                            market=market,
                            trade_date=day.isoformat(),
                            status=status,
                            reason=reason,
                        )
                    )
                continue
            for spec in active:
                row = progress[spec.key]["row"]
                try:

                    def calculate(state):
                        updated, snapshot = advance(spec, state, data, row["start_date"])
                        opening, _ = get_market_session_bounds(market.lower(), data.next_day)
                        snapshot["payload"]["next_is_historical"] = now >= opening
                        snapshot["payload"]["computed_at"] = now.isoformat()
                        snapshot["payload"]["replayed"] = day < end
                        return updated, snapshot

                    snapshot = self.repo.settle(spec, market, day, row["last_date"], calculate)
                    if snapshot is not None:
                        progress[spec.key]["row"] = self.repo.state(spec, market)
                    results.append(
                        dict(strategy_key=spec.key, market=market, trade_date=day.isoformat(), status="success")
                    )
                except Exception as exc:
                    logger.exception("Stock strategy failed: key=%s market=%s day=%s", spec.key, market, day)
                    status = "waiting" if isinstance(exc, DataNotReady) else "failed"
                    reason = redact_secrets(str(exc))[:2000]
                    self.repo.attempt(spec, market, day, status, reason)
                    progress[spec.key]["failed"] = True
                    results.append(
                        dict(
                            strategy_key=spec.key,
                            market=market,
                            trade_date=day.isoformat(),
                            status=status,
                            reason=reason,
                        )
                    )
        return results
