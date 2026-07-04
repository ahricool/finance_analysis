"""Validated JSON/CSV/manual event ingestion with point-in-time semantics."""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.database.repositories.stock import MarketDataSymbolRepository

EVENT_TYPES = {
    "earnings", "revenue_surprise", "eps_surprise", "guidance_up", "guidance_down",
    "rating_upgrade", "rating_downgrade", "target_price_up", "target_price_down", "buyback",
    "offering", "product_launch", "major_order", "regulation", "sanction", "litigation",
    "supply_chain", "industry_policy", "other",
}


def _datetime(value) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None: raise ValueError("Event timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def calculate_available_at(published_at: datetime, market: str) -> datetime:
    published_at = _datetime(published_at)
    if market != "US": return published_at
    local = published_at.astimezone(ZoneInfo("America/New_York"))
    if local.time() <= time(16, 0): return published_at
    day = local.date() + timedelta(days=1)
    while day.weekday() >= 5: day += timedelta(days=1)
    return datetime.combine(day, time(9, 30), ZoneInfo("America/New_York")).astimezone(timezone.utc)


class EventImportService:
    def __init__(self, repository=None, symbols=None):
        self.repository = repository or QuantRepository()
        self.symbols = symbols or MarketDataSymbolRepository()

    def import_json(self, items: list[dict]) -> dict:
        created, duplicates, errors = [], 0, []
        for index, item in enumerate(items):
            try:
                values = self._normalize(item)
                event, inserted = self.repository.upsert_event(values)
                if inserted: created.append(event.id)
                else: duplicates += 1
            except (TypeError, ValueError) as exc:
                errors.append({"index": index, "error": str(exc)})
        return {"created": len(created), "event_ids": created, "duplicates": duplicates, "errors": errors}

    def import_csv(self, content: str) -> dict:
        return self.import_json(list(csv.DictReader(io.StringIO(content))))

    def _normalize(self, item: dict) -> dict:
        event_type = str(item.get("event_type", "")).strip().lower()
        if event_type not in EVENT_TYPES: raise ValueError(f"Unsupported event_type: {event_type}")
        direction = str(item.get("direction", "neutral")).lower()
        if direction not in {"positive", "negative", "neutral"}: raise ValueError("Invalid direction")
        code = str(item.get("code") or "").strip().upper() or None
        symbol = self.symbols.get_by_code(code) if code else None
        if code and not symbol: raise ValueError(f"Unknown market_data_symbol: {code}")
        market = str(item.get("market") or (symbol.market if symbol else "")).upper()
        if market not in {"US", "HK", "CN"}: raise ValueError("market must be US, HK, or CN")
        published_at = _datetime(item["published_at"])
        available_at = _datetime(item["available_at"]) if item.get("available_at") else calculate_available_at(published_at, market)
        if available_at < published_at: raise ValueError("available_at cannot precede published_at")
        source = str(item.get("source") or "manual").strip()
        source_event_id = str(item.get("source_event_id") or "").strip()
        if not source_event_id: source_event_id = hashlib.sha256(f"{source}|{code}|{published_at.isoformat()}|{item.get('title')}".encode()).hexdigest()
        dedupe_key = hashlib.sha256(f"{source}|{source_event_id}".encode()).hexdigest()
        importance, confidence = float(item.get("importance", 0.5)), float(item.get("confidence", 1.0))
        if not 0 <= importance <= 1 or not 0 <= confidence <= 1: raise ValueError("importance/confidence must be between 0 and 1")
        return {
            "symbol_id": symbol.id if symbol else None, "code": code, "market": market, "event_type": event_type,
            "published_at": published_at, "effective_at": _datetime(item["effective_at"]) if item.get("effective_at") else None,
            "available_at": available_at, "direction": direction, "importance": importance, "confidence": confidence,
            "surprise_value": float(item["surprise_value"]) if item.get("surprise_value") not in (None, "") else None,
            "source": source, "source_event_id": source_event_id, "title": str(item.get("title") or "").strip() or event_type,
            "summary": item.get("summary"), "raw_content": item.get("raw_content"), "raw_payload": item.get("raw_payload") or item,
            "dedupe_key": dedupe_key, "review_status": item.get("review_status", "reviewed"), "extractor_model": item.get("extractor_model"),
        }
