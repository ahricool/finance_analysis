# Trend Following Alpha V3

适用于 `trend_following` 的 official / preview 共用计算链。参数事实源为
[`TrendFollowingConfig`](../src/finance_analysis/trend_following/config.py)，实现为
[`scoring.py`](../src/finance_analysis/trend_following/scoring.py)。只改变评分，
不改变趋势状态机主体、市场环境计算、生命周期或脆弱性规则。独立买点研究见[Entry说明](trend-entry.md)。

## 本次公式升级

一级权重不变。相比此前公式，V3修改两个核心定义：

1. R² Quality 加入连续趋势方向因子。
2. Downside/Upside 使用累计负收益绝对值 / 累计正收益，不再使用正负日均收益之比。

Entry是独立买点研究，不进入Alpha。所有参数集中于TrendFollowingConfig。
上线后统一重算全部Trend Following历史快照，不保留旧公式读取或跨版本比较分支。

## 完整公式

所有质量分范围为 0–100，收益、乖离均使用小数（0.12 = 12%）。

```text
Alpha = .40 Trend + .25 RS + .15 Setup + .20 Path
Trend = .30 SlopePercentile + .30 R2Quality + .25 Momentum + .15 DrawdownQuality
Momentum = .60 Return10Quality + .40 Return20Quality
RS = .25 RS5Quality + .45 RS10Quality + .30 RS20Quality
Setup = .50 BreakoutQuality + .25 ExtensionQuality + .15 VolumeQuality + .10 CompressionQuality
Path = .45 ConcentrationQuality + .35 VolatilityQuality + .20 DownsideControlQuality
```

SlopePercentile 沿用当日全市场横截面 average-tie percentile；Weighted R² 仍基于最近15根
log(close)、权重1…15的加权回归，`R2Quality=100 R² × sigmoid(raw_weighted_slope / .002)`；方向因子连续，原始R²保留。
Momentum 汇总相关收益周期；RS 只保留 `stock return − benchmark return`。

定义 `Q(x,s)=50+50 tanh(x/s)`、`σ(x)=1/(1+exp(−x))`、
`G(x,c,w)=exp(−.5((x−c)/w)²)`。

| 质量分 | 实际公式和默认参数 |
| --- | --- |
| Return10 / Return20 | `Q(R10,.12)` / `Q(R20,.18)` |
| RS5 / RS10 / RS20 | `Q(RS5,.08)` / `Q(RS10,.12)` / `Q(RS20,.18)` |
| Drawdown | `100 exp(−abs(DD20)/.15)` |
| Breakout | `zN=(Close−PreviousHighN)/ATR20`；`B(z)=100 σ(z/.15) G(z,.75,1)`；`max(.85 B(z10), B(z20))` |
| Extension | `100 σ((e−.015)/.01) G(max(0,e−.08),0,.12)`，`e=Close/MA20−1` |
| Volume | `Q(VolumeRatio−1,.8)`，VolumeRatio=当日全天量/前20日均量；Preview缺失可靠投影量时质量暂用50 |
| ATR compression | `Q(.90−ATR10/ATR20,.15)`，这里 ATR 均排除当日 |
| Range compression | `Q(.70−Range10/Range20,.20)`，Range=窗口最高high−最低low，排除当日 |
| Compression | `sqrt(ATRCompressionQuality × RangeCompressionQuality)` |
| Concentration | `100(1−smoothstep(c;.45,.80))` |
| Volatility | `100 G(max(0,ATR5/ATR20−1.10),0,.80)`，这里 ATR 包含当日 |
| Downside control | `100 exp(−downside_upside_ratio/1.0)` |

