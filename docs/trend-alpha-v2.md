# Trend Following Alpha V2

适用于 `trend_following` 的 official / preview 共用计算链。参数事实源为
[`TrendFollowingConfig`](../src/finance_analysis/trend_following/config.py)，实现为
[`scoring.py`](../src/finance_analysis/trend_following/scoring.py)。只改变评分，
不改变趋势状态机、市场环境计算、生命周期或脆弱性规则。

## V1 review 与去重

V1 的成交量同时进入 Breakout（20%）与 Alpha（10%），有效 Alpha 权重为 14%；
压缩 bool 同时进入 Breakout（10%）与 Alpha（5%），有效权重为 7%。
突破距离、10D 强度、20D 强度又分别累加；同一次突破可获得三次奖励。
Trend 的 10D/20D 收益与 RS 中两个收益百分位重复衡量绝对涨幅。
TrendResume bool 还会额外奖励同一段恢复走势。

V2 移除 Alpha 顶层 Volume/Compression；RS 删除收益百分位，仅使用相对基准超额收益；
统一连续 BreakoutQuality 取两窗口最大值。TrendResume、PriorCompression、CompressionBreakout
与旧突破原始字段继续保留供状态、解释和短期 V1 对照使用，不参与 V2 计分。
Signed Efficiency Ratio 继续展示，不进入 Alpha。

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
log(close)、权重1…15的加权回归，`R2Quality=100 R²`，不作非线性变换。
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
| Volume | `Q(VolumeRatio−1,.8)`，VolumeRatio=当日量/前20日均量 |
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
- `downside_upside_ratio`：上述负收益绝对值均值 / 正收益均值。
- `path_score`、`setup_score`、`downside_control_quality`、`alpha_version=2`：排名直接需要的评分特征。

没有正收益时集中度和 downside/upside 均为 null，对应质量分为0；有正收益且无负收益时
ratio=0、DownsideControl=100。ATR或Range分母为0时比值为null，对应质量分为0；
ATR20=0时 z10/z20=null、BreakoutQuality=0。不会保存 NaN/Infinity，也不会把缺失值当高质量。
Compression 保持前序窗口，避免当日突破波动抹去已有收缩；Path 用当前窗口识别突破后扩张。

## 快照、API 与页面

复用 `features` 与 `score_breakdown` JSON；无新增表、列或 migration。
已有 `breakout_score` 列作为 Setup Score 的兼容别名，`features.setup_score` 同值。
`score_breakdown` 包含 `trend/rs/setup/path/alpha`：保存原始值、质量分、子权重与分量得分；
`alpha` 保存版本、四个一级分量、权重、贡献和总分。
Trend 中 `return_10d/return_20d/weighted_r2` 是质量分，对应原值用 `raw_*` 保存。

Ranking 查询直接投影 JSON 标量，无全量 detail JSON、无逐股票 detail API。
`features` 返回上述排名字段，`sort_by` 支持 `path_score/setup_score/weighted_r2/positive_return_concentration/
atr_expansion_ratio/downside_control_quality/downside_upside_ratio`；服务端排序后才应用 limit。
表格在整份市场数据上双向排序并虚拟化显示，新增 Path、Weighted R²、Concentration、ATR Expansion、
Downside Control、Setup 列。Drawer 展示这些指标、比值及完整贡献明细；保留原趋势/RS/Breakout/Signed Efficiency。

Ranking cache schema 升至v4，避免旧投影缓存隐藏新字段。Preview仍复用原Redis键和计算链。
旧快照不即时重算，不伪造V2字段：`alpha_version` 缺失时页面显示V1，新增指标显示「—」。
新运行默认生成V2。若需要统一历史口径，使用现有重算流程（会按已有服务语义向后重建状态），
本次代码修改不自动触发历史写入。跨版本的排名/分数差异不能当作纯市场变化。

Candidate 仍要求 TrendCandidate、Trend≥62、RS≥60、ValidSetup、Alpha≥67。
评估后保留 ValidSetup 硬条件：本次没有经过历史校准验证的新 Setup 阈值，不改变交易状态语义。
V2 阈值输入的分布已变化，候选数量可能变化；上线后应观察，并单独讨论状态阈值校准。

## 短期 V1 对照与回归证据

`TrendFollowingConfig(compare_alpha_v1=True)` 仅额外计算
`score_breakdown.alpha_v1`，不影响V2排序或状态。冻结旧公式的 `scoring_v1.py`
只在此开关启用时导入。后续删除该文件、开关及 ranking 中对应分支即可移除V1。
V1固定常数只用于还原旧版本；所有V2可调参数集中在Config。

测试 `tests/test_trend_following_alpha_v2.py` 的合成样本保持相同20D收益约16.78%：

| 样本 | Weighted R² | Concentration | ATR5/ATR20 | Path | Alpha V1 | Alpha V2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A 持续推进、小幅回撤 | .978 | 28.57% | 1.059 | 95.03 | 55.38 | 76.77 |
| B 前段阴跌、两次大涨后宽幅波动 | .697 | 89.28% | 2.869 | 16.14 | 69.59 | 64.87 |

这是合成测试，不是金百泽/天顺风能真实行情回测。两只样本形成0/100斜率百分位极差，
B仍可能有更高Trend；在相同SlopePercentile下A的Trend更高，V2总分也在真实两样本排名中偏向A。
另有固定所有非Path分量的测试，确认Path本身对A的偏好。

覆盖连续边界/单调性、旧饱和阈值以上区分度、成交量贡献上界、突破不重复计分、
布尔解释字段不影响分数、线性R²贡献、无正/负收益、零ATR、official/preview、
排序前limit、旧快照null、全市场前端排序不请求detail及Drawer展示。

## 本次验证结果

- 趋势相关后端：`uv run pytest tests/test_trend_following*.py tests/test_trend_health.py tests/test_trend_breadth.py -q`，159通过。
- `ci_gate.sh syntax / flake8` 通过；完整门禁中的 deterministic 阶段13通过。
- 完整离线门禁：1738通过、25跳过、35失败、4 errors，另92 subtests通过。
  39项失败/错误均为本机 PostgreSQL 测试账号认证失败；未修改数据库凭据或无关模块。
  完整门禁运行后又新增一项feature窗口断言，已包含在上面的159项聚焦结果中。
- Web：`vue-tsc -b`、Vite build（输出临时目录，未改static）、ESLint通过（仓库已有warning）；
  全量Vitest 543通过，后续贡献明细改动的39项页面/API聚焦测试再次通过。
- Playwright 趋势页面7项通过，覆盖1280/1440/1920px深浅主题、Drawer、全市场虚拟排序。
  API全部mock，后端启动占位服务，不访问真实数据库。
- `git diff --check` 通过。
