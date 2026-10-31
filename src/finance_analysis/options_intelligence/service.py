"""Low-frequency research orchestration; all price reads go through MarketDataService."""

import json
import logging
import os
import re
from time import monotonic
from datetime import datetime, timedelta

from billiard.exceptions import SoftTimeLimitExceeded
from pydantic import BaseModel
from finance_analysis.core.time import utc_now, coerce_aware_utc
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
PREVIEW_BUDGET_SECONDS = 20 * 60
PREVIEW_HARD_LIMIT_SECONDS = PREVIEW_BUDGET_SECONDS + 60
OFFICIAL_BUDGET_SECONDS = 45 * 60
OFFICIAL_HARD_LIMIT_SECONDS = OFFICIAL_BUDGET_SECONDS + 60


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


class DailySummary(BaseModel):
    market_overview: str
    notable_symbols: list[str]
    protection_vs_direction: str
    data_limits: list[str]
    risk_notes: list[str]


EVENT_TITLES = {
    "PUT_VOLUME_SPIKE": "Put 成交异常",
    "CALL_VOLUME_SPIKE": "Call 成交异常",
    "VOLUME_OI_ANOMALY": "成交量/OI 异常",
    "LARGE_PREMIUM_ACTIVITY": "大额权利金估算",
    "BEARISH_SKEW_SPIKE": "下行偏斜升高",
    "IV_SPIKE": "隐含波动率异常",
    "IV_TERM_INVERSION": "波动率期限倒挂",
    "LIQUIDITY_DRY_UP": "流动性不足",
    "WIDE_BID_ASK_SPREAD": "买卖点差过宽",
    "OI_BUILDUP_CONFIRMED": "次日 OI 增加确认",
}