`smoothstep(x;low,high)` 令 `t=clip((x−low)/(high−low),0,1)`，返回 `t²(3−2t)`。
集中度在45%以下保持高分，80%以上保持低分，两端一阶导数连续；不是阈值跳变。
其他正收益/RS曲线渐近饱和，不在旧的20%阈值截断。
Breakout 峰值约0.8 ATR（sigmoid使峰值较Gaussian中心略右移），前高以下连续降低，
远离前高后回落。Extension 在3%至8%附近高分，20%以上逐步降温，不突然归零。
Volume 的全部 Alpha 权重为 `.15 × .15 = 2.25%`，从0质量分到100最多影响2.25点；
Compression 有效权重为1.5%。

## 新原始特征与缺失值

- `atr_contraction_ratio`、`range_contraction_ratio`：前一交易日截止的10/20窗口比。
- `atr5`、`atr_expansion_ratio`：当日截止的5/20平均真实波幅比。
- `positive_return_concentration`：最近10个**日简单收益率**中，最大的两个正收益之和 / 所有正收益之和。
- `avg_positive_return`、`avg_negative_return_abs`：分别只对正、负收益日求均值，零收益日不进入这两个均值。
- `downside_upside_ratio`：负收益绝对值之和 / 正收益之和（最近10日）。
- `path_score`、`setup_score`、`downside_control_quality`、`alpha_version=3`：排名直接需要的评分特征。

没有正收益时集中度和 downside/upside 均为 null，对应质量分为0；有正收益且无负收益时
ratio=0、DownsideControl=100。ATR或Range分母为0时比值为null，对应质量分为0；
ATR20=0时 z10/z20=null、BreakoutQuality=0。不会保存 NaN/Infinity，也不会把缺失值当高质量。
Compression 保持前序窗口，避免当日突破波动抹去已有收缩；Path 用当前窗口识别突破后扩张。

## 快照、API 与页面

复用 `features` 与 `score_breakdown` JSON；无新增表、列或 migration。
已有 `breakout_score` 列作为 Setup Score 的兼容别名，`features.setup_score` 同值。
`score_breakdown` 包含 `trend/rs/setup/path/alpha`：保存原始值、质量分、子权重与分量得分；
`alpha` 保存版本、四个一级分量、权重、贡献和总分；`score_breakdown.alpha.version=3`。
Trend 中 `return_10d/return_20d/weighted_r2` 是质量分，对应原值用 `raw_*` 保存。

Ranking 查询直接投影 JSON 标量，无全量 detail JSON、无逐股票 detail API。
`features` 返回上述排名字段，并从 `score_breakdown` 批量投影质量分与 Alpha 贡献标量
（`r2_quality`、`rs_*_quality`、`breakout_quality`、`alpha_*_contribution` 等），
不把整份 `score_breakdown` 塞进约 3800 行排名结果。`sort_by` 支持这些质量分/贡献字段以及
`path_score/setup_score/weighted_r2/weighted_slope_percentile/positive_return_concentration/
atr_expansion_ratio/downside_control_quality/downside_upside_ratio`；服务端排序后才应用 limit。
表格在整份市场数据上双向排序并虚拟化显示。Drawer 展示完整贡献明细；
主表把解释字段（Prior Compression、Compression Breakout、Trend Resume、Signed Efficiency）
放在 Signals / Explain，不与 Score Components 混排。

Ranking cache schema保持v7；Alpha版本号变化不改变payload结构。
历史重算正常触发缓存失效与重建。页面、Drawer与Excel通过统一formatter展示版本：
3显示V3，其他版本号显示对应编号，缺失显示“—”。不将缺失值推断为V1。

Candidate仍要求TrendCandidate、Trend≥62、RS≥60、ValidSetup、Alpha≥67。
本次没有修改delta、movers、rank change、状态转换或Candidate阈值。

## 验证范围

`tests/test_trend_following_alpha_v3.py`覆盖连续质量曲线、权重、收益路径、累计涨跌比，
并断言features.alpha_version与score_breakdown.alpha.version均为3。
Entry规则与Preview量能处理见[trend-entry.md](trend-entry.md)。
