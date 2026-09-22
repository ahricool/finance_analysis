# 盘中确认 V1

目标是确认昨日候选的入场逻辑是否仍得到今日走势支持，不是盘中选股或收益预测。
规则在 `src/finance_analysis/intraday_confirmation/config.py`，V1 为未经回测验证的启发式规则。

## 候选与时间边界

CN/US 各一个 Celery Beat 任务，复用 alerts 队列。当地 09:20 首次冻结、09:25 可重试，交易时段每 5 分钟评估。
任务内部使用交易所日历，处理节假日、US DST/半日市和 CN 午休。GET 永不计算。

冻结时只读取**严格前一个交易日**、冻结时间之前生成的正式结果：

1. Confluence `strong_confluence=true`，按正式分数排序。
2. Trend `CANDIDATE` / `TRENDING`，按正式 alpha 排序。
3. Quant 使用既有正式版本选择，BUY 或前 20 名，排除 SELL/REDUCE/EXIT。

按上述顺序去重、最多 40 只，限 Instrument 中 ACTIVE STOCK；ETF/指数不作为股票候选。
保存来源、候选日期、理由、源生成时间和当日计算所需的昨日 Trend 基线。
不读任何 Preview，不使用当日价格增补候选，不用更早日期填补昨日缺失结果。
候选为空也冻结空池。池一旦冻结不再刷新，缓存丢失或错过冻结时段则当日停止确认，不能盘中补建。

本功能基于包含 Confluence 的分支；部署前需正常应用已有 Confluence migration，本功能没有新增 migration。

## 行情与指标

所有业务请求经过 MarketDataService，仅请求候选及一个 benchmark，不请求 market snapshot。
Tencent 已有 `fetch_quotes_for_codes` 通过标准 REALTIME_QUOTES capability 暴露；没有新增 Provider 或更改默认路由顺序。

- CN：Tencent 按代码批量报价；现有 Sina 5m 原生分钟线（Tencent 当前没有可复用分钟线接口）。
- US：现有 yfinance 报价和批量 5m 线。报价/分钟线时间各自展示，不将抓取时间冒充行情时间。
- benchmark：复用 Trend 的 CN `510300.SH` / US `SPY.US`。
- 历史：候选和 benchmark 只读 DB 前复权日线，不补写、不同步、不运行全市场 Preview。

仅使用当前交易日、常规交易时段、已闭合的 5m 线。重复 bar 按起点去重；未闭合、无效 OHLC 不参与计算。

| 指标 | 口径 |
| --- | --- |
| Gap | 当日 open / Provider previous close − 1；0.3% 内平开，2% 明显高开，5% 过度高开 |
| 5/15/30m | 完整开盘窗口最后 close / 当日 open − 1，同时计算 high/low；分钟不足或中间缺线即 unavailable |
| Opening Range | 前 5m high/low；后续连续 2 根闭合 5m close 超过边界 ±0.1% buffer |
| provisional VWAP | 从开盘连续闭合 5m 的 Σ((H+L+C)/3 × volume) / Σvolume；缺线、缺量或零总量 unavailable |
| Volume | 同一闭合线累计量 /（最近 20 根日线平均量 × 已过交易时间比例）；明确标注线性 approximation，排除午休、适配半日市 |
| 相对大盘 | 股票 price/open−1 减 benchmark price/open−1，数据时间差最多 5 分钟 |
| 相对行业/ETF | unavailable；现有行业日线分数不是行业盘中收益，也没有可靠股票→ETF 映射 |

行情超过 20 分钟、分钟线比报价落后超过 5 分钟，或数据不完整时不推进状态。
VWAP 与 Volume 的基准时间为最后一根闭合线，价格可以来自更近的报价；页面同时展示这些时间。

## Temporary Trend

直接复用 `calculate_features`、`calculate_trend_score`、`calculate_rs_score`、`transition_state`、
`calculate_fragility`、`classify_lifecycle`，没有复制 Trend 算法，也不调用正式 run/save。

当日 OHLCV 来自报价；DB 前复权历史使用 Provider previous close / DB 最后 close 比例对齐到当日价格基准，
避免除权前后直接拼接 raw/adjusted。历史必须截止昨日，缺少上一收盘价、足够历史或昨日正式 Trend 则 unavailable。

