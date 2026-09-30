# 股票策略事件研究（Official Event Study）

## 范围

`/research/trend-following` 提供趋势排名、结构机会、超跌反弹、策略对比四个子视图。
这是信号预测能力研究，不是自动交易、可执行成交回测或组合回测。没有资金曲线、Sharpe、t-stat、
组合年化收益、最大组合回撤或自动评选最佳策略；不接入 LLM，不新增行情 Provider。

Alpha V3 权重与四个子分、Candidate、Trend State、Entry、Fragility、Lifecycle 保持不变。
Box 和 Mean Reversion 独立写入现有 `TrendFollowingSnapshot.features` JSON，无表或 migration。

## 四个事件定义

事件唯一键为 `(market, trade_date, code, strategy)`。只读取当时已冻结的 **Official** snapshot：

| Strategy | 事件条件 |
| --- | --- |
| TREND_FOLLOWING | 当前state=TRENDING，上一条正式snapshot的state已知且不为TRENDING |
| BOX_BREAKOUT | box_state=BOX_BREAKOUT 且 box_breakout_fresh=true |
| PULLBACK_RESUME | 当日原有 features.trend_resume=true；不要求通过Entry门槛 |
| MEAN_REVERSION | mr_state=MR_REBOUND |

同股票同日可以属于多个策略。Trend直接复用状态机事实，上一状态在SQL中用lag获得，包含查询起始日
之前的最后一条snapshot。若首次记录已经TRENDING但没有前态，不推测为新episode，并计为特征覆盖不足。
缺失快照日的后续状态比较沿用现有“上一条可用正式状态”语义。

事件判定不查询未来OHLC、不重新计算历史信号。未来行情只评价事件。修正规则后的历史须通过既有
Trend Following逐日重算流程补齐；GET不会自动回填，也不写事件表。

## Box freshness

保留Box V1几何、Quality和窗口选择。对最终selected窗口 `T−N … T−1`：

- `previous_resistance = max(High[T−N … T−2])`。
- 昨日突破距离 = `(Close[T−1]−previous_resistance) / ATR20[T−2]`。
- ATR截止昨日之前，与昨日自身Box判断所用的基准一致；使用已有TR算法，不包含今日或昨日突破日。
- 昨日CLV=`(Close−Low)/(High−Low)`。

如果昨日距离在 `[0.10,2.0] ATR` 且CLV≥0.60，则今日不产生新的BOX_BREAKOUT。
昨日不足0.10 ATR、仅上影越顶或CLV不足时，今日首次有效确认仍可触发。
昨日ATR历史不足时不认定已经确认；不增加任意天数cooldown。

保存 `box_breakout_fresh`、`box_prior_breakout_confirmed`，详情还保留
`box_previous_resistance`、`box_previous_breakout_atr`、`box_previous_clv`。
昨日确认检查只是补充，不能代表整个episode。

### 一箱一事件

Box从有效FORMING/READY结构开始，首次满足原突破条件时消费episode，保存
`box_episode_consumed=true`、`box_episode_breakout_date=当日`到现有features JSON。
之后回踩、再突破、暂时没有候选箱体都继承已消费标记，不重复生成fresh事件。
只有重新选出quality≥forming门槛的有效箱体，且
`box_start_date > box_episode_breakout_date`，正式计算才rearm；整个新窗口必须位于旧突破之后。
Rearm清除消费标记和旧突破日期；当日若满足突破条件，可记录新事件。无固定天数cooldown。

Service在特征计算前批量读取previous_snapshots，按股票传入上一条正式快照的Box字段。
即使中间缺少有效候选或股票快照也不主动遗忘旧episode。Preview继承同一正式前态，
只能改变今日临时状态，不能rearm已消费episode，也不写正式快照。
无前态时从未消费开始，不从滚动60根K线推测完整episode历史。历史重算沿用同一逐日计算和
持久化前态；从相同起点/前置快照重算得到相同state、freshness、consumed、breakout date。
旧版只有昨日检查的快照须从可靠起点逐日重算，不能用单日重算恢复缺失的episode链。

回归覆盖连续创新高、突破→回踩→再突破、新箱体重启、Preview和逐日运行/历史重算一致性。
Box几何与Quality定义见[Box V1](trend-box-structure.md)。

## Mean Reversion V1

实现：[mean_reversion.py](../src/finance_analysis/trend_following/mean_reversion.py)。
RSI共用[技术指标helper](../src/finance_analysis/analysis/technical/indicators.py)：
原技术分析器继续使用原来的简单滚动RSI，结果不变；MR使用标准Wilder RSI14。
前14个价格差的涨/跌均值初始化，之后 `avg=(previous_avg*13+current_change)/14`；
RSI=`100−100/(1+avg_gain/avg_loss)`。无涨跌为50，只有涨无跌为100，只有跌无涨为0，warmup为空。

