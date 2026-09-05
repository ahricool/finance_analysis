"""Current US index constituents from the maintained Wikipedia index tables."""

from __future__ import annotations

from io import StringIO
from typing import Any

import pandas as pd
import requests

from finance_analysis.integrations.market_data.normalizer import canonical_symbol


class USIndexConstituentProvider:
    """Small reference-data provider; it is not part of daily-bar routing."""

    name = "wikipedia"
    URLS = {
        "SP500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "NASDAQ100": "https://en.wikipedia.org/wiki/Nasdaq-100",
    }

    def __init__(self, *, timeout: float = 30.0, session: Any = None) -> None:
        self.timeout = timeout
        self.session = session or requests.Session()

    def fetch_index_members(self, index_code: str) -> list[dict[str, Any]]:
        key = str(index_code).strip().upper()
        if key not in self.URLS:
            raise ValueError(f"Unsupported US index: {index_code}")
        response = self.session.get(
            self.URLS[key],
            timeout=self.timeout,
            headers={"User-Agent": "finance-analysis reference-data-sync"},
        )
        response.raise_for_status()
        tables = pd.read_html(StringIO(response.text))
        symbol_columns = ("Symbol", "Ticker")
        name_columns = ("Security", "Company")
        table = next(
            (frame for frame in tables if any(column in frame.columns for column in symbol_columns)),
            None,
        )
        if table is None:
            raise ValueError(f"No constituent table found for {key}")
        symbol_column = next(column for column in symbol_columns if column in table.columns)
        name_column = next((column for column in name_columns if column in table.columns), None)
        records: list[dict[str, Any]] = []
        for row in table.to_dict("records"):
            native = str(row.get(symbol_column) or "").strip().upper().replace("/", ".")
            if not native:
                continue
            code = canonical_symbol(native, "US")
            records.append(
                {
                    "market": "US",
                    "code": code,
                    "native_code": native,
                    "name": str(row.get(name_column) or code).strip(),
                    "instrument_type": "STOCK",
                    "currency": "USD",
                    "listing_status": "ACTIVE",
                    "source": "WIKIPEDIA",
                    "metadata": {"index_source": self.URLS[key]},
                }
            )
        return records


__all__ = ["USIndexConstituentProvider"]
