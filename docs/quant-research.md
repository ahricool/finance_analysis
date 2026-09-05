# Qlib quant research

The quant module keeps PostgreSQL as its source of truth. It reads canonical
`instrument` and canonical forward-adjusted `stock_daily` rows, exports immutable
snapshots below `QUANT_ARTIFACT_ROOT`, and sends only artifact URIs and versioned
configuration to the Qlib worker.

## Runtime

The application requires Python 3.13. Qlib 0.9.7 has no CPython 3.13 wheel, so
`qlib-worker` uses Python 3.12, `pyqlib==0.9.7`, and its own `pyproject.toml`
and `uv.lock`. The main Python 3.13 environment does not install Qlib,
LightGBM, or scikit-learn. Both environments share only `./data/quant` and the
Redis Celery broker/backend. PostgreSQL remains the only business database and
the Qlib worker receives no database credentials or application source mount.

The worker remains pinned to `linux/amd64` because this Qlib release has not
been validated by this project on ARM64. Docker Desktop uses emulation on Apple
Silicon while x86_64 production hosts run it natively.

```bash
uv sync
docker compose -f docker-compose.dev.yml up --build postgres redis qlib-worker server worker beat web
```

Apply the schema with the normal application bootstrap or explicitly:

```bash
uv run alembic upgrade head
```

For a genuinely empty database, follow the repository baseline caveat first:
`uv run alembic upgrade 0001_baseline && uv run alembic stamp 0016_dual_engine_backtests`,
then run `uv run alembic upgrade head`.

## Celery workflow

The main worker consumes `celery,alerts,analysis,ingestion,maintenance`; it
never consumes `qlib`. The isolated worker consumes only `qlib` with
concurrency 1, prefetch 1, and one task per child process. Every Qlib task calls
`qlib.init()` for its dataset and process replacement prevents provider/cache
state from leaking into the next task.

Training dispatches `qlib.model.train` and links either
`quant.model.train.finalize` or `quant.model.train.failed` on the `analysis`
queue. Daily prediction uses a Celery chord with two `qlib.model.predict`
tasks; `quant.daily.finalize` performs signal fusion, portfolio construction,
and PostgreSQL persistence. Main workers never wait synchronously for Qlib.

## Business workflow

1. Ensure the resolved Quant stock universe has daily bars in PostgreSQL. The small
   benchmark set uses MarketDataService `db_first` without persisting remote bars.
   Index constituents come from `universe_member`; static Python
   constituent constants and WatchList do not change Quant or Daily Sync membership.
2. An administrator opens **量化研究 → 模型运行 → 创建训练任务** and builds or selects an immutable dataset.
   Failed validation prevents training, and dataset progress remains visible in the task center.
3. The administrator selects one of the two Qlib worker models and creates a model run. Training is asynchronous
   and becomes `candidate` only. The daily pipeline requires both `cross_section_lgbm` and `time_series_lgbm`.
4. An administrator reviews metrics and publishes the candidate manually.
5. The US daily pipeline runs at 19:00 America/New_York and the CN daily
   pipeline runs at 19:00 Asia/Shanghai, each one hour after its market data
   synchronization task.

Model training is intentionally on demand rather than a periodic task: every run must name an immutable dataset,
model type, and version. It therefore appears in the Quant model UI and task history, not in the scheduled-task list.

Each market has exactly one supported quant universe. Clients select only the
market: `US` resolves to `us_quant` and `CN` resolves to `cn_quant`. These are
the only supported Quant universes; Universe CRUD, custom universes, and
Watchlist merging are not supported. Their codes are resolved directly from
the checked-in index variables at runtime through `get_quant_universe_codes()`.
Dataset builds and daily research never read or
initialize `quant_universe_member`. That table remains in the schema only for
historical database compatibility. Other Universe rows may remain only for
referential integrity and cannot create datasets, model runs, predictions,
signals, or portfolios. Market benchmark dependencies come only from the
fixed market configuration; stock industry mappings and industry benchmarks
are not part of the MVP data path.

Exports contain `calendars/day.txt`, `instruments/all.txt`, Qlib float32 binary
feature files, `source/daily.csv`, `manifest.json`, and `validation.json`.
Benchmark ETFs remain in the exported source so labels and regime features can
use them, but Qlib `Alpha158` loads only `manifest.symbols`, the fixed stock
universe. They never participate in model training, prediction, or
cross-sectional ranking. The label benchmark is `SPY.US` for the US universe
and `510300.SH` for the CSI 300 universe; `QQQ.US` and `159915.SZ` remain
style/regime benchmarks.

Daily market regime scoring is an explicit weighted rules model. For China,
`510300.SH` supplies CSI 300 trend, momentum, volatility, and drawdown inputs;
`159915.SZ` contributes only its 20-day relative performance versus the CSI
300 as a growth-style/risk-appetite input. The other inputs are CSI 300 member
breadth. Each persisted `market_regime_snapshot.features.score_breakdown`
contains raw values, normalized component scores, weights, and contributions.
Legacy snapshots without that nested object remain readable. Maximum equity
exposure is linearly interpolated from the configured score/exposure curve
rather than selected from three regime buckets.
Both trainable models build their training and prediction matrices exclusively
with Qlib `Alpha158`. Dataset exports do not contain custom feature panels, and
news or structured events are not uploaded, scored, joined into model inputs,
or fused into daily signals. Existing event-related database columns and tables
remain unused solely for migration compatibility.
Production models whose stored `feature_config` still contains legacy keys
such as `ablation` are rejected before daily fan-out. After upgrading from a
custom-feature release, retrain and publish both daily models with
`{"base": "Alpha158"}` before enabling the scheduled pipeline.
The binary fields include VWAP. Turnover/volume is used when provider units are
valid, common legacy unit factors are checked against the daily price range,
and missing turnover uses an explicit OHLC typical-price proxy only when volume
is positive. Zero-volume rows remain missing rather than being zero-filled.
`stock_daily` is the canonical forward-adjusted daily source. Dataset export,
training, research, and prediction read its OHLC values directly and never
apply a second adjustment. Volume and amount retain provider units. The stable
dataset source revision hashes the stored OHLCV, VWAP, and daily provider, so a
historical price correction invalidates the old dataset key. `source/daily.csv`
and Qlib OHLC/VWAP binaries use the same price units; Qlib `factor.day.bin` is
always the neutral value `1.0` to prevent downstream double adjustment.

Daily inference and production training require at least 90% of the fixed
Universe by default. `QUANT_MIN_UNIVERSE_COVERAGE` can raise or lower this
threshold within `(0, 1]`. Falling below it fails before model fan-out or
training instead of producing rankings from a misleadingly small subset.

Legacy dataset artifacts are not relabeled. Models trained before the canonical
daily-price change should be rebuilt before publication.

Model runs use expanding time-ordered walk-forward folds. The prediction
horizon is purged before validation/test data and the configured embargo is
applied in trading sessions. Every fold is trained and evaluated independently;
the committed model is retrained on the last fold's train+validation window.
Artifacts are written under
`models/{model_key}/{model_version}/{model_run_id}` through a temporary
directory, digested, validated, and atomically renamed. Identical retries reuse
the committed result.

Redis contains only latest-result caches (`quant:market_regime:*`,
`quant:sector_ranking:*`, `quant:ranking:*`, `quant:portfolio:*`,
and `quant:signal:*`). Cache failures are warnings; PostgreSQL rows remain authoritative.
