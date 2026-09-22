# Unified Signal Center v1

Signal Center 主动读取既有 PostgreSQL 正式结果，不由 Trend / Quant 等任务推送。
不运行选股模型，不计算 composite score，不下单，不修改持仓或 Trade Engine。

## 候选与输入

| 来源 | 新增候选 | 读取依据 / 保存的上下文 |
| --- | --- | --- |
| Trend | 全部股票排名前 5%，向上取整；另补最多 20 只显著上升股票 | `rank`；补充范围是当前前 5%–10%、相对前次快照上升至少 `ceil(全榜数量 * 10%)` 名。保存前次日期、rank/state、原始 alpha/trend/RS/breakout score、lifecycle、duration、fragility、价格与已有收益/均线距离/量比/相对强度等字段 |
| Quant | 前 3 只 | 复用固定市场 Universe 的 `latest_signals` 正式日期/模型版本选择，按 `universe_rank`。为其他来源候选补齐同日已有 Quant 上下文；不按预测收益再排名 |
| Industry Strength | CN 前 5 个行业，每行业最多 3 只 | 行业 `strength_rank`，成员按已有物化 `trend_rank`。保存行业原始 strength/state/排名变化/加速度/RS；保留多重行业归属，不挑最高分归属 |
| ETF Rotation | 不新增股票 | 当日前 10 ETF，按现有 `rank`，保留原始 score/state/过热/收益变化；没有可靠股票映射，因此仅作为市场背景 |
| Market Regime | 不新增股票 | 当日 Trend summary 与 ETF market snapshot 各自的 regime、score、coverage/diagnostics，不把两个体系强行统一 |

所有来源只使用 `trade_date == signal_date` 的证据。Quant 若仅有旧结果，记录 `stale`，不纳入。
行业成分只有最新表，必须与当日行业快照 `updated_at` 完全一致，且属于当前最新正式日期；不能用当前成员解释历史。
Intraday Confirmation、Trend/ETF Preview 都是 Redis 临时状态，不加入正式每日输入。
Confluence 自有加权分数不加入此处；龙虎榜暂不进入 Signal Center 的候选与决策。

候选按 canonical symbol 去重，保持字典序，不计算跨模块综合分。
每只候选记录 `symbol/market/name/nominated_by/trend/quant/industry/price/etf_relation`。
顶层记录 `schema_version/market/signal_date/captured_at/source_availability/dependencies/selection_rules`、
`market_regime/etf_context/limitations`。每个来源含 `data_as_of/generated_at/status/count`，行级证据也保留来源日期。
只存实际使用的精简上下文，不重复保存所有源表诊断 JSON。

## 数据比较与候选范围

2026-09-23 只读检查本地生产 Docker 数据：最近正式 CN 2026-09-22 有 3,794 个 Trend 排名，前 5% 为 190 只；
US 2026-09-21 有 918 个排名，前 5% 为 46 只。近两周样本中：

| 范围 | CN 距 MA20 中位数 | US 距 MA20 中位数 | CN 弱状态占比 | US 弱状态占比 |
| --- | --- | --- | --- | --- |
| 前 1% | 18.7% | 10.4% | 0.0% | 0.0% |
| 第 3%–5% | 10.1% | 4.7% | 1.6% | 6.2% |
| 第 5%–10% | 7.1% | 3.1% | 8.1% | 15.8% |

弱状态指 IDLE / WEAKENING / BROKEN。范围选择用于兼顾过热风险与候选覆盖，**不是收益回测或已验证最优阈值**。
不盲目扩到全部前 10%，只补充其中的显著上升股票。前次快照日期、前次总体数量明确提供，排名变化不声称恒为 1D。
实际 dry run 初始去重池 CN 213 只、US 54 只，包含其他模块候选。
其中 Trend 提名 CN210、US51；改为5桶后分别为42/42/42/42/42与11/10/10/10/10。
正常每市场5次初筛+1次最终判断，两市场共12次（未计请求重试）；不足5个非空桶时更少。

## 两阶段 LLM

所有调用经现有 `LLMClient.complete_text`，复用 API/CLI backend、重试、usage/audit 和 CLI 全局 PostgreSQL advisory lock。
Signal Center 不引入第二套 LLM 并发机制。自身每天每市场复用 `PostgreSQLAdvisoryLock` 防止重复运行；业务事务不跨 LLM 网络调用。

1. Trend 扩展池按原始 `rank` 升序（同 rank 按代码）固定轮流分入5桶：排序第1/6/11…进第1桶，第2/7/12…进第2桶，以此类推。桶内保持 rank 顺序，各桶人数最多相差1；不足5只时保留空桶、不调用空桶 LLM。每个非空桶顺序初筛，仍保留0–5只，不先截成Top20。
   `candidate_snapshot.screening_plan` 冻结 `rank_round_robin_v1` 方法和5桶完整代码列表，失败重试复用原分桶与已完成结果。旧版已冻结任务保持旧40只批次，不重新解释历史初筛。
2. 初筛选择与 Quant3 / Industry 候选求并集，发送最终跨模块上下文。所有原始初筛输入仍保留在每日快照。
3. 严格输出一个对象：`market/signal_date/decision/symbol/confidence/thesis/positive_signals/risks/invalidations`。
   `BUY` 必须恰好一个候选代码且具有依据、风险、失效条件；`NO_TRADE` 必须 `symbol=null`。
   校验市场、日期、候选集合、数组数量、重复 JSON 字段，拒绝多对象或额外推荐字段。
   允许单个 Markdown JSON 围栏，不修复畸形 JSON 或抽取局部答案。
