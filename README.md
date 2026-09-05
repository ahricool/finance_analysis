# Finance Analysis 🐣📈

## Reference data / daily sync deployment

After upgrading, manually run **reference_data_sync** once from the existing Task
Center before running daily data or strategy tasks. Alembic seeds Universe
definitions/includes and the curated Index ETF pool; it never downloads index members and startup does not fetch
reference data. Inspect `failed_markets` / `failed_universes` before proceeding.
Thereafter reference sync runs Sundays at 08:00 Asia/Shanghai.

- Instrument Master: TickFlow primary, Longbridge fallback using the existing
  `LONGBRIDGE_APP_KEY`, `LONGBRIDGE_APP_SECRET`, `LONGBRIDGE_ACCESS_TOKEN` configuration.
  Longbridge is **Security Master only**, not a scheduled Daily Bar fallback.
  Directory support and security types must be available from the deployed SDK/API;
  unsupported/untyped responses fail the market safely rather than guessing STOCK.
  Only a complete TickFlow primary directory can reconcile DELISTED.
- Index membership: AkShare CSI300/500/1000/2000 (`932000`); Wikipedia S&P500/Nasdaq100. Index
  responses never overwrite existing Instrument metadata or source. Missing
  identities must first resolve through a Security Master provider.
- Curated ETF membership lives only in `cn_index_etf` / `us_index_etf` (STRATEGY,
  one market each). Migration copies old ETF Rotation members by `instrument_id`,
  preserving source and classification metadata, before deleting the old pools.
  Fresh installs initialize the original 42 CN / 49 US ETF Instruments first.
  Weekly reference sync does not alter these curated memberships.
- CN daily: `cn_daily_sync` = CSI300 + CSI500 + CSI1000 + `cn_index_etf`;
  US daily: `us_daily_sync` = S&P500 + `us_index_etf`. CSI2000, Nasdaq100,
  WatchList and other strategy dependencies do not expand these sets. Daily jobs
  run at 18:00 in Shanghai/New York; monthly full refresh uses the same sets.
- `cn_trend` includes CSI300/500/1000/2000; `us_trend` includes S&P500.
  CSI2000 membership is current-only and refreshed weekly, but its prices are
  not scheduled for persistence. Trend fetches its required history/tail in
  batches through `db_fresh`, uses it in readiness and calculation, and never
  writes those prices to `stock_daily`. Other main-universe stocks remain DB-only.
- MarketDataService queries never create Instruments or write daily bars.
  `db_first` uses any existing local history; `db_only` reads available DB rows;
  `remote_only` bypasses DB. `db_fresh` uses DB history and checks only the latest
  local date against the requested end. Fresh means zero remote requests. Stale
  histories get a batched tail starting ten natural days before the oldest stale
  latest date (bounded by the requested start); securities without any history
  get the requested window in a separate batch. Remote dates override DB dates
  in memory. There is no historical-gap, suspension or listing-date validation.
- ETF Rotation reads the Index ETF pool plus its benchmark with `db_fresh`;
  Trend and Quant benchmarks also use `db_fresh`. A benchmark outside the curated
  pool is still calculation-only and does not expand scheduled daily scope.
- Only explicit data maintenance jobs write daily history. A full refresh with
  any per-symbol request exception leaves that symbol's old history unchanged;
  successful empty responses are not request failures and never erase history.
