# 行业强度（Industry Strength）

行业强度是 **A 股市场观察 / 行业环境分析**。入口为当前 WebUI 的「研究 → 行业强度」
（`/research/industry-strength`）。当前仓库没有独立「分析」顶层菜单，沿用研究导航与二级页签。
仅支持 A 股，不增加 US/HK 分支。行业不是可直接交易的标的，Strength / State 不构成买入建议。

## 来源与可复用 Provider

参考 [扶摇官方行业矩阵示例](https://fuyao.aicubes.cn/best-practices/09-industry-strength-rotation/example.html)
的矩阵、热力图与行业—成分联动；公式改为短线 5/10/20 日，不增加 60 日指标。
协议依据 [官方指数接口文档](https://fuyao.aicubes.cn/docs/api-reference/a-share-index/)。

`integrations/market_data/providers/fuyao.py::FuyaoProvider` 是独立、可复用的数据 Provider，
不导入行业强度业务。它注册三个 CN capability，经现有 registry / router / `MarketDataService` 访问：

| 门面 | Capability | 扶摇 endpoint |
| --- | --- | --- |
| `get_industry_catalog()` | `industry_catalog` | `GET /api/a-share-index/catalog/ths-index-list?tag=industry` |
| `get_index_history(code, start, end)` | `index_history` | `GET /api/a-share-index/prices/historical` |
| `get_index_constituents(code)` | `index_constituents` | `GET /api/a-share-index/constituents/ths-stock-list` |

全部调用固定 HTTPS 官方域名，后端环境变量 `FUYAO_API_KEY` 经 `X-api-key` 请求头传递。
`.env.example` 只有空配置项。不得通过 `VITE_*`、查询参数、任务 payload 或 HTTP 响应传递密钥。
复用统一 FuyaoProvider 的 `_get()`、`_items()`、配置、错误类型及既有 timeout/budget/cache 机制；不另设 HTTP 实现或重试。
错误仅包含安全摘要，不转发上游 body、headers 或 key。

目录每次计算动态获取，不维护固定名单，以扶摇 / 同花顺 industry 目录作为 universe。2026-09-17 的接口验证返回 320 个条目，
这个数量不是配置或契约。目录可能含不同层级及重叠成分，不把所有行业上涨家数相加视为全市场股票家数。

基准固定沪深300 `000300.SH`，与行业指数来自同一个指数 API。请求使用 `interval=1d`、
上海时区自然日边界转换的毫秒 `start/end`；返回 `date_ms`、`*_price`、`turnover` 归一化为
独立 `IndexDailyBar`。指数没有股票复权语义，不伪装成前复权 `stock_daily`。

## 数据流程与 readiness

1. 取最新完整 A 股交易日，并要求它等于当前上海日期。只允许收盘后产生正式快照。
2. 获取最新目录、沪深300与所有行业的指数日线；21 个完整交易日严格对齐交易所日历。
3. 获取行业当前成分，将跨行业股票代码去重后批量查询 `MarketDataService.get_daily_bars()`。
4. 先用 `db_only` 复用已有前复权日线。现有 `cn_daily_sync` Universe 小于全部行业成分；
   对缺少完整 20 个交易日的股票，使用既有 `remote_only` Provider 链批量补取完整窗口到内存。
   不新增股票 Provider，不修改 daily sync Universe，不隐式写入 `stock_daily`。
5. 行业指数数据完整的行业至少占当次目录 **95%** 才可发布。Breadth 独立记录覆盖率，不影响排名准入；某项 Breadth 覆盖低于 **95%** 时仅将该项比例标记为 null。
   基准任一必需交易日缺失、行业覆盖不达标均拒绝发布；不把缺失记作零、不用前值填充停牌。
6. 在整个有效横截面上计算分位、Score、Rank 和状态，原子保存整日结果。
   少量排除的行业与原因记录在任务结果、日志和每个快照 `quality.excluded` 中，页面展示覆盖及排除原因。

参考目录直接固化行业代码和名称到日快照；成分代码固化在 `quality.member_codes` 供内部审计。
不增加重复 reference table，不把 `.TI` 行业指数塞进股票 Instrument 或 ETF Universe。
其他模块需要当前目录时复用 Provider，未来若做持久化主数据维护应复用现有 Instrument / Universe 维护入口。

## 指标与排名

所有 Return、RS、Acceleration、Breadth 比例均以 **小数**存储，前端显示百分比；
RS 和 Acceleration 的差值应按百分点理解。Score 与 percentile 为 0–100。

- `ret_Nd = close[t] / close[t-N] - 1`，N 为 5、10、20。
- `rs_Nd = industry_ret_Nd - csi300_ret_Nd`。
- `previous_5d_return = close[t-5] / close[t-10] - 1`。
- `momentum_acceleration_5d = ret_5d - previous_5d_return`。
- `turnover_ratio_5d = mean(turnover[t-4:t]) / mean(turnover[t-19:t])`。
  20 日成交额必须完整、非负、总额大于零；它衡量自身活跃程度，不奖励行业绝对成交额规模。
- 对三个 RS 与 acceleration 分别计算横截面分位。分位为
  `100 * (严格更小的数量 + (同值数量-1)/2) / (有效行业数-1)`；单行业为 50。
- 每个 `rs_Nd_rank = 1 + 严格更高的行业数`（相同 RS 并列）。
- `strength_score = .40 * percentile(rs_5d) + .35 * percentile(rs_10d) + .25 * percentile(rs_20d)`。
- Score 降序生成唯一 `strength_rank`；相同 Score 以行业代码升序稳定打破平局。**1 = 最强**。
- `rank_change_1d/3d/5d = 对应历史交易日 rank - 当前 rank`，正数为提升。
  按真实交易日偏移，不按“最近存在的第几个快照”替代；历史或行业缺失为 null。
- `ret_1d` 额外用于顶部“上涨行业数”，不是 5 日上涨数。

## Breadth 与时间口径

三个分母分别使用截至观测日的有效、连续交易日窗口，不填补缺日：

- `constituent_count`：当前目录成分总数。
- `daily_valid_count`：T 与 T-1 有效；用于涨跌/平盘计数、`up_ratio`、`equal_weight_return`。
- `ma5_valid_count`：最近 5 日有效；`above_ma5_count / ma5_valid_count`。
- `ma20_valid_count`：最近 20 日有效；`above_ma20_count / ma20_valid_count`。
- 新股只有 10 日历史仍参与 Daily 和 MA5；仅 2 日则参与 Daily。
- quality 保存 `daily_breadth_coverage`、`ma5_coverage`、`ma20_coverage`，以及 `catalog_count`、`ranked_count`。
- 成分获取失败或覆盖不足不会删除指数数据完整的行业。低覆盖比例为 null，计数保留；UI 显示 —，其余展示各自分子/分母。
- State 对缺失 Breadth 跳过该项确认条件，不将缺失转成零；Strength、RS、Acceleration 和 Rank Change 的核心判断保持不变。

**当前成分股等权涨跌仅为行业内部广度代理，不代表行业指数贡献。**
指数本身的涨跌来自原始指数日线，不能用成分等权涨跌替代。

`members_observed_at` 是抓取当前成分的时间，**不是供应商提供的历史成员生效时间**。
历史页面只读取当日保存的 Breadth；不使用今天的成分重算过去。
显式传入 `trade_date` 可补算已收盘交易日的行业指数强度，采用计算时的当前行业目录。
历史补算不读取当前成分或股票行情；Breadth 比例、计数和 `members_observed_at` 为 null，
`quality.breadth_status=unavailable_historical_members`，页面明确标注。已有真实成分观测的历史快照拒绝覆盖。
默认收盘任务仍只生成当天结果。首次部署后逐日积累真实 Breadth 历史。目录增删和少量缺失也会改变排名比较的横截面，排名变化不完全等同于价格动量变化。即使如此，当日抓取的当前列表也不等于官方历史成员档案。

详情下方的“当前成分股”始终单独获取当前列表及最新完整交易日行情，明确显示独立日期与成分获取时间，
不随历史快照日期改变。股票价格为前复权收盘价，不标为盘中实时报价；股票缺失显示空值。

## State（集中配置、确定性判断）

所有阈值位于 `industry_strength/config.py`，规则版本写入 `quality.version`。
按以下优先级匹配第一条，无 LLM：

| 状态 | 条件 |
| --- | --- |
| COOLING | Score ≥60，且 acceleration <0、上涨比例 <45%、Δ3D ≤−3 三者任一成立 |
| EMERGING | Δ3D ≥5、RS5D >0、acceleration >0、acceleration percentile ≥75、turnover pulse ≥1 |
| STRONG | Score ≥75、Rank 在有效行业前25%，3个交易日前 Score 也 ≥75；RS5/10/20D 全正，上涨比例 ≥60%，MA20 上方比例 ≥60% |
| WEAK | Score ≤25、RS5D 与 RS10D 均负、上涨比例 ≤40%、MA20 上方比例 ≤40% |
| NEUTRAL | 其余情况 |

冷却优先，避免高位恶化被 Score 掩盖。持续强势需要历史证据；启动阶段不会伪造它。
“退潮最快”概览按负 acceleration 最低行业显示，若无负值则“暂无”；
“强势数量”只统计 STRONG，不将所有上涨行业视为持续强势。

## 数据库

Alembic `0054_industry_strength` 接续 `0053_trend_states`。
新建独立表 `industry_strength_snapshot`，含指标、三个 RS rank/percentile、前5日收益、
排名变化、状态、成员观测时间、源数据时间、生成/更新时间和质量 JSON。
唯一约束 `(trade_date, industry_code)`；日期与行业代码各建索引；状态有 CHECK 约束。

同日整批 PostgreSQL upsert 保留已有行 id / created_at，更新 updated_at，删除该日不再有效的旧行，
防止“本次95% + 上次5%”混为100%的错误截面。事务级 advisory lock 保证整日发布原子性。
失败不改变已有日快照。历史记录不因后续当前目录变化而改写。

## Scheduler

代码事实源 `tasks/celery/schedule/definitions.py`：

- Job：`industry_strength_cn`；Celery：`scheduled.industry_strength_cn`。
- 时间：周一至周五 **19:10 Asia/Shanghai**，在18:00的 CN daily sync 之后。
- 队列：`analysis`；过期时间沿用 `EXPIRES_ETF_ROTATION`（只复用基础调度常量，不复用策略）。
- 通过任务中心的既有管理员“手动运行”入口触发，无新增同步计算 HTTP 接口。
- 非交易日跳过。任务生命周期记录到 PostgreSQL；独立任务互斥锁避免重复执行。
- readiness / 扶摇不可用：最多重试3次，间隔10分钟；不依赖 Beat 顺序保证数据已经到齐。
- 手动盘中触发不生成昨日 Breadth；因为当前成分不是昨日成分，任务明确失败，等待收盘后运行。

## API

均要求现有登录 Cookie；共享行业观察数据，不读取用户持仓或自选股。

| 路径 | 说明 |
| --- | --- |
| `GET /api/v1/industry-strength/ranking` | `trade_date` 缺省取最新正式日期；可选 `sort_by`、`descending`、`limit`（1–500） |
| `GET /api/v1/industry-strength/dates` | 最近250个有快照日期，降序 |
| `GET /api/v1/industry-strength/history` | `trade_date` 截止日期，`limit` 1–60个快照日，`top` 1–100；默认20天、当日Top20 |
| `GET /api/v1/industry-strength/{industry_code}` | 可选 `trade_date`；所选日指标和截至该日20个快照日历史 |
| `GET /api/v1/industry-strength/{industry_code}/constituents` | 当前成分 + 最新完整日线观察；无历史日期参数 |

排名、日期、详情和热力历史只读 DB，不触发行业计算或访问扶摇。
空排名返回 `items=[]`；指定日期不存在不悄悄回退最新；不存在的行业详情返回404。
排序字段白名单涵盖 Rank、名称、状态、Score、Δ1/3/5D、RS5/10/20D、加速度、三个广度比例和成交脉冲；
默认 Rank 升序、其他数值字段降序，缺失排最后。
成分 endpoint 仅接受最新正式截面已知行业；扶摇错误返回安全503，可独立重试。
公开接口不返回用于审计的 `quality.member_codes`。

## 页面

1. 概览：最强、加速最快、退潮最快、持续强势数量、上涨行业/有效行业数、有效日期。
2. Ranking Table：突出 Rank、状态、排名提升、加速度与广度；点击列名排序。
3. ECharts 气泡矩阵：X=Score、Y=加速度（百分点）、大小=成交脉冲、颜色=State；点击联动详情。
4. ECharts 热力图：所选日期Top20 × 最近约20个快照日；颜色为当日归一化 Rank，悬浮显示真实 Rank。
5. 详情：5/10/20日 Return/RS、加速度、脉冲、Breadth、等权代理、可展开历史指标表，以及独立的当前成分表。

页面提供加载、空态、失败重试、旧日期提示、覆盖与排除清单，遵循 A 股红涨绿跌与现有深浅主题。
快速切换行业/日期采用请求代次防止旧响应覆盖新选择。

## 与 ETF Rotation 的边界

不修改 ETF Rotation 规则、snapshot、Universe 或页面。不输出交易 Action、仓位、止损或候选标的。
行业强度回答“哪些行业强、是否加速、上涨是否有广度”；ETF Rotation 继续回答“哪些可交易ETF符合策略”。
本次没有两个模块的交叉验证或自动联动。

## 验证

```bash
uv run pytest tests/industry_strength tests/test_celery_schedule.py tests/test_celery_task_structure.py -q
# 实际 PostgreSQL upsert 验证需显式提供专用 TEST_POSTGRES_URL，禁止使用业务库
TEST_POSTGRES_URL=<isolated-test-postgresql-url> uv run pytest tests/industry_strength/test_storage_api.py -q
uv run ./scripts/ci_gate.sh
cd web
pnpm run build
pnpm run lint
pnpm run test
pnpm exec playwright test e2e/industry-strength.spec.ts
```

离线测试使用 fake Provider、HTTP MockTransport、SQLite 查询与专用 PostgreSQL schema。
真实扶摇验证仅验证目录、单行业/沪深300历史和一个当前成分列表，未在业务库发布整日结果。


## 指定日期补算与历史选择

`run_industry_strength_cn.apply_async(kwargs={"trade_date": "2026-09-16", "trigger_source": "manual"}, queue="analysis")`
可以生成该交易日的指数快照；未来日期、未收盘日期、非交易日均拒绝。
记录按交易日持久保存，新日期不会删除旧日期；同日成功重算原子替换该日截面。
迁移 `0055_industry_history` 允许未观测成分的历史记录不填成分观察时间，不能虚构历史观测时间进行降级。
页面使用日历选择器查看已保存日期，清空选择返回最新快照；没有快照的日期不可选。
日期目录返回全部已存日期，详情和热力图的窗口仍按现有 API 限制读取。
