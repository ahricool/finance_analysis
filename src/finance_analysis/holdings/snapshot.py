# -*- coding: utf-8 -*-
"""Normalize, hash, and validate a holdings snapshot. fetched_at is excluded from the content hash."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from finance_analysis.core.time import coerce_aware_utc, utc_now  # pragma: allowlist secret
from finance_analysis.holdings.config import get_holdings_config  # pragma: allowlist secret
from finance_analysis.holdings.models import (  # pragma: allowlist secret
    SCHEMA_VERSION,
    HoldingsSnapshot,
    ParsedAccount,
    ParsedLeg,
    ParsedPosition,
)
from finance_analysis.holdings.parser import SheetParseError, group_positions, parse_accounts, parse_legs  # pragma: allowlist secret
from finance_analysis.integrations.google_sheets.client import SheetBatch  # pragma: allowlist secret

from zoneinfo import ZoneInfo


class SnapshotRejected(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _dump(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        aware = coerce_aware_utc(value)
        return aware.isoformat() if aware else None
    if isinstance(value, dict):
        return {str(key): _dump(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_dump(item) for item in value]
    return value


def content_payload(snapshot: HoldingsSnapshot) -> dict[str, Any]:
    body = snapshot.model_dump(mode="python")
    body.pop("fetched_at", None)
    body.pop("generation", None)
    body.pop("content_hash", None)
    return _dump(body)


def content_hash(snapshot: HoldingsSnapshot) -> str:
    encoded = json.dumps(content_payload(snapshot), separators=(",", ":"), sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _nav_validity(account: ParsedAccount, *, now: datetime, max_age: timedelta) -> ParsedAccount:
    if not account.positions_complete:
        return account.model_copy(update={"validity": "INCOMPLETE", "validity_reason": "positions_incomplete"})
    if account.net_asset is None or account.nav_as_of is None:
        return account.model_copy(update={"validity": "NAV_MISSING", "validity_reason": "net_asset_missing"})
    nav_as_of = coerce_aware_utc(account.nav_as_of)
    if nav_as_of is None or now - nav_as_of > max_age:
        return account.model_copy(update={"validity": "NAV_STALE", "validity_reason": "nav_stale"})
    return account


def validate_transition(
    *,
    previous: HoldingsSnapshot | None,
    accounts: list[ParsedAccount],
    positions: list[ParsedPosition],
    now: datetime,
) -> tuple[list[ParsedAccount], list[str]]:
    warnings: list[str] = []
    previous_open: set[tuple[str, str, str]] = set()
    if previous is not None and previous.status == "VALID":
        previous_open = {
            (leg.account_id, leg.position_id, leg.leg_id)
            for position in previous.positions
            for leg in position.legs
            if leg.status == "OPEN" and leg.quantity > 0
        }
    current_keys = {
        (leg.account_id, leg.position_id, leg.leg_id) for position in positions for leg in position.legs
    }
    missing = sorted(previous_open - current_keys)
    if missing:
        if not current_keys:
            raise SnapshotRejected("unexpected_empty", "已有持仓突然空表，不视为清仓")
        raise SnapshotRejected("unexpected_disappearance", "活跃腿意外消失，需显式核对后再同步")

    previous_legs = {}
    if previous is not None:
        previous_legs = {
            (leg.account_id, leg.position_id, leg.leg_id): leg
            for position in previous.positions
            for leg in position.legs
        }
    for position in positions:
        for leg in position.legs:
            prior = previous_legs.get((leg.account_id, leg.position_id, leg.leg_id))
            if prior is None:
                continue
            identity_changed = (
                (prior.canonical_symbol or prior.symbol) != (leg.canonical_symbol or leg.symbol)
                or prior.entry_price != leg.entry_price
                or coerce_aware_utc(prior.entry_time) != coerce_aware_utc(leg.entry_time)
                or prior.leg_role != leg.leg_role
            )
            increased = leg.quantity > prior.quantity
            if identity_changed or increased:
                raise SnapshotRejected(
                    "needs_calibration",
                    f"{leg.account_id}/{leg.position_id}/{leg.leg_id} 身份或数量增加需要校准，不能自动猜成交",
                )

    open_by_account: dict[str, list[ParsedLeg]] = {}
    for position in positions:
        for leg in position.legs:
            if leg.status == "OPEN" and leg.quantity > 0:
                open_by_account.setdefault(leg.account_id, []).append(leg)

    config = get_holdings_config()
    max_age = timedelta(hours=config.nav_max_age_hours)
    validated: list[ParsedAccount] = []
    for account in accounts:
        current = _nav_validity(account, now=now, max_age=max_age)
        open_legs = open_by_account.get(account.account_id, [])
        if not account.positions_complete:
            raise SnapshotRejected("positions_incomplete", f"{account.account_id} 正在编辑，positions_complete=false")
        if not open_legs:
            had_open = any(item[0] == account.account_id for item in previous_open)
            closed_rows = [
                leg
                for position in positions
                for leg in position.legs
                if leg.account_id == account.account_id and leg.status == "CLOSED"
            ]
            if had_open and not closed_rows:
                raise SnapshotRejected("unexpected_empty", f"{account.account_id} 已有持仓突然空表，不视为清仓")
            current = current.model_copy(update={"validity": "EMPTY_VALID", "validity_reason": "empty_confirmed"})
        validated.append(current)
    return validated, warnings


def refresh_validity(snapshot: HoldingsSnapshot, *, now: datetime | None = None) -> HoldingsSnapshot:
    current = coerce_aware_utc(now) or utc_now()
    config = get_holdings_config()
    max_age = timedelta(hours=config.nav_max_age_hours)
    accounts = [_nav_validity(account, now=current, max_age=max_age) for account in snapshot.accounts]
    warnings = list(snapshot.warnings)
    for account in accounts:
        holdings_as_of = coerce_aware_utc(account.holdings_as_of)
        if holdings_as_of is None or current - holdings_as_of > max_age:
            warnings.append(f"{account.account_id}:holdings_stale")
    return snapshot.model_copy(update={"accounts": accounts, "warnings": warnings})


def build_snapshot(
    uid: int,
    source_id: int,
    batch: SheetBatch,
    generation: int,
    previous: HoldingsSnapshot | None = None,
    now: datetime | None = None,
) -> HoldingsSnapshot:
    tz = ZoneInfo(batch.timezone)
    fetched_at = coerce_aware_utc(now) or utc_now()
    try:
        accounts = parse_accounts(batch.values.get("Accounts") or [], tz=tz)
        legs = parse_legs(batch.values.get("Positions") or [], tz=tz)
        account_ids = {account.account_id for account in accounts}
        for leg in legs:
            if leg.account_id not in account_ids:
                raise SheetParseError("orphan_leg", f"腿 {leg.leg_id} 引用未知账户 {leg.account_id}")
        positions = group_positions(legs)
        accounts, warnings = validate_transition(
            previous=previous, accounts=accounts, positions=positions, now=fetched_at
        )
    except SheetParseError as exc:
        raise SnapshotRejected(exc.code, exc.message) from exc

    uncovered = [leg for position in positions for leg in position.legs if leg.coverage != "COVERED"]
    snapshot = HoldingsSnapshot(
        uid=uid,
        source_id=source_id,
        spreadsheet_id=batch.spreadsheet_id,
        generation=generation,
        content_hash="",
        fetched_at=fetched_at,
        timezone=batch.timezone,
        status="VALID",
        accounts=sorted(accounts, key=lambda item: item.account_id),
        positions=positions,
        uncovered_legs=uncovered,
        warnings=warnings,
        schema_version=SCHEMA_VERSION,
    )
    return snapshot.model_copy(update={"content_hash": content_hash(snapshot)})
