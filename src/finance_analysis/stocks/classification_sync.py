"""Weekly US industry reference maintenance, separate from volatile market snapshots."""

from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.stock import InstrumentRepository
from finance_analysis.integrations.market_data.service import MarketDataService


class USClassificationSyncService:
    def __init__(self, repository=None, market_data=None):
        self.repository = repository or InstrumentRepository()
        self.market_data = market_data or MarketDataService()

    def run(self):
        rows = self.market_data.get_stock_classifications("US")
        observed_at = utc_now()
        saved = self.repository.save_us_classifications(rows, observed_at)
        return {"source": "yfinance", "fetched": len(rows), "saved": saved, "observed_at": observed_at.isoformat()}
