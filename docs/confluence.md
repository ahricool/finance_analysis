# Signal Confluence V1

用于 2–14 天中短线研究的正式结果聚合层，不是预测模型或交易动作。
领域 `confluence/` 只读已有 PostgreSQL 结果；不会调用行情 Provider、LLM、Redis Preview 或策略重算。

## 存储与接口

迁移 `0065_confluence` 接在 `0064_dragon_tiger_flow` 后；`0066_confluence_rules` 为生成记录增加 nullable rules JSONB。

- `confluence_snapshot`：按 market + trade_date + instrument_id 唯一；分数、覆盖权重、维度计数、紧凑证据和理由。
- `confluence_run`：按 market + trade_date 保存生成时间、算法版本、本次实际使用的 rules 和各来源 availability；空榜和失败来源也可追溯。
- 同日写入在事务锁下 upsert，清理已不在结果内的股票。较早开始的任务不得覆盖较新任务。
- GET `/api/v1/confluence/ranking`：market、trade_date、min_score、min_signals、industry（精确代码/名称）、lifecycle、early_only、top_industry、strong_only、limit。
- GET `/api/v1/confluence/dates`、`/{code}`：仅读存量快照，详情使用明确 market/date。
- POST `/api/v1/confluence/run`：管理员，JSON `{market, trade_date?}`，异步返回 task_id。
- 页面：研究 → 多信号共振，`/research/confluence`。股票详情展示各维度、来源时间、贡献分数及 Why Confluence。

榜单默认至少 3 个有效维度；可降低门槛观察有限证据，页面会标注“证据不足”。
摘要按整个快照统计，不受筛选/前 200 条影响。Signals 为正向 / 有效维度，共 5 维。

## 已有来源与日期

| 维度 | 正式来源和字段 | 时间/映射边界 |
| --- | --- | --- |
| Industry | `industry_strength_snapshot` strength_rank、strength_score、state、rank_change_1d/3d/5d、momentum_acceleration_5d | 最新且不晚于目标日期的截面；通过 `industry_strength_constituent.stock_code` 精确映射。仅目标日等于最新行业快照日期、快照具有 members_observed_at 且快照/成分 updated_at 完全一致时使用（同一正式写入代次）；多行业歧义保留 unavailable，不挑最高分。|
| Trend | `trend_following_snapshot` state、trend_lifecycle、trend_score、rank、trend_duration_days、fragility_score、rs_score；features 中 trend_acceleration、trend_quality、rs_5d | 最新正式截面；另读前次正式排名并标明实际日期，不把跳日误称 1D。|
| Quant | `model_signal` universe_rank、final_score、signal、predicted_return、cross_section_score、model_version | 固定 cn_quant/us_quant Universe；复用 QuantRepository.latest_signals 的同日最新版本选择，不混合多个模型版本；不按今天 production 模型覆盖历史版本。|
| Dragon Tiger | `dragon_tiger_flow_batch.payload.sources.all.rows` net_value、org_net_value、hot_money_net_value、range_days、concepts | 目标日前最近 3 个 CN 交易日的记录；每只股票最新记录评分，同日优先 1D，再用原生 3D；两个榜单和不同日期不累计。概念方向复用已有 selected_rows/allocate/sum_known，仅作解释。缺记录为 unavailable；明确净流出为 negative。|
| ETF | V1 没有股票→ETF 可靠映射 | 已有 ETF Universe category/theme/risk_group 没有股票关联键，也没有历史 ETF 持仓映射。全部 unavailable，不做模糊名称或 LLM 推断。|

Industry 仅 CN；不能用证券名称或自由文本行业拼接 Fuyao industry_code。
行业成分表是最新表：更新后的成分不能回填更早历史日期。此前已保存的 Confluence 证据不受成分更新影响；主动重跑历史时，无法重建的映射保持 unavailable；该日已有有效 Industry signal 则原样保留，其他来源照常更新，并在 availability 标注保留数量。没有新增历史成分系统。
US 目前通常只有 Trend、Quant，默认榜单为空是正常结果；不降低默认门槛或人为填充维度。
龙虎榜机构与游资分类可能重叠；不推算“其他”，不从席位样本合成股票级净额。

每个 signal 保存 trade_date、source_generated_at、source_module，证据保留源 row id / batch id / model_version 及成分观测时间。
trade_date 边界表示“截至该交易日期的当前正式版本”，不是不可变的历史发布时点回放；来源事后修订仍可能被重跑读取。
来源日期可能早于目标日，不伪装为同日。未增加陈旧度扣分；使用时必须检查实际日期。
非核心来源读取失败仍可发布其他证据，manifest 标记 failed；无结果标记 unavailable。

## 简单评分规则

所有阈值集中 `confluence/config.py`，版本 `confluence_v1`。未经回测验证。
每次生成把 min_signals、strong_min_signals、strong_min_positive、strong_min_score 保存到 confluence_run.rules；评分和资格使用同一份 rules。历史 ranking 返回保存值，默认维度门槛也取保存值；迁移前 rules 为空的旧记录兼容回退当前配置。

| 维度 | 权重 | positive | negative（优先） |
| --- | ---: | --- | --- |
| Industry | 25 | rank ≤ 10 | state WEAK / COOLING |
| Trend | 30 | state CANDIDATE / TRENDING 且 lifecycle IGNITION / EMERGING / EXPANSION | state WEAKENING / BROKEN 或 fragility ≥ 70 |
| Quant | 20 | buy；或非 avoid 且 rank ≤ 20 | avoid（不受排名覆盖） |
| ETF | 15 | 保留适配规则：rank ≤ 10、candidate 且 BUY/HOLD；当前无映射不启用 | WEAK / EXHAUSTED / COOLING |
| 龙虎榜 | 10 | 最近一次记录 net_value > 0 | net_value < 0 |

Quant 的真实状态为 buy/watch/hold/avoid；watch/hold 在不满足 Top Rank 辅助条件时为 neutral。有数据但不满足上述正负条件为 neutral。positive / neutral / negative 分别贡献权重 × 1 / 0.5 / 0；unavailable 的 score 为 null，权重不入分母。

`confluence_score = 100 × 贡献分数合计 / available_weight`，没有有效维度时为 null。

例如 Industry 正向25、Trend正向30、Quant中性10、龙虎榜正向10：75/85×100 = 88.24。
单一强信号可有标准化 100 分，但不能进入默认榜单，也不会标记 Strong。
Strong 需至少 4 个有效维度、3 个 positive、score ≥ 75。
排序：分数降序、正向维度数降序、Trend 贡献、Industry 贡献、股票代码。
排名变化、加速、低脆弱性、机构资金、概念方向只用于解释，不在同一维度里重复加分。

## 调度

- CN：上海 20:30；ETF 18:30、Trend 18:40、Quant 19:00、Industry 19:10、龙虎榜 19:30 之后。
- US：纽约 23:30；ETF 21:30、Trend 21:40、Quant 22:30 之后，DST 随市场时区。
- 复用 analysis 队列、任务生命周期和手动运行入口。默认通过 get_effective_trading_date 选择最近已完成交易日；显式非交易日 skip，未来日期拒绝，未收盘交易日通过 is_market_session_closed 检查后 skip。
- 这是靠后调度，不是硬性依赖屏障。上游延迟时读取各自截至目标日的最新正式数据，保留日期；上游补齐后可同日重跑。

## 未实现

没有 ETF 猜测映射、US 行业强度、Preview、ML、LLM、新行情源、自动交易、回测系统、60D+ 新指标，也没有修改成熟策略算法。
