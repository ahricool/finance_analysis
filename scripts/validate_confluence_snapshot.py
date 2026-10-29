"""Replay exported Confluence sources offline, never connecting to production or writing a DB.

Input: {market: {day, stocks, sources, read_seconds?, errors?}}. The source rows
are the public research projections from ConfluenceRepository, not account data.
"""

import argparse
from datetime import date
import json
from pathlib import Path
from time import perf_counter

from finance_analysis.confluence.service import ConfluenceService, json_safe
from finance_analysis.interfaces.api.v1.schemas.confluence import Ranking


class SnapshotRepository:
    def __init__(self, record):
        self.record = record
        self.names = {stock["id"]: stock for stock in record["stocks"]}
        self.snapshot = {"items": []}

    def __getattr__(self, name):
        key = "trend" if name == "trend_v2" else name
        if key in self.record["sources"]:
            return lambda *_: self.record["sources"][key]
        raise AttributeError(name)

    def instruments(self, *_):
        return self.record["stocks"]

    def read(self, *_):
        return self.snapshot

    def save(self, market, day, rows, manifest):
        self.snapshot = dict(
            market=market,
            trade_date=day,
            **manifest,
            items=[
                dict(row, code=self.names[row["instrument_id"]]["code"], name=self.names[row["instrument_id"]]["name"])
                for row in rows
            ],
        )
        return True


def validate(records):
    output = {}
    for market, record in records.items():
        if market not in {"CN", "US"} or record.get("errors"):
            raise ValueError("Require CN/US exported research sources without read failures")
        day = date.fromisoformat(record["day"])
        repository = SnapshotRepository(record)
        service = ConfluenceService(repository)
        started = perf_counter()
        result = service.run(market, day)
        elapsed = perf_counter() - started
        response = Ranking.model_validate(service.ranking(market, day))
        first = [(r.instrument_id, r.confluence_score) for r in response.items]
        service.run(market, day)
        repeated = service.ranking(market, day)
        assert first == [(r["instrument_id"], r["confluence_score"]) for r in repeated["items"]]
        assert result["count"] <= 10
        output[market] = dict(
            summary=result,
            cpu_seconds=elapsed,
            read_seconds=record.get("read_seconds"),
            rerun_stable=True,
            snapshot=response.model_dump(mode="json"),
        )
    return json_safe(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate(json.loads(args.input.read_text()))
    serialized = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        args.output.write_text(serialized)
    else:
        print(serialized)


if __name__ == "__main__":
    main()
