"""One atomic daily document; no minute bars or permanent research writes."""

import json
from finance_analysis.trend_following.preview_cache import _redis_client, json_ready
from .session import expires_at


class ConfirmationCache:
    def __init__(self, client=None):
        self.client = client if client is not None else _redis_client()
        if self.client is None:
            raise RuntimeError("Intraday Confirmation Redis unavailable")

    @staticmethod
    def key(market, day):
        return f"intraday_confirmation:{market}:{day}"

    def load(self, market, day):
        raw = self.client.get(self.key(market, day))
        return json.loads(raw) if raw else None

    def save(self, session, payload):
        self.client.set(
            self.key(session.market, session.day),
            json.dumps(json_ready(payload), ensure_ascii=False, allow_nan=False),
            exat=int(expires_at(session).timestamp()),
        )

    def lock(self, session):
        from .config import LOCK_SECONDS

        return self.client.lock(
            self.key(session.market, session.day) + ":lock", timeout=LOCK_SECONDS, blocking_timeout=0
        )
