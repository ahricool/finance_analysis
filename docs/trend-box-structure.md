# Trend Following 箱体结构 V1

## 定位与边界

`/research/trend-following` 共用市场、日期、Official / Preview，提供「趋势排名」和「结构机会」。
Box 是独立市场结构研究信号，存入现有 snapshot `features` JSON，不新增表、列、迁移、任务或 LLM。
Alpha V3 权重、Trend / RS / Setup / Path、rank、Candidate、State、Entry、Fragility、生命周期均不变。

`COMPRESSION_BREAKOUT` 仍表示短期 ATR/Range 压缩后突破前10日高点。
`BOX_BREAKOUT` 表示突破识别出的15–60日横盘箱体；二者可以同时成立，不互相覆盖。
Box 不成为新 Entry Type，也不以 Trend、RS、Momentum、Alpha、成交量作为资格门槛。

实现：[box.py](../src/finance_analysis/trend_following/box.py)、
[config.py](../src/finance_analysis/trend_following/config.py)。

## Point-in-time 定义

对交易日 T，输入按日期升序、截至 T。候选窗口 n 属于 `(15,20,30,40,60)`，
仅使用 `bars[-n-1:-1]`，需要 n 个历史日和今日。服务最多保留
`max(history_bars, max(box_windows)+1)` 根计算日线，默认61根；原趋势指标仍使用原来的短窗口。

箱顶 H=max(历史High)，箱底 L=min(历史Low)，中点 M=(H+L)/2，宽度 W=H−L，比例 w=W/M。
W≤0、M≤0 或 w>15% 不参加候选。历史不足某窗口时跳过该窗口。

Box 的 A=截至 T−1 的 ATR20（已有 `prior_tr` 最近20根TR均值），保存为 `box_atr20`。
不改变已有包含 T 的 `atr20`。ATR收缩与Range收缩完全复用现有排除T的10/20比值。
当仅有20个历史日时，最早TR沿用现有helper的High−Low规则；更长历史使用真实前收。

对窗口内 log(Close) 做等权 OLS，x=0…n−1：

- `box_slope`：每日 log-price 斜率；`box_r_squared`：拟合R²，常量序列为1。
- `box_slope_atr = abs(exp(fitted[n−1])−exp(fitted[0])) / A`。
- `box_occupancy`：Close位于 `[L+0.1W,H−0.1W]` 的比例。
- touch容差=max(0.25A,0.05W)。High≥H−容差计上沿测试；Low≤L+容差计下沿测试。
  连续满足的交易日合并为一次访问，离开容差区后再次进入才新增一次测试。
- `box_start_date` / `box_end_date` 是实际历史窗口首尾交易日期。

## 连续质量公式

定义 `S(x,a,b)`：先把 `(x−a)/(b−a)` 截断到[0,1]，再计算 `t²(3−2t)`；
`G(x,c,s)=exp(−0.5((x−c)/s)²)`；`Q(x,s)=50+50*tanh(x/s)`。

| 组件 | 0–100公式 |
| --- | --- |
| Width | `100*S(w,.01,.05)*(1−S(w,.08,.15))` |
| Flatness | `100*G(box_slope_atr,0,1.5)` |
| Occupancy | `100*box_occupancy` |
| Compression | `sqrt(Q(.90−ATR10/ATR20,.15)*Q(.70−Range10/Range20,.20))` |
| Touch | `100*S(upper_touches,0,3)` |

Width在5%–8%为满分，8%之后平滑衰减到15%的0分；低于5%平滑降分，避免极窄区间额外获奖。
Flatness对上涨与下跌对称降分。Compression与现有Setup使用相同参数和公式；比值缺失的分量为0。
Touch达到3次后不再增分；下沿测试仅解释，不计分。

`box_quality = .25 Width + .30 Flatness + .15 Occupancy + .20 Compression + .10 Touch`。

先保留质量≥60的有效窗口，再找全局最高分。在与最高分差≤3的窗口中选最长周期。
以全局最高分为基准，避免两两比较导致分数差累计。所有值保留计算精度，展示时格式化。

## 状态（按优先级）

设 C=今日收盘/盘中最新价，`d=(H−C)/H`，`z=(C−H)/A`。

1. **BOX_BREAKOUT / 刚突破**：quality≥70，`0.10≤z≤2.0`，今日CLV≥0.60。
2. **BOX_READY / 待突破**：quality≥70，`C≥L`，`z≤0.10`，`d≤0.03`。
   允许不超过0.10 ATR的小幅越顶；恰好0.10且CLV合格时由BREAKOUT优先。
3. **BOX_FORMING / 整理中**：有效箱体quality≥60，`L≤C≤H`，且不满足上述两类。
   质量60–70的近顶箱体也属于形成中。
4. **NONE**：无有效窗口，或今日已经离开箱体但不满足突破资格。
   跌破箱底、过度延伸、越顶超过0.10 ATR但CLV不足/缺失，均不伪装为READY/FORMING。

无有效窗口时研究数值返回null；有有效箱体但今日状态为NONE时仍保留其几何和质量数据。
`distance_to_box_high_pct=d`、`distance_to_box_high_atr=−z`（箱顶下方为正）；
`box_breakout_distance_atr=z`（箱顶上方为正）。UI「距箱顶」显示−d，突破距离显示带符号ATR。

## Official / Preview

