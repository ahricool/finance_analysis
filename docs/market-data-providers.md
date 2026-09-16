# 股票 Market Data Provider

外部 Provider 仅有 `tickflow`、`yfinance`、`longbridge`、`fuyao` 和
`easyquotation`。`ProviderRegistry.names()` 返回外部列表；数据库和 Streamer Redis
读取器是内部来源，`names(include_internal=True)` 可用于检查完整路由。

## 路由顺序

以 `integrations/market_data/config.py` 为事实源：

| Capability | CN | US | HK |
| --- | --- | --- | --- |
| DAILY_BARS | tickflow → fuyao → yfinance | yfinance → tickflow | longbridge → yfinance |
| MINUTE_BARS | streaming → longbridge | streaming → longbridge → yfinance | streaming → longbridge |
| REALTIME_QUOTES | streaming → longbridge → fuyao | streaming → longbridge → yfinance | streaming → longbridge → yfinance |
| LATEST_MARKET_SNAPSHOT | fuyao | — | — |
| MARKET_INDICES | fuyao | longbridge → yfinance | longbridge → yfinance |
| MARKET_STATS / SECTOR_RANKINGS | fuyao | — | — |
| INSTRUMENT_INFO | database → tickflow → longbridge → fuyao → yfinance | database → tickflow → longbridge → yfinance | database → tickflow → longbridge → yfinance |

本次只替换或删除原来源位置，没有提升 Fuyao 相对 TickFlow、yfinance 或 Longbridge
的优先级。easyquotation 仍用于 Tencent CN Trend Following / ETF Rotation Preview，
不参与通用 fallback。TickFlow → Longbridge 的证券主数据同步顺序不变。

## Fuyao 接入

设置 `FUYAO_API_KEY`，请求超时由 `FUYAO_TIMEOUT_SECONDS` 控制（默认 10 秒）。
密钥只放在请求头，不写日志、报告或仓库。未配置时返回明确失败，Router 按已有语义
fallback / fail-open；HTTP 错误和业务信封错误均检查，429 / 4001 不立即重试。

业务调用继续经过 `MarketDataService`。Provider 内部将数据转换为现有 canonical
models，价格为 CNY 元、成交量为股、涨跌幅为百分数值、时间为 aware UTC。
明确的交易所后缀必须保留：`000001.SH` 与 `000001.SZ` 是不同标的。

官方契约：[聚合文档](https://fuyao.aicubes.cn/llms-full.txt)。以下为接入路径：

| 数据 | Fuyao REST 路径（省略 `/api`） |
| --- | --- |
| 股票日线 / 快照 | `/a-share/prices/historical`、`/a-share/prices/snapshot` |
| 指数日线 / 六大指数快照 | `/a-share-index/prices/historical`、`/a-share-index/prices/snapshot` |
| ETF 前复权日线 / 快照 | `/fund/market/historical`、`/fund/market/snapshot` |
| 标的信息 / 目录 | `/meta/tickers/search`、`/meta/tickers/list` |
| 板块排行 | `/a-share-index/catalog/ths-index-list` + 指数快照 |
| 市场统计 | 股票全市场分页快照 + `/a-share/special-data/limit-up-pool`、`limit-down-pool` |
| CN 指数成分 | `/a-share-index/constituents/ths-stock-list` |
| 财务三表 | `/a-share/financials/income-statements`、`balance-sheets`、`cash-flow-statements` |
| 财务指标 / 估值 | `/a-share/financials/indicators`、`/a-share/valuations/snapshot` |
| 分红与复权事件 | `/a-share/corporate-actions/adjustment-factors` |
| 龙虎榜 | `/a-share/special-data/dragon-tiger-list` |

股票日线显式请求 `adjust=forward`；ETF 专用接口固定前复权，但响应 `adjust=null`；
指数没有复权事件，保持价格原值。标的类型由 Fuyao 目录确认，不靠代码猜接口。
股票/指数历史按最多 10 年、ETF 按最多 5 年拆窗；失败不把局部历史标为完整成功。
只有显式维护任务写数据库，查询不写库。

全市场快照按目录 offset 分页；缺页、重复或目录规模变化不能成为完整市场统计。
无价格且无成交活动的记录（例如停牌、尚未交易）列为 missing，排除于涨跌/平盘统计；
不将缺失补零。成交额缺失时总成交额为 null。涨跌停池使用快照交易日，接口失败不
伪造零涨跌停。行业与概念指数统一按涨跌幅排序，不将涨跌幅解释为资金流。

基本面保留 revenue、净利润/归母净利润、同比、ROE、毛利率、经营现金流、报表日期，
以及 PE TTM/MRQ、PB MRQ、PS TTM、PCF TTM。三表按报告期对齐；
`report_date` 为报告期末，`announcement_date` 为披露日，不使用披露季度查询指标。
估值缺失保留 null，负数不取绝对值；原有 quote 来源已经提供的 PE/PB 仍优先。
分红只统计已发生的税前现金分红，保留每股金额、除息日、TTM 金额及事件数；
未提供的登记日、公告日不补造。龙虎榜按现有回看天数请求交易日数据，最多 3 并发，
单日失败保留其他日期并标记 partial。

## 因来源收敛取消的能力

- 原国内分钟行情 fallback：仅保留 Streamer / Longbridge，没有 Fuyao 分钟 K。
- 业绩预告、业绩快报、机构持仓变化、十大股东持仓变化。
- 筹码分布、个股所属行业/概念板块反查。
- 个股和板块主力资金流：官方页面明确尚未开放外部调用。
- US S&P 500 / Nasdaq-100 自动成分更新：五个保留来源没有已接入的等价能力；
  reference sync 明确报告失败，保留既有成员，不清空 Universe。
- 原国内来源提供的 HK/US 专项 fallback，仅移除对应节点，保留其余顺序。

报告 schema、数据库 schema、策略计算、Preview 专用数据链、财经日历、新闻及
Streamer Redis schema 不变。可选基本面模块返回 failed / not_supported / partial，
不阻断股票分析。

## 开发验证与待观察事项

2026-09-16 开发验证：股票/ETF 日线、股票快照、六大指数、三表、财务指标、估值、
分红事件、行业/概念排行和涨跌停池均有成功响应。沪深300、中证500、中证1000
成分分别返回 300/500/1000 条；`932000.SH` 成分返回 1002，且目录搜索未找到，
中证2000 同步需继续观察 API 覆盖，失败时保留已有成员。

财务指标实测使用 `calculate_operating_income_yoy_growth_ratio` 和
`calculate_parent_holder_net_profit_yoy_growth_ratio`；适配器同时识别文档中公布的
同比 ID。后者为归母净利润同比，与报告的 `net_profit_parent` 配对。需关注官方
字段契约更新、缺失率、数据就绪时间、停牌记录、分页期间的跨时点偏差，以及
跨 Provider 前复权基准、复权事件后历史重算的一致性。此次不据此变更源优先级。

离线契约测试在 `tests/test_fuyao_provider.py`。真实接口检查只在开发时显式执行，
默认测试不依赖网络或密钥。
