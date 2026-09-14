# US Macro V1

US Macro 用 ETF 与 VIX 构建美股宏观看板，属于共享系统市场数据。
Macro 不自己同步行情，Macro API 不访问 yfinance；正式行情统一来自 `stock_daily`。

## 数据与同步

- 系统 Universe：`us_macro` / `US Macro` / `US`，类型 `STRATEGY`。
- 成员按展示顺序：`SPY.US, QQQ.US, TLT.US, UUP.US, USO.US, GLD.US,
  HYG.US, LQD.US, IWM.US, SMH.US, XLY.US, XLP.US, VIX.US`。
- 全部为 USD；VIX 是 INDEX，其余是 ETF。复用已有 Instrument ID 和名称。
- `us_daily_sync` include `us_sp500`、`us_index_etf`、`us_macro`。
  `us_index_etf` 的 ETF Rotation 成员和分类不变。
- Migration `0051_us_macro` 与启动参考数据 seed 幂等补齐证券、成员及 include；
  downgrade 仅删除 Macro Universe 及关系，保留共享证券与行情。
- 现有 `MarketDataSyncService("US")` 通过 MarketDataService 的 US Provider 链同步。
  管理员手动补数仍使用 Task Center 的 Market Data Sync，无 Macro sync API/任务。
- Yahoo 使用 `_US_INDICES` / `_HK_INDICES` 派生的集中 ticker overrides，包含 `VIX.US → ^VIX`。
  日线 normalizer 仅在显式 `instrument_type="INDEX"` 时将缺失 volume 记为 0；
  Yahoo 只对已知 index 映射传入此标记，STOCK/ETF 的缺失 volume 仍不接受。
  OHLC 仍必须完整，并经过现有路由层有效性校验。

## 计算

价格均为现有前复权 close；收益是小数，例如 `0.01` 表示 1%。
`ret_nd = close / close_n_bars_ago - 1`，n 为 1、5、20 个有效 bar。
至少 20 根 bar 才计算 MA20 趋势：close 大于/小于/等于 MA20 对应 UP/DOWN/NEUTRAL。
不足数据的收益、趋势为 null。

Ratio 配置在 `macro/config.py`：

| Key | 分子 / 分母 |
| --- | --- |
| HYG_LQD | HYG.US / LQD.US |
| IWM_SPY | IWM.US / SPY.US |
| SMH_SPY | SMH.US / SPY.US |
| XLY_XLP | XLY.US / XLP.US |

严格按共同日期 inner join，分母为 0 跳过，不填充交易日，不按数组位置相除。
Ratio 也按有效共同 bar 计算收益和 MA20 趋势；缺失交集、历史不足或过期标为 partial。
价格非有限或非正数不参与计算。

## Regime

下列条件取得全部对应权重；相反趋势得 0，NEUTRAL 得一半。

| 信号 | Risk On 条件 | 权重 |
| --- | --- | ---: |
| SPY | UP | 15 |
| QQQ | UP | 10 |
| HYG/LQD | UP | 15 |
| IWM/SPY | UP | 10 |
| SMH/SPY | UP | 10 |
| XLY/XLP | UP | 10 |
| VIX | DOWN | 20 |
| TLT | DOWN | 5 |
| UUP | DOWN | 5 |

TLT 仅作为小权重的防御需求代理，并非利率因果模型；以上均为可解释的 V1 规则。
历史不足和最新日期落后于 dashboard 基准的信号不计入分子或分母。
`signal_coverage = 可用权重 / 100`；小于 65% 时 risk_score、regime 均为 null。
否则 `risk_score = 已获贡献 / 可用权重 × 100`，
`>=65 RISK_ON`、`35<=score<65 NEUTRAL`、`<35 RISK_OFF`。
响应 `signals` 列出 key、risk_on_trend、trend、weight、contribution，缺失贡献为 null。