两者调用同一纯计算函数。历史窗口仅使用 T 之前的正式前复权日线。
Official以T正式OHLC判断位置与CLV；Preview以T临时OHLC判断。
Preview High/Low/Close均不进入候选窗口、ATR基准、压缩比或箱体Quality。
当临时报价具备High>Low时复用CLV；缺失CLV不确认BREAKOUT。
Preview可从READY变为BREAKOUT，也可撤销盘中突破。

成交量保持原语义：Official真实量比；Preview累计原始量保留但不充当全天估计，UI显示「盘中估算 —」。
不新增成交量预测或行情请求。Preview仍只写现有Redis缓存，不写正式快照、不改变后续状态链。
历史重算逐日截至目标交易日，未来追加K线不会改变该日重放结果。

## API / UI

沿用 `/api/v1/trend-following/ranking`，新增可选 `box_state=NONE|BOX_FORMING|BOX_READY|BOX_BREAKOUT`。
筛选、排序先于limit；过滤请求不复用未过滤缓存。新增sort_by：
`box_quality`、`box_window_days`、`box_width_pct`、`distance_to_box_high_pct`、
`distance_to_box_high_atr`、`box_breakout_distance_atr`。沿用现有服务端降序、缺值置后的规则。

Ranking `features`、Detail `features`、Preview `features`均提供：

- `box_state, box_quality, box_window_days, box_high, box_low, box_mid, box_width_pct`
- `box_slope, box_slope_atr, box_r_squared, box_occupancy, box_upper_touches, box_lower_touches`
- `distance_to_box_high_pct, distance_to_box_high_atr, box_breakout_distance_atr, box_atr20`
- `box_width_quality, box_flatness_quality, box_occupancy_quality, box_compression_quality, box_touch_quality`
- `box_start_date, box_end_date`

正式Ranking缓存升级v8，避免旧payload遮蔽新增字段；Preview key不变，已有Preview待下次运行更新。
旧snapshot不在GET时隐式重算，缺失字段显示「—」，默认机会列表不会纳入旧行。

页面使用完整已有Ranking数据本地筛选/排序，默认仅BREAKOUT+READY；形成中通过筛选打开。
默认按BREAKOUT→READY→FORMING、Quality降序、Alpha降序、code升序排列；Alpha仅同分兜底。
点击列头可覆盖默认排序。共用搜索、虚拟表格、Excel导出和同一Drawer，趋势核心列不变。

## 新配置默认值

全部位于 `TrendFollowingConfig`：

| 参数 | 默认值 |
| --- | --- |
| box_windows / box_min_days | (15,20,30,40,60) / 15 |
| box_max_width_pct / box_ideal_width_pct | .15 / .08 |
| box_width_plateau_min_pct / box_dead_width_pct | .05 / .01 |
| box_flatness_scale_atr / box_inner_margin | 1.5 / .10 |
| box_quality_tie_tolerance | 3 |
| box_ready_distance_pct | .03 |
| box_forming_quality_min / box_ready_quality_min / box_breakout_quality_min | 60 / 70 / 70 |
| box_breakout_min_atr / box_breakout_max_atr / box_breakout_clv_min | .10 / 2.0 / .60 |
| box_touch_atr_tolerance / box_touch_width_tolerance / box_touch_target | .25 / .05 / 3 |
| box_quality_weights | width .25, flatness .30, occupancy .15, compression .20, touch .10 |

Compression继续引用已有 `atr_compression_center/scale`、`range_compression_center/scale`，未修改它们。

## 验证与后续

单测覆盖横盘、方向性通道、宽区间、窗口选择、平局、T隔离、突破边界、缺失CLV和历史重放。
服务回归去掉Box字段后比较完整snapshot与summary，包含Alpha/Entry/Candidate/State/健康指标。
Repository测试JSON读写/标量投影/排序；API测试先过滤排序再limit及缓存隔离；UI覆盖Official/Preview、
旧snapshot、筛选排序、同一Drawer，Playwright覆盖三种桌面宽度和深浅色。

本次未完成5/10/20日forward-return、MFE/MAE校准，也没有新增回测框架。
上线后需要通过既有历史重算流程生成Box历史；本次开发未操作生产数据。
现有Preview的前复权历史与原始盘中报价在除权日可能不在同一价格尺度（见[Entry文档](trend-entry.md#已知数据边界)）；
该已有行情边界同样影响Box，需独立修复。回测还应考虑历史Universe的存活偏差与复权数据修订。

## 后续增量：fresh breakout 与统一研究

BOX_BREAKOUT现在是**新确认突破事件**，不表示连续创新高的持续状态。
最终selected box的几何、Quality、候选选择保持V1；额外检查昨日是否已越过
`max(High[T−N…T−2])` 达0.10–2.0倍昨日判断时的ATR基准（截止T−2），且昨日CLV≥0.60。
若昨日已确认，今日不再生成BOX_BREAKOUT，不使用固定天数cooldown。
`box_breakout_fresh`和`box_prior_breakout_confirmed`供Ranking/Detail解释；
昨日弱越顶、仅上影越顶或CLV不足，不阻断今日首次真正确认。

结构机会与趋势排名共用3/5/10/20D T-close收益列，Preview为空。
正式Ranking缓存当前v9；早期Box历史缺fresh字段，在Event Study中计为覆盖不足，需重算。
统一四策略事件定义、MR、超额收益、MFE/MAE和覆盖率见
[trend-strategy-event-study.md](trend-strategy-event-study.md)。
