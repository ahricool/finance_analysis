# Qlib quant research

The quant module keeps PostgreSQL as its source of truth. It reads canonical <!-- pragma: allowlist secret -->
`instrument` and canonical forward-adjusted `stock_daily` rows, exports immutable
snapshots below `QUANT_ARTIFACT_ROOT`, and sends only artifact URIs and versioned
configuration to the Qlib worker.

## Runtime

The application requires Python 3.13. Qlib 0.9.7 has no CPython 3.13 wheel, so
`qlib-worker` uses Python 3.12, `pyqlib==0.9.7`, and its own `pyproject.toml`
and `uv.lock`. The main Python 3.13 environment does not install Qlib,
LightGBM, or scikit-learn. Both environments share only `./data/quant` and the
Redis Celery broker/backend. PostgreSQL remains the only business database and <!-- pragma: allowlist secret -->
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

For a genuinely empty database, Alembic creates the current ORM metadata and
stamps the single head. Existing databases run the migration chain normally.

## Celery workflow

The main worker consumes `celery,alerts,analysis,ingestion,maintenance`; it
never consumes `qlib`. The isolated worker consumes only `qlib` with
concurrency 1, prefetch 1, and one task per child process. Every Qlib task calls
`qlib.init()` for its dataset and process replacement prevents provider/cache
state from leaking into the next task.

Training dispatches `qlib.model.train` and links either
`quant.model.train.finalize` or `quant.model.train.failed` on the `analysis`
queue. Daily prediction dispatches a single `qlib.daily.predict` task with both
production model artifacts. The worker initializes Qlib and loads Alpha158 once,
then scores Cross Section and Time Series against the same feature matrix.
`quant.daily.finalize` performs signal fusion, ranking, target-portfolio
construction, and PostgreSQL persistence. <!-- pragma: allowlist secret --> A failed Qlib task never writes a
partial signal/portfolio set. Main workers never wait synchronously for Qlib.
Single-model `qlib.model.predict` remains available for isolated tests; the
scheduled pipeline does not use it.

## Model targets

Model type owns production target semantics. Administrators cannot override
benchmark or excess-return flags when creating a run.

| Model | Task | Label |
| --- | --- | --- |
| `cross_section_lgbm` | regression | T+1 open → T+5 close excess return versus the market benchmark |
| `time_series_lgbm` | classification | T+1 open → T+5 close absolute return `> 0` |

Both models share the same 5-session horizon, entry price, and exit price. Daily
prediction refuses production models whose stored `target_config` does not match
this contract, including legacy time-series runs that still used the
cross-section excess-return default.

## Metrics

Cross-section evaluation uses daily Rank IC statistics, not a pooled global
Rank IC as the headline number:

- primary: `daily_rank_ic_mean`, `icir`, `top5_excess_return_pct`,
  `top10_excess_return_pct`, `rank_ic_positive_day_ratio`
- auxiliary: global `ic` / `rank_ic`, `mae`, `rmse`
- lightweight OOS trading proxies from walk-forward test predictions: Top 5/10
  mean forward return, positive-period ratio, naive Sharpe, max drawdown,
  one-way turnover, and cost-adjusted return. Cost is a fixed 10 bps one-way
  assumption recorded in `metrics.assumptions`. This is not a backtest engine.

Time-series evaluation uses classification metrics: ROC AUC, balanced accuracy,
precision, recall, F1, Brier score, and directional hit rate. A fold with a
single class records `roc_auc=null` and a warning instead of failing training.

The committed production model retrains on the last fold's train+validation
window using `median(fold best_iteration_)` as `n_estimators`. Metadata stores
`fold_best_iterations` and `final_n_estimators`.

## Signal fusion, market regime, and portfolio

`SignalFusion` ranks names:

```text
final_score = cs_score * 0.60 + ts_score * 0.40 - risk_penalty
```

Market regime and market score remain in `score_components` for explanation.
They do not multiply alpha scores. Regime only sets `max_equity_exposure` for
`PortfolioBuilder`.

