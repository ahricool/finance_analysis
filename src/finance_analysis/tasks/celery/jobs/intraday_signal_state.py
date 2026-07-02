# -*- coding: utf-8 -*-
"""Shared Redis-backed state for low-noise intraday signal processing.

The five-minute jobs still run their deterministic rules on every window.  This
module keeps the expensive and user-visible stages stateful: unchanged signals
are only re-reviewed periodically, and notifications are emitted for a new,
reappearing, materially changed, or escalated signal.
"""

from __future__ import annotations

import json
import logging
import math
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from finance_analysis.integrations.market_data.realtime_types import safe_float

logger = logging.getLogger(__name__)

DEFAULT_REVIEW_SECONDS = 30 * 60
RISK_REVIEW_SECONDS = 10 * 60
NOTIFICATION_COOLDOWN_SECONDS = 15 * 60
STATE_TTL_SECONDS = 7 * 24 * 60 * 60

_SEVERITY_RANK = {
    "info": 0,
    "low": 0,
    "medium": 1,
    "warning": 2,
    "high": 3,
    "error": 4,
    "critical": 5,
}

_SHARED_MEMORY: Dict[str, Dict[str, Any]] = {}
_SHARED_MEMORY_ACTIVE: Dict[str, set[str]] = {}
_SHARED_MEMORY_LOCK = threading.Lock()

_SIGNATURE_NUMERIC_FIELDS = (
    "change_5m",
    "change_15m",
    "change_30m",
    "relative_to_qqq_15m",
    "relative_to_main_index_15m",
    "relative_to_board_index_15m",
    "drawdown_from_high_pct",
    "rebound_from_low_pct",
    "low_distance_pct",
    "distance_to_limit_up_pct",
    "distance_to_limit_down_pct",
)
_SIGNATURE_RATIO_FIELDS = ("volume_ratio_5m", "intraday_volume_ratio")
_SIGNATURE_BOOLEAN_FIELDS = (
    "price_above_vwap",
    "price_below_vwap",
    "crossed_above_vwap",
    "crossed_below_vwap",
    "is_limit_up",
    "opened_from_limit_up",
    "one_word_limit_up",
)


