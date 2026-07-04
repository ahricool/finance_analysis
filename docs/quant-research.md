# Qlib quant research

The quant module keeps PostgreSQL as its source of truth. It reads canonical
`market_data_symbol`, `stock_daily`, and `stock_minute` rows, exports immutable
snapshots below `QUANT_ARTIFACT_ROOT`, and sends only artifact URIs and versioned
configuration to the Qlib worker.

## Runtime

The application requires Python 3.13. Qlib 0.9.7 has no CPython 3.13 wheel, so
`qlib-worker` uses Python 3.12 and a pinned dependency set. Both services share
`./data`, PostgreSQL remains the only business database, and the worker never
serves the Vue application directly.

The Qlib 0.9.7 Linux wheel is x86_64-only. The worker therefore declares
`linux/amd64`; Docker Desktop uses emulation on Apple Silicon while ordinary
x86_64 production hosts run it natively.

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

## Workflow

1. Ensure candidate and benchmark symbols (`QQQ.US`, `SPY.US`, `SOXX.US`) have
   daily bars in PostgreSQL.
2. Build a dataset from the Quant UI/API. Failed validation prevents training.
3. Create a model run. Training is asynchronous and becomes `candidate` only.
4. An administrator reviews metrics and publishes the candidate manually.
5. The daily pipeline runs at 19:00 America/New_York, after the 18:00 data sync.

Exports contain `calendars/day.txt`, `instruments/all.txt`, Qlib float32 binary
feature files, `source/daily.csv`, `manifest.json`, and `validation.json`.
Features and labels use one price mode per snapshot. Currently only raw prices
exist, so every run carries the corporate-action warning. The initial universe
is explicitly a fixed observation universe and therefore carries a survivorship
bias warning.

Redis contains only latest-result caches (`quant:market_regime:*`,
`quant:sector_ranking:*`, `quant:ranking:*`, `quant:portfolio:*`,
`quant:signal:*`, and `quant:intraday_confirmation:*`). Cache failures are
warnings; PostgreSQL rows remain authoritative.
