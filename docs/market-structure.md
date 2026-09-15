# Market Structure 与 Trend Health

这两组能力用于市场结构解释和趋势风险感知。正式指标在后台计算并写 PostgreSQL；请求只读取、组装和格式化 snapshot，不扫描日线、不重跑 feature/ranking。趋势状态仅描述股票趋势；Qlib 模型不变。

## 复用与业务边界

- Market Structure 复用现有 Daily Sync 的 `cn_daily_sync` / `us_daily_sync` Universe，仅选择同市场 ACTIVE STOCK 成员（排除 ETF），以及 `TrendFollowingConfig.benchmark_codes`（当前 CN `510300.SH`、US `SPY.US`）。没有第二套 benchmark 配置或新增 Provider。
- CN Trend Universe 另含中证 2000，现有 Daily Sync 不覆盖它，因此没有直接把全部 `cn_trend` 作为 DB-only 市场结构样本。现有 CN 日线范围为 CSI300/500/1000，US 为 S&P500；Quant Universe 则可能依赖已有数据库成员配置。快照明确保存 Universe key、样本数及覆盖率；若现有 Daily Sync 股票 Universe 为空或其行情不足，任务失败，不偷偷切换范围。
- `UniverseResolver` 沿用现有当前成员语义，不重构历史成员。Market Structure 的样本应解读为这个 Universe 的结构，而非交易所全部股票。
- `stock_daily` 批量历史读取复用 `TrendFollowingRepository.load_daily_history`；股票成员仅接受数据库前复权日线。每个成员对齐同一组最近 20 个交易所交易日，缺少任一日的标的不纳入本次样本。至少 90% eligible Universe 覆盖才写快照（eligibility 规则见回填章节）。
- Benchmark 通过 `MarketDataService.get_daily_bars(..., adjustment="forward", source_policy="db_fresh")` 读取，复用数据库历史并按需补远程 tail。它是 calculation-only dependency，不要求属于任何 Daily Sync / ETF Universe；远程数据仅参与本次计算，不写 `stock_daily`。目标日及前五个交易日必须全部存在有效收盘价，否则任务失败，不使用 stale benchmark。
- Market Regime 已有 MA20 breadth，但 Quant 采用至少 61 根历史的样本门槛，Trend 使用另一个 Universe 且可有只读远程尾部；两者没有持久化本次同样本的 5D 中位收益与正收益贡献。因此不直接混用其 breadth 数值；从本次 leadership 必须加载的同一批收盘序列计算广度，不再读取第二批 Universe 历史。
- Trend Health 复用现有 `calculate_features`、15D weighted regression、RS、ranking、`count_trend_duration_days`、历史 snapshot、正式/preview 共用 `_run_single_date`。新字段不参与 `rank_candidates` 和交易决策。

## 正式任务与失败语义

```text
Daily Sync（已有）
  → ETF Rotation（已有，18:30 市场当地时间）
  → Market Structure（新增，18:50 市场当地时间）
      → 校验交易日已经收盘
      → 读取当日及最多 5 个历史 ETF 横截面
      → 批量读取股票 Universe 的 DB-only 日线并验证 readiness
      → MarketDataService db_fresh 读取 benchmark（只读补尾部）
      → 计算 breadth / rotation / leadership
      → 单行原子 upsert
```

`market_structure_cn` / `market_structure_us` 在周一至周五当地时间 18:50 发布到 `analysis` 队列，分别用 `Asia/Shanghai` / `America/New_York`，保留 DST 行为。注册、路由、TaskRecord 生命周期和 Task Center 手动运行均复用已有注册表。

依赖通过当日 ETF snapshot 的存在检查，而非仅靠时钟保证。Market Structure 不重新运行 ETF Ranking；ETF 任务迟到/失败时本任务失败，可以在上游完成后手动重试。交易日非收盘、benchmark 缺失、股票覆盖不足也不生成新快照。没有与 Daily Sync / ETF Rotation 共用写事务，失败不回滚上游。

Dashboard 显示最近正式快照的日期；落后于日历的最近已收盘交易日时显示“暂无今日市场结构数据”。没有任何 request-time 计算回退。本版没有 Market Structure Preview。

## Snapshot 与 API

迁移 `0050_market_structure_health` 接在 `0049_notification_center` 后面：

