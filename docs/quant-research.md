# Qlib quant research

The quant module keeps PostgreSQL as its source of truth. It reads canonical
`market_data_symbol`, `stock_daily`, and `stock_minute` rows, exports immutable
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
   PostgreSQL. US uses S&P 500 plus the US watchlist; CN uses CSI 300 plus the
   A-share watchlist. Benchmark dependencies are synchronized separately and
   never enter stock ranking.
2. Build a dataset from the Quant UI/API. Failed validation prevents training.
3. Create a model run. Training is asynchronous and becomes `candidate` only.
4. An administrator reviews metrics and publishes the candidate manually.
5. The US daily pipeline runs at 19:00 America/New_York and the CN daily
   pipeline runs at 19:00 Asia/Shanghai, each one hour after its market data
   synchronization task.

Each market has exactly one supported quant universe. Clients select only the
market: `US` resolves to `us_sp500_watchlist` and `CN` resolves to
`cn_csi300_watchlist`. Membership is refreshed idempotently from the same
`MarketDataScopeResolver` used by daily market-data synchronization. Removed
members retain effective-dated history. Disabled/deprecated universes remain
only for referential integrity and cannot create datasets, model runs,
predictions, signals, or portfolios.

Exports contain `calendars/day.txt`, `instruments/all.txt`, Qlib float32 binary
feature files, `source/daily.csv`, `manifest.json`, and `validation.json`.
The binary fields include VWAP. Turnover/volume is used when provider units are
valid, common legacy unit factors are checked against the daily price range,
and missing turnover uses an explicit OHLC typical-price proxy only when volume
is positive. Zero-volume rows remain missing rather than being zero-filled.
Features and labels use one price mode per snapshot. Currently only raw prices
exist, so every run carries the corporate-action warning. Dataset manifests
record the effective dynamic universe, synchronized benchmark dependencies,
and validation warnings for the requested market.

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