昨日横截面 slope percentile 固定，今日价格/RS 特征重算，不对候选小池重新排名。
Trend Score delta 因而是**固定昨日横截面基线下的临时变化**，不能解读为正式盘中 Trend 排名。
生命周期沿用昨日持续天数加一并由同一分类函数推导；3D/5D 衰减和 rank 脆弱度不完整，
所以 temporary fragility / fragility delta 为 unavailable，生命周期为 provisional。

- broken：Trend state 或 lifecycle 为 BROKEN。
- deteriorating：WEAKENING 或 trend score 较昨日下降至少 5 分。
- improving：trend score 增加至少 5 分。
- intact：其余可计算情况。

不写正式 Trend snapshot、lifecycle、rank、缓存或下一轮计算输入。

## 状态、理由与追高

**CONFIRMED** 同时满足：连续闭合线突破 OR high、价格高于 VWAP、完整 15m 收益非负、
没有明显高开低走、相对大盘至少 +0.3%、量比至少 1.2x、Temporary Trend intact/improving。
指标缺失不视为负面，但缺少必需证据不能确认。

**FAILED** 满足组合结构：

- 连续闭合线跌破 OR low，且另有一项：VWAP 距离 ≤−0.5%、相对大盘 ≤−0.8%、
  完整 15/30m ≤−1%、高开至少 2% 后自 open 回落至少 1.5%、Temporary Trend broken；或
- Temporary Trend broken，同时弱于 VWAP 与 benchmark 上述阈值。

其余为 **WAIT**，不是负面状态。每次评估均保存结构化 reason code/text。

状态变化另需连续 2 次**不同、更晚的闭合线**评估，间隔至少 4 分钟且两次证据相隔不超过 20 分钟。
同一根线反复手动运行不累计。缺数据/中断条件重置 pending。CONFIRMED 保持到稳定 FAILED；
FAILED 当天锁定，恢复时仅显示 `current_price_recovered`。保存状态变更理由与当前观察理由，避免混淆。

确认分按 Price 45 / RS 25 / Volume 20 / Trend 10 加总，减追高 penalty（0/5/10），限制 0–100。
分数用于排序，不决定状态。数据缺失不生成负向理由。

Gap≥5%、距昨收≥8%、距 VWAP≥3.5% 或开盘30m≥5% 任一触发 HIGH chase risk；否则 Gap≥2% 为 MEDIUM。
允许 CONFIRMED + HIGH，表示趋势确认但已不适合追价。

## 存储、API 与页面

Redis `intraday_confirmation:{market}:{trade_date}` 保存当天完整原子快照：冻结候选、当前指标、稳定计数、
first_confirmed_at、failed_at、max score、状态变更理由。当地午夜过期，不保存分钟线。
同市场任务用 Redis lock 串行；cache 写失败使任务失败，任务硬时限小于锁时限。

V1 不新增 DB 业务表，也不保存跨日确认历史。优点是小而独立；代价是 Redis 丢失则当天停止，隔日无法复盘。
现有 TaskRecord 仍保存任务执行结果摘要，不保存分钟输入。若以后需要回测/审计再设计状态事件持久化。

- `GET /api/v1/intraday-confirmation?market=CN&state=WAIT&candidate_source=trend`
- `GET /api/v1/intraday-confirmation/{code}?market=CN`
- 管理员 `POST /api/v1/intraday-confirmation/run`，body `{ "market": "CN" }`，只排队。
- 任务：`intraday_confirmation_cn/us`，既有任务中心可跟踪。
- 页面：研究 → `/research/intraday-confirmation`，只读取快照，手动刷新。
- 排序：CONFIRMED → WAIT → FAILED；组内 score 降序、chase risk 升序、code 稳定排序。
- Dialog 展示昨日逻辑、完整 Price Action/RS/Trend、当前理由及状态变更理由、数据/生成时间。

没有实现全市场分钟选股、分钟 Quant、ML/LLM、自动下单、新 Provider、永久分钟库、60D+ 新指标、复杂回测，
未修改 Trend/Quant/ETF 正式策略规则，也不发送交易通知。

## 验证

`pytest tests/intraday_confirmation -q` 覆盖冻结日期、非候选排除、窗口完整性、VWAP 缺失、真实闭合突破、
失败组合、不同 bar 的稳定机制、FAILED 锁定、延迟时间、只读 GET、管理员任务、日历及 Tencent 定向路由。
前端测试覆盖 API snake/camel 转换、null 与数据时间、筛选、候选理由、独立追高风险和空池提示。
