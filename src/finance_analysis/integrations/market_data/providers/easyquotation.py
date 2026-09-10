"""Tencent full-market A-share snapshot via easyquotation. Preview-only; not a general realtime fallback."""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo

from finance_analysis.integrations.market_data.models import BatchQuoteResult, Market, MarketQuote  # pragma: allowlist secret
from finance_analysis.integrations.market_data.normalizer import currency_for_market  # pragma: allowlist secret

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")
PROVIDER_NAME = "easyquotation"
PROVIDER_LABEL = "easyquotation_tencent"


def tencent_code_to_canonical(raw_code: str) -> str | None:
    """Keep SH/SZ/BJ from Tencent prefixes so indexes do not collide with stocks."""
    value = str(raw_code or "").strip()
    if not value:
        return None
    lowered = value.lower()
    if len(lowered) >= 8 and lowered[:2] in {"sh", "sz", "bj"} and lowered[2:].isdigit() and len(lowered[2:]) == 6:
        return f"{lowered[2:]}.{lowered[:2].upper()}"
    return None


def canonical_to_tencent_code(symbol: str) -> str | None:
    """Encode 510300.SH as sh510300 for a single Tencent real() batch."""
    value = str(symbol or "").strip().upper()
    if "." not in value:
        return None
    ticker, exchange = value.rsplit(".", 1)
    if exchange not in {"SH", "SZ", "BJ"} or not ticker.isdigit() or len(ticker) != 6:
        return None
    return f"{exchange.lower()}{ticker}"


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _quote_time(row: Mapping[str, Any]) -> datetime | None:
    value = row.get("datetime")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=CN_TZ)
        return value
    date_text = str(row.get("date") or "").strip()
    time_text = str(row.get("time") or "").strip()
    if date_text and time_text:
        try:
            parsed = datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
        return parsed.replace(tzinfo=CN_TZ)
    return None


def quote_from_tencent_row(raw_code: str, row: Mapping[str, Any]) -> MarketQuote | None:
    """Build a quote without canonical_symbol(), which would map 000001.SH onto 000001.SZ."""
    symbol = tencent_code_to_canonical(raw_code)
    if symbol is None or not isinstance(row, Mapping):
        return None
    price = _number(row.get("now"))
    if price is None or price <= 0:
        return None
    volume = _number(row.get("volume"))
    amount = _number(row.get("成交额(万)"))
    return MarketQuote(
        symbol=symbol,
        market=Market.CN,
        provider=PROVIDER_NAME,
        currency=currency_for_market(Market.CN),
        name=str(row.get("name") or "").strip(),
        price=price,
        open_price=_number(row.get("open")),
        high=_number(row.get("high")),
        low=_number(row.get("low")),
        pre_close=_number(row.get("close")),
        volume=None if volume is None else int(volume),
        amount=amount,
        quote_time=_quote_time(row),
    )


def _ingest_quotes(raw: Mapping[Any, Any] | None) -> BatchQuoteResult:
    result = BatchQuoteResult()
    if not raw:
        return result
    for raw_code, row in raw.items():
        try:
            quote = quote_from_tencent_row(str(raw_code), row if isinstance(row, Mapping) else {})
        except (TypeError, ValueError):
            continue
        if quote is None:
            continue
        result.data[quote.symbol] = quote
        result.providers_used[quote.symbol] = PROVIDER_NAME
    return result


class EasyQuotationProvider:
    name = PROVIDER_NAME

    def __init__(self, *, client_factory: Callable[[], Any] | None = None) -> None:
        self._client_factory = client_factory

    def _client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory()
        import easyquotation

        return easyquotation.use("tencent")

    def fetch_market_snapshot(self, market: Market) -> BatchQuoteResult:
        if market is not Market.CN:
            raise ValueError("easyquotation tencent snapshot supports CN only")
        try:
            raw = self._client().market_snapshot(prefix=True)
        except Exception:
            logger.exception("provider=%s market=CN action=market_snapshot failed", PROVIDER_LABEL)
            raise
        if not raw:
            raise RuntimeError("easyquotation tencent returned empty snapshot")
        result = _ingest_quotes(raw)
        if not result.data:
            raise RuntimeError("easyquotation tencent snapshot contained no usable quotes")
        return result

    def fetch_quotes_for_codes(self, symbols: Iterable[str]) -> BatchQuoteResult:
        """One Tencent real() batch for codes missing from market_snapshot, typically ETFs."""
        codes: list[str] = []
        seen: set[str] = set()
        for symbol in symbols:
            tencent = canonical_to_tencent_code(symbol)
            if tencent is None or tencent in seen:
                continue
            seen.add(tencent)
            codes.append(tencent)
        if not codes:
            return BatchQuoteResult()
        try:
            raw = self._client().real(codes, prefix=True)
        except Exception:
            logger.exception(
                "provider=%s action=real failed requested=%s",
                PROVIDER_LABEL,
                len(codes),
            )
            raise
        result = _ingest_quotes(raw)
        logger.info(
            "provider=%s action=real requested=%s returned=%s usable=%s",
            PROVIDER_LABEL,
            len(codes),
            0 if not raw else len(raw),
            len(result.data),
        )
        return result


__all__ = [
    "EasyQuotationProvider",
    "PROVIDER_LABEL",
    "PROVIDER_NAME",
    "canonical_to_tencent_code",
    "quote_from_tencent_row",
    "tencent_code_to_canonical",
]
