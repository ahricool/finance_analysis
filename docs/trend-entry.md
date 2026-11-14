# Trend Entry 买点评估 V2

Entry 在 Alpha 排名、候选/趋势状态及 Fragility 之后独立计算，不改变它们的规则或默认排名。
突破、MA5 浅回踩、MA10 回踩、已确认突破位回测分别识别、评分和保存；同一天允许多个分支确认。
质量分与状态分离：未确认、延伸、失效仍保留连续质量分，不能将质量分视为确认信号或成功概率。

代码入口为 `trend_following/entry.py`，过程证据在 `entry_setups.py`，参数集中在 `TrendFollowingConfig`。
这些参数是待回测的初始设置；本次未验证或宣称收益提升。

## 近期资格与当前结构

回踩资格严格排除今日，在此前10个交易所交易日中至少一天达到现有四项绝对趋势门槛：
当日 Close > MA(N/2)、MA(N/2) > MA(N)、N/2 日收益 > 0、N 日加权对数斜率 > 0。
每一天只使用截至该日的价格，不把今日横截面百分位或 Alpha 回填到过去。

当前要求 MA(N) 高于昨日 MA(N)、Close ≥ MA(N)，且对应回踩过程的支撑没有失效。
回踩不再要求当天 Alpha≥67，也不再用当天 Trend/RS/Path/Fragility 分数硬性否决；这些值可继续参与质量或风险观察。
原 `trend_resume`、`setup` 是 Alpha V3 的旧解释特征，保持既有含义；新 Entry 的三个回踩分支独立保存，不依赖旧特征的互斥优先级。
既有事件研究的PULLBACK_RESUME样本仍按旧`trend_resume`定义，不能用其统计评价本次Entry V2规则的收益。

## 过程与支撑

执行均线固定为**截至上一交易日**的 MA5/MA10，不随10/20/40日趋势周期变化。
ATR 使用所选趋势周期 N 的前一交易日 ATR(N)，每个观察日各自计算，不让当日大波幅扩大自己的容差。

1. 此前上涨：回踩前已经存在趋势资格，上一收盘比支撑高至少0.5 ATR，
   并比此前10日内最低收盘上涨至少1 ATR。上涨证据必须先于触及日；当日高点不能证明先涨后跌的顺序。
2. 随后回踩：最低价到达支撑上方0.25 ATR以内，日内最高价仍可到达支撑下方0.25 ATR以上，
   且相对此前上涨收盘至少回落0.25 ATR。MA5 和 MA10 的过程各自观察。
3. 恢复确认：已触及支撑，当前参考收盘/Preview最新价高于支撑0.1 ATR，
   并高于昨日收盘或今日开盘，CLV≥0.60。允许同一天低点触及、尾部价格收回，无须昨日收于均线下方。
4. 失效：上涨过程已具备后，观察过程任一低点低于当日支撑0.75 ATR，或者当前长期均线结构转弱。
   单独触碰支撑不构成确认。
5. 延伸：已经发生回踩，但当前价高于支撑超过2 ATR；保留质量分并标记执行窗口已延伸。

突破位回测仅使用此前10个交易日中已经确认的突破。
对历史突破日 b，先以 b 之前 N/2 或 N 根日线最高价分别冻结阻力（重复价位去重）；b 日收盘至少超出该阻力0.1 ATR，CLV≥0.60才视为价格突破确认。
最早在 b+1 日观察回测，不使用今日高点或事后枢轴重画历史阻力。
多个历史突破位分别评估，依次优先已确认、回踩中、已延伸、等待、已失效，同优先级按时间先后稳定选择。

## 突破分支

保留当天 RS≥60、Alpha≥67、Path≥50、Trend≥62、长期均线上升、短期RS为正、CLV≥0.60；
Fragility 有值时必须<50，缺失时不单独否决。
当前收盘必须突破此前 N/2 或 N 日高点，距对应原阻力0.1–3 ATR。距离不再以 MA(N) 乖离百分比硬限制。
突破和回踩没有互斥条件；同时满足时 `entry_type=BREAKOUT_AND_PULLBACK`。
突破形成但其余条件不足时，状态及简短原因明确提示待确认。

## 质量与状态

保留既有 Gaussian / tanh、CLV、相对强弱、路径质量和 Fragility 评分组件；缺失分量移出分母后归一化：

```text
Breakout = .30 BreakoutQuality + .20 ATRDistanceQuality + .15 CLVQuality
         + .10 VolumeQuality + .10 RSQuality + .10 PathScore + .05 FragilityQuality
Pullback = .30 ReclaimQuality + .20 PullbackDepthQuality + .15 RSQuality
         + .15 ATRDistanceQuality + .10 CLVQuality + .10 FragilityQuality
```

各回踩分支使用自身支撑、恢复距离及触及后的最大下探深度，单位均为 ATR。
Gaussian 复用既有函数；恢复距离中心/宽度0.5/0.75，深度中心/宽度0.25/0.75；
支撑距离中心/宽度0.5/1.0；突破距离中心/宽度0.75/1.0。
没有触及证据时深度分量不可用，而非伪造为0分。
没有已知支撑参照（例如尚无历史确认突破位）时，整个分支质量留空，不能仅凭RS/CLV制造高分形态。