- 新表 `market_structure_snapshot`：`id`、`market`、`trade_date`，唯一约束 `(market, trade_date)`；`market` 限 CN/US。
- Float 列：`benchmark_return_5d`、`median_member_return_5d`、`breadth_divergence_5d`、`member_positive_ratio_5d`、`member_above_ma10_ratio`、`member_above_ma20_ratio`。
- Float 列：`rotation_velocity_1d/3d/5d`、`leadership_concentration_1d/5d`、`leadership_hhi_5d`。
- `metrics_json`：算法版本、Universe/benchmark、覆盖率、样本数、正收益股票数、Top 样本数、ETF 比较日期和状态分类。`created_at` / `updated_at` 为 aware UTC；重跑同日保留 id 和 created_at。
- 已有 `trend_following_snapshot` 加 nullable `trend_lifecycle`、`fragility_score`、`fragility_breakdown`。已有 `trend_duration_days` 继续复用。没有新增 Trend 表，不改历史结果，旧行新增字段为 null。
- Trend 的新增解释特征、`health_version=1`、归一化排名保存在已有 `features` JSON。汇总阶段数量和高脆弱性趋势数量写入已有 summary `features`。

接口：

```text
GET  /api/v1/market-structure?market=CN[&trade_date=2026-09-01]
POST /api/v1/market-structure/run
```

GET 默认读最新，指定日期精确匹配，缺失返回 404。响应包含 `market`、`trade_date`、`expected_trade_date`、`breadth`、`rotation`、`leadership`、`metrics`。GET 要求登录；POST 要求管理员，返回 202 / task_id。

Trend 已有 ranking、detail/history、preview 接口自然携带新字段。Ranking 返回 lifecycle、duration、fragility_score，完整 breakdown 在 detail/history/preview snapshot 中；支持 `sort_by=fragility_score`。更新了正式排名缓存 schema，旧缓存不会遮蔽新字段。

请求时派生仅包括最近已收盘日期、快照过期提示、字段分组、百分比/小数格式和前端状态文案。没有另存或新增 fragility_level；breadth/rotation 状态在任务中生成并保存。

## 公式与单位

收益和比例以小数存储，前端显示百分数；velocity、归一化 HHI 和 fragility 使用 0–100。

### Breadth Divergence

```text
r5_i = close_i(t) / close_i(t-5 exchange sessions) - 1
D5 = benchmark_r5 - median(r5_i)
positive_ratio = count(r5_i > 0) / n
above_MAk_ratio = count(close_i > mean(last k closes_i)) / n
```

分类优先级（`market_structure/config.py`）：

1. benchmark 5D 上涨且 D5 ≥ 2.5 个百分点：STRONG_DIVERGENCE。
2. benchmark 5D 上涨且 D5 ≥ 1 个百分点：MILD_DIVERGENCE。
3. 5D 上涨占比 ≥ 70% 且 D5 < 1 个百分点：BROAD_STRENGTH。
4. 其余 NORMAL。指数下跌期间不会误标“指数上涨、成分股跟不上”。

### Rotation Velocity

比较 `etf_momentum_snapshot.rank`（综合排名），不是 `rank_1d` 或重新计算 ETF 因子。

```text
rho_N = Spearman(rank_t, rank_(Nth previous snapshot date))
velocity_N = 50 × (1 - rho_N), N ∈ {1, 3, 5}
```

Spearman 用平均并列秩的 Pearson 相关实现。完全相同 = 0，完全反转 = 100。少于两个 ETF、成员集合不一致、排名缺失、常数序列或历史不足均为 null；不取交集伪装相同 Universe，不按自然日回退。

主展示 3D。分类：`[0,20)` STABLE、`[20,50)` NORMAL、`[50,75)` FAST、`[75,100]` EXTREME。

### Leadership

```text
p_i = max(r_i, 0)
k = ceil(0.10 × n)
concentration = sum(largest k p_i) / sum(p_i)
w_i = p_i / sum(p_i)
HHI_raw = sum(w_i²)
HHI_100 = 100 × (HHI_raw - 1/n) / (1 - 1/n)
```

Top 10% 的分母人数是全部有效样本（含非正收益股票），不是正收益股票数。无正收益时 concentration、HHI 均为 null；单样本且上涨时两者分别为 1、100。1D/5D concentration 均持久化，HHI 主展示 5D。这个指标描述正收益分布，不代表市值加权指数点数贡献。

## Trend Lifecycle 与 Fragility

原 Trend feature 没有 ETF 同名 quality/acceleration/efficiency。没有重跑 ETF feature，而是在 Trend 本次已加载的价格数组上补充：

