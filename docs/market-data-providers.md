# 股票 Market Data Provider

外部 Provider 仅有 `tickflow`、`yfinance`、`longbridge`、`fuyao` 和
`easyquotation`。`ProviderRegistry.names()` 返回外部列表；数据库和 Streamer Redis
读取器是内部来源，`names(include_internal=True)` 可用于检查完整路由。

`USIndexConstituentProvider` 是独立 Reference Data Source，不属于 Market Data Provider，
不注册到 ProviderRegistry，也不参与日线、Quote 或分钟 fallback。S&P 500 / Nasdaq-100
当前成分继续通过 Wikipedia 同步；四个 CN 指数 Universe 恢复通过 AkShare
`index_stock_cons_csindex` 同步（000300 / 000905 / 000852 / 932000）。
`AkShareIndexConstituentProvider` 同样仅属于 Reference Data Source，不加入行情 registry
或 fallback。AkShare 及其传递依赖为此恢复，不恢复其旧行情/基本面实现。
ReferenceDataSyncService 独立路由这两类来源。请求失败或返回空成员时记录该 Universe
同步失败，不执行 replacement，保留数据库已有成员。

## 路由顺序

以 `integrations/market_data/config.py` 为事实源：

| Capability | CN | US | HK |
| --- | --- | --- | --- |
| DAILY_BARS | tickflow → fuyao → yfinance | yfinance → tickflow | longbridge → yfinance |
| MINUTE_BARS | streaming → longbridge | streaming → longbridge → yfinance | streaming → longbridge |
| REALTIME_QUOTES | streaming → longbridge → fuyao | streaming → longbridge → yfinance | streaming → longbridge → yfinance |
| LATEST_MARKET_SNAPSHOT | fuyao → easyquotation（腾讯） | — | — |
| MARKET_INDICES | fuyao | longbridge → yfinance | longbridge → yfinance |
| MARKET_STATS / SECTOR_RANKINGS | fuyao | — | — |
| INSTRUMENT_INFO | database → tickflow → longbridge → fuyao → yfinance | database → tickflow → longbridge → yfinance | database → tickflow → longbridge → yfinance |

本次只替换或删除原来源位置，没有提升 Fuyao 相对 TickFlow、yfinance 或 Longbridge
的优先级。easyquotation 用于 Tencent CN Trend Following / ETF Rotation Preview，
并作为 CN 全市场快照的备用来源；不参与逐股 Quote、指数或板块排行 fallback。
TickFlow → Longbridge 的证券主数据同步顺序不变。

## Fuyao 接入

设置 `FUYAO_API_KEY`，请求超时由 `FUYAO_TIMEOUT_SECONDS` 控制（默认 10 秒）。
密钥只放在请求头，不写日志、报告或仓库。未配置时返回明确失败，Router 按已有语义
fallback / fail-open；HTTP 错误和业务信封错误均检查。所有扶摇 API 统一经
`FuyaoProvider._get()` 请求：HTTP 429 / 业务码 4001 按 1、2、4 秒指数退避，
最多重试 3 次（含首次共 4 次），其他错误不重试。每次重试重新计算请求时间预算；
预算不足以完成等待并发起请求时直接结束。快照重试耗尽或其他失败后由 Router
切换 easyquotation，日志记录失败原因与 fallback 来源。

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
估值缺失保留 null，负数不取绝对值；流水线传入已取得的实时 Quote，沿用其 PE/PB，
不在受预算限制的基本面阶段重复启动无法限制 deadline 的 SDK Quote 链。
分红只统计已发生的税前现金分红，保留每股金额、除息日、TTM 金额及事件数；
未提供的登记日、公告日不补造。龙虎榜按现有回看天数请求交易日数据，
单日失败保留其他日期并标记 partial。

基本面入口用 monotonic deadline 限制请求调度，依次获取三表、指标、估值、分红，
再执行龙虎榜与板块排行。所有 Fuyao 请求共享剩余预算；不足 0.8 秒时不再启动请求，
否则 HTTP 四阶段 timeout 各不超过剩余时间的四分之一（最低启动值为每阶段 0.2 秒）。
这是同步协作式 deadline，不启动超时后继续运行的后台线程；HTTP 阶段超时并非操作系统
硬中断，DNS/持续分块响应仍受传输层语义约束。已成功数据保留，未执行块标记
`skipped_budget`；普通行情仍使用配置的默认 10 秒 timeout。

