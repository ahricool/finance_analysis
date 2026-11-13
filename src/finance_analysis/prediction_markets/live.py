"""Disposable shared cache and on-demand data. No database imports or writes."""

import copy
import json
import logging
import threading
import time
from concurrent.futures import Future
from functools import lru_cache

from finance_analysis.core.time import utc_now
from finance_analysis.integrations.polymarket.client import Client, probability
from .config import get_config

logger = logging.getLogger(__name__)


def array(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return value if isinstance(value, list) else []


def live_projection(raw):
    markets = []
    for m in raw.get("markets") or []:
        version = m.get("version")
        ids = array(m.get("positionIds" if version == "v2" else "clobTokenIds")) if version in {"v1", "v2"} else []
        names, prices = array(m.get("outcomes")), array(m.get("outcomePrices"))
        # Gamma placeholders without demonstrated trading activity are not reliable probabilities.
        try:
            import math

            volume = float(m.get("volumeNum") or m.get("volume") or 0)
            traded = math.isfinite(volume) and volume > 0
        except (TypeError, ValueError):
            traded = False
        settled = str(m.get("resolutionStatus") or m.get("umaResolutionStatus") or "").lower() == "resolved"
        outcomes = []
        for index, label in enumerate(names):
            price = probability(prices[index]) if index < len(prices) and (traded or settled) else None
            outcomes.append(
                dict(
                    id=str(ids[index]) if index < len(ids) and ids[index] is not None else None,
                    label=str(label),
                    probability=price,
                    price_type="settlement" if settled else "gamma_outcome_price",
                    missing_reason=None if price is not None else "no_reliable_trading_price",
                )
            )
        markets.append(
            dict(
                id=str(m["id"]),
                question=m.get("question"),
                version=version,
                end_at=m.get("endDate"),
                closed=m.get("closed"),
                resolved=settled,
                observed_at=None,
                outcomes=outcomes,
            )
        )
    return dict(
        event_id=str(raw["id"]),
        closed=raw.get("closed"),
        archived=raw.get("archived"),
        markets=markets,
        observed_at=None,
        source="Polymarket Gamma",
        protocol_coverage=["v1", "v2"],
    )


def changes(points, now, latest_tolerance=900, baseline_tolerance=3600, closed=False):
    """Same series only; no quote/history mixing or forward baseline observations."""
    result = {}
    for name, window in [("24h", 86400), ("7d", 7 * 86400)]:
        value, reason = None, "insufficient_history"
        if closed:
            reason = "closed_or_resolved"
        elif points:
            latest = points[-1]
            target = latest["timestamp"] - window
            baseline = next((p for p in reversed(points) if p["timestamp"] <= target), None)
            if (
                not 0 <= now - latest["timestamp"] <= latest_tolerance
                or latest["resolution_seconds"] > latest_tolerance
            ):
                reason = "latest_observation_stale_or_coarse"
            elif (
                baseline
                and target - baseline["timestamp"] <= baseline_tolerance
                and baseline["resolution_seconds"] <= baseline_tolerance
            ):
                value, reason = round((latest["price"] - baseline["price"]) * 100, 4), None
            elif baseline:
                reason = "baseline_stale_or_coarse"
        result[name] = {"percentage_points": value, "reason": reason}
    return result


class LiveService:
    def __init__(self, client=None, redis=None, config=None, clock=time.time):
        self.config, self.clock = config or get_config(), clock
        self.client = client or Client()
        if redis is None:
            import redis as redis_module
            from finance_analysis.database.config import get_database_config

            redis = redis_module.Redis.from_url(
                get_database_config().redis_url, decode_responses=True, socket_connect_timeout=1, socket_timeout=1
            )
        self.redis = redis
        self.gate = threading.BoundedSemaphore(self.config.concurrency)
        self.lock, self.inflight = threading.Lock(), {}

    def cached(self, key, ttl, loader):
        key = "prediction:public:v1-v2:data-v2:" + key
        with self.lock:
            future = self.inflight.get(key)
            owner = future is None
            if owner:
                future = self.inflight[key] = Future()
        if not owner:
            return copy.deepcopy(future.result())
        try:
            old = None
            try:
                raw = self.redis.get(key)
                old = json.loads(raw) if raw else None
                if not isinstance(old, dict) or not isinstance(old.get("cached_at"), (float, int)):
                    old = None
            except Exception:
                logger.warning("Prediction cache read unavailable")
            if old and self.clock() - old["cached_at"] <= ttl:
                result = {**old, "cache_status": "hit", "stale": False}
            else:
                try:
                    with self.gate:
                        payload = loader()
                    result = {
                        **payload,
                        "fetched_at": utc_now().isoformat(),
                        "cached_at": self.clock(),
                        "cache_status": "miss",
                        "stale": False,
                        "status": "ready",
                    }
                    try:
                        self.redis.set(key, json.dumps(result, allow_nan=False), ex=ttl + self.config.stale_seconds)
                    except Exception:
                        logger.warning("Prediction cache write unavailable")
                except Exception:
                    if old and self.clock() - old["cached_at"] <= ttl + self.config.stale_seconds:
                        result = {**old, "cache_status": "stale", "stale": True, "error": "upstream_unavailable"}
                    else:
                        result = dict(
                            status="unavailable",
                            error="upstream_unavailable",
                            stale=False,
                            fetched_at=None,
                            cache_status="miss",
                        )
            future.set_result(result)
            return copy.deepcopy(result)
        except BaseException as exc:
            future.set_exception(exc)
            raise
        finally:
            with self.lock:
                self.inflight.pop(key, None)

    def live(self, event_id):
        return self.cached(
            "event:" + event_id, self.config.live_ttl, lambda: live_projection(self.client.event(event_id))
        )

    def history(self, event_id, market_id, outcome_id, window):
        live = self.live(event_id)
        if live["status"] != "ready" or live.get("stale"):
            return dict(
                status="unavailable", error="membership_unavailable", fetched_at=None, stale=False, cache_status="miss"
            )
        market = next((m for m in live["markets"] if m["id"] == market_id), None)
        if not market or not any(o["id"] == outcome_id for o in market["outcomes"]):
            raise ValueError("结果不属于该事件的当前市场")

        def load():
            points = self.client.history(outcome_id, interval=window)
            # Retain the native window's detail. Only absent/coarse baselines need extra
            # point-in-time reads from this same Data API series, anchored at its terminal tick.
            summary = list(points)
            if points and not (market["closed"] or market["resolved"]):
                latest = points[-1]["timestamp"]
                for seconds in (86400, 7 * 86400):
                    target = latest - seconds
                    baseline = next((p for p in reversed(points) if p["timestamp"] <= target), None)
                    if (
                        baseline is None
                        or target - baseline["timestamp"] > self.config.baseline_tolerance
                        or baseline["resolution_seconds"] > self.config.baseline_tolerance
                    ):
                        try:
                            summary.extend(self.client.history(outcome_id, as_of=target))
                        except Exception:
                            logger.warning("Prediction history baseline unavailable")
            summary = sorted({p["timestamp"]: p for p in summary}.values(), key=lambda p: p["timestamp"])
            delta = changes(
                summary,
                int(self.clock()),
                self.config.latest_tolerance,
                self.config.baseline_tolerance,
                bool(market["closed"] or market["resolved"]),
            )
            chart = points
            return dict(
                points=chart,
                changes=delta,
                series_as_of=points[-1]["timestamp"] if points else None,
                source="Polymarket Data API v2",
                window=window,
                market_id=market_id,
                outcome_id=outcome_id,
                closed=market["closed"],
                resolved=market["resolved"],
            )

        result = self.cached(f"history:{market['version']}:{outcome_id}:{window}:auto", self.config.history_ttl, load)
        if result["status"] == "ready":
            # Live lifecycle is authoritative even when history's longer cache predates closure.
            result.update(closed=market["closed"], resolved=market["resolved"])
            if market["closed"] or market["resolved"]:
                result["changes"] = changes([], int(self.clock()), closed=True)
        return result


@lru_cache
def get_live_service():
    return LiveService()
