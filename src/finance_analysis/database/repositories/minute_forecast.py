"""Shared symbol opt-ins; a missing row is always disabled."""

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from finance_analysis.database.models.minute_forecast import MinuteForecastPreference
from finance_analysis.database.session import DatabaseManager


class MinuteForecastPreferences:
    def __init__(self, db=None):
        self.db = db or DatabaseManager.get_instance()

    def enabled(self, symbol: str) -> bool:
        with self.db.get_session() as session:
            return session.get(MinuteForecastPreference, symbol) is not None

    def set_enabled(self, symbol: str, enabled: bool) -> bool:
        with self.db.session_scope() as session:
            if enabled:
                session.execute(
                    insert(MinuteForecastPreference).values(symbol=symbol).on_conflict_do_nothing()
                )
            else:
                session.execute(delete(MinuteForecastPreference).where(
                    MinuteForecastPreference.symbol == symbol,
                ))
        return enabled

    def enabled_symbols(self) -> set[str]:
        with self.db.get_session() as session:
            return set(session.scalars(select(MinuteForecastPreference.symbol)))