The exposure curve is unchanged. `risk_off` still allows a small book (about
10% at score 0, rising with the curve to 80% at score 1). There is no hidden
zero-exposure gate.

`buy_top_k=5` is a floor. When `max_equity_exposure / single_stock_max_weight`
needs more names, the builder selects enough buy-eligible names to make the
exposure reachable without breaking the 8% single-stock cap. Equal-weight names
are clipped to that cap. If too few eligible names exist, exposure is capped
and a warning is recorded.

Persisted `model_signal.score_components.lineage` and
`portfolio_recommendation.summary.lineage` identify the Cross Section and Time
Series run ids/versions, regime/fusion/portfolio/feature versions, dataset URI,
and source revision. The `model_version` column remains the Cross Section
version for the existing unique constraint.

## Daily prediction lookback

Alpha158 rolling windows in this project are `[5, 10, 20, 30, 60]` sessions.
Daily prediction datasets therefore use 80 trading sessions (60 plus a 20-session
buffer), counted on the market calendar rather than 500 calendar days. Regime
and liquidity research still load a longer history because those rules need at
least 61 sessions of benchmark and member bars.

Empirical Alpha158 comparisons on a synthetic Qlib dataset confirmed that
features on the target trade date match a 500-calendar-day window once the
exported history covers those 80 sessions. Shorter calendar windows that still
contain 80 sessions also match; the old 500-day pad was not required by the
feature expressions.

## VWAP proxy

Dataset VWAP binaries are an HLC3 estimate, `(high + low + close) / 3`, not
`amount / volume`. Provider amount quality is not trusted, so this proxy is an
intentional design. Do not replace it with turnover-implied VWAP. Source
revision still hashes the stored OHLCV, this VWAP proxy, and the daily
provider.

## Business workflow

1. Ensure the resolved Quant stock universe has daily bars in PostgreSQL. The small <!-- pragma: allowlist secret -->
   benchmark set uses MarketDataService `db_fresh`: fresh DB history needs no remote
   request; stale history gets a batched tail, and no-history symbols get the requested
   window. Remote bars are merged in memory without persistence. Index constituents
   come from current `universe_member` membership; WatchList does not change Quant
   or Daily Sync membership.
2. An administrator opens **量化研究 → 模型运行 → 创建训练任务** and builds or selects an immutable dataset.
   Failed validation prevents training, and dataset progress remains visible in the task center.
3. The administrator selects one of the two Qlib worker models and creates a model run. Training is asynchronous
   and becomes `candidate` only. The daily pipeline requires both `cross_section_lgbm` and `time_series_lgbm`.
   Walk-forward dates are generated by the worker; create-run requests no longer accept fake
   `train_start` / `valid_*` / `test_*` windows or a caller-supplied target contract.
4. An administrator reviews model-type metrics and publishes the candidate manually.
5. The US daily pipeline runs at 19:00 America/New_York and the CN daily
   pipeline runs at 19:00 Asia/Shanghai, each one hour after its market data
   synchronization task.

Model training is intentionally on demand rather than a periodic task: every run must name an immutable dataset,
model type, and version. It therefore appears in the Quant model UI and task history, not in the scheduled-task list.

Each market has exactly one supported quant universe. Clients select only the
market: `US` resolves to `us_quant` and `CN` resolves to `cn_quant`. These are
the only supported Quant universes; Universe CRUD, custom universes, and
Watchlist merging are not supported. Codes are resolved from the database's
`Universe` / `UniverseInclude` / `UniverseMember` records through
`get_universe_codes()` and `UniverseResolver`; there are no runtime static
constituent lists or legacy `quant_universe_member` compatibility tables.
Stock readiness remains DB-only. Daily persistence is independently scoped to
CN CSI300/500/1000 + `cn_index_etf`, and US S&P500 + `us_index_etf`;
CSI2000, Nasdaq100 and other strategy dependencies do not expand it.
Market benchmark dependencies come only from the fixed market configuration.
Quant has no sector regime model, sector score, sector ranking, or sector
portfolio cap.

