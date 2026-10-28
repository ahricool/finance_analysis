"""Atomic latest-only preview replacement and bounded read projections."""

from copy import deepcopy

from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from finance_analysis.core.time import coerce_aware_utc, ensure_aware_utc, utc_now
from finance_analysis.database.models.research_preview import ResearchPreview, ResearchPreviewItem
from finance_analysis.database.models.stock import Instrument


class PreviewRepository:
    def __init__(self, db_manager=None):
        if db_manager is None:
            from finance_analysis.database.session import DatabaseManager

            db_manager = DatabaseManager.get_instance()
        self.db = db_manager

    @staticmethod
    def _scope(model, namespace, market, variant):
        return (model.namespace == namespace, model.market == market, model.variant == variant)

    def publish(self, namespace, market, variant, header, items, *, observed_at, expires_at,
                shared=None, merge=False, remove_keys=(), merge_header=None):
        """Writers serialize on the batch; deletion and insertion commit together.

        Merge is only for incremental options checkpoints: a symbol has exactly one
        row, failed symbols are deleted, and a new session always replaces everything.
        """
        batch, item = ResearchPreview, ResearchPreviewItem
        observed_at, expires_at = ensure_aware_utc(observed_at), ensure_aware_utc(expires_at)
        scope = dict(namespace=namespace, market=market, variant=variant)
        values = dict(**scope, header=header, shared=shared or {}, observed_at=observed_at, expires_at=expires_at)
        with self.db.session_scope() as session:
            dialect_insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
            session.execute(dialect_insert(batch).values(**values).on_conflict_do_nothing())
            current = session.execute(select(batch).where(*self._scope(batch, **scope)).with_for_update()).scalar_one()
            if coerce_aware_utc(current.observed_at) > observed_at:
                return False
            if (current.header.get("trade_date") and header.get("trade_date")
                    and current.header["trade_date"] > header["trade_date"]):
                return False
            same_session = current.header.get("trade_date") == header.get("trade_date")
            merge = merge and same_session and coerce_aware_utc(current.expires_at) > observed_at
            if merge and merge_header:
                header = merge_header(deepcopy(current.header), deepcopy(header))
            deletion = delete(item).where(*self._scope(item, **scope))
            if merge:
                keys = {row["item_key"] for row in items} | set(remove_keys)
                deletion = deletion.where(item.item_key.in_(keys))
            session.execute(deletion)
            # One lookup for the whole batch; names belong to the security master.
            codes = {row["summary"].get("code") for row in items if "name" in row["summary"]}
            instruments = dict(session.execute(select(Instrument.code, Instrument.id).where(
                Instrument.market == market, Instrument.code.in_(codes - {None}),
            )).all()) if codes else {}
            stored = []
            for position, row in enumerate(items):
                summary = deepcopy(row["summary"])
                instrument_id = instruments.get(summary.get("code"))
                has_name = instrument_id is not None and "name" in summary
                if has_name:
                    summary.pop("name")
                stored.append(dict(
                    **scope, kind=row["kind"], item_key=row["item_key"], position=position,
                    instrument_id=instrument_id, has_name=has_name, summary=summary, detail=row.get("detail", {}),
                ))
            if stored:
                session.execute(insert(item), stored)
            current.header, current.shared = header, shared or {}
            current.observed_at, current.expires_at = observed_at, expires_at
        return True

    def read(self, namespace, market, variant=0, *, kind=None, item_key=None, view="full", now=None):
        """Hold a shared batch lock so two bounded SELECTs see one publication."""
        batch, item = ResearchPreview, ResearchPreviewItem
        now = ensure_aware_utc(now or utc_now())
        scope = dict(namespace=namespace, market=market, variant=variant)
        with self.db.get_session() as session:
            current = session.execute(select(batch).where(
                *self._scope(batch, **scope), batch.expires_at > now,
            ).with_for_update(read=True)).scalar_one_or_none()
            if current is None:
                return None
            result = {"header": deepcopy(current.header), "shared": deepcopy(current.shared), "items": []}
            if view == "header":
                return result
            columns = [item.kind, item.item_key, item.has_name, Instrument.name.label("instrument_name")]
            if view == "states":
                columns.extend(item.summary[key].as_string().label(key) for key in ("code", "name", "state"))
                columns.append(item.summary["rank"].as_integer().label("rank"))
                columns.extend(item.summary[key].as_float().label(key) for key in ("alpha_score", "fragility_score"))
            else:
                columns.append(item.summary)
            if view == "full":
                columns.append(item.detail)
            query = select(*columns).outerjoin(Instrument, Instrument.id == item.instrument_id).where(
                *self._scope(item, **scope),
            ).order_by(item.position, item.item_key)
            if kind is not None:
                query = query.where(item.kind == kind)
            if item_key is not None:
                query = query.where(item.item_key == item_key)
            for row in session.execute(query).mappings():
                data = ({key: row[key] for key in ("code", "name", "state", "rank", "alpha_score", "fragility_score")}
                        if view == "states" else deepcopy(row["summary"]))
                if view == "states":
                    # An absent scalar may have been factored into the shared batch.
                    data = {key: value for key, value in data.items() if value is not None}
                if row["has_name"]:
                    data["name"] = row["instrument_name"] or data.get("code") or row["item_key"]
                result["items"].append({
                    "kind": row["kind"], "item_key": row["item_key"], "summary": data,
                    "detail": deepcopy(row.get("detail", {})),
                })
            return result
