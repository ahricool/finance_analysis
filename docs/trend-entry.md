# Trend Following Entry

Alpha Score 用于选股（stock selection）；Entry Score 用于买点研究（entry timing）。
Alpha 一级权重保持 `0.40 Trend + 0.25 RS + 0.15 Setup + 0.20 Path`。
Entry 在排名、状态和 Fragility 完成后计算，不参与 Alpha、rank、Candidate、state、仓位或交易动作。
市场环境只提供上下文，不作为 Entry 条件。

实现：[features.py](../src/finance_analysis/trend_following/features.py)、
[entry.py](../src/finance_analysis/trend_following/entry.py)、
[config.py](../src/finance_analysis/trend_following/config.py)。

## 结构与条件

两类 Entry 共用：RS≥60、Alpha≥67、Path≥50、MA20 slope>0、RS10>0；
Fragility 有值时必须<50，为空时不否决。

### BREAKOUT

存在 COMPRESSION_BREAKOUT、BREAKOUT_20D 或 BREAKOUT_10D；Trend≥62；
Close/MA20−1 在闭区间 [2%,10%]；CLV≥0.60。CLV 缺失时无法确认突破收盘位置，Entry 不成立。
复用 Alpha V3 的 Gaussian BreakoutQuality，不增加第二套突破距离公式。

### PULLBACK_RESUME

此前5个交易日（不含今天）至少一天 Close≤当日MA10，或者距当日MA10≤0.5倍当日ATR20。
每一天必须具备完整 MA20 slope / ATR 历史；样本不足时不推定结构完好。
这5天 MA20 slope 均>0、收盘均≥MA20，且不能触发状态机同一个 `structure_broken` 纯函数：
收盘低于此前10日最低价，或收盘低于不再上升的MA20。
这里保守检查整个回踩观察窗口，拒绝短暂跌破MA20后立即恢复的样本。

今日：昨日Close≤昨日MA10，今日Close>今日MA10，今日Close>昨日Close，
MA10>MA20、MA20 slope>0、raw weighted slope>0、RS10>0。
不再要求Return10 percentile≥60或用3D收益代替reclaim。

Setup优先级：COMPRESSION_BREAKOUT > BREAKOUT_20D > BREAKOUT_10D > PULLBACK_RESUME > NONE。
`trend_resume` bool保留，但语义为上述真实回踩恢复。
Resume Entry另要求Trend≥60、MA20乖离在(0,8%]；不要求突破新高。

## 连续分数

令 `G(x,c,w)=exp(-0.5*((x-c)/w)^2)`，`Q(x,s)=50+50*tanh(x/s)`。
以下组件均为0–100；布尔条件只决定资格，不累加得分。

```text
Breakout = .30 BreakoutQuality + .20 ExtensionQuality + .15 CLVQuality
         + .10 VolumeQuality + .10 RSQuality + .10 PathScore + .05 FragilityQuality
Resume   = .30 ReclaimQuality + .20 PullbackDepthQuality + .15 RSQuality
         + .15 DistanceQuality + .10 CLVQuality + .10 FragilityQuality
```

- BreakoutQuality、ExtensionQuality、VolumeQuality复用[Alpha V3](trend-alpha-v3.md)。
- CLVQuality = 100×CLV。
- RSQuality = Q(RS10,.12)。
- FragilityQuality = 100−Fragility。
- ReclaimQuality = 100×G((Close−MA10)/ATR20,.5,.75)。
- PullbackDepthQuality = 100×G(depth,.25,.75)，depth为回踩触及日 `(MA10−Close)/ATR20` 的最大值。
- DistanceQuality = 100×G(Close/MA20−1,.03,.04)。

缺失Fragility、Resume的CLV或Preview投影量时，剔除对应组件后将可用权重归一化。
满足全部条件才输出对应Entry Type与分数；否则 `NONE / 0`。
`quality_score`保留条件过滤前的连续分，`checks`解释为何无有效Entry。
因此资格边界允许跳变，质量曲线本身连续；高Alpha但过度延伸或低CLV可以得到NONE/0。

## 参数

所有阈值与曲线位于TrendFollowingConfig：

