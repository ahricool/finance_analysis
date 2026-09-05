"""Persistence and recursive resolution for unified universes."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select, update

from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.models.universe import Universe, UniverseInclude, UniverseMember


class UniverseCycleError(ValueError):
    pass


@dataclass(frozen=True)
class MembershipSyncStats:
    inserted: int = 0
    deleted: int = 0
    total: int = 0


class UniverseRepository:
    def __init__(self, db_manager=None):
        if db_manager is None:
            from finance_analysis.database.session import DatabaseManager

            db_manager = DatabaseManager.get_instance()
        self.db = db_manager

    def get_by_key(self, key: str) -> Universe | None:
        with self.db.get_session() as session:
            row = session.execute(select(Universe).where(Universe.key == key)).scalar_one_or_none()
            if row is not None:
                session.expunge(row)
            return row

    def list_members(self, universe_id: int) -> list[UniverseMember]:
        with self.db.get_session() as session:
            rows = list(session.execute(
                select(UniverseMember).where(UniverseMember.universe_id == universe_id)
            ).scalars().unique())
            for row in rows:
                session.expunge(row)
            return rows

    def list_included_universes(self, universe_id: int) -> list[Universe]:
        with self.db.get_session() as session:
            rows = list(session.execute(
                select(Universe).join(UniverseInclude, Universe.id == UniverseInclude.included_universe_id)
                .where(UniverseInclude.universe_id == universe_id, Universe.enabled.is_(True))
            ).scalars())
            for row in rows:
                session.expunge(row)
            return rows

    def list_market_instruments(self, market: str) -> list[Instrument]:
        with self.db.get_session() as session:
            rows = list(session.execute(
                select(Instrument).where(
                    Instrument.market == market,
                    Instrument.instrument_type == "STOCK",
                    Instrument.listing_status == "ACTIVE",
                ).order_by(Instrument.code)
            ).scalars())
            for row in rows:
                session.expunge(row)
            return rows

    def replace_members(self, key: str, instruments: Iterable[dict[str, Any]], source: str) -> int:
        return self.replace_members_with_stats(key, instruments, source).total

    def replace_members_with_stats(
        self, key: str, instruments: Iterable[dict[str, Any]], source: str
    ) -> MembershipSyncStats:
        records = list(instruments)
        with self.db.session_scope() as session:
            universe = session.execute(select(Universe).where(Universe.key == key)).scalar_one()
            codes = {str(item["code"]).upper() for item in records}
            ids = dict(session.execute(select(Instrument.code, Instrument.id).where(Instrument.code.in_(codes))).all())
            missing = sorted(codes - set(ids))
            if missing:
                raise ValueError(f"Universe instruments are not registered: {', '.join(missing[:10])}")
            existing = dict(
                session.execute(
                    select(Instrument.code, UniverseMember.id)
                    .join(UniverseMember, UniverseMember.instrument_id == Instrument.id)
                    .where(UniverseMember.universe_id == universe.id)
                ).all()
            )
            stale_codes = set(existing) - codes
            if stale_codes:
                session.execute(
                    delete(UniverseMember).where(
                        UniverseMember.id.in_([existing[code] for code in stale_codes])
                    )
                )
            inserted = 0
            for item in records:
                code = str(item["code"]).upper()
                if code in existing:
                    session.execute(
                        update(UniverseMember)
                        .where(UniverseMember.id == existing[code])
                        .values(source=source, member_metadata=item.get("metadata", {}))
                    )
                    continue
                session.add(
                    UniverseMember(
                        universe_id=universe.id,
                        instrument_id=ids[code],
                        source=source,
                        member_metadata=item.get("metadata", {}),
                    )
                )
                inserted += 1
        return MembershipSyncStats(inserted=inserted, deleted=len(stale_codes), total=len(codes))


class UniverseResolver:
    def __init__(self, repository: UniverseRepository | None = None):
        self.repository = repository or UniverseRepository()

    def resolve_universe(self, key: str) -> tuple[Instrument, ...]:
        resolved = self._resolve(key, path=())
        return tuple(resolved[code] for code in sorted(resolved))

    def _resolve(self, key: str, path: tuple[str, ...]) -> dict[str, Instrument]:
        if key in path:
            raise UniverseCycleError(f"Universe include cycle: {' -> '.join((*path, key))}")
        universe = self.repository.get_by_key(key)
        if universe is None or not universe.enabled:
            raise ValueError(f"Enabled universe not found: {key}")
        if universe.universe_type == "MARKET":
            members = self.repository.list_market_instruments(universe.market)
        else:
            members = [member.instrument for member in self.repository.list_members(universe.id)]
        resolved = {item.code: item for item in members}
        for child in self.repository.list_included_universes(universe.id):
            resolved.update(self._resolve(child.key, (*path, key)))
        return resolved


__all__ = ["MembershipSyncStats", "UniverseCycleError", "UniverseRepository", "UniverseResolver"]