def build_candidate_state_signature(candidate: Mapping[str, Any]) -> str:
    """Build a stable, coarse signature for meaningful rule-state changes."""
    metrics = candidate.get("metrics") if isinstance(candidate.get("metrics"), Mapping) else {}
    payload: Dict[str, Any] = {
        "signal_type": str(candidate.get("signal_type") or ""),
        "rule_strength": str(candidate.get("rule_strength") or ""),
        "severity": str(candidate.get("severity") or ""),
        "score": _score_bucket(candidate.get("score")),
    }
    for field in _SIGNATURE_NUMERIC_FIELDS:
        payload[field] = _numeric_bucket(metrics.get(field), step=0.5)
    for field in _SIGNATURE_RATIO_FIELDS:
        payload[field] = _ratio_bucket(metrics.get(field))
    for field in _SIGNATURE_BOOLEAN_FIELDS:
        value = metrics.get(field)
        payload[field] = bool(value) if value is not None else None
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def build_notification_signature(
    *,
    decision: str,
    severity: str,
    candidate_signature: str,
) -> str:
    """Return the notification state signature used after LLM review."""
    return json.dumps(
        {
            "candidate": candidate_signature,
            "decision": str(decision or "").strip().lower(),
            "severity": _normalize_severity(severity),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


class IntradaySignalStateStore:
    """Persist active/reviewed/notified signal state in the existing Redis.

    Redis failures degrade to a process-local shared store so analysis and risk
    alerts remain available.  The fallback is intentionally fail-open and does
    not replace Redis as the cross-worker coordination mechanism.
    """

    def __init__(self, redis_client: Any = None, *, ttl_seconds: int = STATE_TTL_SECONDS) -> None:
        isolated_memory = redis_client is False
        self._redis = None if redis_client is False else redis_client
        self._redis_initialized = redis_client is not None
        self.ttl_seconds = max(60, int(ttl_seconds))
        self._memory = {} if isolated_memory else _SHARED_MEMORY
        self._memory_active = {} if isolated_memory else _SHARED_MEMORY_ACTIVE
        self._lock = threading.Lock() if isolated_memory else _SHARED_MEMORY_LOCK

    def filter_candidates_for_review(
        self,
        market: str,
        candidates: Sequence[Dict[str, Any]],
        *,
        session_id: str,
        now: datetime,
        normal_review_seconds: int = DEFAULT_REVIEW_SECONDS,
        risk_review_seconds: int = RISK_REVIEW_SECONDS,
        observed_symbols: Optional[Iterable[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Observe all rule hits and return only candidates needing LLM review."""
        now_ts = _timestamp(now)
        market_key = _normalize_market(market)
        current_ids: set[str] = set()
        selected: List[Dict[str, Any]] = []

        for candidate in candidates:
            symbol = _candidate_symbol(candidate)
            signal_type = str(candidate.get("signal_type") or "").strip()
            if not symbol or not signal_type:
                continue
            identity = _identity(symbol, signal_type)
            current_ids.add(identity)
            state = self._read_state(market_key, identity) or {}
            signature = str(candidate.get("state_signature") or build_candidate_state_signature(candidate))
            severity = _normalize_severity(candidate.get("severity"))
            category = str(candidate.get("category") or "").strip().lower()
            was_active = bool(state.get("active"))
            session_changed = str(state.get("session_id") or "") != str(session_id)
            signature_changed = str(state.get("candidate_signature") or "") != signature
            generation = int(state.get("generation") or 0)
            transition = "unchanged"
            if not state:
                transition = "new"
                generation = 1
            elif session_changed or not was_active:
                transition = "reappeared"
                generation += 1
            elif signature_changed:
                transition = "changed"
                generation += 1

            last_reviewed_at = _as_float(state.get("last_reviewed_at"))
            prior_notification_severity = _normalize_severity(state.get("notification_severity"))
            risk_priority = (
                category == "risk"
                or _is_risk(severity)
                or _is_risk(prior_notification_severity)
            )
            review_seconds = risk_review_seconds if risk_priority else normal_review_seconds
            review_due = last_reviewed_at is None or now_ts - last_reviewed_at >= max(0, review_seconds)
            should_review = transition != "unchanged" or review_due

            state.update(
                {
                    "active": True,
                    "candidate_signature": signature,
                    "generation": generation,
                    "last_seen_at": now_ts,
                    "session_id": str(session_id),
                    "severity": severity,
                }
            )
            if should_review:
                state["last_reviewed_at"] = now_ts
                observed = dict(candidate)
                observed["state_signature"] = signature
                observed["state_transition"] = transition
                observed["state_generation"] = generation
                selected.append(observed)
            self._write_state(market_key, identity, state)

        normalized_observed = None
        if observed_symbols is not None:
            normalized_observed = {str(symbol).strip().upper() for symbol in observed_symbols}
        self._deactivate_missing(market_key, current_ids, now_ts, normalized_observed)
        return selected

    def should_notify(
        self,
        market: str,
        *,
        symbol: str,
        signal_type: str,
        notification_signature: str,
        severity: str,
        now: datetime,
        cooldown_seconds: int = NOTIFICATION_COOLDOWN_SECONDS,
    ) -> bool:
        """Allow notifications only for state transitions, with escalation priority."""
        market_key = _normalize_market(market)
        identity = _identity(symbol, signal_type)
        state = self._read_state(market_key, identity) or {
            "active": True,
            "generation": 1,
            "candidate_signature": "",
        }
        previous_signature = str(state.get("notification_signature") or "")
        previous_severity = _normalize_severity(state.get("notification_severity"))
        current_severity = _normalize_severity(severity)
        generation = int(state.get("generation") or 1)
        notified_generation = int(state.get("notified_generation") or 0)
        last_notified_at = _as_float(state.get("last_notified_at"))
        now_ts = _timestamp(now)

        if not previous_signature:
            return True
        if _severity_rank(current_severity) > _severity_rank(previous_severity):
            return True

        changed = previous_signature != notification_signature or generation > notified_generation
        if not changed:
            return False
        if last_notified_at is not None and now_ts - last_notified_at < max(0, cooldown_seconds):
            return False
        return True

    def mark_notified(
        self,
        market: str,
        *,
        symbol: str,
        signal_type: str,
        notification_signature: str,
        severity: str,
        now: datetime,
    ) -> None:
        market_key = _normalize_market(market)
        identity = _identity(symbol, signal_type)
        state = self._read_state(market_key, identity) or {"active": True, "generation": 1}
        state.update(
            {
                "last_notified_at": _timestamp(now),
                "notification_signature": notification_signature,
                "notification_severity": _normalize_severity(severity),
                "notified_generation": int(state.get("generation") or 1),
            }
        )
        self._write_state(market_key, identity, state)

    def _deactivate_missing(
        self,
        market: str,
        current_ids: set[str],
        now_ts: float,
        observed_symbols: Optional[set[str]],
    ) -> None:
        for identity in self._active_identities(market) - current_ids:
            symbol = identity.split("|", 1)[0]
            if observed_symbols is not None and symbol not in observed_symbols:
                continue
            state = self._read_state(market, identity)
            if not state:
                continue
            state["active"] = False
            state["last_inactive_at"] = now_ts
            self._write_state(market, identity, state, active=False)

    def _read_state(self, market: str, identity: str) -> Optional[Dict[str, Any]]:
        redis_client = self._redis_client()
        if redis_client is not None:
            try:
                raw = redis_client.get(self._state_key(market, identity))
                if raw:
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    return dict(json.loads(raw))
            except Exception as exc:
                self._disable_redis(exc)
        with self._lock:
            state = self._memory.get(self._state_key(market, identity))
            return dict(state) if state is not None else None

    def _write_state(
        self,
        market: str,
        identity: str,
        state: Mapping[str, Any],
        *,
        active: bool = True,
    ) -> None:
        key = self._state_key(market, identity)
        redis_client = self._redis_client()
        if redis_client is not None:
            try:
                pipe = redis_client.pipeline(transaction=False)
                pipe.set(key, json.dumps(dict(state), ensure_ascii=True, separators=(",", ":")), ex=self.ttl_seconds)
                if active:
                    pipe.sadd(self._active_key(market), identity)
                else:
                    pipe.srem(self._active_key(market), identity)
                pipe.expire(self._active_key(market), self.ttl_seconds)
                pipe.execute()
                return
            except Exception as exc:
                self._disable_redis(exc)
        with self._lock:
            self._memory[key] = dict(state)
            active_set = self._memory_active.setdefault(market, set())
            if active:
                active_set.add(identity)
            else:
                active_set.discard(identity)

    def _active_identities(self, market: str) -> set[str]:
        redis_client = self._redis_client()
        if redis_client is not None:
            try:
                values: Iterable[Any] = redis_client.smembers(self._active_key(market)) or []
                return {
                    item.decode("utf-8") if isinstance(item, bytes) else str(item)
                    for item in values
                }
            except Exception as exc:
                self._disable_redis(exc)
        with self._lock:
            return set(self._memory_active.get(market, set()))

    def _redis_client(self) -> Any:
        if self._redis_initialized:
            return self._redis
        self._redis_initialized = True
        try:
            import redis

            from finance_analysis.database.config import get_database_config

            self._redis = redis.Redis.from_url(get_database_config().redis_url, decode_responses=True)
        except Exception as exc:
            logger.warning("无法初始化盘中信号 Redis 状态，降级为进程内状态: %s", exc)
            self._redis = None
        return self._redis

    def _disable_redis(self, exc: Exception) -> None:
        logger.warning("盘中信号 Redis 状态不可用，降级为进程内状态: %s", exc)
        self._redis = None
        self._redis_initialized = True

    @staticmethod
    def _state_key(market: str, identity: str) -> str:
        return f"intraday:signal_state:{market}:{identity}"

    @staticmethod
    def _active_key(market: str) -> str:
        return f"intraday:signal_state:{market}:active"


def _candidate_symbol(candidate: Mapping[str, Any]) -> str:
    return str(candidate.get("symbol") or candidate.get("code") or "").strip().upper()


def _identity(symbol: str, signal_type: str) -> str:
    return f"{str(symbol).strip().upper()}|{str(signal_type).strip()}"


def _normalize_market(market: str) -> str:
    return str(market or "unknown").strip().lower() or "unknown"


def _normalize_severity(value: Any) -> str:
    normalized = str(value or "info").strip().lower()
    return normalized if normalized in _SEVERITY_RANK else "info"


def _severity_rank(value: str) -> int:
    return _SEVERITY_RANK.get(_normalize_severity(value), 0)


def _is_risk(severity: str) -> bool:
    return _severity_rank(severity) >= _severity_rank("warning")


def _timestamp(value: datetime) -> float:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _as_float(value: Any) -> Optional[float]:
    parsed = safe_float(value)
    return parsed if parsed is not None and math.isfinite(parsed) else None


def _numeric_bucket(value: Any, *, step: float) -> Optional[int]:
    parsed = _as_float(value)
    if parsed is None:
        return None
    return math.floor(parsed / step)


def _score_bucket(value: Any) -> Optional[int]:
    parsed = _as_float(value)
    return None if parsed is None else int(math.floor(parsed))


def _ratio_bucket(value: Any) -> Optional[str]:
    parsed = _as_float(value)
    if parsed is None:
        return None
    for threshold in (1.0, 1.5, 2.0, 3.0, 5.0):
        if parsed < threshold:
            return f"<{threshold:g}"
    return ">=5"


__all__ = [
    "DEFAULT_REVIEW_SECONDS",
    "IntradaySignalStateStore",
    "NOTIFICATION_COOLDOWN_SECONDS",
    "RISK_REVIEW_SECONDS",
    "build_candidate_state_signature",
    "build_notification_signature",
]