```text
quality = 100 × existing weighted_r2_15d
acceleration = 252 × (weighted_log_slope_5d - existing weighted_log_slope_15d)
signed_efficiency_10d = (close_t - close_(t-10)) / sum(abs(daily close change), last 10)
distance_from_recent_high = close_t / max(last 20 closes) - 1
rank_percentile = (rank - 1) / max(cross_section_size - 1, 1)
```

Acceleration 是年化对数斜率差，不是百分位分数；Quality 衡量拟合稳定度。RS 直接复用 `rs_5d`，MA20 距离直接复用 `distance_from_ma20`。

### 六个 Fragility 分量

每项以之前第 3、第 5 个市场正式 snapshot 日为基准；有两个基准时取两者分量的平均，有一个时使用该基准，不足时 null。只使用 `health_version=1` 的特征，缺行情携带过来的旧状态不成为新的观察值。

| 分量 | 0–100 归一化（clip） | 权重 |
| --- | --- | --- |
| acceleration_decay | `(历史 acceleration - 当前) / 0.50 × 100` | 25% |
| quality_decay | `(历史 quality - 当前) / 30 × 100` | 20% |
| efficiency_decay | `(历史 signed efficiency - 当前) / 0.50 × 100` | 15% |
| relative_strength_decay | `(历史 rs_5d - 当前) / 0.05 × 100` | 15% |
| rank_decay | `(当前 rank_percentile - 历史) / 0.25 × 100` | 15% |
| price_structure_risk | `max(-高点距离/0.10, -MA20距离/0.05) × 100` | 10% |

总分 = 可用分量加权和 / 可用权重之和。可用权重低于 50% 时总分 null，不把“只有价格结构”包装成完整 Fragility；所有缺失分量仍保留 null。高脆弱性汇总阈值为 65，且只统计非 BROKEN 的可用趋势。全部阈值集中在 `trend_following/health_config.py`。

Fragility 不使用 trend_score 或 alpha_score 的补数。稳定的 90 分趋势可以得到 0；同样 90 分、但多个内部特征迅速恶化的趋势可以超过 90。权重是解释性规则，不代表经过回测验证的交易阈值。

### Lifecycle 最终规则（按优先级）

1. `trend_candidate=False` → BROKEN。复用现有四条件至少三项通过的绝对趋势定义；它与六态 state 的 BROKEN 判断独立。
2. 当前没有可用 feature/duration（包括仅携带旧状态的标的）→ null。
3. 至少两项 Fragility 分量 ≥ 50 → EXHAUSTION；candidate 此时仍成立。
4. duration ≤ 3，acceleration > 0，quality ≥ 50 → IGNITION。
5. 未满足 IGNITION 且 duration ≤ 7 → EMERGING（硬年龄上限）。
6. duration ≥ 20 → MATURE，不再要求高质量/正效率/加速度阈值。仍有效且没有充分衰竭证据的老趋势不会退回 EMERGING。
7. 7 < duration < 20，quality ≥ 80，efficiency ≥ 0.55，RS5 ≥ 0，价格高于 MA20，acceleration ≥ -0.05 → EXPANSION。
8. 7 < duration < 20 的其余有效趋势 → MATURE。这里表示已过早期形成、处于存续阶段，不为了年龄强行标成强扩张，也不退回早期 EMERGING。

原实现把 MATURE 与严格 healthy 条件绑定，并对未匹配的所有年龄统一 fallback EMERGING，导致 30D / 35D 趋势仅因 acceleration=-0.08 就被标成早期趋势。本修复只增加当前 snapshot 的年龄约束，不依赖前日 lifecycle，不创建状态机，不调整 Fragility 定义或权重。MATURE 不代表强趋势、买入或卖出。

MATURE 仅描述成熟阶段。生命周期为解释字段，不改变 state/setup。

## 页面与 Preview

- Dashboard 新增紧凑 Market Structure 区域，CN/US 独立加载、失败和重试；四项指标可展开说明，并展示样本范围/广度明细。另展示来自正式 Trend summary 的阶段数量、高脆弱性数量及独立日期，不展示个股明细。
- Trend Ranking 保持 12 列：原 duration 单列改成 Lifecycle + 次级 Age，原 Setup 主表位置改为 Fragility；Setup 仍在详情中。Lifecycle/Age 列保持按年龄排序。
- Trend Detail 展示年龄、阶段、质量、加速度、signed efficiency、脆弱性；六项 breakdown 默认折叠，增加读取历史 snapshot 的小型 Fragility 折线图，null 保留断点。
- Rotation Velocity 本版放在 Dashboard；ETF 页面重复展示不是必需，未新增独立市场结构页。
- Preview 走同一个 `_run_single_date(persist=False)`，读取之前的正式历史作为基准，计算相同 lifecycle/fragility，最后仅写已有 Redis preview。正式任务不读取 preview，preview 不反馈下一次正式结果。不新增 lifecycle task。

