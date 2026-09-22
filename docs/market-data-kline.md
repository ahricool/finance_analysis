# 统一金融 K 线

`MarketKLineChart.vue` 只绘图，使用 KLineChart 10.x 的 `init/dispose`、
`setSymbol/setPeriod/setDataLoader`，实时单根更新走 loader 的
`subscribeBar/unsubscribeBar`。切换标的、周期或 sourceKey 时销毁并重新初始化；
历史数据替换时 `resetData`；ResizeObserver 与 Vue 卸载一起清理。
红涨绿跌，主题跟随 `useTheme`，默认 VOL，日线叠加 MA5/10/20。
其他统计图继续使用 ECharts。通用组件接受 `pricePrecision`，BTC 明确传 2；
DailyKLineCard 从展示的 OHLC 推导 2～4 位小数（12.35 → 2、1.237 → 3、0.8567 → 4），
忽略第 4 位之后的浮点噪声。KLineChart 将 symbol 精度同步到 MA 等价格指标。

## 日线接口

`GET /api/v1/market-data/daily-bars/{symbol}`，沿用会话鉴权。

- `symbol` 使用现有 canonicalization，响应如 `600519.SH`、`AAPL.US`。
- `start_date`、`end_date` 为可选 ISO 日期，含首尾。
- CN/US 的 end 默认市场本地当日，HK 保持 UTC 当日；start 默认 end 前 365 个自然日。
- start 晚于 end 或非法日期返回 422。
- 返回 `symbol/market/interval/adjustment/source/items`；interval 固定 `1d`，
  adjustment 固定 `forward`，source 表示历史 K 来源（`database` 或实际 provider），空结果可为 null；不代表今日临时 K 来源。
- items 按日期升序，包含 `trade_date/open/high/low/close/volume/amount`。
- 无数据返回空 items；历史日 K 上游失败且没有恢复到数据时返回 503。今日行情失败不导致 503。

历史已完成日 K（DB/provider finalized daily bars）继续调用 `MarketDataService.get_daily_bars(source_policy="db_latest", adjustment="forward")`：

1. 复用现有市场交易日历，在市场时区以 `min(当前时刻, end_date 当天结束)`
   求最近一个已完成交易日。历史请求使用历史截止日，盘中不要求当天的收盘 K。
2. DB 有该 symbol 在这个交易日的数据，整个请求直接用 DB，不检查中间 gap，
   不因停牌、IPO 或历史不足回源。请求区间外用于 freshness 判断的数据不进入响应。
3. DB 无此日数据（包括无该证券日线）或查询异常，调用现有 `router.route_daily`
   获取整个请求窗口，不合并或补取 stale tail。DB 异常先 warning。
4. router 保持 CN TickFlow → Fuyao → yfinance、US yfinance → TickFlow、
   HK Longbridge → yfinance 的既有顺序。
5. 降级取得数据即可展示，即使存在早先 provider 的 sticky request error。

例如周日 9/20 查到最近完成交易日为 9/18，有 9/18 即用 DB；9/18 盘中只要求 9/17，
收盘后要求 9/18。历史 end_date=8/9 周日则要求 8/7，与今天无关。
原有 `db_first` 与 `db_fresh` 不变；本 API 不使用 `db_fresh`。

> Daily K HTTP API is read-only.
> DB freshness is determined only by whether the latest completed trading day on or before the requested end date exists for the symbol.
> If it exists, trust DB as-is. Do not check historical gaps.
> If it does not exist, fall back to the configured market-data providers for this request only.
> Provider fallback must never trigger database synchronization or persistence.

所有查询均不写库，不调用 Celery / sync task，不刷新 DB，不补 gap 或 DB tail。
旧 `/stocks/{stock_code}/history` 保留，新 UI 不使用它。

## 今日实时日 K

历史查询完成后，同一个接口通过 `MarketDataService.get_intraday_daily_bar()` 在内存中补充今日 K：

- 复用市场时区、`market_trading_date` 和交易日历；仅当请求首尾范围包含市场本地今天、
  且今天为交易日时尝试。周末、节假日、历史区间不请求实时行情，HK 保持现状。
- 此场景显式指定 CN：**Fuyao → Longbridge**，US：**yfinance → Longbridge**。
  不改变全局 REALTIME_QUOTES、DAILY_BARS 或 Streamer 的优先级。
- Quote 的 `quote_time` 必须带时区，转换到市场本地日期后等于今天。
  US yfinance 使用同一 regularMarket payload 的行情时间和 OHLCV，不能用请求时间冒充行情时间；
  Fuyao 和 CN/US Longbridge 缺少源时间时保留为空。昨日残留或时间缺失不可构造今日 K。
- `open/high/low/close` 分别取 `open_price/high/low/price`，必须有限、为正，
  且 high/low 包含 open/close；volume/amount 直接来自 Quote，并通过日 K 校验。
- 主 Provider 失败、缺数据、时间过期或 OHLC 无效均继续尝试 Longbridge；
  全部失败则保留历史结果。已有当天历史 K 时由有效实时 K 覆盖，按 trade_date 去重、升序返回。
- **今日 K 仅在查询时动态构造，不入库**，不触发 daily sync、Celery、补 gap，
  不参与或改变 `db_latest` 的 freshness 判断。历史 DB 仍只保存 finalized daily bars。
- `DailyKLineCard.vue` 直接绘制响应 items，无需额外行情请求或前端合并。

## 页面

- BTC：`BtcKlineChart` 仅转换现有 `useCryptoBtc` 的历史和当前分钟，REST/WS/HTTP fallback 不变。
- ETF Rotation 详情：Factor Grid 后、Raw Metrics 前。
- Trend Following 详情：核心指标后、breakdown 前。
- Quant Signal 详情：核心得分后、原因说明前。
- 自选股/持仓共用的 StockDetailDialog：实时行情后、自选/持仓信息前。

后三种策略详情的 `endDate` 使用返回详情/信号的 tradeDate（包含 Preview 当日），
而不是浏览器当天或外部列表日期。StockDetailDialog 使用最新可用窗口。
统一 `DailyKLineCard` 独立请求、展示 loading/empty/error/retry，取消过期请求并防止旧响应覆盖，
不会阻断业务详情主请求。前端以 UTC 午夜把日历日期转换成 timestamp。
