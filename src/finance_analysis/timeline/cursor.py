"""Opaque, stateless position in the investment feed's three-part ordering."""

import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone


class InvalidTimelineCursor(ValueError):
    """The supplied cursor is not a valid feed position."""


@dataclass(frozen=True)
class TimelineCursor:
    event_time: datetime
    source_type: str
    source_id: int

    def encode(self) -> str:
        payload = dict(
            event_time=self.event_time.astimezone(timezone.utc).isoformat(),
            source_type=self.source_type,
            source_id=self.source_id,
        )
        return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")

    @classmethod
    def decode(cls, token: str):
        try:
            if len(token) > 1024 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
                raise ValueError("Invalid encoding")
            payload = json.loads(base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True))
            if not isinstance(payload, dict) or set(payload) != {"event_time", "source_type", "source_id"}:
                raise ValueError("Invalid fields")
            if not isinstance(payload["event_time"], str):
                raise ValueError("Invalid timestamp")
            timestamp = datetime.fromisoformat(payload["event_time"])
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("Timestamp must include timezone")
            if payload["source_type"] not in ("finance_event", "news", "report", "note"):
                raise ValueError("Invalid source")
            if type(payload["source_id"]) is not int or not 0 < payload["source_id"] <= 2147483647:
                raise ValueError("Invalid source id")
            return cls(timestamp.astimezone(timezone.utc), payload["source_type"], payload["source_id"])
        except (ValueError, TypeError, OverflowError, RecursionError) as exc:
            raise InvalidTimelineCursor("Invalid timeline cursor") from exc