| 参数 | 默认值 |
| --- | --- |
| slope_direction_scale | .002（日log斜率） |
| resume_lookback_days / resume_touch_atr | 5 / .5 |
| entry_trend_min / entry_resume_trend_min | 62 / 60 |
| entry_rs_min / entry_alpha_min / entry_path_min | 60 / 67 / 50 |
| entry_fragility_max | 50（严格小于） |
| entry_extension_min / entry_extension_max | .02 / .10 |
| entry_resume_extension_max / entry_clv_min | .08 / .60 |
| entry_reclaim_center_atr / entry_reclaim_width_atr | .5 / .75 |
| entry_pullback_center_atr / entry_pullback_width_atr | .25 / .75 |
| entry_resume_distance_center / entry_resume_distance_width | .03 / .04 |
| preview_volume_neutral_quality | 50 |
| breakout_entry_weights / resume_entry_weights | 上述权重 |

## 新特征与统计修正

- CLV = (Close−Low)/(High−Low)，High=Low返回null。
- ATR% = ATR20/Close；底层ATR20与详情绝对值保留。
- R²Quality = 100×weighted_r2×sigmoid(raw_weighted_slope/.002)。原始R²和斜率不变，横截面斜率排名不变。
- Downside/Upside = 最近10个简单日收益中负收益绝对值之和 / 正收益之和。
  无正收益为null；有正收益而无负收益为0。质量仍为100×exp(−ratio)。
- 删除重复Trend Quality展示与Ranking投影。存储JSON保留旧字段作为Confluence/Signal Center
  的内部兼容别名，不作为独立研究指标展示，不修改这两个模块。生命周期/Fragility的旧拟合质量语义保持：
  直接使用raw weighted_r2×100，不再回退读取旧trend_quality。

## Official / Preview

两者经过相同features、Alpha、Resume、Entry函数；只有成交量处理不同。
现有CN快照与US当日5分钟聚合没有可靠的历史同时刻参与率，本次不新增请求或量能数据库。

- Official：volume_ratio=当日全天量/前20个交易日全天均量。
- Preview：raw_volume_ratio保留累计量/前20日全天均量；旧volume_ratio字段保留同一原始语义。
- projected_volume_ratio=null，volume_provisional=true。不把raw ratio作为全天量信号。
- Alpha Setup的VolumeQuality暂用50，明确标为暂定；因此不调整原Alpha权重。
- Entry排除缺失的VolumeQuality，重新归一化，不用盘中raw量硬否决。
- UI标为“盘中估算 —”和“暂定”；该降级并非预测全天成交量。

Preview依旧只读此前official状态，只写现有Redis预演缓存；不写正式快照、不影响后续正式运行。
由于成交量处理不同，即使OHLC一致，Official/Preview的Setup和Alpha也可能不同。

## 存储、API与兼容

Entry存入现有features JSON：entry_score、entry_type、entry_breakdown；无migration。
Ranking、detail和Preview同时投影一级entry_score / entry_type，不要求前端解析breakdown。
Ranking仅取标量，详情提供组件、归一化权重、贡献、条件与参数。
新增atr_percent、close_location_value、raw_volume_ratio、projected_volume_ratio、
pullback_detected、ma10_reclaimed、volume_provisional。支持entry_score排序，默认仍按Alpha。

上线后统一重算全部历史快照为Alpha V3；不保留旧公式或跨版本处理。Ranking缓存保持v7，
重算正常触发失效和重建。Excel使用统一版本formatter，Preview的正式Volume Ratio单元格留空，
Official仍导出完整volume_ratio。
修正R²、Path统计与Resume定义会改变Alpha或Candidate结果，这是规则修正的直接影响；
Entry自身不参与这些计算。历史重算由上线流程执行；本次未做历史收益回测或阈值校准。

## 已知数据边界

现有Trend Preview直接拼接DB前复权历史与原始盘中报价，没有像独立盘中确认模块那样
用昨收锚点调整历史价格尺度。若除权日DB前复权基准尚未刷新，MA/ATR、突破与Entry
可能失真。本次保持行情链路边界，未引入复权因子请求；此问题需独立修复与验证。


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
