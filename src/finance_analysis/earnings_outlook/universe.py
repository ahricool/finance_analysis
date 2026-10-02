"""The only eligible scope: active stock Instrument identities in two indices."""

from finance_analysis.database.repositories.universe import UniverseResolver
from finance_analysis.database.models.stock import validate_instrument_code
from .config import UNIVERSES


def resolve_members(resolver=None):
    resolver = resolver or UniverseResolver()
    members = {}
    for key in UNIVERSES:
        rows = resolver.resolve_universe(key)
        active = [r for r in rows if r.market == "US" and r.instrument_type == "STOCK" and r.listing_status == "ACTIVE"]
        if not active:
            raise ValueError(f"Empty active earnings universe: {key}")
        for row in active:
            code = validate_instrument_code("US", row.code)
            item = members.setdefault(row.id, dict(instrument_id=row.id, symbol=code, name=row.name, memberships=[]))
            item["memberships"].append(key)
    return {item["symbol"]: item for item in members.values()}