复用现有今日MA20、ATR20、return_3d、return_5d、CLV，不引入同义字段。
`distance_from_ma20_atr=(Close−MA20)/ATR20`。RSI与episode初始化使用本次可见的完整历史窗口；
若上一交易日正式snapshot已有MR字段，优先继承其MR状态、RSI和episode消费标记。
这样逐日重算及Preview不因滚动warmup重新触发已消费的episode。前态缺失时从可见历史顺序初始化，
历史长度会影响Wilder种子，早期样本应结合覆盖信息研究。

### 状态

- **MR_OVERSOLD**：RSI14≤35、MA20距离≤−1.0 ATR、return_5d<0，且今日未生成REBOUND。
- **MR_REBOUND**：昨日MR_OVERSOLD，当前episode尚未触发反弹，Close>昨日Close，CLV≥0.60，
  RSI14>昨日RSI14。REBOUND优先于当日仍满足的oversold资格。
- **MR_NONE**：其余情况。

每个连续oversold episode最多一次REBOUND。触发后保存 `mr_episode_consumed=true`；
即使接下来仍超跌并继续上涨，也不重复触发。只有离开原始oversold资格区后，随后重新进入
oversold并再确认反弹，才能生成新事件。没有固定天数冷却。

MA20 slope<0、弱RS、低Trend或高Fragility不硬否决。它们和当日regime作为冻结研究上下文保留。

### 连续质量

定义 `Q(x,s)=50+50*tanh(x/s)`，`G(x,c,w)=exp(−0.5*((x−c)/w)^2)`：

```text
Oversold = Q(30−RSI14,10)
Distance = 100*G(distance_from_ma20_atr,−2.25,1.25)
Shock = .5*Q(−return_3d,.06) + .5*Q(−return_5d,.10)
Reversal = 100*CLV*clamp((RSI14−previous_RSI14)/10,0,1)
MR Quality = .35 Oversold + .35 Distance + .20 Shock + .10 Reversal
```

缺失CLV/RSI的reversal为0。Distance在−2.25 ATR最高，过浅或−6 ATR等极端偏离均降分。
Quality仅排序解释，不是额外状态门槛，更不进入Alpha或Entry。
新增JSON字段：`rsi14, distance_from_ma20_atr, mr_state, mr_quality, mr_previous_rsi14,
mr_episode_consumed, mr_oversold_quality, mr_distance_quality, mr_shock_quality, mr_reversal_quality`。

参数集中于TrendFollowingConfig：`mr_rsi_period=14, mr_rsi_max=35, mr_distance_max_atr=-1,
mr_return_5d_max=0, mr_rebound_clv_min=.60, mr_rsi_quality_center=30, mr_rsi_quality_scale=10,
mr_distance_center_atr=-2.25, mr_distance_width_atr=1.25, mr_shock_3d_scale=.06,
mr_shock_5d_scale=.10, mr_quality_weights={oversold:.35,distance:.35,shock:.20,reversal:.10}`。

## Preview

当前机会可以使用临时日线计算Box、MR，但此前部分只使用T−1及之前正式日线和正式MR前态。
库内T日记录被临时日线替换，不混入未来日线。Preview仍仅写原Redis缓存，不持久化正式研究事件。
策略对比Tab在Preview模式明确停用，不发送Event Study请求。

## 收益与交易日

公共 `forward_returns.HORIZONS=(3,5,10,20)`，已有3/5/10字段保留，新增20D。
趋势排名、结构机会复用公共四列；Preview为空。

```text
R_N = Close(T+N) / Close(T) − 1
```

N是精确交易所session，复用exchange_calendars的XSHG/XNYS及session_close，包含节假日、
美国DST和提前收盘。目标session未收盘不使用该日临时数据；缺失目标日不顺延。
研究API汇总5/10/20D，公共页面仍支持3D。

**T-close forward return是事后研究指标，不代表能按T收盘价真实成交。**
没有改成Signal Center的`next_session_open_v1`。共享交易日/有效价格基础helper，不共享成交基准。

评价用DB同一前复权序列的T收盘作为分母，避免后来除权修订造成历史snapshot价格与新OHLC尺度混用。
事件 `signal_price` 保留当时snapshot参考价；`evaluation_base_price` 单独返回本次DB T收盘价。
价格调整可修订评价数值，但不能改动冻结的事件条件及上下文。

## Benchmark excess

CN=`510300.SH`，US=`SPY.US`，复用配置benchmark_codes。
Benchmark分母与目标日严格等于股票的signal date和target session：

```text
excess_N = stock_R_N − benchmark_R_N
```

基准缺少T或目标日时，股票收益仍可用，超额为missing；不替换日期、不使用当前基准收益。

## MFE20 / MAE20

```text
MFE20 = max(High(T+1 … T+20)/Close(T) − 1)
MAE20 = min(Low(T+1 … T+20)/Close(T) − 1)
```

使用未来20个精确session，排除信号日。完整20日OHLC路径均有效时才返回/汇总。
公式不额外裁剪零：若整个未来区间都低于基准，MFE可能为负；全程高于基准时MAE可能为正。
共同有效性helper要求OHLC有限、正数、High/Low关系成立、volume>0。
收益终点只要求T和target的有效close/volume，不因中间缺日失效；路径指标严格要求每个session。