市场级缓存为进程内缓存，按 API 凭据与 transport 隔离，跨 Provider/Service 实例共享：

- `dragon_tiger:latest` 和 `dragon_tiger:{trade_date}`：最近 7 天 TTL 600 秒，
  更早日期 TTL 21600 秒；最新响应也填充对应日期缓存。
- `sector_rankings:CN`：完整 canonical 排行 TTL 300 秒，返回独立副本。
- 缓存最多 512 项，过期清理；单锁合并并发 cache miss，市场级加载最多一个并发，
  等锁消耗同一预算。失败不写入缓存，不清除其他日期已成功的数据。

冷缓存单股完整请求量为 `6 + D + 2 + ceil(S / 100)`（不含原重复 Quote 链），
其中 D 是实际回看交易日数，S 是板块指数数量。暖缓存后市场级请求为零，
单股最多保留 6 个财务/估值/分红请求；预算不足时更少。例如 D=20、板块快照
7–10 批时，从 35–38 次降至最多 6 次，另外省去重复 Quote 请求。首次冷加载
仍有原有数据量，不能将暖缓存收益理解为每次都只需 6 次。

Router 拒绝带 `failed_symbols[market]` 的全市场 Snapshot，即使其中 data 非空；
有后续 Provider 则 fallback，无后续 Provider 则返回无 data 的市场级失败。
单个 symbol 校验失败仍允许其余有效 Quote 返回。

已取消的个股板块反查不再生成字段或发起调用。收盘前复盘依赖该反查的候选链路
同步清理，维持当前实际的空候选结果；报告字段与 prompt 不变。

## 因来源收敛取消的能力

- 原国内分钟行情 fallback：仅保留 Streamer / Longbridge，没有 Fuyao 分钟 K。
- 业绩预告、业绩快报、机构持仓变化、十大股东持仓变化。
- 筹码分布、个股所属行业/概念板块反查。
- 个股和板块主力资金流：官方页面明确尚未开放外部调用。
- 原国内来源提供的 HK/US 专项 fallback，仅移除对应节点，保留其余顺序。

报告 schema、数据库 schema、策略计算、Preview 专用数据链、财经日历、新闻及
Streamer Redis schema 不变。可选基本面模块返回 failed / not_supported / partial，
不阻断股票分析。

## 开发验证与待观察事项

2026-09-16 开发验证：股票/ETF 日线、股票快照、六大指数、三表、财务指标、估值、
分红事件、行业/概念排行和涨跌停池均有成功响应。沪深300、中证500、中证1000
成分分别返回 300/500/1000 条；`932000.SH` 请求返回业务错误码 `1002`
（`Unknown thscode: 932000.SH`），不是返回 1002 条成分。目录搜索 `932000` 为空，
搜索“中证2000”仅返回 ETF。该成分接口官方仅声明 `thscode` 参数，无分页参数；
实测增加 `limit/offset` 或 `page/size` 后仍返回相同错误，未取得任何有效成分数据。
因此四个 CN Universe 已恢复原 AkShare 成分来源；失败或空结果仍保留已有成员。
2026-09-17 通过恢复后的适配器实际请求，四个指数分别返回 300 / 500 / 1000 / 2000 条，
canonical code 去重后数量相同。AkShare 依赖的 openpyxl/xlrd 用于上游成分文件读取，
与已删除的用户股票列表导入功能无关。

财务指标实测使用 `calculate_operating_income_yoy_growth_ratio` 和
`calculate_parent_holder_net_profit_yoy_growth_ratio`；适配器同时识别文档中公布的
同比 ID。后者为归母净利润同比，与报告的 `net_profit_parent` 配对。需关注官方
字段契约更新、缺失率、数据就绪时间、停牌记录、分页期间的跨时点偏差，以及
跨 Provider 前复权基准、复权事件后历史重算的一致性。此次不据此变更源优先级。

离线契约测试在 `tests/test_fuyao_provider.py`。真实接口检查只在开发时显式执行，
默认测试不依赖网络或密钥。
