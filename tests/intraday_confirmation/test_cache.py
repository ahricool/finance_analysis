from contextlib import nullcontext
from datetime import datetime, date
from zoneinfo import ZoneInfo
import json
import pytest
from finance_analysis.intraday_confirmation.cache import ConfirmationCache
from finance_analysis.intraday_confirmation.session import Session


def test_atomic_daily_payload_expiry_and_write_failure():
    class Redis:
        raw = None
        fail = False

        def set(self, key, raw, **kwargs):
            if self.fail:
                raise RuntimeError("Redis down")
            self.key, self.raw, self.options = key, raw, kwargs

        def get(self, key):
            return self.raw

        def lock(self, key, **kwargs):
            self.lock_key, self.lock_options = key, kwargs
            return nullcontext()

    client = Redis()
    cache = ConfirmationCache(client)
    tz = ZoneInfo("America/New_York")
    opened = datetime(2026, 9, 21, 9, 30, tzinfo=tz)
    session = Session("US", opened, opened.replace(hour=16, minute=0), date(2026, 9, 18))
    payload = dict(items=[], frozen_at=opened, generated_at=opened)
    with cache.lock(session):
        cache.save(session, payload)
    assert client.key == "intraday_confirmation:US:2026-09-21"
    assert client.options["exat"] == int(datetime(2026, 9, 22, tzinfo=tz).timestamp())
    assert cache.load("US", session.day) == json.loads(client.raw)
    assert client.lock_options["blocking_timeout"] == 0
    client.fail = True
    with pytest.raises(RuntimeError, match="Redis down"):
        cache.save(session, payload)
