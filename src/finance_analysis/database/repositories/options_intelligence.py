"""Atomic batch persistence; initial event evidence and daily metrics never take future OI."""

import hashlib
import json
from datetime import date, datetime, timedelta
from sqlalchemy import select, func
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

    def monitored_symbols(self, defaults, uid=None):
        from finance_analysis.database.models import PortfolioPosition, WatchListItem

        with self.db.get_session() as session:
            positions = select(PortfolioPosition.symbol).where(
                PortfolioPosition.market == "US", PortfolioPosition.quantity > 0
            )
            watches = select(WatchListItem.code).where(WatchListItem.market_type == "US")
            if uid is not None:
                positions, watches = positions.where(PortfolioPosition.uid == uid), watches.where(
                    WatchListItem.uid == uid
                )
            symbols = set(defaults) | set(session.scalars(positions)) | set(session.scalars(watches))
            return sorted(s if s.endswith(".US") else s + ".US" for s in symbols)

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

    def latest(self, symbol):
        with self.db.get_session() as session:
            row = session.scalars(
                select(OptionQuoteSnapshot)
                .where(OptionQuoteSnapshot.symbol == symbol)
                .order_by(OptionQuoteSnapshot.observed_at.desc(), OptionQuoteSnapshot.id.desc())
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

    def scan(self, symbols):
        # One latest-row query for the user's visible universe; never return someone else's membership.
        with self.db.get_session() as session:
            ranked = (
                select(
                    OptionQuoteSnapshot.id,
                    func.row_number()
                    .over(
                        partition_by=OptionQuoteSnapshot.symbol,
                        order_by=(OptionQuoteSnapshot.observed_at.desc(), OptionQuoteSnapshot.id.desc()),
                    )
                    .label("rank"),
                )
                .where(OptionQuoteSnapshot.symbol.in_(symbols))
                .subquery()
            )
            rows = session.scalars(
                select(OptionQuoteSnapshot)
                .join(ranked, ranked.c.id == OptionQuoteSnapshot.id)
                .where(ranked.c.rank == 1)
            ).all()
            found = {r.symbol: self._metrics_view(r) for r in rows}
            return [
                found.get(
                    symbol,
                    {
                        "symbol": symbol,
                        "status": "not_scanned",
                        "scores": None,
                        "limitations": ["尚未采集，请启动Worker/Beat或手动刷新"],
                    },
                )
                for symbol in symbols
            ]

    def save(self, chain, metrics, bucket, mode):
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

    def events(self, symbol, limit=100):
        with self.db.get_session() as session:
            return [
                {c.name: getattr(row, c.name) for c in OptionAnomalyEvent.__table__.columns}
                for row in session.scalars(
                    select(OptionAnomalyEvent)
                    .where(OptionAnomalyEvent.symbol == symbol)
                    .order_by(OptionAnomalyEvent.occurred_at.desc(), OptionAnomalyEvent.id.desc())
                    .limit(limit)
                )
            ]

    def daily(self, symbol, limit=120):
        with self.db.get_session() as session:
            return [
                r.metrics
                for r in session.scalars(
                    select(OptionDailyMetrics)
                    .where(OptionDailyMetrics.symbol == symbol)
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

    def analysis_history(self, symbol):
        with self.db.get_session() as session:
            return [
                {"created_at": row.created_at, "trade_date": day, "explanation": row.explanation, "model": row.model}
                for row, day in session.execute(
                    select(OptionAnalysis, OptionQuoteSnapshot.trade_date)
                    .join(OptionQuoteSnapshot)
                    .where(OptionQuoteSnapshot.symbol == symbol)
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
