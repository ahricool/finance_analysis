"""PostgreSQL -> immutable Qlib binary dataset snapshot."""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select

from finance_analysis.core.time import utc_isoformat, utc_now
from finance_analysis.database.models.quant import DailyFeatureSnapshot, EventFeatureDaily
from finance_analysis.database.models.stock import MarketDataSymbol
from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.quant.config import get_quant_config
from finance_analysis.quant.data import DailyBarLoader
from finance_analysis.quant.datasets.artifact_store import ArtifactStore
from finance_analysis.quant.datasets.validator import validate_daily_bars
from finance_analysis.quant.exceptions import QuantDatasetValidationError
from finance_analysis.quant.features.daily import add_relative_strength, build_daily_features
from finance_analysis.quant.markets import (
    get_quant_market_config,
    get_quant_universe_codes,
    validate_universe_for_market,
)
from finance_analysis.quant.price_modes import (
    ADJUSTMENT_MODE_FORWARD,
    DEFAULT_QUANT_PRICE_MODE,
    normalize_price_mode,
)

logger = logging.getLogger(__name__)


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=2).strip()
    except (OSError, subprocess.SubprocessError):
        return None


class QlibDatasetExporter:
    FIELDS = ("open", "high", "low", "close", "volume", "amount", "factor", "vwap")

    def __init__(self, repository=None, artifact_store=None):
        self.repository = repository or QuantRepository()
        self.artifacts = artifact_store or ArtifactStore()

    def export(
        self,
        market: str,
        universe: str,
        date_from: date,
        date_to: date,
        frequency: str = "day",
        price_mode: str = DEFAULT_QUANT_PRICE_MODE.value,
        feature_version: str | None = None,
        candidate_codes: set[str] | None = None,
    ):
        if frequency != "day":
            raise ValueError("First release supports daily Qlib datasets only")
        price_mode = normalize_price_mode(price_mode)
        market_config = get_quant_market_config(market)
        universe = validate_universe_for_market(market_config.market, universe)
        definition = self.repository.get_universe(universe)
        if (
            not definition
            or definition.market != market_config.market
            or not getattr(definition, "enabled", True)
        ):
            raise ValueError(f"Supported {market_config.market} universe {universe} is not available")
        universe_codes = get_quant_universe_codes(market_config.market)
        candidate_codes = set(candidate_codes or universe_codes)
        if not candidate_codes.issubset(universe_codes):
            raise ValueError("Candidate codes must belong to the fixed Quant Universe")
        benchmark_codes = set(market_config.benchmark_dependencies)
        loaded = DailyBarLoader(self.repository).load(
            market_config.market,
            candidate_codes | benchmark_codes,
            date_from,
            date_to,
            price_mode,
        )
        source_revision = loaded.source_revision
        feature_version = feature_version or get_quant_config().feature_version
        key_parts = (
            market,
            universe,
            date_from,
            date_to,
            frequency,
            price_mode.value,
            feature_version,
            source_revision,
        )
        dataset_key = hashlib.sha256("|".join(map(str, key_parts)).encode()).hexdigest()
        snapshot = self.repository.create_dataset(
            {
                "dataset_key": dataset_key,
                "market": market.upper(),
                "universe_id": definition.id,
                "frequency": frequency,
                "date_from": date_from,
                "date_to": date_to,
                "price_mode": price_mode.value,
                "feature_version": feature_version,
                "source_revision": source_revision,
                "code_commit": _git_commit(),
                "status": "building",
                "validation_result": {},
            }
        )
        try:
            frame = loaded.frame
            report = validate_daily_bars(
                frame,
                candidate_codes,
                benchmark_codes,
                price_mode=price_mode.value,
            )
            report["adjustment_coverage"] = loaded.adjustment_coverage
            report["adjustment_sources"] = loaded.adjustment_sources
            if not report["valid"]:
                raise QuantDatasetValidationError("; ".join(report["errors"]))
            vwap_report = loaded.vwap
            report["vwap"] = vwap_report
            if vwap_report["valid_rows"] == 0:
                raise QuantDatasetValidationError("Dataset has no valid VWAP observations")
            if vwap_report["estimated_rows"]:
                report["warnings"].append(
                    f"VWAP used HLC3 estimates for {vwap_report['estimated_rows']} rows"
                )
            logger.info(
                "Qlib VWAP quality provider_calculated=%.2f%% estimated=%.2f%% missing=%.2f%%",
                vwap_report["provider_calculated_ratio"] * 100,
                vwap_report["estimated_ratio"] * 100,
                vwap_report["missing_ratio"] * 100,
            )
            relative = f"datasets/{dataset_key}"
            root = self.artifacts.directory(relative)
            self._write_qlib(
                root,
                frame,
                candidate_codes,
                market_config.primary_benchmark,
                market_config.market,
            )
            manifest = {
                "dataset_key": dataset_key,
                "market": market.upper(),
                "universe": universe,
                "frequency": frequency,
                "date_from": str(date_from),
                "date_to": str(date_to),
                "price_mode": price_mode.value,
                "adjustment_mode": ADJUSTMENT_MODE_FORWARD,
                "adjustment_coverage": loaded.adjustment_coverage,
                "adjustment_sources": loaded.adjustment_sources,
                "symbols": sorted(candidate_codes),
                "benchmark_codes": sorted(benchmark_codes),
                "feature_version": feature_version,
                "source_revision": source_revision,
                "code_commit": _git_commit(),
                "created_at": utc_isoformat(utc_now()),
                "market_benchmark": market_config.primary_benchmark,
                "vwap": vwap_report,
                "warnings": report["warnings"],
            }
            (root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
            (root / "validation.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
            self.repository.update_dataset(
                snapshot.id,
                artifact_uri=f"quant://{relative}",
                row_count=len(frame),
                symbol_count=len(candidate_codes),
                status="ready",
                validation_result=report,
                finished_at=utc_now(),
            )
        except Exception as exc:
            self.repository.update_dataset(
                snapshot.id,
                status="failed",
                validation_result={"valid": False, "errors": [str(exc)]},
                finished_at=utc_now(),
            )
            raise
        return self.repository.get_dataset(snapshot.id)

    def _write_qlib(
        self,
        root,
        frame: pd.DataFrame,
        candidate_codes: set[str],
        market_benchmark: str | None,
        market: str = "US",
    ) -> None:
        calendars = root / "calendars"
        instruments = root / "instruments"
        features = root / "features"
        source = root / "source"
        for directory in (calendars, instruments, features, source):
            directory.mkdir(parents=True, exist_ok=True)
        dates = sorted(pd.to_datetime(frame["datetime"]).dt.date.unique())
        date_index = {value: index for index, value in enumerate(dates)}
        (calendars / "day.txt").write_text("\n".join(map(str, dates)) + "\n", encoding="utf-8")
        lines = []
        for code, group in frame.groupby("instrument", sort=True):
            group = group.sort_values("datetime")
            group_dates = pd.to_datetime(group["datetime"]).dt.date
            lines.append(f"{code}\t{group_dates.iloc[0]}\t{group_dates.iloc[-1]}")
            directory = features / code.lower()
            directory.mkdir(parents=True, exist_ok=True)
            start_index = date_index[group_dates.iloc[0]]
            positions = [date_index[item] - start_index for item in group_dates]
            length = max(positions) + 1
            for field in self.FIELDS:
                values = np.full(length, np.nan, dtype="<f4")
                # Qlib's external binary field is named ``factor`` and defines
                # adjusted_price / raw_price, matching our canonical factor.
                source_field = "forward_adjustment_factor" if field == "factor" else field
                values[positions] = group[source_field].to_numpy(dtype="<f4")
                np.concatenate((np.array([start_index], dtype="<f4"), values)).tofile(directory / f"{field}.day.bin")
        (instruments / "all.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        frame.to_csv(source / "daily.csv", index=False)
        custom = self._custom_features(
            frame,
            candidate_codes,
            market_benchmark,
            market,
        )
        if not custom.empty:
            custom.to_parquet(source / "custom_features.parquet", index=False)

    def _custom_features(
        self,
        frame: pd.DataFrame,
        candidate_codes: set[str],
        market_benchmark: str | None,
        market: str,
    ) -> pd.DataFrame:
        groups = {
            code: group.rename(columns={"datetime": "date"}).drop(columns="instrument").sort_values("date")
            for code, group in frame.groupby("instrument")
        }
        market_frame = groups.get(market_benchmark or "")
        if market_frame is None:
            return pd.DataFrame()
        columns = [
            "ret_1d",
            "ret_5d",
            "ret_20d",
            "ret_60d",
            "price_ma20_ratio",
            "price_ma60_ratio",
            "volume_ratio_5d",
            "atr_14",
            "realized_vol_20d",
            "distance_from_20d_high",
            "gap_return",
            "rsi_14",
            "relative_5d_to_market",
            "relative_20d_to_market",
            "relative_5d_to_sector",
            "relative_20d_to_sector",
        ]
        output = []
        for code in sorted(candidate_codes):
            bars = groups.get(code)
            sector = market_frame
            if bars is None or sector is None:
                continue
            features = add_relative_strength(build_daily_features(bars), market_frame, sector)
            features["instrument"] = code
            features = features.rename(columns={"date": "datetime"})
            output.append(features[["datetime", "instrument", *columns]])
        if not output:
            return pd.DataFrame()
        result = pd.concat(output, ignore_index=True)
        with self.repository.db.get_session() as session:
            rows = session.execute(
                select(
                    MarketDataSymbol.code,
                    DailyFeatureSnapshot.trade_date,
                    DailyFeatureSnapshot.market_score,
                    DailyFeatureSnapshot.sector_score,
                    EventFeatureDaily.event_score,
                    EventFeatureDaily.negative_event_veto,
                )
                .join(DailyFeatureSnapshot, DailyFeatureSnapshot.symbol_id == MarketDataSymbol.id)
                .join(
                    EventFeatureDaily,
                    (EventFeatureDaily.symbol_id == DailyFeatureSnapshot.symbol_id)
                    & (EventFeatureDaily.trade_date == DailyFeatureSnapshot.trade_date),
                )
                .where(
                    MarketDataSymbol.market == market,
                    MarketDataSymbol.code.in_(candidate_codes),
                    DailyFeatureSnapshot.feature_version == get_quant_config().feature_version,
                    EventFeatureDaily.feature_version == get_quant_config().event_feature_version,
                )
            ).all()
        snapshots = pd.DataFrame(
            rows,
            columns=["instrument", "datetime", "market_score", "sector_score", "event_score", "negative_event_veto"],
        )
        if not snapshots.empty:
            result["datetime"] = pd.to_datetime(result["datetime"])
            snapshots["datetime"] = pd.to_datetime(snapshots["datetime"])
            result = result.merge(snapshots, on=["datetime", "instrument"], how="left", validate="one_to_one")
        return result
