# 统一金融 K 线

`MarketKLineChart.vue` 只绘图，使用 KLineChart 10.x 的 `init/dispose`、
`setSymbol/setPeriod/setDataLoader`，实时单根更新走 loader 的
`subscribeBar/unsubscribeBar`。切换标的、周期或 sourceKey 时销毁并重新初始化；
历史数据替换时 `resetData`；ResizeObserver 与 Vue 卸载一起清理。
红涨绿跌，主题跟随 `useTheme`，默认 VOL，日线叠加 MA5/10/20。
其他统计图继续使用 ECharts。

## 日线接口

`GET /api/v1/market-data/daily-bars/{symbol}`，沿用会话鉴权。

- `symbol` 使用现有 canonicalization，响应如 `600519.SH`、`AAPL.US`。
- `start_date`、`end_date` 为可选 ISO 日期，含首尾。
- end 默认 UTC 当日；start 默认 end 前 365 个自然日。
- start 晚于 end 或非法日期返回 422。
- 返回 `symbol/market/interval/adjustment/source/items`；interval 固定 `1d`，
  adjustment 固定 `forward`，source 为 `database` 或实际 provider，空结果可为 null。
- items 按日期升序，包含 `trade_date/open/high/low/close/volume/amount`。
- 无数据返回空 items；上游失败且没有恢复到数据时返回 503。

入口只调用 `MarketDataService.get_daily_bars(source_policy="db_first", adjustment="forward")`：

1. 有本地历史时读取请求区间，来源为 database。
2. 证券不存在或从未存过日线时，走现有 `router.route_daily`。
3. 数据库读取异常时，服务层 warning 后走同一 router。
4. router 保持 CN TickFlow → Fuyao → yfinance、US yfinance → TickFlow、
   HK Longbridge → yfinance 的既有顺序。
5. 降级取得数据即可展示，即使存在早先 provider 的 sticky request error。

保留 db_first 的“已有任何历史即信任 DB”语义：若仅请求区间无记录而区间外有历史，
返回空结果，不自动补 gap。所有查询均不写库，不触发行情同步。
旧 `/stocks/{stock_code}/history` 保留，新 UI 不使用它。

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