class OptionsIntelligenceService:
    def __init__(self, repo=None, market_data=None, config=None, llm=None, preview_repository=None, notifier=None):
        self.repo = repo or OptionsRepository()
        self.market = market_data or MarketDataService()
        self.config = config or get_options_config()
        self.llm = llm
        self.preview_repository = preview_repository
        self.notifier = notifier
        self._notifier_provided = notifier is not None

    def _get_notifier(self):
        if os.getenv("PYTEST_CURRENT_TEST") and not self._notifier_provided:
            return None
        if self.notifier is None:
            from finance_analysis.notification.service import NotificationService  # pragma: allowlist secret

            self.notifier = NotificationService()
        return self.notifier

    def summarize_daily(self, trade_date, total_count=None, failed_count=0, unfinished_count=0):
        notifier = self._get_notifier()
        symbols = self.repo.monitored_symbols()
        rows = [row for row in self.repo.scan(symbols, trade_date) if row.get("status") in {"ready", "warming_up"}]
        if not rows:
            return None
        scored = []
        for row in rows:
            scores = row.get("scores") or {}
            bearish = (scores.get("bearish_demand") or {}).get("value")
            activity = (scores.get("unusual_activity") or {}).get("value")
            liquidity = (scores.get("liquidity_risk") or {}).get("value")
            events = row.get("events") or []
            top_event = max(events, key=lambda e: e.get("severity") or 0, default=None)
            scored.append(
                {
                    "symbol": row["symbol"],
                    "status": row.get("status"),
                    "evidence_grade": row.get("evidence_grade"),
                    "bearish_demand": bearish,
                    "unusual_activity": activity,
                    "liquidity_risk": liquidity,
                    "iv_30d": row.get("iv_30d"),
                    "iv_percentile": row.get("iv_percentile"),
                    "skew_30d": row.get("skew_30d"),
                    "put_call_volume_ratio": row.get("put_call_volume_ratio"),
                    "event_count": len(events),
                    "top_event": (
                        {
                            "event_type": top_event.get("event_type"),
                            "contract_symbol": top_event.get("contract_symbol"),
                            "severity": top_event.get("severity"),
                            "value": top_event.get("value"),
                        }
                        if top_event
                        else None
                    ),
                }
            )
        scored.sort(
            key=lambda r: (
                max(r["unusual_activity"] or 0, r["bearish_demand"] or 0),
                r["event_count"],
            ),
            reverse=True,
        )
        summary_data = None
        try:
            client = self.llm or LLMClient()
            if client.is_available():
                payload = {
                    "trade_date": trade_date.isoformat(),
                    "scanned_count": len(rows),
                    "total_planned": total_count or len(symbols),
                    "failed_count": failed_count,
                    "unfinished_count": unfinished_count,
                    "anomalous_stock_count": sum(1 for r in scored if r["event_count"] > 0),
                    "top_candidates": scored[:15],
                }
                prompt = json.dumps(payload, ensure_ascii=False, default=str)
                system = (
                    "你汇总美股盘后期权情报扫描结果，只做结构化研究总结，不预测股价、不输出买卖建议。"
                    "不得编造大单、机构流向、主动买卖方向或净空头；Indicative不是NBBO；Put成交与Skew升高只代表保护需求或成交活跃证据。"
                    "输出中文JSON，字段为market_overview(str),notable_symbols(list[str]),protection_vs_direction(str),"
                    "data_limits(list[str]),risk_notes(list[str])。"
                )

                def validate(text):
                    DailySummary.model_validate(parse_llm_json_response(text))

                llm_res = client.complete_text(
                    LLMRequest(
                        prompt=prompt,
                        system_prompt=system,
                        call_type="options_intelligence_daily_summary",
                        web_search=False,
                    ),
                    validator=validate,
                )
                summary_data = DailySummary.model_validate(parse_llm_json_response(llm_res.text)).model_dump()
        except Exception as exc:
            logger.warning("Options daily LLM summary failed category=%s", type(exc).__name__)

        lines = [
            f"# 【期权盘后日报】{trade_date.isoformat()}（有效快照 {len(rows)} 只）",
            "",
        ]
        if summary_data:
            lines.extend(
                [
                    summary_data["market_overview"],
                    "",
                    "## 重点标的观察",
                    *[f"- {item}" for item in summary_data["notable_symbols"]],
                    "",
                    "## 保护需求与方向边界",
                    summary_data["protection_vs_direction"],
                    "",
                    "## 数据限制与风险提示",
                    *[f"- {item}" for item in [*summary_data["data_limits"], *summary_data["risk_notes"]]],
                ]
            )
        else:
            lines.append("今日盘后正式扫描已完成（LLM 未启用或暂不可用，以下为确定性规则摘要）：")
            lines.append("")
            for item in scored[:10]:
                top = item["top_event"]
                top_text = (
                    f"{EVENT_TITLES.get(top['event_type'], top['event_type'])} ({top['contract_symbol'] or item['symbol']})"
                    if top
                    else "无触发规则事件"
                )
                lines.append(
                    f"- **{item['symbol']}**：看跌保护 `{item['bearish_demand'] if item['bearish_demand'] is not None else 'N/A'}` · "
                    f"异常活动 `{item['unusual_activity'] if item['unusual_activity'] is not None else 'N/A'}` · "
                    f"流动性风险 `{item['liquidity_risk'] if item['liquidity_risk'] is not None else 'N/A'}` · {top_text}"
                )
        if notifier is not None:
            key = f"options_daily_summary:{trade_date.isoformat()}"
            try:
                notifier.send(
                    "\n".join(lines),
                    title=f"期权盘后日报（{trade_date.isoformat()}）",
                    route_type="report",
                    severity="info",
                    dedup_key=key,
                    cooldown_key=key,
                )
            except Exception as exc:
                logger.warning("Options daily summary notification failed category=%s", type(exc).__name__)
        return summary_data

    def run(self, symbol, now=None, explain=False, view=None, publish_preview=True, bars=None):
        realtime_run = now is None
        now = now or utc_now()
        symbol = us_symbol(symbol)
        day, phase, _, close = session_context(now)
        view = view or ("preview" if phase == "intraday" else "official")
        if view not in {"preview", "official"}:
            raise ValueError("Unknown options data view")
        if view == "preview" and (phase != "intraday" or day != calendar.get_market_now("us", now).date()):
            raise ValueError("Options preview requires an open US session")
        if view == "official" and (
            day != calendar.get_market_now("us", now).date() or phase != "daily" or (now - close).total_seconds() < 1800
        ):
            raise ValueError("Official options scan requires at least 30 minutes after close")
        bucket = now.replace(minute=now.minute // 30 * 30, second=0, microsecond=0)
        mode = "daily" if phase == "daily" else calendar.get_market_now("us", bucket).strftime("%H:%M")
        chain = self.market.get_option_chain(symbol, now=now)
        if realtime_run:
            # Network completion is the first time a fetched chain can be known to this system.
            now = utc_now()
            current_day, current_phase, _, _ = session_context(now)
            if (
                current_day != day
                or calendar.get_market_now("us", now).date() != day
                or view == "preview"
                and current_phase != "intraday"
            ):
                raise ValueError("US session changed while fetching the option chain")
        if not chain.observations:
            raise ValueError("Options data unavailable: " + "; ".join(chain.errors))
        # A delayed/cached observation before today's close must never become a full-day baseline.
        if view == "official" and chain.observed_at < close:
            raise ValueError("Cached intraday chain cannot become an official daily snapshot")
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
        if calendar.get_market_now("us", now).date() != day or view == "preview" and now > close:
            raise ValueError("US session changed while fetching the stock reference")
        # Also re-filter a chain whose stock reference was supplied after its initial fetch.
        limit_chain(chain, day, self.config)
        if not chain.observations:
            raise ValueError("Options data unavailable: " + "; ".join(chain.errors))
        history = self.repo.history(symbol, day, self.config.history_days, "daily")
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
        bar_data = getattr(bars, "data", None)
        if not isinstance(bar_data, dict):
            bars = self.market.get_daily_bars(
                [symbol], day - timedelta(days=60), last_closed, adjustment="forward", source_policy="db_only"
            )
        expected = calendar.get_completed_trading_days("us", 21, now)
        by_date = {b.trade_date: b.close for b in bars.data.get(symbol, [])}
        closes = [by_date.get(d) for d in expected]
        metrics = analyze(chain, day, now, history, mode, self.config, closes, changes)
        if view == "preview":
            metrics["view"] = "preview"
            if publish_preview:
                self._publish_preview([metrics], now, merge=True)
            return metrics
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

    def _publish_preview(self, items, now, merge=False, failures=(), trade_date=None):
        from .preview_cache import save_preview

        save_preview(
            {
                "trade_date": (trade_date or calendar.get_market_now("us", now).date()).isoformat(),
                "observed_at": now.isoformat(),
                "items": items,
                "failures": list(failures),
            },
            repository=self.preview_repository,
            now=now,
            merge=merge,
        )

    def scan(self, symbols=None, now=None, view=None):
        supplied_now = now
        selected = self.repo.monitored_symbols() if symbols is None else symbols
        if not selected:
            raise ValueError("No Nasdaq-100 constituents or US watch-list symbols available")
        now = now or utc_now()
        day, phase, _, close = session_context(now)
        view = view or ("preview" if phase == "intraday" else "official")
        if view == "official" and (
            day != calendar.get_market_now("us", now).date() or phase != "daily" or now < close + timedelta(minutes=30)
        ):
            raise ValueError("Official options scan requires at least 30 minutes after close on today's US session")
        if view == "preview" and (phase != "intraday" or day != calendar.get_market_now("us", now).date()):
            raise ValueError("Options preview requires an open US session")
        started = monotonic()
        deadline = min(now + timedelta(seconds=PREVIEW_BUDGET_SECONDS), close)
        results = []
        if view == "preview" and symbols is None:
            # Rebuild this round; subsequent atomic checkpoints survive a worker hard timeout.
            self._publish_preview([], now, trade_date=day)
        selected_codes = [us_symbol(symbol) for symbol in selected]
        last_closed = calendar.get_effective_trading_date("us", now)
        try:
            bars = self.market.get_daily_bars(
                selected_codes, day - timedelta(days=60), last_closed, adjustment="forward", source_policy="db_only"
            )
        except SoftTimeLimitExceeded:
            raise
        except Exception:
            bars = None
        # Sequential option-chain requests plus a process-wide task mutex keep chain concurrency at one.
        for symbol in selected:
            if calendar.get_market_now("us", supplied_now or utc_now()).date() != day:
                break  # Never label a later session's results as this round's trade_date.
            if view == "preview" and (
                monotonic() - started >= PREVIEW_BUDGET_SECONDS or (supplied_now or utc_now()) >= deadline
            ):
                break
            try:
                results.append(
                    self.run(symbol, supplied_now, view=view, publish_preview=False, bars=bars)
                )
            except SoftTimeLimitExceeded:
                logger.warning("Options %s execution budget reached symbol=%s", view, symbol)
                break
            except Exception as exc:
                logger.warning("Options scan failed symbol=%s category=%s", symbol, type(exc).__name__)
                results.append(
                    {
                        "symbol": symbol,
                        "status": "failed",
                        "reason": str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
                    }
                )
            if view == "preview":
                row = results[-1]
                self._publish_preview(
                    [row] if row["status"] != "failed" else [],
                    supplied_now or utc_now(),
                    merge=True,
                    failures=[row] if row["status"] == "failed" else [],
                    trade_date=day,
                )
        failures = [r for r in results if r["status"] == "failed"]
        succeeded = [r for r in results if r["status"] != "failed"]
        unfinished = len(selected) - len(results)
        logger.info(
            "Options scan view=%s trade_date=%s elapsed_seconds=%.1f success=%s failed=%s unfinished=%s",
            view,
            day,
            monotonic() - started,
            len(succeeded),
            len(failures),
            unfinished,
        )
        if view == "preview":
            self._publish_preview(
                succeeded,
                supplied_now or utc_now(),
                merge=symbols is not None,
                failures=failures,
                trade_date=day,
            )
        elif symbols is None and succeeded:
            self.summarize_daily(
                day,
                total_count=len(selected),
                failed_count=len(failures),
                unfinished_count=unfinished,
            )
        return {
            "view": view,
            "trade_date": day.isoformat(),
            "total_count": len(selected),
            "unfinished_count": unfinished,
            "status_counts": {
                "success": len(results) - len(failures),
                "failed": len(failures),
                "unfinished": unfinished,
            },
            "results": [{k: r[k] for k in ("symbol", "status", "reason", "snapshot_id") if k in r} for r in results],
            "failed_count": len(failures),
        }

    def explain(self, symbol, trade_date=None):
        symbol = us_symbol(symbol)
        latest = self.repo.latest(symbol, trade_date)
        if latest is None:
            raise ValueError("Scan this symbol before requesting an explanation")
        if latest["llm_analysis"]:
            return latest["llm_analysis"]
        client = self.llm or LLMClient()
        if not client.is_available():
            raise ValueError("LLM is not configured")
        # Explain the selected snapshot with only context available at its computation,
        # including when a user requests an old date long after it was published.
        now = coerce_aware_utc(datetime.fromisoformat(latest["computed_at"]))
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
                prompt=prompt, system_prompt=system, call_type="options_intelligence", web_search=False
            ),
            validator=validate,
        )
        explanation = Explanation.model_validate(parse_llm_json_response(result.text)).model_dump()
        self.repo.save_analysis(latest["snapshot_id"], explanation, result, system + "\n" + prompt)
        return explanation
