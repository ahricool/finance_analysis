"""Durable daily confirmation evidence; live providers are used only by evaluation tasks."""

from datetime import date, datetime, timedelta
from time import monotonic
from zoneinfo import ZoneInfo
from finance_analysis.core.time import utc_now
from . import config as c
from .returns import positive, with_returns
from .session import resolve_session
from .engine import metrics, decision, stabilize
from .trend import temporary_trend
from .market_data import collect_data


class ConfirmationService:
    def __init__(self, store=None, repository=None, market_data=None):
        self._store = store
        self.repository = repository
        self.market_data = market_data

    @property
    def store(self):
        if self._store is None:
            from finance_analysis.database.repositories.intraday_confirmation_store import ConfirmationStore

            self._store = ConfirmationStore()
        return self._store

    def dates(self, market):
        return {"dates": self.store.dates(market)}

    def read(self, market, state=None, candidate_source=None, now=None, trade_date=None):
        now = now or utc_now()
        tz = ZoneInfo("Asia/Shanghai" if market == "CN" else "America/New_York")
        day = trade_date or now.astimezone(tz).date()
        payload = self.store.load(market, day) or dict(
            market=market,
            trade_date=day.isoformat(),
            candidate_trade_date=None,
            frozen_at=None,
            generated_at=None,
            status="not_frozen",
            items=[],
            warnings=["所选日期尚无持久化冻结候选；盘中不会补建"],
        )
        # Candidate baselines remain private to the task; API returns compact evidence.
        evaluated = with_returns(self.store, market, day, payload["items"], now)
        rows = [
            {
                k: v
                for k, v in r.items()
                if k
                not in {
                    "official_trend",
                    "pending_since",
                    "last_observation",
                    "first_confirmation_open",
                    "return_evidence",
                }
            }
            for r in evaluated
        ]
        if payload.get("rule_version") == c.RULE_VERSION and day == now.astimezone(tz).date():
            try:
                session = resolve_session(market, now)
            except RuntimeError:
                session = None
            if session is None or session.active(now):
                for row in rows:
                    quote_time = row.get("metrics", {}).get("quote_time")
                    stamp = datetime.fromisoformat(quote_time) if isinstance(quote_time, str) else quote_time
                    if stamp is None or (now - stamp).total_seconds() > c.MAX_DATA_AGE_SECONDS:
                        row.update(
                            current_status="UNAVAILABLE",
                            data_status="UNAVAILABLE",
                            proposed_state=None,
                            confirmation_score=None,
                            available_score_weight=0,
                            chase_risk="UNKNOWN",
                            conditions={key: None for key in row.get("conditions", {})},
                            score_breakdown={key: None for key in row.get("score_breakdown", {})},
                            reasons=[
                                *row.get("reasons", []),
                                {"code": "read_stale", "text": "报价已过期，指标为最后观测值"},
                            ],
                        )
        summary = {s: sum(r["state"] == s for r in rows) for s in ("WAIT", "CONFIRMED", "FAILED")}
        summary["total"] = len(rows)
        summary["ever_confirmed"] = sum(bool(r.get("first_confirmed_at")) or r["state"] == "CONFIRMED" for r in rows)
        summary["active"] = sum(r.get("current_status") == "ACTIVE" for r in rows)
        summary["attention"] = sum(r.get("current_status") in {"WEAKENING", "FAILED", "UNAVAILABLE"} for r in rows)
        rows = [
            r
            for r in rows
            if (state is None or r["state"] == state)
            and (candidate_source is None or candidate_source in r.get("candidate_sources", [r["candidate_source"]]))
        ]
        rows.sort(
            key=lambda r: (
                {
                    "ACTIVE": 0,
                    "PENDING": 1,
                    "WAIT": 2,
                    "WEAKENING": 3,
                    "RECOVERED": 4,
                    "FAILED": 5,
                    "UNAVAILABLE": 6,
                    "PREOPEN": 7,
                }.get(r.get("current_status"), 8),
                {"CONFIRMED": 0, "WAIT": 1, "FAILED": 2}[r["state"]],
                r.get("confirmation_score") is None,
                -(r.get("confirmation_score") or 0),
                {"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get(r.get("chase_risk"), 3),
                r["code"],
            )
        )
        return {
            **{k: v for k, v in payload.items() if k != "_revision"},
            "items": rows,
            "summary": summary,
            "rule_version": payload.get("rule_version", "intraday_v1"),
            "rules_note": (
                "V2 · 1分钟线 / 每5分钟评估 · 价格60 / 相对强弱25 / 趋势10 / 量能5；不自动交易。"
                if payload.get("rule_version") == c.RULE_VERSION
                else "V1历史规则快照；不按新规则重算。"
            ),
        }

    def refresh_returns(self, market, day, now):
        # Task-only bounded catch-up, also on manual calls outside trading hours.
        for payload in self.store.pending_returns(market, day):
            trade_date = date.fromisoformat(payload["trade_date"])
            evaluated = with_returns(self.store, market, trade_date, payload["items"], now)
            self.store.save_returns(market, trade_date, evaluated, now)

    def run(self, market, now=None):
        now = now or utc_now()
        started = monotonic()
        tz = ZoneInfo("Asia/Shanghai" if market == "CN" else "America/New_York")
        day = now.astimezone(tz).date()
        with self.store.lock(market, day) as lock:
            if not lock.acquired:
                return dict(status="skipped", reason="本市场已有确认任务运行")
            self.refresh_returns(market, day, now)
            session = resolve_session(market, now)
            if session is None:
                return dict(status="skipped", reason="非交易日；已检查历史待到期收益")
            if not (session.opened - timedelta(minutes=c.FREEZE_LEAD_MINUTES) <= now <= session.closed):
                return dict(status="skipped", reason="不在冻结或交易窗口；已检查历史待到期收益")
            payload = self.store.load(market, session.day)
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
                        current_status="PREOPEN",
                        confirmation_score=None,
                        available_score_weight=0,
                        chase_risk="UNKNOWN",
                        metrics={},
                        trend={},
                        reasons=[dict(code="preopen", text="昨日正式候选已冻结，等待开盘确认")],
                    )
                self.store.save(
                    session,
                    dict(
                        market=market,
                        trade_date=session.day,
                        candidate_trade_date=session.previous_date,
                        frozen_at=now,
                        generated_at=now,
                        status="frozen",
                        rule_version=c.RULE_VERSION,
                        items=rows,
                        warnings=[],
                    ),
                )
                return dict(status="frozen", count=len(rows))
            if payload is None:
                return dict(status="skipped", reason="缺少开盘前冻结池，禁止盘中重建")
            if payload.get("rule_version") != c.RULE_VERSION:
                return dict(status="skipped", reason="当日池属于旧规则，保留原始证据；下一交易日启用V2")
            if not session.active(now):
                return dict(status="skipped", reason="午休")
            if not payload["items"]:
                return dict(status="empty", count=0)
            return self._evaluate(session, payload, now + timedelta(seconds=monotonic() - started))

    def _evaluate(self, session, payload, now):
        started = monotonic()
        if self.market_data is None:
            from finance_analysis.integrations.market_data import MarketDataService

            self.market_data = MarketDataService()
        market = session.market
        benchmark = c.BENCHMARKS[market]
        codes = list(dict.fromkeys([benchmark] + [r["code"] for r in payload["items"]]))
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
            result = stabilize(result, candidate, m["bar_time"] if result["data_status"] == "READY" else None, now)
            row = {**candidate, **result, "metrics": m, "trend": trend, "generated_at": now}
            if not candidate.get("first_confirmed_at") and result.get("first_confirmed_at"):
                # Freeze exactly the quote used in the first stabilized confirmation. An
                # unavailable anchor stays null; a later quote must never fill or reset it.
                row.update(
                    first_confirmed_price=m["price"] if m["data_fresh"] and positive(m["price"]) else None,
                    first_confirmed_quote_time=m["quote_time"] if m["data_fresh"] else None,
                    first_confirmation_open=m["open"] if m["data_fresh"] and positive(m["open"]) else None,
                )
            rows.append(row)
        payload.update(items=rows, generated_at=now, status="evaluated")
        self.store.save(session, payload)
        return dict(status="evaluated", count=len(rows), market=market, trade_date=session.day.isoformat())
