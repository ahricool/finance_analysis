"""Atomic batch persistence; initial event evidence and daily metrics never take future OI."""

import hashlib
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select, or_
from finance_analysis.core.time import coerce_aware_utc
from finance_analysis.database.models.options_intelligence import (
    OptionContract,
    OptionQuoteSnapshot,
    OptionDailyMetrics,
    OptionAnomalyEvent,
    OptionAnalysis,
)
from finance_analysis.integrations.options.models import OptionObservation


class OptionsRepository:
    def __init__(self, db=None):
        if db is None:
            from finance_analysis.database.session import DatabaseManager

            db = DatabaseManager.get_instance()
        self.db = db

    def monitored_symbols(self, uid=None):
        from finance_analysis.database.models import Instrument, Universe, UniverseMember, WatchListItem

        with self.db.get_session() as session:
            constituents = (
                select(Instrument.code)
                .join(UniverseMember, UniverseMember.instrument_id == Instrument.id)
                .join(Universe, Universe.id == UniverseMember.universe_id)
                .where(
                    Universe.key == "us_nasdaq100",
                    Universe.enabled.is_(True),
                    Instrument.market == "US",
                    Instrument.listing_status == "ACTIVE",
                    Instrument.instrument_type == "STOCK",
                )
            )
            watches = select(WatchListItem.code).where(WatchListItem.market_type == "US")
            if uid is not None:
                watches = watches.where(WatchListItem.uid == uid)
            symbols = set(session.scalars(constituents)) | set(session.scalars(watches))
            return sorted({s.upper() if s.upper().endswith(".US") else s.upper() + ".US" for s in symbols})

    def dates(self, symbols, uid=None):
        with self.db.get_session() as session:
            dates = set(
                session.scalars(
                    select(OptionDailyMetrics.trade_date)
                    .where(OptionDailyMetrics.symbol.in_(symbols))
                    .distinct()
                    .order_by(OptionDailyMetrics.trade_date.desc())
                )
            )
            # A failed-only date must remain selectable even without any daily snapshots.
            for result in self._scan_task_results(session, uid):
                if any(row.get("symbol") in symbols for row in result.get("results", [])):
                    dates.add(date.fromisoformat(result["trade_date"]))
            return sorted(dates, reverse=True)

    def history(self, symbol, before, lookback, mode=None):
        with self.db.get_session() as session:
            rows = session.scalars(
                select(OptionQuoteSnapshot)
                .where(
                    OptionQuoteSnapshot.symbol == symbol,
                    OptionQuoteSnapshot.trade_date < before,
                    OptionQuoteSnapshot.trade_date >= before - timedelta(days=lookback),
                    *([OptionQuoteSnapshot.mode == mode] if mode else []),
                    *([OptionQuoteSnapshot.id.in_(select(OptionDailyMetrics.snapshot_id))] if mode == "daily" else []),
                )
                .order_by(OptionQuoteSnapshot.trade_date, OptionQuoteSnapshot.bucket)
            ).all()
            return [
                {
                    "trade_date": r.trade_date,
                    "mode": r.mode,
                    "observed_at": coerce_aware_utc(r.observed_at),
                    "metrics": r.metrics,
                    "rows": [OptionObservation.model_validate(v) for v in r.payload["observations"]],
                }
                for r in rows
            ]

    @staticmethod
    def _metrics_view(row):
        raw = {(v["symbol"], v["data_source"], v["feed_type"]): v for v in row.payload["observations"]}
        return {
            **row.metrics,
            "contracts": [
                {**raw.get((v["symbol"], v["data_source"], v["feed_type"]), {}), **v} for v in row.metrics["contracts"]
            ],
        }

    def latest(self, symbol, trade_date=None):
        with self.db.get_session() as session:
            row = session.scalars(
                select(OptionQuoteSnapshot)
                .join(OptionDailyMetrics, OptionDailyMetrics.snapshot_id == OptionQuoteSnapshot.id)
                .where(
                    OptionQuoteSnapshot.symbol == symbol,
                    *([OptionDailyMetrics.trade_date == trade_date] if trade_date else []),
                )
                .order_by(OptionDailyMetrics.trade_date.desc())
                .limit(1)
            ).first()
            if row is None:
                return None
            analysis = session.scalar(select(OptionAnalysis).where(OptionAnalysis.snapshot_id == row.id))
            return {
                "snapshot_id": row.id,
                **self._metrics_view(row),
                "llm_analysis": analysis.explanation if analysis else None,
            }

    @staticmethod
    def _scan_task_results(session, uid, trade_date=None):
        from finance_analysis.database.models.task import TaskRecord

        query = (
            select(TaskRecord)
            .where(
                TaskRecord.task_type.in_(("options_intelligence", "scheduled_options_intelligence_daily")),
                TaskRecord.status.in_(("completed", "partial", "failed")),
                or_(TaskRecord.uid.is_(None), TaskRecord.uid == uid),
            )
            .order_by(TaskRecord.started_at.desc(), TaskRecord.id.desc())
        )
        if trade_date is not None:
            start = datetime.combine(trade_date, datetime.min.time(), ZoneInfo("America/New_York"))
            end = datetime.combine(trade_date + timedelta(days=1), datetime.min.time(), start.tzinfo)
            query = query.where(
                TaskRecord.started_at >= coerce_aware_utc(start), TaskRecord.started_at < coerce_aware_utc(end)
            )
        else:
            query = query.limit(200)  # Bounded discovery of recent failed-only dates.
        for record in session.scalars(query):
            try:
                result = json.loads(record.result or "null")
                if not isinstance(result, dict) or result.get("view") != "official" or record.started_at is None:
                    continue
                day = date.fromisoformat(result.get("trade_date", ""))
            except (ValueError, TypeError):
                continue
            if day != coerce_aware_utc(record.started_at).astimezone(ZoneInfo("America/New_York")).date():
                continue
            if trade_date is None or day == trade_date:
                yield result

    def scan_failures(self, symbols, trade_date, uid=None):
        """Only explicit, same-session outcomes from public or this user's tasks."""
        if trade_date is None:
            return {}
        outcomes = {}
        with self.db.get_session() as session:
            for result in self._scan_task_results(session, uid, trade_date):
                # Lifecycle summaries can truncate results; absent entries are unknown.
                for row in result.get("results", []):
                    symbol = row.get("symbol")
                    if symbol in symbols and symbol not in outcomes:
                        outcomes[symbol] = row
        return {
            symbol: row.get("reason", "期权采集失败")
            for symbol, row in outcomes.items()
            if row.get("status") == "failed"
        }

    def scan_task_summary(self, trade_date, uid=None):
        if trade_date is None:
            return None
        with self.db.get_session() as session:
            for result in self._scan_task_results(session, uid, trade_date):
                if "failed_count" in result and "total_count" in result:
                    return {"failed_count": result["failed_count"], "total_count": result["total_count"]}
        return None

    def scan(self, symbols, trade_date=None, uid=None):
        # A single official date for every row; never mix failed symbols' older sessions into it.
        if trade_date is None:
            dates = self.dates(symbols, uid=uid)
            trade_date = dates[0] if dates else None
        failures = self.scan_failures(symbols, trade_date, uid)
        with self.db.get_session() as session:
            rows = session.scalars(
                select(OptionDailyMetrics).where(
                    OptionDailyMetrics.symbol.in_(symbols), OptionDailyMetrics.trade_date == trade_date
                )
            ).all()
            # Daily metrics omit contracts: listing 100 stocks must not load every raw chain.
            found = {r.symbol: r.metrics for r in rows}
            return [
                found.get(
                    symbol,
                    {
                        "symbol": symbol,
                        "status": "failed" if symbol in failures else "not_scanned",
                        "failure_source": "TaskRecord" if symbol in failures else None,
                        "scores": None,
                        "limitations": (
                            [failures[symbol]] if symbol in failures else ["无正式快照或可确认的逐股失败记录"]
                        ),
                    },
                )
                for symbol in symbols
            ]

    def save(self, chain, metrics, bucket, mode):
        if mode != "daily":
            raise ValueError("Only daily options results may be persisted")
        payload = chain.model_dump(mode="json")
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        trade_date = date.fromisoformat(metrics["trade_date"])
        with self.db.session_scope() as session:
            existing = session.scalar(
                select(OptionQuoteSnapshot).where(
                    OptionQuoteSnapshot.symbol == chain.symbol,
                    OptionQuoteSnapshot.bucket == bucket,
                    OptionQuoteSnapshot.mode == mode,
                )
            )
            if existing:
                return existing.id
            contracts = {
                row.symbol: row
                for row in session.scalars(
                    select(OptionContract).where(OptionContract.symbol.in_({r.symbol for r in chain.observations}))
                )
            }
            for row in chain.observations:
                if row.symbol not in contracts:
                    contract = OptionContract(
                        **row.model_dump(
                            include={
                                "symbol",
                                "underlying_symbol",
                                "option_type",
                                "expiration",
                                "strike",
                                "multiplier",
                            }
                        )
                    )
                    session.add(contract)
                    contracts[row.symbol] = contract
                elif contracts[row.symbol].multiplier is None and row.multiplier is not None:
                    contracts[row.symbol].multiplier = row.multiplier
            # Raw observations are stored once. Metrics keep only contract IDs and derived evidence.
            raw_fields = set(OptionObservation.model_fields) - {"symbol", "data_source", "feed_type"}
            compact_metrics = {
                **metrics,
                "contracts": [{k: v for k, v in row.items() if k not in raw_fields} for row in metrics["contracts"]],
            }
            snapshot = OptionQuoteSnapshot(
                symbol=chain.symbol,
                trade_date=trade_date,
                bucket=bucket,
                mode=mode,
                observed_at=chain.observed_at,
                payload=payload,
                metrics=compact_metrics,
                fingerprint=fingerprint,
            )
            session.add(snapshot)
            session.flush()
            if (
                mode == "daily"
                and session.scalar(
                    select(OptionDailyMetrics.id).where(
                        OptionDailyMetrics.symbol == chain.symbol, OptionDailyMetrics.trade_date == trade_date
                    )
                )
                is None
            ):
                session.add(
                    OptionDailyMetrics(
                        symbol=chain.symbol,
                        trade_date=trade_date,
                        snapshot_id=snapshot.id,
                        metrics={k: v for k, v in metrics.items() if k != "contracts"},
                    )
                )
            known_at = datetime.fromisoformat(metrics["computed_at"])
            self._events(session, chain.symbol, trade_date, known_at, metrics)
            for contract in metrics["contracts"]:
                oi = contract.get("oi_change")
                if not oi:
                    continue
                related = session.scalars(
                    select(OptionAnomalyEvent).where(
                        OptionAnomalyEvent.symbol == chain.symbol,
                        OptionAnomalyEvent.contract_symbol == contract["symbol"],
                        OptionAnomalyEvent.trade_date == date.fromisoformat(oi["oi_date"]),
                        OptionAnomalyEvent.event_type != "OI_BUILDUP_CONFIRMED",
                    )
                ).all()
                for event in related:
                    if coerce_aware_utc(event.occurred_at) < known_at and not event.validation.get("oi_confirmation"):
                        event.validation = {
                            **event.validation,
                            "oi_confirmation": oi,
                            "status": "net_oi_increased" if oi["change"] > 0 else "no_net_oi_increase",
                            "meaning": "net_OI_change_not_direction_or_realtime_opening",
                        }
            return snapshot.id

    @staticmethod
    def _events(session, symbol, day, now, metrics):
        for evidence in metrics["events"]:
            keys = {
                "symbol": symbol,
                "contract_symbol": evidence["contract_symbol"],
                "event_type": evidence["event_type"],
                "trade_date": day,
                "data_source": evidence["source"],
                "feed_type": evidence["feed_type"],
            }
            row = session.scalar(select(OptionAnomalyEvent).filter_by(**keys))
            evidence = {
                **evidence,
                "known_at": now.isoformat(),
                "underlying_price": metrics["underlying_price"],
                "scores": metrics["scores"],
                "rv_20d": metrics.get("rv_20d"),
            }
            if row is None:
                row = OptionAnomalyEvent(
                    **keys,
                    occurred_at=now,
                    updated_at=now,
                    initial_evidence=evidence,
                    latest_evidence=evidence,
                    changes=[],
                    validation={},
                )
                session.add(row)
                session.flush()
            else:
                material = (
                    "value",
                    "severity",
                    "reference",
                    "evidence_grade",
                    "confidence",
                    "direction",
                    "explanation",
                )
                if any(row.latest_evidence.get(key) != evidence.get(key) for key in material):
                    row.changes = (
                        row.changes
                        + [
                            {
                                "known_at": now.isoformat(),
                                **{key: evidence.get(key) for key in material},
                            }
                        ]
                    )[-48:]
                row.latest_evidence, row.updated_at = evidence, now
            if evidence["event_type"] == "OI_BUILDUP_CONFIRMED":
                oi = evidence["reference"]
                related = session.scalars(
                    select(OptionAnomalyEvent).where(
                        OptionAnomalyEvent.symbol == symbol,
                        OptionAnomalyEvent.contract_symbol == evidence["contract_symbol"],
                        OptionAnomalyEvent.trade_date == date.fromisoformat(oi["oi_date"]),
                        OptionAnomalyEvent.event_type != "OI_BUILDUP_CONFIRMED",
                    )
                ).all()
                for prior in related:
                    if coerce_aware_utc(prior.occurred_at) < now:
                        prior.validation = {
                            **prior.validation,
                            "oi_confirmation": oi,
                            "meaning": "net_OI_increase_not_direction_or_realtime_opening",
                        }

    def events(self, symbol, limit=100, through=None):
        with self.db.get_session() as session:
            return [
                {c.name: getattr(row, c.name) for c in OptionAnomalyEvent.__table__.columns}
                for row in session.scalars(
                    select(OptionAnomalyEvent)
                    .where(
                        OptionAnomalyEvent.symbol == symbol,
                        *([OptionAnomalyEvent.trade_date <= through] if through else []),
                    )
                    .order_by(OptionAnomalyEvent.occurred_at.desc(), OptionAnomalyEvent.id.desc())
                    .limit(limit)
                )
            ]

    def daily(self, symbol, limit=120, through=None):
        with self.db.get_session() as session:
            return [
                r.metrics
                for r in session.scalars(
                    select(OptionDailyMetrics)
                    .where(
                        OptionDailyMetrics.symbol == symbol,
                        *([OptionDailyMetrics.trade_date <= through] if through else []),
                    )
                    .order_by(OptionDailyMetrics.trade_date.desc())
                    .limit(limit)
                )
            ][::-1]

    def save_analysis(self, snapshot_id, explanation, result, prompt):
        with self.db.session_scope() as session:
            if session.scalar(select(OptionAnalysis.id).where(OptionAnalysis.snapshot_id == snapshot_id)) is None:
                session.add(
                    OptionAnalysis(
                        snapshot_id=snapshot_id,
                        explanation=explanation,
                        model=result.model,
                        prompt=prompt,
                        raw_response=result.text,
                    )
                )

    def analysis_history(self, symbol, through=None):
        with self.db.get_session() as session:
            return [
                {"created_at": row.created_at, "trade_date": day, "explanation": row.explanation, "model": row.model}
                for row, day in session.execute(
                    select(OptionAnalysis, OptionQuoteSnapshot.trade_date)
                    .join(OptionQuoteSnapshot)
                    .where(
                        OptionQuoteSnapshot.symbol == symbol,
                        *([OptionQuoteSnapshot.trade_date <= through] if through else []),
                    )
                    .order_by(OptionAnalysis.created_at.desc())
                    .limit(30)
                )
            ]

    def context(self, symbol, now):
        from finance_analysis.database.models import NewsIntel, NewsIntelUsage, FinanceEvent

        with self.db.get_session() as session:
            news = session.scalars(
                select(NewsIntel)
                .join(NewsIntelUsage)
                .where(
                    NewsIntelUsage.symbol == symbol,
                    NewsIntel.published_date <= now,
                    NewsIntel.published_date >= now - timedelta(days=7),
                    NewsIntel.fetched_at <= now,
                    NewsIntel.provider == "longbridge",
                )
                .distinct()
                .order_by(NewsIntel.published_date.desc())
                .limit(10)
            )
            events = session.scalars(
                select(FinanceEvent)
                .where(
                    FinanceEvent.symbol == symbol,
                    FinanceEvent.first_seen_at <= now,
                    FinanceEvent.event_date >= now.date() - timedelta(days=7),
                    FinanceEvent.event_date <= now.date() + timedelta(days=30),
                )
                .limit(10)
            )
            return {
                "news": [{"title": r.title, "url": r.url, "published_at": r.published_date.isoformat()} for r in news],
                "calendar": [
                    {"title": r.title, "date": r.event_date.isoformat(), "type": r.calendar_type} for r in events
                ],
            }