- **pending**：目标session尚未收盘；MFE20未满20日也为pending，不计入完整路径统计。
- **missing**：已经到期但基准/目标价缺失或无效；完整路径内任一日缺失也为missing。
- **available**：对应数据完整。

`missing_dates`、`observed_sessions`独立返回；即使20D仍pending，也可以看到已到期部分的路径缺口。
没有静默忽略停牌日后生成完整MFE，也不生成貌似完整的部分路径MFE。

## 汇总、Regime与覆盖

按market、strategy、signal date snapshot中的`market_regime`分组，提供ALL及RISK_ON/NEUTRAL/RISK_OFF。
不读取评价日市场环境。每个horizon返回可评价数量、pending/missing数量、均值、中位数、严格`>0`胜率，
以及独立超额样本数量、均值、中位数、严格`>0`超额胜率。零收益不是胜利。
`matured_count`表示已到期且收益可评价的样本数量；缺数据单独计missing，不并入胜率分母。
MFE/MAE分别提供均值、中位数及完整路径数量。

Coverage按请求范围实际snapshot行计数：

- Box必须同时存在box_state、box_breakout_fresh与box_episode_consumed；旧版仅有昨日freshness的快照也需要重算。
- MR必须存在mr_state；缺失不能视为MR_NONE。
- Pullback必须存在trend_resume；Trend必须已知上一正式state。
- 返回snapshot_dates、missing_snapshot_dates、各组feature_coverage、feature_snapshot_count、snapshot_count、
  incomplete_dates、continuous_complete_since。后者是延续至请求区间末尾的完整后缀起点：
  从该日起，该策略所有已有行字段齐全，且没有应已收盘session整日缺快照；字段缺失或整日缺失均打断后缀。
  最后应已收盘日不完整、无完整后缀或无该分组样本时为null；周末/休市和尚未收盘日不算缺失。
  Regime分组仅检查对应Regime的已有行，但整日缺快照因无法确定Regime会打断所有分组。
  例如完整/缺失/完整/完整对应第三日起连续完整，不再返回误导性的earliest_complete_date。
- `box_feature_coverage`、`mr_feature_coverage`额外提供整个请求范围的覆盖摘要。
- 任一字段缺失或应已收盘session整日无snapshot，都标记`insufficient_feature_history`。
  仍可查看已覆盖样本的描述统计，但UI明确提示不能据此判断策略优劣。
- 覆盖率分母是已有snapshot，不代表历史Universe全部证券均有行情；还需注意既有数据覆盖及存活偏差。

Event之间可能时间重叠，同股票反复出现，多策略也可重合，因此样本并非独立。
本次不对这些重叠observation计算t-stat或组合指标，不声称统计显著性或已完成收益校准。

## API与性能

`GET /api/v1/trend-following/event-study`，沿用会话鉴权，参数：

- market=CN|US；start_date/end_date默认最近180自然日。
- strategy=ALL|TREND_FOLLOWING|BOX_BREAKOUT|PULLBACK_RESUME|MEAN_REVERSION。
- regime=ALL|RISK_ON|NEUTRAL|RISK_OFF。
- offset≥0，limit=100、最多500；仅分页样本，汇总始终使用完整选中范围。
- 日期范围最多730天，配置 `event_study_default_days` / `event_study_max_days`。

每次请求最多两次SQL：一次正式snapshot标量投影，一次所有事件股票+benchmark的DB日线OHLC批量读取。
前态SQL先按[start_date,end_date]产生范围CTE，再对区间涉及的instrument用已有
(instrument_id,trade_date)索引查找start之前最近一条state（ORDER BY date DESC LIMIT 1）。
UNION ALL后才执行lag，因此window仅含范围行和每个相关股票最多一条前态；多年旧行不进入window。
JSON上下文投影限于请求日期范围，不加载整份features或score_breakdown。
基准不按股票重复查询，horizon不分别查询。交易日计划按不同signal date计算一次；内存派生、评价、汇总。
空事件仅一次snapshot查询。两年CN区间仍可能较大，建议从180日开始；不设置隐藏采样或截断汇总。

正式Ranking缓存v10；旧snapshot和Preview缺MR或fresh字段时显示「—」，等待正式重算/下次Preview刷新。
策略对比提供日期、市场和Regime过滤、任意汇总列排序、策略样本分页及汇总Excel。
样本上下文只来自信号当日snapshot，不向当前Detail请求指标。

## 验证

测试覆盖fresh Box连续三天创新高、宽度合格的方向通道Flatness、Wilder种子与旧RSI兼容、MR反弹边沿、
原Alpha/Entry/State不变、四类重叠事件、精确session/节假日/DST/提前收盘、基准同日对齐、缺口不顺延、
pending及胜率分母、旧字段覆盖、查询数不随事件数增加、Official/Preview页面隔离和桌面深浅色视图。
