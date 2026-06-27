from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from finance_analysis.tasks.jobs.intraday_signal_state import (
    IntradaySignalStateStore,
    build_notification_signature,
)

NY = ZoneInfo("America/New_York")


class _FakePipeline:
    def __init__(self, redis):
        self.redis = redis

    def set(self, key, value, ex=None):
        self.redis.values[key] = value
        return self

    def sadd(self, key, value):
        self.redis.sets.setdefault(key, set()).add(value)
        return self

    def srem(self, key, value):
        self.redis.sets.setdefault(key, set()).discard(value)
        return self

    def expire(self, key, seconds):
        return self

    def execute(self):
        return []


class _FakeRedis:
    def __init__(self):
        self.values = {}
        self.sets = {}

    def get(self, key):
        return self.values.get(key)

    def smembers(self, key):
        return set(self.sets.get(key, set()))

    def pipeline(self, transaction=False):
        return _FakePipeline(self)


def _candidate(*, severity="medium", category="opportunity", strength="normal", change_5m=1.0):
    return {
        "symbol": "NVDA",
        "signal_type": "relative_strength_breakout",
        "severity": severity,
        "category": category,
        "rule_strength": strength,
        "score": 4.0,
        "metrics": {
            "change_5m": change_5m,
            "change_15m": 2.0,
            "volume_ratio_5m": 2.2,
            "price_above_vwap": True,
        },
    }


def test_unchanged_candidate_is_not_re_reviewed_every_five_minutes():
    redis = _FakeRedis()
    first_worker = IntradaySignalStateStore(redis_client=redis)
    second_worker = IntradaySignalStateStore(redis_client=redis)
    now = datetime(2026, 6, 26, 10, 0, tzinfo=NY)

    first = first_worker.filter_candidates_for_review(
        "us", [_candidate()], session_id="2026-06-26", now=now
    )
    repeated = second_worker.filter_candidates_for_review(
        "us", [_candidate()], session_id="2026-06-26", now=now + timedelta(minutes=5)
    )
    periodic = second_worker.filter_candidates_for_review(
        "us", [_candidate()], session_id="2026-06-26", now=now + timedelta(minutes=30)
    )

    assert first[0]["state_transition"] == "new"
    assert repeated == []
    assert periodic[0]["state_transition"] == "unchanged"


def test_risk_is_re_reviewed_sooner_and_escalation_is_immediate():
    store = IntradaySignalStateStore(redis_client=False)
    now = datetime(2026, 6, 26, 10, 0, tzinfo=NY)
    risk = _candidate(severity="warning", category="risk")

    store.filter_candidates_for_review("us", [risk], session_id="2026-06-26", now=now)
    assert store.filter_candidates_for_review(
        "us", [risk], session_id="2026-06-26", now=now + timedelta(minutes=5)
    ) == []
    assert store.filter_candidates_for_review(
        "us", [risk], session_id="2026-06-26", now=now + timedelta(minutes=10)
    )

    escalated = _candidate(severity="high", category="risk", strength="strong", change_5m=2.0)
    changed = store.filter_candidates_for_review(
        "us", [escalated], session_id="2026-06-26", now=now + timedelta(minutes=15)
    )
    assert changed[0]["state_transition"] == "changed"


def test_signal_reappearance_and_new_session_trigger_review():
    store = IntradaySignalStateStore(redis_client=False)
    now = datetime(2026, 6, 26, 10, 0, tzinfo=NY)

    store.filter_candidates_for_review("us", [_candidate()], session_id="2026-06-26", now=now)
    store.filter_candidates_for_review("us", [], session_id="2026-06-26", now=now + timedelta(minutes=5))
    reappeared = store.filter_candidates_for_review(
        "us", [_candidate()], session_id="2026-06-26", now=now + timedelta(minutes=10)
    )
    next_session = store.filter_candidates_for_review(
        "us", [_candidate()], session_id="2026-06-29", now=now + timedelta(days=3)
    )

    assert reappeared[0]["state_transition"] == "reappeared"
    assert next_session[0]["state_transition"] == "reappeared"


def test_unobserved_symbol_is_not_marked_inactive_during_data_failure():
    store = IntradaySignalStateStore(redis_client=False)
    now = datetime(2026, 6, 26, 10, 0, tzinfo=NY)

    store.filter_candidates_for_review(
        "us",
        [_candidate()],
        session_id="2026-06-26",
        now=now,
        observed_symbols={"NVDA"},
    )
    store.filter_candidates_for_review(
        "us",
        [],
        session_id="2026-06-26",
        now=now + timedelta(minutes=5),
        observed_symbols={"MSFT"},
    )
    repeated = store.filter_candidates_for_review(
        "us",
        [_candidate()],
        session_id="2026-06-26",
        now=now + timedelta(minutes=5),
        observed_symbols={"NVDA"},
    )

    assert repeated == []


def test_notification_requires_state_change_and_respects_cooldown_except_escalation():
    store = IntradaySignalStateStore(redis_client=False)
    now = datetime(2026, 6, 26, 10, 0, tzinfo=NY)
    candidate = store.filter_candidates_for_review(
        "us", [_candidate()], session_id="2026-06-26", now=now
    )[0]
    first_signature = build_notification_signature(
        decision="watch",
        severity="warning",
        candidate_signature=candidate["state_signature"],
    )

    assert store.should_notify(
        "us",
        symbol="NVDA",
        signal_type="relative_strength_breakout",
        notification_signature=first_signature,
        severity="warning",
        now=now,
    )
    store.mark_notified(
        "us",
        symbol="NVDA",
        signal_type="relative_strength_breakout",
        notification_signature=first_signature,
        severity="warning",
        now=now,
    )
    assert not store.should_notify(
        "us",
        symbol="NVDA",
        signal_type="relative_strength_breakout",
        notification_signature=first_signature,
        severity="warning",
        now=now + timedelta(minutes=5),
    )

    changed_signature = build_notification_signature(
        decision="risk",
        severity="warning",
        candidate_signature=candidate["state_signature"],
    )
    assert not store.should_notify(
        "us",
        symbol="NVDA",
        signal_type="relative_strength_breakout",
        notification_signature=changed_signature,
        severity="warning",
        now=now + timedelta(minutes=5),
    )
    assert store.should_notify(
        "us",
        symbol="NVDA",
        signal_type="relative_strength_breakout",
        notification_signature=changed_signature,
        severity="error",
        now=now + timedelta(minutes=5),
    )
