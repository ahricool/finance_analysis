"""AkShare current CSI constituents: reference data only, never a quote provider."""

from typing import Any

from ..normalizer import canonical_symbol


class AkShareIndexConstituentProvider:
    def fetch_index_members(self, index_code: str) -> list[dict[str, Any]]:
        """Fetch current CSI constituents without membership history."""
        import akshare as ak

        frame = ak.index_stock_cons_csindex(symbol=str(index_code))
        records = []
        for row in frame.to_dict("records"):
            native = str(row.get("成分券代码") or row.get("品种代码") or row.get("code") or "").zfill(6)
            code = canonical_symbol(native, "CN")
            name = str(row.get("成分券名称") or row.get("品种名称") or row.get("name") or code).strip()
            records.append(
                {
                    "market": "CN",
                    "code": code,
                    "native_code": native,
                    "name": name,
                    "instrument_type": "STOCK",
                    "currency": "CNY",
                    "listing_status": "ACTIVE",
                    "source": "AKSHARE",
                    "metadata": {},
                }
            )
        return records