## 查询数、Point-in-time 与回填

Universe 使用已有 resolver（按 Universe 结构批量成员查询），不对每只股票查询。Market Structure 的股票历史日线、ETF 横截面、全历史 `MIN(stock_daily.date) GROUP BY instrument/code` 各一条 SQL；benchmark 另做一次 MarketDataService db_fresh 批请求；ETF 日期子查询限制最多六个日期。仓储测试在 1/500 个请求标的下都验证是三条股票行情/eligibility/snapshot 查询，benchmark 的补尾部走已有门面。写入一个原子 upsert。

Trend 新增一次市场级历史查询，最多前五个正式日期；内存按 code/date-offset 建索引。日期偏移按市场日期集计算，不随个股缺失重新编号。现有策略需要的 previous-state 查询继续保留。

用于收益计算的日线条件 `date <= trade_date`，ETF 条件 `trade_date <= requested`，Trend 基准严格 `< requested`；计算函数再次排除未来数据。历史查询直接读取存量 JSON/列，不扫描旧 K 线。没有历史 Universe 改造，因此当前成员筛选及现有前复权存储的既有历史语义仍然适用。

### Historical eligible universe

继续解析当前配置的 Universe，不查询历史指数成员。`Instrument.listing_date` 虽然存在，但允许空值：TickFlow 目录读取可选 ext，证券补录/其他 fallback 路径不保证带上市日期；没有统一的日期可靠性标记。因此采用同一个批量查询的首条 `stock_daily.date` 作为开始交易的代理：

- first_trade_date > target_date：排除在 eligible 集合之外，不进入分母。
- first_trade_date ≤ target_date（包括恰好当天）：保留在分母。缺目标日、20-session 中任何一根 bar、或上市不满20个交易日均使其不 ready，但不删除它。
- 无日线/没有查到首次日期：无法证明尚未开始交易，保守保留分母，不以缺数据提高覆盖率。

`eligible_universe_size` 是上述集合人数；`member_count` 是其中满足原完整 session 要求的股票数；`data_coverage = member_count / eligible_universe_size`，仍要求 ≥90%。eligible 为空时失败，不除零、不保存快照。此规则对正式计算和手动回填使用同一条路径。

`metrics_json` 保存 `current_universe_size`、`eligible_universe_size`、`member_count`、`data_coverage`，以及 `eligibility_basis=first_available_stock_daily`。已有 `universe_size` 字段作为 eligible 分母的兼容别名，让现有 UI 的样本数/覆盖率分母一致，不改 Dashboard 设计。旧 snapshot 不自动改写。

Historical Market Structure uses the currently configured universe, excluding members that had not started trading by the target date. It does not reconstruct historical point-in-time index membership.

首次本地日线仅是交易开始的代理：历史存储本身被截短时，可能晚于真实上市日期。本次不修复历史数据缺口，也不恢复已退出当前 Universe 的成员。首日聚合允许看到目标日期之后的首次日期，但仅用于用户要求的 eligibility 筛选，未来价格与排名不参与指标计算。

管理员手动回填例子：

```http
POST /api/v1/market-structure/run
Content-Type: application/json

{"market":"CN","start_date":"2026-09-01","end_date":"2026-09-11"}
```

也可以传 `{"market":"US","trade_date":"2026-09-10"}`，或在 Task Center 手动运行最新日期。范围内按交易日依次处理，单日原子写入；遇到不完整日期停止并让任务失败，已完成日期保留，可补齐上游后重试。历史 ETF 不足仅使 rotation 对应 horizon 为 null；当日 ETF 缺失则整日不写。迁移和服务启动不会自动回填。

Market Structure 可以在已有股票 DB 日线、当日 ETF snapshot 和 db_fresh benchmark 历史足够时回填。旧 Trend snapshot 未保存短窗斜率、signed efficiency、高点距离和新定义版本，不能可靠直接重建完整 health；本次不提供伪造的 Trend 历史回填，也不调用现有交易状态重放来覆盖历史策略结果。新版本上线后自然积累，至少出现一个可用 3D 基准后才有完整分数的可能。

## 验证

