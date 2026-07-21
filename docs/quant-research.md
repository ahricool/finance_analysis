# Qlib quant research

The quant module keeps PostgreSQL as its source of truth. It reads canonical
`market_data_symbol`, raw `stock_daily`, and `stock_adjustment_factor` rows, exports immutable
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

1. Ensure the market scope and benchmark dependencies have daily bars in
   PostgreSQL. US uses the fixed `SP500_STOCK_INDEX` constituents; CN uses the
   fixed `CSI300_STOCK_INDEX` constituents. Watchlists and user-defined pools
   do not change Quant membership. Benchmark dependencies are synchronized
   separately and never enter stock ranking.
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
market: `US` resolves to `us_sp500` and `CN` resolves to `cn_csi300`. These are
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
The binary fields include VWAP. Turnover/volume is used when provider units are
valid, common legacy unit factors are checked against the daily price range,
and missing turnover uses an explicit OHLC typical-price proxy only when volume
is positive. Zero-volume rows remain missing rather than being zero-filled.
Features and labels use one price mode per snapshot. Production dataset builds,
training, and daily prediction require `price_mode="forward_adjusted"`. The
single canonical formula is
`forward_adjusted_price = raw_price * forward_adjustment_factor` and it is
applied once to open, high, low, close, and VWAP. VWAP is first sourced or
estimated in raw-price units. Volume and amount remain raw because the project
does not have a separately sourced volume-adjustment factor. Raw mode remains
available only for diagnostics and cannot train a production model.

Every daily bar must have a positive factor before a production dataset or
research snapshot is built; there is no implicit `1.0` fallback. Validation
reports include expected rows, factor rows, missing rows, coverage ratio, and
provider distribution. The stable dataset source revision hashes raw OHLCV,
VWAP, the forward-adjustment factor, provider, and provider content hash, so a
historical factor correction invalidates the old dataset key even when raw bars
do not change. `source/daily.csv` and Qlib OHLC/VWAP binaries use the same
forward-adjusted price units, while Qlib `factor.day.bin` contains
`forward_adjustment_factor` (adjusted price divided by raw price).

Legacy raw snapshots remain immutable historical artifacts and are never
relabeled. Model metadata records its training price mode; prediction fails if
that mode differs from the prediction dataset, so models trained on legacy raw
snapshots must be retrained before publication on the adjusted data path.

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
`quant:signal:*`, and `quant:intraday_confirmation:*`). Cache failures are
warnings; PostgreSQL rows remain authoritative.
