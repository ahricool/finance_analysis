# 盘中确认 V1

目标是确认昨日候选的入场逻辑是否仍得到今日走势支持，不是盘中选股或收益预测。
规则在 `src/finance_analysis/intraday_confirmation/config.py`，V1 为未经回测验证的启发式规则。

## 候选与时间边界

CN/US 各一个 Celery Beat 任务，复用 alerts 队列。当地 09:20 首次冻结、09:25 可重试，交易时段每 15 分钟评估（每小时 00/15/30/45 分）。
任务内部使用交易所日历，处理节假日、US DST/半日市和 CN 午休。GET 不重跑盘中评估，只用持久化日线计算已实现收益。
评估仍读取已闭合的 5m 行情；状态变化需要连续两次有效评估，通常至少间隔 15 分钟。

冻结时只读取**严格前一个交易日**、冻结时间之前生成的正式结果：

1. Confluence `strong_confluence=true`，按正式分数排序。
2. Trend `CANDIDATE` / `TRENDING`，按正式 alpha 排序。
3. Quant 使用既有正式版本选择，`avoid` 永远排除（即使排名第 1）；`buy` 纳入；`watch` / `hold` 仅在排名前 20 时纳入。

按上述顺序去重、最多 40 只，限 Instrument 中 ACTIVE STOCK；ETF/指数不作为股票候选。
保存来源、候选日期、理由、源生成时间和当日计算所需的昨日 Trend 基线。
不读任何 Preview，不使用当日价格增补候选，不用更早日期填补昨日缺失结果。
候选为空也冻结空池。池一旦冻结不再刷新；重启或 Redis 丢失后从 PostgreSQL 恢复。错过冻结时段且数据库无当日池则不能盘中补建。

部署需要应用 `0072_intraday_confirmation`，接在 `0071_user_avatar` 后；不改已有 migration。

## 行情与指标

所有业务请求经过 MarketDataService，仅请求候选及一个 benchmark，不请求 market snapshot。
Tencent 已有 `fetch_quotes_for_codes` 通过标准 REALTIME_QUOTES capability 暴露；没有新增 Provider 或更改默认路由顺序。

- CN：Tencent 按代码批量报价；现有 Sina 5m 原生分钟线（Tencent 当前没有可复用分钟线接口）。
- US：现有 yfinance 报价和批量 5m 线。报价/分钟线时间各自展示，不将抓取时间冒充行情时间。
- benchmark：复用 Trend 的 CN `510300.SH` / US `SPY.US`。
- 历史：候选和 benchmark 只读 DB 前复权日线，不补写、不同步、不运行全市场 Preview。

行情获取阶段共用 `MARKET_DATA_BUDGET_SECONDS=210` 秒预算，报价/分钟线/DB 日线读取并行。
Sina 分钟请求最多 6 个并发；Yahoo 报价沿用 `Ticker.info`，使用已有 max_workers 配置（默认 3，上限 6），
继续读取真实 `regularMarketTime`。两个 Provider 使用固定共享线程池，并逐股隔离失败。
Provider 提前 2 秒收集已完成的部分结果，外层总预算到期则停止等待未完成来源；缺失数据走既有 unavailable/WAIT 规则。
取消未开始的请求，到期不再重试。Python 无法强制中断正在执行的 SDK 调用，这些调用可能在后台结束，
但不会修改已返回批次或快照；共享线程池限制后续任务的线程数量。Sina 不在并发请求中修改进程级 socket 默认超时。

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

确认分使用 Price 45 / RS 25 / Volume 20 / Trend 10 权重，仅按可用证据归一化，减已知追高 penalty（0/5/10），限制 0–100。
分数用于排序，不决定状态。数据缺失不生成负向理由。

Gap≥5%、距昨收≥8%、距 VWAP≥3.5% 或开盘30m≥5% 任一触发 HIGH chase risk；否则 Gap≥2% 为 MEDIUM。
允许 CONFIRMED + HIGH，表示趋势确认但已不适合追价。

## 存储、API 与页面

PostgreSQL `intraday_confirmation_snapshot` 以 `(market, trade_date)` 为主键，保存每日完整原子快照：
冻结候选、当前指标、稳定计数、first_confirmed_at、first_confirmed_price、first_confirmed_quote_time、
首次确认报价中的原始当日 open、failed_at、max score 与状态变更理由。不保存分钟线或每次评估事件。
每个交易日保留一份最新状态；冻结候选/来源证据及首次确认基准一经写入不再改变。
后续 CONFIRMED、转为 FAILED、重复执行或任务重试均不重置首次确认价格/时间；首次确认缺失的价格基准也不能用后续报价补填。

同市场/交易日用 PostgreSQL session advisory lock 串行评估，没有 Redis TTL 锁过期竞态；
冻结插入使用主键冲突保护，更新使用行锁与 revision CAS 拒绝旧写入。行情请求在业务事务外进行；
整份快照更新在同一事务提交，数据库写失败使任务失败。GET 和任务均以数据库为事实源，不依赖 Redis 缓存。
TaskRecord 仍只保存任务执行摘要，不替代业务快照。

### 首次确认收益率

