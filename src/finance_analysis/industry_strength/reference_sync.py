"""Explicit weekly maintenance of the complete industry reference generation."""

import logging
from time import monotonic

from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.industry_strength import IndustryStrengthRepository
from finance_analysis.integrations.market_data.service import MarketDataService

logger = logging.getLogger(__name__)


class IndustryReferenceSyncService:
    def __init__(self, repository=None, market_data=None):
        self.repository = repository or IndustryStrengthRepository()
        self.market_data = market_data or MarketDataService()

    def run(self):
        started = monotonic()
        catalog = self.market_data.get_industry_catalog()
        if not catalog:
            raise ValueError("Industry catalog is empty; previous reference retained")
        memberships = {}
        for item in catalog:
            code = item["thscode"]
            memberships[code] = self.market_data.get_index_constituents(code)
            if not memberships[code]:
                raise ValueError(f"Industry {code} has no members; previous reference retained")
        observed_at = utc_now()
        self.repository.save_reference(catalog, memberships, observed_at)
        logger.info("Industry reference synchronized industries=%s unique_stocks=%s elapsed_seconds=%.3f",
                    len(catalog), len({m["thscode"] for rows in memberships.values() for m in rows}),
                    monotonic() - started)
        return {"status": "completed", "industries": len(catalog), "observed_at": observed_at.isoformat()}
