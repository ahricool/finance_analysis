"""Low-frequency research orchestration; all price reads go through MarketDataService."""

import json
import logging
import re
from datetime import timedelta

from pydantic import BaseModel
from finance_analysis.core.time import utc_now
from finance_analysis.market_review import trading_calendar as calendar
from finance_analysis.integrations.market_data.service import MarketDataService
from finance_analysis.integrations.options.service import attach_reference, quote_reference, limit_chain
from finance_analysis.integrations.options.providers import number
from finance_analysis.database.repositories.options_intelligence import OptionsRepository
from finance_analysis.llm import LLMClient, LLMRequest, parse_llm_json_response
from .config import get_options_config
from .engine import analyze
from .metrics import oi_change

logger = logging.getLogger(__name__)


def us_symbol(value):
    value = value.strip().upper()
    if value.endswith((".HK", ".SH", ".SZ")):
        raise ValueError("Options Intelligence requires a US equity symbol")
    if not value.endswith(".US"):
        value += ".US"
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,20}\.US", value):
        raise ValueError("Options Intelligence requires a US equity symbol")
    return value


def session_context(now):
    # This module fails closed if the real calendar cannot be loaded.
    if not calendar._XCALS_AVAILABLE:
        raise ValueError("US exchange calendar unavailable")
    cal = calendar.xcals.get_calendar("XNYS")
    local = calendar.get_market_now("us", now)
    if cal.is_session(local.date()):
        session = cal.date_to_session(local.date())
        opened, closed = (cal.session_open(session).to_pydatetime(), cal.session_close(session).to_pydatetime())
        if opened <= now <= closed:
            return session.date(), "intraday", opened, closed
        if now > closed:
            return session.date(), "daily", opened, closed
    session = cal.date_to_session(local.date(), direction="previous")
    if cal.is_session(local.date()):
        session = cal.previous_session(session)
    return (
        session.date(),
        "daily",
        cal.session_open(session).to_pydatetime(),
        cal.session_close(session).to_pydatetime(),
    )


class Explanation(BaseModel):
    why_it_matters: str
    possible_catalysts: list[str]
    protection_vs_direction: str
    alternative_explanations: list[str]
    data_limits: list[str]
    trading_risks: list[str]


