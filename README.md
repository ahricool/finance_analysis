# Finance Analysis 🐣📈

## Reference data / daily sync deployment

After upgrading, manually run **reference_data_sync** once from the existing Task
Center before running daily data or strategy tasks. Alembic seeds Universe
definitions/includes only; it never downloads members and startup does not fetch
reference data. Inspect `failed_markets` / `failed_universes` before proceeding.
Thereafter reference sync runs Sundays at 08:00 Asia/Shanghai.

- Instrument Master: TickFlow primary, Longbridge fallback using the existing
  `LONGBRIDGE_APP_KEY`, `LONGBRIDGE_APP_SECRET`, `LONGBRIDGE_ACCESS_TOKEN` configuration.
  Longbridge is **Security Master only**, not a scheduled Daily Bar fallback.
  Directory support and security types must be available from the deployed SDK/API;
  unsupported/untyped responses fail the market safely rather than guessing STOCK.
  Only a complete TickFlow primary directory can reconcile DELISTED.
- Index membership: AkShare CSI300/500/1000; Wikipedia S&P500/Nasdaq100. Index
  responses never overwrite existing Instrument metadata or source. Missing
  identities must first resolve through a Security Master provider.
- CN daily: `cn_daily_sync` = CSI300 + CSI500 + CSI1000; US daily:
  `us_daily_sync` = S&P500 only. Neither Nasdaq100 nor strategy/WatchList/benchmark
  dependencies expand these sets. Daily jobs run at 18:00 in Shanghai/New York;
  monthly full refresh uses the same sets.
- MarketDataService is a read facade, **not a read-through cache**. `db_first`
  uses DB if the instrument has any local history, even outside the requested
  range; otherwise it returns provider data. No calendar-gap checks or automatic
  writes occur. `db_only` returns available DB rows (possibly empty), and
  `remote_only` bypasses DB. Ordinary queries never create Instruments or daily bars.
- ETF Rotation reads its finite ETF/benchmark set through `db_first`; Trend and
  Quant use it only for their small benchmark dependencies, not their stock
  universes. Their main universe coverage checks remain DB-backed.
- Only explicit data maintenance jobs write daily history. A full refresh with
  any per-symbol request exception leaves that symbol's old history unchanged;
  successful empty responses are not request failures and never erase history.
