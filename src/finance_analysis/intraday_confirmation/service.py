"""Frozen candidates in Redis; providers are only called by the task evaluation path."""

from datetime import timedelta
from time import monotonic
from zoneinfo import ZoneInfo
from finance_analysis.core.time import utc_now
from . import config as c
from .cache import ConfirmationCache
from .session import resolve_session
from .engine import metrics, decision, stabilize
from .trend import temporary_trend
from .market_data import collect_data


class ConfirmationService:
    def __init__(self, cache=None, repository=None, market_data=None):
        self.cache = cache if cache is not None else ConfirmationCache()
        self.repository = repository
        self.market_data = market_data

    def read(self, market, state=None, candidate_source=None, now=None):
        now = now or utc_now()
        tz = ZoneInfo("Asia/Shanghai" if market == "CN" else "America/New_York")
        day = now.astimezone(tz).date()
        payload = self.cache.load(market, day) or dict(
            market=market,
            trade_date=day.isoformat(),
            candidate_trade_date=None,
            frozen_at=None,
            generated_at=None,
            status="not_frozen",
            items=[],
            warnings=["当天尚无开盘前冻结候选；盘中不会补建"],
        )
        # Candidate baselines remain private to the task; API returns compact evidence.
        rows = [
            {k: v for k, v in r.items() if k not in {"official_trend", "pending_since", "last_observation"}}
            for r in payload["items"]
        ]
        summary = {s: sum(r["state"] == s for r in rows) for s in ("WAIT", "CONFIRMED", "FAILED")}
        summary["total"] = len(rows)
        rows = [
            r
            for r in rows
            if (state is None or r["state"] == state)
            and (candidate_source is None or r["candidate_source"] == candidate_source)
        ]
        rows.sort(
            key=lambda r: (
                {"CONFIRMED": 0, "WAIT": 1, "FAILED": 2}[r["state"]],
                r.get("confirmation_score") is None,
                -(r.get("confirmation_score") or 0),
                {"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get(r.get("chase_risk"), 3),
                r["code"],
            )
        )
        return {
            **payload,
            "items": rows,
            "summary": summary,
            "rules_note": "V1 启发式规则，未经回测验证；确认不代表适合追入，不自动交易。",
        }

    def run(self, market, now=None):
        now = now or utc_now()
        session = resolve_session(market, now)
        if session is None:
            return dict(status="skipped", reason="非交易日")
        if not (session.opened - timedelta(minutes=c.FREEZE_LEAD_MINUTES) <= now <= session.closed):
            return dict(status="skipped", reason="不在冻结或交易窗口")
        with self.cache.lock(session):
            payload = self.cache.load(market, session.day)
            if now < session.opened:
                if payload is not None:
                    return dict(status="already_frozen", count=len(payload["items"]))
                if self.repository is None:
                    from finance_analysis.database.repositories.intraday_confirmation import CandidateRepository

                    self.repository = CandidateRepository()
                rows = self.repository.candidates(market, session.previous_date, now)
                for row in rows:
                    row.update(
                        state="WAIT",
                        confirmation_score=None,
                        available_score_weight=0,
                        chase_risk="UNKNOWN",
                        metrics={},
                        trend={},
                        reasons=[dict(code="preopen", text="昨日正式候选已冻结，等待开盘确认")],
                    )
                self.cache.save(
                    session,
                    dict(
                        market=market,
                        trade_date=session.day,
                        candidate_trade_date=session.previous_date,
                        frozen_at=now,
                        generated_at=now,
                        status="frozen",
                        items=rows,
                        warnings=[],
                    ),
                )
                return dict(status="frozen", count=len(rows))
            if payload is None:
                return dict(status="skipped", reason="缺少开盘前冻结池，禁止盘中重建")
            if not session.active(now):
                return dict(status="skipped", reason="午休")
            if not payload["items"]:
                return dict(status="empty", count=0)
            return self._evaluate(session, payload, now)

    def _evaluate(self, session, payload, now):
        started = monotonic()
        if self.market_data is None:
            from finance_analysis.integrations.market_data import MarketDataService

            self.market_data = MarketDataService()
        market = session.market
        benchmark = c.BENCHMARKS[market]
        codes = list(dict.fromkeys([r["code"] for r in payload["items"]] + [benchmark]))
        quotes, minute, history = collect_data(self.market_data, codes, session, now)
        # Quotes may advance while network requests run; use completion time, not task start.
        now += timedelta(seconds=monotonic() - started)
        rows = []
        for candidate in payload["items"]:
            code = candidate["code"]
            quote, bench = quotes.get(code), quotes.get(benchmark)
            bars = history.get(code, [])
            m = metrics(quote, minute.get(code, []), bench, bars, session, now)
            trend = temporary_trend(
                candidate.get("official_trend"),
                bars,
                quote if m["quote_usable"] else None,
                history.get(benchmark, []),
                bench if m["relative_to_market"] is not None else None,
                session.day,
                session.previous_date,
            )
            result = decision(m, trend)
            result = stabilize(result, candidate, m["bar_time"] if m["data_fresh"] else None, now)
            rows.append({**candidate, **result, "metrics": m, "trend": trend, "generated_at": now})
        payload.update(items=rows, generated_at=now, status="evaluated")
        self.cache.save(session, payload)
        return dict(status="evaluated", count=len(rows), market=market, trade_date=session.day.isoformat())
