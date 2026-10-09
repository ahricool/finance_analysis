"""Expire current liquidity evidence at read time without mutating historical scores."""

from copy import deepcopy
from statistics import mean
from finance_analysis.core.time import utc_now
from finance_analysis.market_review.trading_calendar import get_market_now
from finance_analysis.integrations.options.models import OptionObservation
from .config import get_options_config
from .metrics import liquidity, weighted_score


def current_view(metrics, now=None):
    if not metrics or not metrics.get("scores"):
        return metrics
    now = now or utc_now()
    result = deepcopy(metrics)
    config = get_options_config()
    valid = []
    for contract in result.get("contracts", []):
        row = OptionObservation.model_validate(contract)
        calculated = liquidity(row, now, get_market_now("us", now).date(), config)
        # Volume/OI belongs to the snapshot's dated session, unlike current quote freshness.
        calculated["volume_oi"] = contract.get("volume_oi")
        contract.update(calculated)
        if calculated["risk"]["value"] is not None:
            valid.append(calculated["risk"]["value"])
    result["snapshot_liquidity_score"] = result["scores"]["liquidity_risk"]
    result["scores"]["liquidity_risk"] = weighted_score(
        [mean(valid)] if valid else [], (1,), "initial_price_dte_moneyness_rules", "fresh_real_quotes_unavailable"
    )
    result["liquidity_checked_at"] = now.isoformat()
    return result


def scan_view(metrics):
    # Stored research scores describe the observation time, including historical dates.
    # Live execution freshness remains a separate contract risk/quote_status field.
    current = metrics
    result = {k: v for k, v in current.items() if k not in {"contracts", "events"}}
    if "events" in current:
        result["event_types"] = sorted({e["event_type"] for e in current["events"]})
        result["top_event"] = max(current["events"], key=lambda e: e["severity"], default=None)
    else:
        # Redis already stores compact summaries; don't discard their anomaly evidence.
        result.setdefault("event_types", [])
        result.setdefault("top_event", None)
    return result
