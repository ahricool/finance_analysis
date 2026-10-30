"""Task-owned prediction inputs. Never create a dataset database record."""
from __future__ import annotations

import fcntl
import json
import shutil
from contextlib import contextmanager
from pathlib import Path

from finance_analysis.quant.datasets.artifact_store import ArtifactStore
from finance_analysis.quant.datasets.exporter import QlibDatasetExporter
from finance_analysis.quant.datasets.validator import validate_daily_bars
from finance_analysis.quant.markets import get_quant_market_config


@contextmanager
def input_lock(root: Path):
    """The worker uses the same POSIX lock while reading; never remove a live input."""
    with (root / '.lease').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class PredictionInputs:
    def __init__(self, store=None):
        self.store = store or ArtifactStore()

    def build(self, execution_id, market, universe, loaded, symbols, date_from, date_to):
        config = get_quant_market_config(market)
        frame = loaded.frame
        dates = frame['datetime'].astype(str).str[:10]
        frame = frame[dates.between(str(date_from), str(date_to)) &
                      frame['instrument'].isin(set(symbols) | set(config.benchmark_dependencies))].reset_index(drop=True)
        report = validate_daily_bars(frame, set(symbols), set(config.benchmark_dependencies))
        if not report['valid']:
            raise ValueError('; '.join(report['errors']))
        relative = f'temporary/{execution_id}'
        root = self.store.directory(relative)
        try:
            with input_lock(root):
                QlibDatasetExporter._write_qlib(None, root, frame, include_source=False)
                manifest = {
                    'purpose': 'prediction', 'execution_id': execution_id,
                    'market': market, 'universe': universe,
                    'date_from': str(date_from), 'date_to': str(date_to),
                    'symbols': sorted(symbols), 'benchmark_codes': sorted(config.benchmark_dependencies),
                    'market_benchmark': config.label_benchmark,
                    'price_mode': 'forward_adjusted', 'feature_version': 'alpha158-v1',
                    'source_revision': loaded.source_revision,
                }
                (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise
        return f'quant://{relative}'

    def remove(self, uri):
        if not uri or not uri.startswith('quant://temporary/'):
            return False
        root = self.store.path(uri.removeprefix('quant://'))
        temporary = (self.store.root / "temporary").resolve()
        if root.parent != temporary or root == temporary:
            raise ValueError("Invalid temporary input path")
        if not root.exists():
            return True
        try:
            with input_lock(root):
                shutil.rmtree(root)
            return True
        except BlockingIOError:
            return False
