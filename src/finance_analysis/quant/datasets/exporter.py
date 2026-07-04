"""PostgreSQL -> immutable Qlib binary dataset snapshot."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select

from finance_analysis.core.time import utc_isoformat, utc_now
from finance_analysis.database.models.quant import DailyFeatureSnapshot, EventFeatureDaily
from finance_analysis.database.models.stock import MarketDataSymbol, StockDaily
from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.quant.config import get_quant_config
from finance_analysis.quant.datasets.artifact_store import ArtifactStore
from finance_analysis.quant.datasets.validator import validate_daily_bars
from finance_analysis.quant.exceptions import BenchmarkDataMissingError, QuantDatasetValidationError
from finance_analysis.quant.features.daily import add_relative_strength, build_daily_features


def _git_commit() -> str | None:
    try: return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=2).strip()
    except (OSError, subprocess.SubprocessError): return None


class QlibDatasetExporter:
    FIELDS = ("open", "high", "low", "close", "volume", "amount", "factor")

    def __init__(self, repository=None, artifact_store=None):
        self.repository = repository or QuantRepository()
        self.artifacts = artifact_store or ArtifactStore()

    def export(self, market: str, universe: str, date_from: date, date_to: date, frequency: str = "day", price_mode: str = "raw", feature_version: str | None = None):
        if frequency != "day": raise ValueError("First release supports daily Qlib datasets only")
        if price_mode != "raw": raise ValueError("Adjusted prices are unavailable; use price_mode=raw")
        definition = self.repository.get_universe(universe)
        if not definition or definition.market != market.upper(): raise ValueError(f"Unknown universe: {universe}")
        members = self.repository.active_members(definition.id, date_to)
        candidate_codes = {symbol.code for _, symbol in members}
        benchmark_codes = {definition.benchmark_code} if definition.benchmark_code else set()
        benchmark_codes.update(member.sector_benchmark_code for member, _ in members if member.sector_benchmark_code)
        if not benchmark_codes: raise BenchmarkDataMissingError("Universe has no available benchmark mapping")
        source_revision = self._source_revision(candidate_codes | benchmark_codes, date_from, date_to)
        feature_version = feature_version or get_quant_config().feature_version
        dataset_key = hashlib.sha256(f"{market}|{universe}|{date_from}|{date_to}|{frequency}|{price_mode}|{feature_version}|{source_revision}".encode()).hexdigest()
        snapshot = self.repository.create_dataset({"dataset_key": dataset_key, "market": market.upper(), "universe_id": definition.id, "frequency": frequency, "date_from": date_from, "date_to": date_to, "price_mode": price_mode, "feature_version": feature_version, "source_revision": source_revision, "code_commit": _git_commit(), "status": "building", "validation_result": {}})
        try:
            frame = self._load(candidate_codes | benchmark_codes, date_from, date_to)
            report = validate_daily_bars(frame, candidate_codes, benchmark_codes)
            if not report["valid"]: raise QuantDatasetValidationError("; ".join(report["errors"]))
            relative = f"datasets/{dataset_key}"
            root = self.artifacts.directory(relative)
            sector_mapping={symbol.code:member.sector_benchmark_code for member,symbol in members}
            self._write_qlib(root, frame, candidate_codes, definition.benchmark_code, sector_mapping)
            manifest = {"dataset_key": dataset_key, "market": market.upper(), "universe": universe, "frequency": frequency,
                        "date_from": str(date_from), "date_to": str(date_to), "price_mode": price_mode,
                        "symbols": sorted(candidate_codes), "benchmark_codes": sorted(benchmark_codes), "feature_version": feature_version,
                        "source_revision": source_revision, "code_commit": _git_commit(), "created_at": utc_isoformat(utc_now()),
                        "sector_benchmark_mapping": sector_mapping,
                        "warnings": report["warnings"]}
            (root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
            (root / "validation.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
            self.repository.update_dataset(snapshot.id, artifact_uri=f"quant://{relative}", row_count=len(frame), symbol_count=len(candidate_codes), status="ready", validation_result=report, finished_at=utc_now())
        except Exception as exc:
            self.repository.update_dataset(snapshot.id, status="failed", validation_result={"valid": False, "errors": [str(exc)]}, finished_at=utc_now())
            raise
        return self.repository.get_dataset(snapshot.id)

    def _load(self, codes: set[str], start: date, end: date) -> pd.DataFrame:
        with self.repository.db.get_session() as session:
            rows = session.execute(select(MarketDataSymbol.code, StockDaily.date, StockDaily.open, StockDaily.high,
                StockDaily.low, StockDaily.close, StockDaily.volume, StockDaily.amount).join(StockDaily, StockDaily.symbol_id == MarketDataSymbol.id)
                .where(MarketDataSymbol.code.in_(codes), StockDaily.date.between(start, end)).order_by(MarketDataSymbol.code, StockDaily.date)).all()
        frame = pd.DataFrame(rows, columns=["instrument", "datetime", "open", "high", "low", "close", "volume", "amount"])
        if not frame.empty: frame["factor"] = 1.0
        return frame

    def _source_revision(self, codes: set[str], start: date, end: date) -> str:
        frame = self._load(codes, start, end)
        payload = frame.to_csv(index=False, lineterminator="\n").encode()
        return hashlib.sha256(payload).hexdigest()

    def _write_qlib(self, root, frame: pd.DataFrame, candidate_codes: set[str], market_benchmark: str | None, sector_mapping: dict[str,str|None]) -> None:
        calendars = root / "calendars"; instruments = root / "instruments"; features = root / "features"; source = root / "source"
        for directory in (calendars, instruments, features, source): directory.mkdir(parents=True, exist_ok=True)
        dates = sorted(pd.to_datetime(frame["datetime"]).dt.date.unique()); date_index = {value: index for index, value in enumerate(dates)}
        (calendars / "day.txt").write_text("\n".join(map(str, dates)) + "\n", encoding="utf-8")
        lines = []
        for code, group in frame.groupby("instrument", sort=True):
            group = group.sort_values("datetime"); group_dates = pd.to_datetime(group["datetime"]).dt.date
            lines.append(f"{code}\t{group_dates.iloc[0]}\t{group_dates.iloc[-1]}")
            directory = features / code.lower(); directory.mkdir(parents=True, exist_ok=True)
            start_index = date_index[group_dates.iloc[0]]; positions = [date_index[item] - start_index for item in group_dates]
            length = max(positions) + 1
            for field in self.FIELDS:
                values = np.full(length, np.nan, dtype="<f4")
                values[positions] = group[field].fillna(0 if field == "amount" else 1 if field == "factor" else np.nan).to_numpy(dtype="<f4")
                np.concatenate((np.array([start_index], dtype="<f4"), values)).tofile(directory / f"{field}.day.bin")
        (instruments / "all.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        frame.to_csv(source / "daily.csv", index=False)
        custom=self._custom_features(frame,candidate_codes,market_benchmark,sector_mapping)
        if not custom.empty: custom.to_parquet(source / "custom_features.parquet",index=False)

    def _custom_features(self, frame: pd.DataFrame, candidate_codes: set[str], market_benchmark: str | None, sector_mapping: dict[str,str|None]) -> pd.DataFrame:
        groups={code:group.rename(columns={"datetime":"date"}).drop(columns="instrument").sort_values("date") for code,group in frame.groupby("instrument")}
        market=groups.get(market_benchmark or "QQQ.US")
        if market is None: market=groups.get("QQQ.US")
        if market is None: return pd.DataFrame()
        columns=["ret_1d","ret_5d","ret_20d","ret_60d","price_ma20_ratio","price_ma60_ratio","volume_ratio_5d","atr_14",
                 "realized_vol_20d","distance_from_20d_high","gap_return","rsi_14","relative_5d_to_market","relative_20d_to_market",
                 "relative_5d_to_sector","relative_20d_to_sector"]
        output=[]
        for code in sorted(candidate_codes):
            bars=groups.get(code);sector=groups.get(sector_mapping.get(code) or market_benchmark or "QQQ.US")
            if bars is None or sector is None: continue
            features=add_relative_strength(build_daily_features(bars),market,sector)
            features["instrument"]=code;features=features.rename(columns={"date":"datetime"});output.append(features[["datetime","instrument",*columns]])
        if not output: return pd.DataFrame()
        result=pd.concat(output,ignore_index=True)
        with self.repository.db.get_session() as session:
            rows=session.execute(select(MarketDataSymbol.code,DailyFeatureSnapshot.trade_date,DailyFeatureSnapshot.market_score,
                DailyFeatureSnapshot.sector_score,EventFeatureDaily.event_score,EventFeatureDaily.negative_event_veto)
                .join(DailyFeatureSnapshot,DailyFeatureSnapshot.symbol_id==MarketDataSymbol.id)
                .join(EventFeatureDaily,(EventFeatureDaily.symbol_id==DailyFeatureSnapshot.symbol_id)&(EventFeatureDaily.trade_date==DailyFeatureSnapshot.trade_date))
                .where(MarketDataSymbol.code.in_(candidate_codes),DailyFeatureSnapshot.feature_version==get_quant_config().feature_version,
                       EventFeatureDaily.feature_version==get_quant_config().event_feature_version)).all()
        snapshots=pd.DataFrame(rows,columns=["instrument","datetime","market_score","sector_score","event_score","negative_event_veto"])
        if not snapshots.empty:
            result["datetime"]=pd.to_datetime(result["datetime"]);snapshots["datetime"]=pd.to_datetime(snapshots["datetime"])
            result=result.merge(snapshots,on=["datetime","instrument"],how="left",validate="one_to_one")
        return result
