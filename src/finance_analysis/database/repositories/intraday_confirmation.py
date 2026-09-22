"""Read only exact prior-session formal candidates. No live universe scanning."""

from sqlalchemy import select
from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.models.trend_following import TrendFollowingSnapshot
from finance_analysis.database.models.confluence import ConfluenceSnapshot
from finance_analysis.database.repositories.confluence import ConfluenceRepository, values
from finance_analysis.intraday_confirmation import config as c


class CandidateRepository:
    def __init__(self, db_manager=None):
        self.formal = ConfluenceRepository(db_manager)
        self.db = self.formal.db

    def candidates(self, market, day, cutoff):
        result = {}
        with self.db.get_session() as session:
            for model, source, condition in (
                (ConfluenceSnapshot, "confluence", ConfluenceSnapshot.strong_confluence.is_(True)),
                (TrendFollowingSnapshot, "trend", TrendFollowingSnapshot.state.in_(c.TREND_STATES)),
            ):
                rows = session.execute(
                    select(model, Instrument.code, Instrument.name)
                    .join(Instrument, Instrument.id == model.instrument_id)
                    .where(
                        model.market == market,
                        model.trade_date == day,
                        model.generated_at < cutoff,
                        Instrument.instrument_type == "STOCK",
                        Instrument.listing_status == "ACTIVE",
                        condition,
                    )
                ).all()
                rows.sort(
                    key=lambda r: (-(getattr(r[0], "confluence_score", None) or getattr(r[0], "alpha_score", 0)), r[1])
                )
                for row, code, name in rows:
                    result.setdefault(
                        code,
                        dict(
                            code=code,
                            name=name,
                            candidate_source=source,
                            candidate_trade_date=day,
                            candidate_reason=(row.reasons or [source]),
                            source_generated_at=row.generated_at,
                        ),
                    )
            # Reuse formal Quant publication/version selection, then enforce the exact day/cutoff.
            quant = [
                r
                for r in self.formal.quant(market, day)
                if r["trade_date"] == day
                and r["generated_at"] < cutoff
                and (
                    str(r["signal"]).lower() == "buy"
                    or (
                        str(r["signal"]).lower() in {"watch", "hold"}
                        and r["universe_rank"] is not None
                        and r["universe_rank"] <= c.QUANT_TOP
                    )
                )
            ]
            ids = [r["instrument_id"] for r in quant]
            instruments = (
                {
                    r.id: r
                    for r in session.scalars(
                        select(Instrument).where(
                            Instrument.id.in_(ids),
                            Instrument.market == market,
                            Instrument.instrument_type == "STOCK",
                            Instrument.listing_status == "ACTIVE",
                        )
                    )
                }
                if ids
                else {}
            )
            for row in sorted(quant, key=lambda r: (r["universe_rank"] or 100000, r["instrument_id"])):
                stock = instruments.get(row["instrument_id"])
                if stock:
                    result.setdefault(
                        stock.code,
                        dict(
                            code=stock.code,
                            name=stock.name,
                            candidate_source="quant",
                            candidate_trade_date=day,
                            candidate_reason=[f"Quant {row['signal']}，正式排名 {row['universe_rank']}"],
                            source_generated_at=row["generated_at"],
                        ),
                    )
            selected = list(result.values())[: c.MAX_CANDIDATES]
            codes = [r["code"] for r in selected]
            official = (
                {
                    r.code: values(
                        r,
                        "state trend_lifecycle trend_score fragility_score features " "trend_duration_days trade_date",
                    )
                    for r in session.scalars(
                        select(TrendFollowingSnapshot).where(
                            TrendFollowingSnapshot.market == market,
                            TrendFollowingSnapshot.trade_date == day,
                            TrendFollowingSnapshot.code.in_(codes),
                            TrendFollowingSnapshot.generated_at < cutoff,
                        )
                    )
                }
                if codes
                else {}
            )
        for row in selected:
            row["official_trend"] = official.get(row["code"])
        return selected