- 公式、状态、并列排名、成员变化、无正收益、缺历史、未来数据排除、读取 API 不计算、批量查询、preview 不落正式库均有离线测试。
- SQLite 上实际执行 migration upgrade/downgrade，验证旧 Trend/ETF 行不变；可用专用 `TEST_POSTGRES_URL` 执行 PostgreSQL migration、精确日期读取及重复 upsert 的 id/created_at 保持测试。
- 完整后端门禁使用独立临时 PostgreSQL/Redis，避免连接开发库。Web 执行 build、lint、Vitest 和 Dashboard/Trend 的桌面 Playwright 检查。

本次验证结果：后端完整门禁 2134 passed、20 skipped、2 deselected（含专用 PostgreSQL 迁移/upsert 测试）；Web build 通过，lint 0 errors（既有格式警告），Vitest 514 passed，Dashboard / Trend Following 桌面 Playwright 12 passed。检查了 1280/1440/1920px Dashboard 以及 1280/1440px Trend Detail 深浅色截图。

PR #295 review 修复：benchmark 改走 db_fresh；新增 CN 未持久化 benchmark 成功、失败不写快照、未来数据排除和只读调用契约测试。

Lifecycle Age / historical eligibility review 验证：相关 Market Structure、Trend Health、Trend service/preview、API、Celery schedule/task 聚焦回归 142 passed、1 skipped；独立临时 PostgreSQL/Redis 上完整 `scripts/ci_gate.sh` 2162 passed、20 skipped、2 deselected，104 subtests passed（包含专用 PostgreSQL 测试）。Benchmark db_fresh 修复及其回归测试保持通过。

### Trend State Heatmap（趋势状态轨迹）

趋势跟踪页面排名表格上方增加独立加载的状态热力图，使用 ECharts Heatmap、现有主题和详情弹窗。
纵轴固定为锚点日期按 `snapshot.rank ASC, code ASC` 选出的 Top 50；不是每天重新选择 Top 50，
也不受页面表格搜索/排序影响。横轴取 DB 中最近 30 个存在 `trend_following_snapshot` 的 session，
缺失快照或无有效 Rank 的历史格子保留 null，不填充、不重算 State。纵向滚轮/滑块默认查看约 20 行，
可浏览全部 50 行；单元格和股票标签可打开锚点日期的现有 Detail。

接口为 `GET /api/v1/trend-following/state-history`，参数 `market=CN|US`、`days=30`（1–120）、
`limit=50`（1–100）、可选 `as_of=YYYY-MM-DD` 和 `include_preview=false`。
返回 `anchor_date`、升序 `dates`、`official_count`、`preview_date/time`、`generated_at`、`warnings`，
以及 `items[{code,name,current_rank,history}]`。每只股票的 `history` 与 `dates` 按位置对应；
单元格附带原始 rank/state、Alpha/Trend/RS Score、Fragility 和持续天数。

正常历史读取固定两次 SQL：先取市场 snapshot session，再在 SQL 内选锚点 Top N 并批量读取其历史标量字段。
Preview 模式从 Redis `snapshots` 按 Rank 选 Top N 后走同一个批量历史查询，不加载全 Universe 的历史 JSON。
没有历史或显式日期无快照时可提前返回，最多两次 SQL，无逐股票/逐格查询。

`as_of` 是精确锚点，所选日期无快照时不暗中替换成前一日 Top N；超过市场当地今天返回 422。
历史日期不读取 Preview。只有当地当天已完成的 Preview 可作为额外第 31 列，并以 Preview 的 Rank 选股；
当天已有任何正式 snapshot 时全列和 Top N 都使用正式数据。Preview 用 `P` 日期后缀、列边框和说明标识。
无可用 Preview 时提示并展示可用正式历史（未指定 `as_of` 时锚点为最新正式 session）。

颜色表示股票趋势 State：IDLE 灰、WATCHING 蓝、CANDIDATE 青、TRENDING 绿、
WEAKENING 黄、BROKEN 红；不是数值评分或额外的 `trend_lifecycle` 分类。
注意现有策略可能在行情缺失时**持久化**延续的持仓状态/Rank，热力图忠实读取这些已有快照；
它本身不做前向填充，也不据此判定行情一定新鲜。旧快照缺失 Fragility/持续天数显示 `—`。

历史锚点中的股票即使已退出当前 Universe，仍可通过带明确 `trade_date` 的现有 Detail 接口查看；
必须存在该日真实 snapshot 及 summary，否则返回 404。Preview 详情保持现有模式；
若热力图因同日正式快照而优先展示正式列，点击会打开正式详情及其 Rank / Fragility 历史图。