| 状态 | 含义 |
| --- | --- |
| WAITING_PULLBACK | 等待回踩、上涨资格/预热或突破形态 |
| PULLING_BACK | 已触及但没有满足恢复确认；突破分支表示形态已有、尚待其他确认条件 |
| CONFIRMED | 当前分支条件满足 |
| EXTENDED | 已超出执行距离 |
| INVALIDATED | 长期均线结构或支撑失效 |

`entry_score` 为四个分支最高质量分，任何状态都不强制归零；`entry_type` 仅汇总已经确认的分支，未确认仍为 NONE。
列表保留四套独立质量/状态/短原因，详情包含完整评分拆解和过程日期、支撑与ATR距离，Excel导出对应独立列及原因。
状态列按确认、回踩中、等待、延伸、失效排序；缺失值在两个方向均靠后。Alpha仍为默认排序。
Confluence读取已确认突破时使用其独立突破质量，避免把其他回踩分支的质量当作突破分数。

## 默认参数与预热

| 参数 | 默认值 |
| --- | --- |
| entry_trend_lookback | 10个交易日，不含今天 |
| entry_approach_atr / entry_advance_atr | 0.5 / 1.0 |
| entry_touch_atr / entry_pullback_decline_atr | 0.25 / 0.25 |
| entry_support_failure_atr | 0.75 |
| entry_recovery_atr / entry_clv_min | 0.10 / 0.60 |
| entry_extended_atr | 2.0 |
| entry_breakout_min_atr / entry_breakout_max_atr | 0.10 / 3.0 |

Entry需要至少 N+10+2 根日线预热，并核对真实交易所日期，不能用更早的有效数据行跳过缺日。
读取窗口为 max(N+N/4+2, N+10+2)，10/20/40周期分别读取22/32/52根；
原Alpha、箱体和超跌反弹等计算仍使用原N+N/4+2窗口，防止新增Entry预热改变Wilder RSI初始化等其他规则。
股票/基准历史仍复用现有批量输入，不增加逐股请求，不写行情。
预热不足或窗口缺日只禁止新回踩确认并说明原因，不阻断已有趋势计算。

## 正式、Preview、API与兼容

正式和Preview共用同一个Entry函数。Preview使用截至采集时已知的临时OHLC，不表示收盘确认；
盘中触及、收回或状态变化均可能继续改变。原始累计量比不冒充全天量，Preview无投影量时质量评分排除成交量项。

新增结果保存在现有features JSON，`entry_version=2`，无schema迁移。
排名API/紧凑表格、Preview列表、详情及导出均读取保存的结果，GET不重算。
旧快照没有分支状态时显示缺失，不按新规则补造确认；已有质量分维持原值。
重新运行对应日期的正式计算可生成V2证据，没有自动改写全部历史。

已知行情边界：Trend Preview沿用现有DB前复权历史与原始盘中日K拼接方式。
若除权日数据库基准尚未刷新，均线、ATR及Entry可能失真；本次不扩大到行情复权链路改造。

## Detail 风险仓位建议

个股 Detail 在状态摘要之后展示独立的 `features.risk_sizing`。Official 与 Preview
在共享 snapshot 构造链中、Entry 计算完成后生成；不参与 Alpha / Entry / State / Candidate / Ranking。
不增加行情请求、数据库列或账户数据依赖，旧快照没有字段时显示暂无风险建议。

`TrendFollowingConfig` 默认账户风险预算 0.01、ATR 倍数 2.5、单票仓位上限 0.25。
所有百分比均为小数单位（0.05 = 5%）：

- ATR 距离 = 2.5 × ATR20 / reference_price。
- 结构距离 = (reference_price − previous_low_10) / reference_price；仅有效正数且低于参考价时参与，否则为 0。
- 止损距离 = max(ATR 距离, 结构距离)；止损价 = max(0, reference_price × (1 − 止损距离))。
- 建议仓位 = min(风险预算 / 止损距离, 单票上限)。结构距离严格更大时为 STRUCTURE，否则为 ATR。

参考价或 ATR 缺失、非正数、非有限数、不可表示的计算结果或最终止损距离 ≥ 100% 时返回 null；结构缺失可用纯 ATR。
ATR20 保持最近20个 TR 的算术平均，结构低点为前10日最低价（排除今天）。
Preview 保持既有临时日线逻辑，ATR 与建议仓位/止损在收盘前可能变化。
仓位按账户净值计算，与 Entry 和 State 独立；1%是计划风险预算，实际跳空损失可能超过预算。

新版统一买点机会、独立形态窗口、稳定结构身份与分支事件研究见 [trend-opportunities.md](trend-opportunities.md)。兼容 Entry 分仍为综合形态质量；当前主买点仅从有效确认分支选择，不使用该兼容分排序。
