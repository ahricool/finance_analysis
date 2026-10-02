"""Short database transactions around external calls, append-only successful versions."""

from datetime import timedelta
from sqlalchemy import select
from finance_analysis.core.time import utc_now
from finance_analysis.database.models.market_calendar import FinanceEvent
from finance_analysis.database.models.earnings_outlook import EarningsResearch, EarningsPrediction, EarningsOutlookState
from finance_analysis.database.session import DatabaseManager
from finance_analysis.earnings_outlook.rules import digest, schedule, timestamp
from finance_analysis.earnings_outlook.facts import has_actual
from finance_analysis.tasks.advisory_lock import PostgreSQLAdvisoryLock


class EarningsOutlookRepository:
    def __init__(self, db=None):
        self.db = db or DatabaseManager.get_instance()

    def lock(self, event_id):
        return PostgreSQLAdvisoryLock(event_id, db_manager=self.db, namespace=20_261_002)

    def slot(self, number):
        return PostgreSQLAdvisoryLock(number, db_manager=self.db, namespace=20_261_003)

    def event(self, event_id):
        with self.db.get_session() as s:
            row = s.get(FinanceEvent, event_id)
            if row:
                s.expunge(row)
            return row

    def events(self, start, end):
        with self.db.get_session() as s:
            rows = list(
                s.scalars(
                    select(FinanceEvent)
                    .where(
                        FinanceEvent.calendar_type == "earnings",
                        FinanceEvent.market == "US",
                        FinanceEvent.event_date.between(start, end),
                    )
                    .order_by(FinanceEvent.event_date, FinanceEvent.id)
                )
            )
            for row in rows:
                s.expunge(row)
            return rows

    def history_events(self, symbol, before):
        with self.db.get_session() as s:
            rows = s.scalars(
                select(FinanceEvent)
                .where(
                    FinanceEvent.symbol == symbol,
                    FinanceEvent.calendar_type == "earnings",
                    FinanceEvent.event_date < before,
                    FinanceEvent.reported_eps.is_not(None),
                )
                .order_by(FinanceEvent.event_date.desc())
                .limit(4)
            )
            return [
                dict(
                    quarter=r.reporting_period,
                    date=str(r.event_date),
                    eps=r.reported_eps,
                    eps_estimate=r.eps_estimate,
                    currency=r.currency,
                    basis=None,
                )
                for r in rows
            ]

    def market_context(self, now):
        from finance_analysis.database.models.market_structure import MarketStructureSnapshot

        with self.db.get_session() as s:
            row = s.scalar(
                select(MarketStructureSnapshot)
                .where(MarketStructureSnapshot.market == "US", MarketStructureSnapshot.created_at <= now)
                .order_by(MarketStructureSnapshot.trade_date.desc())
                .limit(1)
            )
            structure = dict(date=str(row.trade_date), metrics=row.metrics_json) if row else None
            macros = list(
                s.scalars(
                    select(FinanceEvent)
                    .where(
                        FinanceEvent.calendar_type == "macro",
                        FinanceEvent.event_date.between(now.date(), now.date() + timedelta(days=7)),
                        FinanceEvent.first_seen_at <= now,
                    )
                    .limit(30)
                )
            )
            return dict(
                market_structure=structure,
                macro_events=[dict(title=e.title, date=str(e.event_date)) for e in macros],
                sector=None,
                sector_missing_reason="无可靠证券到行业基准映射",
            )

    def cached_research(self, event_id, cache_key, now):
        with self.db.get_session() as s:
            row = s.scalar(
                select(EarningsResearch)
                .where(
                    EarningsResearch.event_id == event_id,
                    EarningsResearch.cache_key == cache_key,
                    EarningsResearch.expires_at > now,
                )
                .order_by(EarningsResearch.id.desc())
                .limit(1)
            )
            if row:
                s.expunge(row)
            return row

    def save_research(self, **values):
        def write(s):
            row = EarningsResearch(**values)
            s.add(row)
            s.flush()
            s.expunge(row)
            return row

        return self.db._run_write_transaction("earnings.research", write)

    def state(self, event_id):
        with self.db.get_session() as s:
            row = s.get(EarningsOutlookState, event_id)
            if row:
                s.expunge(row)
            return row

    def mark(self, event_id, status, error=None, **values):
        def write(s):
            row = s.get(EarningsOutlookState, event_id)
            if row is None:
                row = EarningsOutlookState(event_id=event_id, summary={})
                s.add(row)
            row.status, row.error, row.updated_at = status, error, utc_now()
            for key, value in values.items():
                setattr(row, key, value)

        self.db._run_write_transaction("earnings.state", write)

    def completed(self, event_id, stage, day, schedule_hash, research_id):
        with self.db.get_session() as s:
            rows = s.scalars(
                select(EarningsPrediction)
                .where(
                    EarningsPrediction.event_id == event_id,
                    EarningsPrediction.stage == stage,
                    EarningsPrediction.schedule_hash == schedule_hash,
                    EarningsPrediction.research_id == research_id,
                )
                .order_by(EarningsPrediction.id.desc())
                .limit(1)
            )
            return next((r for r in rows if r.context.get("run_date") == str(day)), None)

    def find_input(self, event_id, stage, input_hash):
        with self.db.get_session() as s:
            return s.scalar(
                select(EarningsPrediction.id).where(
                    EarningsPrediction.event_id == event_id,
                    EarningsPrediction.stage == stage,
                    EarningsPrediction.input_hash == input_hash,
                )
            )

    def save_prediction(self, summary, **values):
        def write(s):
            event = s.get(FinanceEvent, values["event_id"], with_for_update=True)
            if digest(schedule(event)) != values["schedule_hash"] or has_actual(event):
                raise ValueError("Event changed or reported during research")
            if utc_now() >= values["release_cutoff"]:
                raise ValueError("Release cutoff passed during research")
            row = s.scalar(
                select(EarningsPrediction).where(
                    EarningsPrediction.event_id == values["event_id"],
                    EarningsPrediction.stage == values["stage"],
                    EarningsPrediction.input_hash == values["input_hash"],
                )
            )
            if row is None:
                row = EarningsPrediction(**values)
                s.add(row)
                s.flush()
            state = s.get(EarningsOutlookState, row.event_id)
            if state is None:
                state = EarningsOutlookState(event_id=row.event_id)
                s.add(state)
            state.latest_prediction_id, state.status, state.error = row.id, "success", None
            state.schedule_hash, state.summary = row.schedule_hash, {**summary, "prediction_id": row.id}
            state.updated_at = utc_now()
            return row.id

        return self.db._run_write_transaction("earnings.predict", write)

    def detail(self, event_id):
        with self.db.get_session() as s:
            versions = list(
                s.scalars(
                    select(EarningsPrediction)
                    .where(EarningsPrediction.event_id == event_id)
                    .order_by(EarningsPrediction.id.desc())
                    .limit(100)
                )
            )
            research = (
                {
                    r.id: r
                    for r in s.scalars(
                        select(EarningsResearch).where(EarningsResearch.id.in_([v.research_id for v in versions]))
                    )
                }
                if versions
                else {}
            )
            state = s.get(EarningsOutlookState, event_id)
            return dict(
                status=state.status if state else "pending",
                error=state.error if state else None,
                actual=state.actual if state else None,
                versions=[
                    dict(
                        id=v.id,
                        stage=v.stage,
                        generated_at=v.created_at,
                        data_cutoff=v.data_cutoff,
                        release_cutoff=v.release_cutoff,
                        model=v.model,
                        backend=v.backend,
                        prompt_version=v.prompt_version,
                        schedule_hash=v.schedule_hash,
                        prediction=v.prediction,
                        context=v.context,
                        research=research[v.research_id].bundle,
                        search_evidence=research[v.research_id].search_evidence,
                    )
                    for v in versions
                ],
            )

    def pending_reviews(self):
        with self.db.get_session() as s:
            rows = list(
                s.scalars(
                    select(EarningsPrediction)
                    .join(EarningsOutlookState, EarningsOutlookState.latest_prediction_id == EarningsPrediction.id)
                    .where(EarningsPrediction.release_cutoff <= utc_now())
                )
            )
            for row in rows:
                s.expunge(row)
            return rows

    @staticmethod
    def summaries(session, events, members, now):
        ids = [e.id for e in events if e.market == "US" and e.calendar_type == "earnings"]
        states = (
            {
                s.event_id: s
                for s in session.scalars(select(EarningsOutlookState).where(EarningsOutlookState.event_id.in_(ids)))
            }
            if ids
            else {}
        )
        return {e.id: display_summary(e, states.get(e.id), members, now) for e in events if e.id in ids}


def display_summary(event, state, members, now):
    member = members.get(event.symbol)
    if not member:
        return None
    if not state or not state.latest_prediction_id:
        return dict(
            status=state.status if state else "pending",
            memberships=member["memberships"],
            earnings_high=False,
            reaction_high=False,
        )
    value = {**state.summary, "memberships": member["memberships"], "last_error": state.error}
    if state.schedule_hash != digest(schedule(event)):
        return dict(status="superseded", memberships=member["memberships"], earnings_high=False, reaction_high=False)
    status = "current"
    if has_actual(event) or now >= timestamp(value["release_cutoff"]) or state.status == "frozen":
        status = "frozen"
    elif now >= timestamp(value["expires_at"]):
        status = "stale"
    value["status"] = status
    value["earnings_high"] = status == "current" and bool(value.get("earnings_high"))
    value["reaction_high"] = status == "current" and bool(value.get("reaction_high"))
    return value