class OptionsIntelligenceService:
    def __init__(self, repo=None, market_data=None, config=None, llm=None):
        self.repo = repo or OptionsRepository()
        self.market = market_data or MarketDataService()
        self.config = config or get_options_config()
        self.llm = llm

    def run(self, symbol, now=None, explain=False):
        realtime_run = now is None
        now = now or utc_now()
        symbol = us_symbol(symbol)
        day, phase, _, close = session_context(now)
        bucket = now.replace(minute=now.minute // 30 * 30, second=0, microsecond=0)
        mode = "daily" if phase == "daily" else calendar.get_market_now("us", bucket).strftime("%H:%M")
        chain = self.market.get_option_chain(symbol, now=now)
        if realtime_run:
            # Network completion is the first time a fetched chain can be known to this system.
            now = utc_now()
        if not chain.observations:
            raise ValueError("Options data unavailable: " + "; ".join(chain.errors))
        # A delayed/cached observation before today's close must never become a full-day baseline.
        if phase == "daily" and chain.observed_at < close:
            mode = calendar.get_market_now("us", chain.observed_at).strftime("%H:%M")
        # A quiet contract may retain yesterday's dailyBar. Keep its raw data, but exclude
        # that volume from today's metrics instead of rejecting the whole multi-source chain.
        for row in chain.observations:
            if row.volume is not None and row.volume_date != day:
                row.limitations.append("volume_session_unknown_or_stale")
        if chain.observations and not any(number(r.underlying_price) for r in chain.observations):
            quotes = self.market.get_realtime_quotes([symbol])
            if realtime_run:
                now = utc_now()
            reference = quote_reference(quotes.data.get(symbol), now)
            if reference:
                attach_reference(chain.observations, reference)
        # Also re-filter a chain whose stock reference was supplied after its initial fetch.
        limit_chain(chain, day, self.config)
        if not chain.observations:
            raise ValueError("Options data unavailable: " + "; ".join(chain.errors))
        history = self.repo.history(symbol, day, self.config.history_days, mode)
        oi_history = self.repo.history(symbol, day, 7, "daily")
        changes = {}
        cal = calendar.xcals.get_calendar("XNYS")
        for row in chain.observations:
            if row.oi_date is None or not cal.is_session(row.oi_date):
                continue
            prev_day = cal.previous_session(row.oi_date).date()
            previous = next(
                (
                    old
                    for h in reversed(oi_history)
                    for old in h["rows"]
                    if (old.symbol, old.data_source, old.feed_type, old.oi_date)
                    == (row.symbol, row.data_source, row.feed_type, prev_day)
                ),
                None,
            )
            change = oi_change(row, previous, prev_day, now)
            if change:
                changes[(row.symbol, row.data_source, row.feed_type)] = change
        last_closed = calendar.get_effective_trading_date("us", now)
        bars = self.market.get_daily_bars(
            [symbol], day - timedelta(days=60), last_closed, adjustment="forward", source_policy="db_only"
        )
        expected = calendar.get_completed_trading_days("us", 21, now)
        by_date = {b.trade_date: b.close for b in bars.data.get(symbol, [])}
        closes = [by_date.get(d) for d in expected]
        metrics = analyze(chain, day, now, history, mode, self.config, closes, changes)
        snapshot_id = self.repo.save(chain, metrics, bucket, mode)
        previous_analysis = self.repo.analysis_history(symbol) if self.config.auto_explain else []
        already_explained_today = any(item["trade_date"] == day for item in previous_analysis)
        if (
            explain
            or self.config.auto_explain
            and not already_explained_today
            and metrics["events"]
            and max(e["severity"] for e in metrics["events"]) >= self.config.llm_score
        ):
            try:
                self.explain(symbol)
            except Exception as exc:
                logger.warning("Options explanation failed symbol=%s category=%s", symbol, type(exc).__name__)
        return {
            "symbol": symbol,
            "snapshot_id": snapshot_id,
            "status": metrics["status"],
            "event_count": len(metrics["events"]),
            "evidence_grade": metrics["evidence_grade"],
        }

    def scan(self, symbols=None, now=None):
        supplied_now = now
        selected = symbols or self.repo.monitored_symbols(self.config.default_symbols)
        results = []
        # Sequential requests plus a process-wide task mutex keep request concurrency at one.
        for symbol in selected:
            try:
                results.append(self.run(symbol, supplied_now))
            except Exception as exc:
                logger.warning("Options scan failed symbol=%s category=%s", symbol, type(exc).__name__)
                results.append(
                    {
                        "symbol": symbol,
                        "status": "failed",
                        "reason": str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
                    }
                )
        if all(r["status"] == "failed" for r in results):
            raise ValueError("All option scans failed; " + "; ".join(r["reason"] for r in results[:3]))
        return {"results": results}

    def explain(self, symbol):
        symbol = us_symbol(symbol)
        latest = self.repo.latest(symbol)
        if latest is None:
            raise ValueError("Scan this symbol before requesting an explanation")
        if latest["llm_analysis"]:
            return latest["llm_analysis"]
        client = self.llm or LLMClient()
        if not client.is_available():
            raise ValueError("LLM is not configured")
        now = utc_now()
        payload = {k: v for k, v in latest.items() if k not in {"contracts", "llm_analysis"}}
        payload["anomalous_contracts"] = sorted(
            [r for r in latest["contracts"] if r["events"]], key=lambda r: r["volume_percentile"] or 0, reverse=True
        )[:12]
        payload["context"] = self.repo.context(symbol, now)
        bars = self.market.get_daily_bars(
            [symbol],
            now.date() - timedelta(days=30),
            calendar.get_effective_trading_date("us", now),
            adjustment="forward",
            source_policy="db_only",
        )
        payload["recent_prices"] = [
            {"date": b.trade_date.isoformat(), "close": b.close} for b in bars.data.get(symbol, [])
        ]
        prompt = json.dumps(payload, ensure_ascii=False, default=str)
        system = (
            "你解释已计算期权风险，不计算评分、不预测价格、不建议自动交易。仅使用提供的数据。"
            "不得编造大单、机构仓位、主动买卖、净开仓；Indicative不是NBBO。Put成交、OI和Skew不能证明净空头。"
            "权利金估算不是真实成交额；公开事件只有上下文提供证据时才可确认，否则写可能或未知。"
            "输出中文JSON，字段为why_it_matters(str),possible_catalysts(list[str]),protection_vs_direction(str),"
            "alternative_explanations(list[str]),data_limits(list[str]),trading_risks(list[str])。"
        )

        def validate(text):
            Explanation.model_validate(parse_llm_json_response(text))

        result = client.complete_text(
            LLMRequest(
                prompt=prompt, system_prompt=system, temperature=0.2, call_type="options_intelligence", web_search=False
            ),
            validator=validate,
        )
        explanation = Explanation.model_validate(parse_llm_json_response(result.text)).model_dump()
        self.repo.save_analysis(latest["snapshot_id"], explanation, result, system + "\n" + prompt)
        return explanation