states 同样仅使用新鲜且有 MA20 的信号，否则为 null：
TLT 上/下为 rates EASING/PRESSURE；HYG/LQD 上/下为 credit HEALTHY/WEAK；
UUP 上/下为 dollar STRONG/WEAK；VIX 上/下为 volatility ELEVATED/CALM；持平为 NEUTRAL。

## API

两个 GET 均要求现有 Cookie 登录认证，不接受 uid，不存储用户数据。

### `GET /api/v1/macro/dashboard?as_of=2026-09-12`

返回 `trade_date, generated_at, regime, risk_score, signal_coverage, signals, states,
instruments, ratios, data_quality`。
Instrument 包括 `code/name/category/close/trade_date/ret_1d/ret_5d/ret_20d/trend`；
Ratio 包括 `key/name/value/trade_date/ret_1d/ret_5d/ret_20d/trend/signal/partial`。
每个成员的实际日期单独返回，防止将旧 close 当作基准日 close。

默认基准为已启用 `us_macro` 成员中最新有效 close 的日期；指定 as_of 后仅使用
`date <= as_of`，周末自然回退。不会用服务器今日假设行情存在，也不把基准降到最老成员的日期。
完全无数据仍返回 HTTP 200 的明确 partial 空状态：trade_date、score、regime 和各指标为 null。
这是数据库相对新鲜度：如果所有成员都停更，基准也停留在已有最新日期，不代表已同步至今天。

### `GET /api/v1/macro/series`

参数：

- `range=20d|60d|120d|250d|ytd`，默认 60d。
- `mode=price|normalized|relative`，默认 normalized。
- `symbols=SPY.US,QQQ.US,TLT.US`，省略且没有 ratio keys 时为全部 Macro 成员。
- `series=HYG_LQD,IWM_SPY,SMH_SPY,XLY_XLP`；只指定此参数时仅返回 Ratio。
- `benchmark=SPY.US`，仅用于 relative，必须来自固定 Macro 配置。
- 可选 `as_of` 与 dashboard 相同。

返回 `range/mode/benchmark/trade_date/series/data_quality`；每条曲线有
`key/code/name/category/points/partial`，points 为 `{date, value}`，按日期递增。
price 返回 close 或原始 Ratio；normalized 将每条曲线首个有效值归一到 100；
relative 对 symbol 与 benchmark 按日期求比值，再归一到 100。
Ratio 支持 price/normalized；`relative + series=<ratio>` 返回 422，避免对已有比值再次除以资产价格。
未知 symbol、ratio、range、mode 或非法日期返回 422。

Nd 范围指截至基准的最近 N 个数据库有效交易日（所有 Macro 成员日期的并集），
并非 N 个自然日，也不因单个标的缺失而扩展其曲线到更早日期。
YTD 从基准所在年份 1 月 1 日开始。各曲线从自身首个有效值归一化；若起点不同，
不应将归一化终值解读为完全相同时段的收益比较。

## Data quality 与实现边界

- `expected`：dashboard 固定为 13；series 为选中曲线依赖的证券（包含 benchmark、Ratio 两端）去重数。
- `available`：本次窗口有有效 close，且最新日期等于基准的证券数；`coverage=available/expected`。
- `missing_symbols`：截至 as_of 完全没有有效 close，或缺少启用 Universe 成员关系。
- `stale_symbols`：有历史，但最新日期早于基准；即使不在图表窗口中也报告 stale。
- `insufficient_history_symbols`：有历史但 dashboard 少于 21 根有效 bar，或 Nd series 窗口少于 N 根。
- `partial`：缺失、过期、历史不足或派生曲线不完整。单独一个 close 可计入 available，
  但不足 MA20/收益窗口仍通过 null 和历史不足列表明确暴露。

MacroRepository 批量读取 Universe、最新日期和窗口边界；价格唯一经
`MarketDataService.get_daily_bars(..., source_policy="db_only", adjustment="forward")`，
使用已有 StockRepository 批量历史读取。普通请求最多四次 SELECT，数量不随成员数增长。
没有远程补数、日线写入、Macro 行情表、snapshot、Redis cache 或派生指标持久化。