4. 输入不足为 `skipped`；LLM/校验失败为 `failed`，不能伪装成 `NO_TRADE`。

Prompt 强調共振、冲突、追高/过热、生命周期、行业边际变化及市场环境；不联网、不推断股票ETF关系、不做仓位建议。
新任务版本为 `signal-center-v1.1-rank-buckets`。精简掉重复诊断字段后，CN/US 的真实 CLI dry run 均完成且通过结构校验。
若 CLI 使用默认模型且 transport 未回传名称，明确保存 `unreported:cli/agy`，不伪造模型名称；
需要精确模型可复现性时应在现有 LLM 配置中显式指定 `LLM_CLI_MODEL`。API 则使用返回的模型名称。

## 持久化与迁移

新增 `0067_signal_center`，创建 `signal_center_run`：

- 复合主键 `(market, signal_date)`，每天每市场最多一个最终结果。
- `status`：pending / completed / failed / skipped；`decision`：BUY / NO_TRADE；`selected_symbol/confidence`。
- `candidate_snapshot JSONB`、`analysis JSONB`（thesis/positive_signals/risks/invalidations）。
- `prompt_version/system_prompt/prompt` 保存初始输入；`screening JSONB` 保存每批实际 prompt、结果、模型和时间；
  `final_prompt/raw_response/model/backend/created_at/completed_at/error` 保存最终调用证据。
- SQL CHECK 限制市场、状态、confidence、decision 与 symbol 的组合；completed 不能没有 decision。

输入在首次 LLM 前提交；成功初筛批次逐批提交。失败重试使用保存的输入及已完成批次，不读取当前市场结果重建历史。
completed / skipped 不覆盖。历史 GET 只读取这张表，不联查当前行情补解释。
轻量收益回看见下节；不新增收益表或空收益列。

## 历史信号收益回看

用户追加范围：为已完成 BUY 信号提供独立 `evaluation`，在 daily/history/detail GET 中批量读取已存 `stock_daily` 后计算。
不修改选股 snapshot、历史解释或 Prompt，不调用 LLM、远程行情或新增任务/迁移。NO_TRADE、failed、skipped 不计算收益。

- 方法版本 `next_session_open_v1`：信号日期之后、且开盘严格晚于 `completed_at` 的首个交易日开盘为基准。延期重试不能使用已经错过的开盘价。
- 交易日与收盘时刻复用 exchange-calendars 的 CN/US 日历，包含节假日、夏令时及提前收盘；日历不可用时不猜测。
- 1/3/5/10D = 基准交易日起第 N 个交易日收盘 / 基准开盘 − 1；1D 是买入当日的开收盘表现。
- MFE / MAE = 截至已观察的前10交易日，最高价/最低价相对基准的最大有利/不利变动（含0）。
- 收盘最大回撤 = 基准价及后续收盘序列，从历史高点到后续低点的最小收益率；它与 MAE 不同，也不代表日内路径回撤。
- 只用已收盘日期的前复权 OHLC；每个日期固定，缺日、零成交量、非法价格不补零、不用后一条行情替代。
- 某 horizon 的预期窗口缺行情则该收益为空；区间极值/回撤要求全部已收盘预期日期完整。未到期与缺行情分开显示。
- 每次响应对去重后的 `(symbol, date)` 一次批量读取，每信号最多10行。记录基准日期/价格、数据截至日、缺失日期、已观察天数及计算时间。

历史表增加四个收益列，详情显示基准、各目标日期、MFE/MAE/收盘回撤和缺失说明。
这是价格表现研究，非实际成交或账户收益，未计费用、滑点、涨跌停及其他成交约束；A股1D不代表允许当日卖出。
收益使用当前已入库的前复权日线，后续行情补齐、修订或复权调整可改变评价；**当时的选择与分析始终不变**。
不增加胜率排行、资金曲线、组合再平衡、执行模拟或完整 Backtest。

## 调度与页面

Beat 主动检查：CN 当地 20:40–21:50 每 10 分钟，US 当地 23:10–23:50 每 10 分钟，均为工作日并再次检查交易日/收盘。
现有任务中心自动注册两条任务，路由复用 `analysis` 队列，管理员可在任务中心手动运行当日任务。
所有来源完整就立即生成；有非关键来源缺失则等待后续 Beat 检查，不 sleep、不修改生产者任务。
截止时按可用当日来源运行：至少有一个 Trend/Quant 核心排名、候选和当日市场环境，否则保存 skipped 快照。
读取当天 TaskRecord，pending / processing / retrying 的来源不作为已完成证据；Quant 的 processing 包括 Qlib 异步 callback 阶段。
失败或缺失来源及日期显式给 LLM。截止后的长期故障不会自动创建未来日期的替代信号。

认证 GET：`/api/v1/signal-center/daily?signal_date=...`、`/history?limit=50&offset=0`、`/{CN|US}/{date}`。
页面沿用现有研究导航 `/research/signal-center`，两个市场卡片、日期、理由/风险/失效条件/来源日期，下面分页历史表及详情 Dialog。
默认今天使用各自市场当地日期，绝不把昨日信号默认为今日结果。无记录、分析失败、输入不足、NO_TRADE 分别展示。
Docker 无新增服务、provider 或队列；部署仍是 `bash deploy.sh`，应用启动按现有机制执行迁移。

## 本版不包含

自动交易、Position sizing、组合优化、策略改造、新因子、加权综合模型、Web Search、新闻 Agent、盘中临时数据整合、历史输入重建、完整 Backtest/Evaluation。
