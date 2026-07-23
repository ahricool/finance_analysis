"""PostgreSQL -> immutable Qlib binary dataset snapshot."""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from datetime import date

import numpy as np
import pandas as pd

from finance_analysis.core.time import utc_isoformat, utc_now
from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.quant.config import get_quant_config
from finance_analysis.quant.data import DailyBarLoader
from finance_analysis.quant.datasets.artifact_store import ArtifactStore
from finance_analysis.quant.datasets.validator import validate_daily_bars
from finance_analysis.quant.exceptions import ModelArtifactMissingError, QuantDatasetValidationError
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
        snapshot_values = {
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
        snapshot = self.repository.get_dataset_by_key(dataset_key)
        if snapshot and snapshot.status == "ready" and snapshot.artifact_uri:
            try:
                self.artifacts.resolve_uri(snapshot.artifact_uri)
            except ModelArtifactMissingError:
                logger.warning("Rebuilding dataset with missing artifact: %s", snapshot.artifact_uri)
            else:
                return snapshot
        if snapshot:
            self.repository.update_dataset(
                snapshot.id,
                status="building",
                validation_result={},
                finished_at=None,
            )
        else:
            snapshot = self.repository.create_dataset(snapshot_values)
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
            self._write_qlib(root, frame)
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
