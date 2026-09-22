"""One deadline for the three read-only data sources; return completed batches only."""

import logging
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from datetime import timedelta

from finance_analysis.integrations.market_data.bounded_requests import bounded_results
from finance_analysis.integrations.market_data.request_budget import request_budget, remaining_seconds
from . import config as c

logger = logging.getLogger(__name__)
_DATA_EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix="intraday-data")


def collect_data(market_data, codes, session, now):
    quote_provider, minute_provider = c.PROVIDERS[session.market]
    calls = {
        "quotes": partial(market_data.get_realtime_quotes, codes, providers=(quote_provider,)),
        "minute": partial(
            market_data.get_minute_bars, codes, session.opened, now, interval="5m", providers=(minute_provider,)
        ),
        "history": partial(
            market_data.get_daily_bars,
            codes,
            session.previous_date - timedelta(days=c.HISTORY_CALENDAR_DAYS),
            session.previous_date,
            adjustment="forward",
            source_policy="db_only",
        ),
    }

    def fetch(call):
        # Allow bounded providers to assemble their partial BatchResult before the
        # outer boundary stops waiting on SDKs which do not support cancellation.
        with request_budget(max(0, remaining_seconds() - c.MARKET_DATA_RETURN_RESERVE_SECONDS)):
            return call().data

    data = {key: {} for key in calls}
    with request_budget(c.MARKET_DATA_BUDGET_SECONDS):
        for key, value, error in bounded_results(
            {key: partial(fetch, call) for key, call in calls.items()}, _DATA_EXECUTOR, len(calls)
        ):
            if error is None:
                data[key] = value
            else:
                logger.warning("Intraday data source unavailable: source=%s error_type=%s", key, type(error).__name__)
    return data["quotes"], data["minute"], data["history"]