- 仅在规则稳定状态第一次进入 CONFIRMED 时，冻结这一轮实际有效报价价格与原始开盘价；确认处理时间和报价时间分别保存。
- 3/5/10D 分别指**不含确认当日**的第 3/5/10 个交易所交易日收盘，按 CN/US 真实交易日历定位，处理假期、DST 与半日市；缺日不顺延。
- 收益率在 GET 时读取已持久化结果；尚未保存的期限可批量只读 `stock_daily` 计算，GET 不调用 Provider、不写任何数据。
- 首次确认价是原始盘中价格，而 DB 日线是前复权；用同日开盘价对齐：
  `当前前复权基准 = 冻结首次确认价 × 当前DB确认日open ÷ 冻结原始确认日open`，
  `收益率 = 目标日前复权close ÷ 当前前复权基准 − 1`。
  冻结价格保持不变。首次计算时确认日及窗口内日线必须来自相同 `data_source` 和完全一致的 `updated_at` 写入代次，
  才能证明共享复权尺度；单次查询并不能保证历史价格处在同一尺度。已有增量同步会忽略小幅复权变化，
  因此不能只依赖它的整段刷新判断。代次/来源不同或缺失时宁可留空，不推测因子。
- 既有确认任务每次先处理最多 10 个存在待到期收益的历史日，按最早检查时间轮转；即使当前不在交易时段也会检查。
  不新增 Beat 任务；正常工作日盘前/盘中调度自动补算，手动任务也可补算。第一次得到已成熟且同源同代次的完整窗口时，
  原子保存该期限的收益、完整 OHLCV 输入、来源、写入代次、目标日与计算时间。后续不覆盖已保存结果，
  避免历史滚出增量同步窗口或行情被清理后，原本有效的收益消失。历史查询不触发保存。
  未成熟/缺行情继续等待，超过 10D 不过期；始终缺失的旧记录通过轮转不会饿死较新记录。
  冻结时缺少不可补救的首次价格/开盘价/报价时间不会进入补算队列。若服务长期停止且历史已变为混合尺度，
  无法验证的未保存期限仍为空，必须等待一致的历史日线恢复，不进行猜测性回填。
- 确认日期/报价时间、正数价格或开盘对齐基准缺失、日历不可用、目标尚未收盘、
  确认日或期间任一交易日 OHLCV 缺失/无效（含停牌零量）时，对应期限为 null；表格留空，不显示 0%。
  较晚期限缺行情不影响已完整的较短期限。确认后转为 FAILED 仍保留首次确认收益。已保存的成熟收益不会因后续数据修订或更换来源自动重算。
- 这是事后价格收益观察，不代表真实成交、组合收益或含成本回测。

### 部署切换与历史边界

旧版只存 Redis 的历史没有可靠首次确认价，午夜过期后无法重建。因此本 migration 不伪造或追溯回填旧确认历史，
也不从旧缓存导入可能已经确认但没有首次价格的记录。升级后下一个开盘前冻结开始持续保存；
若盘中升级且数据库没有当日池，当日保持未冻结，等待下一次正常盘前冻结。后续 Redis 丢失不再影响已持久化池。
数据库升级由既有部署流程执行，本变更本身不运行生产迁移。

- `GET /api/v1/intraday-confirmation?market=CN&state=WAIT&candidate_source=trend&trade_date=2026-09-21`
- `GET /api/v1/intraday-confirmation/{code}?market=CN&trade_date=2026-09-21`
- `GET /api/v1/intraday-confirmation/dates?market=CN`，返回持久化日期降序列表；省略 trade_date 默认市场当日，不回退历史。
- 管理员 `POST /api/v1/intraday-confirmation/run`，body `{ "market": "CN" }`，只排队。
- 任务：`intraday_confirmation_cn/us`，既有任务中心可跟踪。
- 页面：研究 → `/research/intraday-confirmation`，只读取快照，手动刷新；日期选择可复盘，历史视图不能提交当日确认任务。
- 排序：CONFIRMED → WAIT → FAILED；组内 score 降序、chase risk 升序、code 稳定排序。
- Dialog 展示昨日逻辑、完整 Price Action/RS/Trend、当前理由及状态变更理由、数据/生成时间。

没有实现全市场分钟选股、分钟 Quant、ML/LLM、自动下单、新 Provider、永久分钟库、60D+ 新指标、复杂回测，
未修改 Trend/Quant/ETF 正式策略规则，也不发送交易通知。

## 验证

`pytest tests/intraday_confirmation -q` 覆盖冻结日期、非候选排除、窗口完整性、VWAP 缺失、真实闭合突破、
失败组合、不同 bar 的稳定机制、FAILED 锁定、延迟时间、只读 GET、管理员任务、日历及 Tencent 定向路由。
前端测试覆盖 API snake/camel 转换、null 与数据时间、筛选、候选理由、独立追高风险和空池提示。

### 缺失数据展示

本轮 Quote 过期或闭合分钟线不足时，确认分为 null、有效权重为 0、追高风险为 UNKNOWN；已有 CONFIRMED / FAILED 状态保留。
行情 fresh 时，评分只按实际可用维度归一化到 100 分，再扣除已知风险罚分；价格的三个子项各占价格权重的三分之一。
`available_score_weight` 显示参与评分的原始权重（满额 100），缺失子项不加分也不扣分；完全无可用维度时返回 null。
追高风险需要 fresh 行情及 Gap、相对昨收收益、VWAP 距离；30m 完整窗口可用后补充判断。必要数据缺失时返回 UNKNOWN，使用中性样式。
盘前冻结结果同样为 null / UNKNOWN，排序时同状态的 null 分数放在有分数的结果之后。

持久化/收益测试另外覆盖重复冻结、竞争 revision、失败回滚、重启恢复、不可变首次价格、复权缩放、未收盘、缺日/停牌、假期/半日市和迁移单 head。