Exports contain `calendars/day.txt`, `instruments/all.txt`, Qlib float32 binary
feature files, `source/daily.csv`, `manifest.json`, and `validation.json`.
Benchmark ETFs remain in the exported source so labels and regime features can
use them, but Qlib `Alpha158` loads only `manifest.symbols`, the fixed stock
universe. They never participate in model training, prediction, or
cross-sectional ranking. The label benchmark is `SPY.US` for the US universe
and `510300.SH` for the CN universe; `QQQ.US` and `159915.SZ` remain
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
or fused into daily signals. Quant does not retain event tables or prediction
staging rows: Qlib prediction payloads flow directly into signal fusion and
`model_signal`.
Production models whose stored `feature_config` still contains legacy keys
such as `ablation` are rejected before daily fan-out. After upgrading from a
custom-feature release, retrain and publish both daily models with
`{"base": "Alpha158"}` before enabling the scheduled pipeline.
`stock_daily` is the canonical forward-adjusted daily source. Dataset export,
training, research, and prediction read its OHLC values directly and never
apply a second adjustment. Volume and amount retain provider units. The stable
dataset source revision hashes the stored OHLCV, VWAP proxy, and daily provider, so a
historical price correction invalidates the old dataset key. `source/daily.csv`
and Qlib OHLC/VWAP binaries use the same price units; Qlib `factor.day.bin` is
always the neutral value `1.0` to prevent downstream double adjustment.

Daily inference and production training require at least 90% of the fixed
Universe by default. `QUANT_MIN_UNIVERSE_COVERAGE` can raise or lower this
threshold within `(0, 1]`. Falling below it fails before Qlib prediction or
training instead of producing rankings from a misleadingly small subset.

Legacy dataset artifacts are not relabeled. Models trained before the canonical
daily-price change should be rebuilt before publication.

The daily pipeline calculates only the temporary liquidity, data-sufficiency,
close-price, and volatility-risk context needed by signal fusion and portfolio
selection. That context travels in the Celery callback payload and is not
persisted. It is not a model feature panel; `daily_feature_snapshot` has been
removed.

`PortfolioBuilder` produces a model target portfolio. It does not read user
holdings and does not emit increase/reduce/sell or current-weight deltas. The
persisted items contain rank, target weight, final score, signal, reasons, and
applied constraints. Allocation is bounded by market-regime exposure,
single-stock weight, data sufficiency, and liquidity.

Model runs use expanding time-ordered walk-forward folds. The prediction
horizon is purged before validation/test data and the configured embargo is
applied in trading sessions. Every fold is trained and evaluated independently;
the committed model is retrained on the last fold's train+validation window.
Artifacts are written under
`models/{model_key}/{model_version}/{model_run_id}` through a temporary
directory, digested, validated, and atomically renamed. Identical retries reuse
the committed result.

Quant ranking and target-portfolio queries read PostgreSQL directly; Quant no <!-- pragma: allowlist secret -->
longer writes a separate Redis result cache.

## Follow-up: point-in-time universe

This release does not implement historical universe membership.

`UniverseMember` is a current-time unique `(universe_id, instrument_id)` row.
`UniverseRepository.replace_members*` replaces today's constituents in place.
`UniverseResolver` and `get_universe_codes()` therefore return the live set.
Dataset export covers that live set across the whole requested history, so a
model trained on today's S&P 500 / CSI 300/500/1000 members back through the
training window has survivorship bias: names that were added later appear in
the past, and names that left the index disappear from history.

CN index members come from AkShare current CSI lists; US members come from the
current Wikipedia S&P 500 / Nasdaq-100 tables. Neither pipeline stores
effective-from / effective-to dates.

Supporting point-in-time membership would need at least:

- a membership history table or `effective_from` / `effective_to` on members
- resolver and exporter APIs that take an as-of date
- training/daily jobs that request the as-of universe for each session
- a historical constituent source; current providers do not supply one

Do not retrofit this as a large Universe rewrite until a historical data source
exists.
