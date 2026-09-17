# A 股市场情绪 / Market Sentiment

页面 `/research/market-sentiment`，仅完整 A 股交易日的盘后观察。数据全局共享，登录后读取，管理员可异步运行。不读持仓、不调用 LLM，不产生交易动作、仓位或收益预测；与 Industry Strength、ETF Rotation 的 Market Regime、Trend Following、Quant 及个股 `sentiment_score` 独立。

## 数据源与契约

唯一生产入口为现有 `MarketDataService → registry/router → FuyaoProvider`，后端复用 `FUYAO_API_KEY`，没有新增 SDK/CLI/MCP 依赖，也不改变既有 provider inventory 或 fallback。新增 CN capabilities：`limit_up_pool`、`limit_down_pool`、`limit_break_pool`、`limit_up_ladder`。

官方参考（2026-09-17 阅读；Financial-API commit `0a629aba2b3977a419f7c4330972d2047c8612da`）：

- [04 涨停池与连板天梯](https://fuyao.aicubes.cn/best-practices/04-limit-up-market/example.html)
- [12 涨停情绪市场脉冲屏](https://fuyao.aicubes.cn/best-practices/12-limitup-sentiment-timing/example.html)
- [官方 Skill / REST 契约入口](https://github.com/HiThink-Tech/Financial-API/tree/main/skills/hithink-finance)
- [涨停池](https://github.com/HiThink-Tech/Financial-API/blob/main/skills/hithink-finance/references/api/a-share/special-data-limit-up-pool.md)、[天梯](https://github.com/HiThink-Tech/Financial-API/blob/main/skills/hithink-finance/references/api/a-share/special-data-limit-up-ladder.md)、[跌停池](https://github.com/HiThink-Tech/Financial-API/blob/main/skills/hithink-finance/references/api/a-share/special-data-limit-down-pool.md)、[炸板池](https://github.com/HiThink-Tech/Financial-API/blob/main/skills/hithink-finance/references/api/a-share/special-data-limit-break-pool.md)

版本差异：示例12 README 仍写“接口不提供炸板池”，且建议有限天梯样本晋级；当前原子文档已提供炸板接口。FA 按原子契约接入补充池，晋级只使用完整涨停池，未复用示例模拟数据、静态状态或演示算法。

三个池都显式发送上海零点 `date_ms`、`page=1..`、`size=200`、`sort_dir=desc`。涨停按 `continue_day_cnt`，跌停按 `last_limit_time`，炸板按 `open_times` 排序。每页验证页码、size、total、pages、预期行数、标准 `thscode`、唯一代码与源版本一致；最多100页并受120秒请求预算约束。失败、重复、缺页均不返回完整源。`code=0,total=0` 是合法零；3002、超时、权限错误等不是零。限流复用原有退避。

`requested_trade_date` 是请求目标日期；`source_timestamp` 是文档定义的数据就绪时间；`fetched_at` 是 FA 抓取时间。源时间不得早于请求日收盘或明显晚于抓取时钟；若响应有 `date_ms` 回显则校验一致。契约未提供强制交易日回显，故日期依据明确记录为 `explicit_date_ms`，不会拿源时间的自然日当作历史归属日。历史就绪时间可以晚于目标日期。真实协议未验证前不宣称上游兑现了此契约。

金额以元保存；`price_change_ratio_pct` 原值保留，规范字段 `price_change_ratio` 只除100一次。时间、原因、金额缺失不删除涨停记录。

## 主观察口径与指标

主观察固定 `is_st=false AND is_new=false`。`is_new` 仅指官方未开板新股，不按上市天数推断。保存完整上游池，同时返回上游总数、主观察数、ST/新股各自排除数、去重排除数与未知标记数。非法/缺失布尔值规范为 null，原始标记另存；无法确认主口径时相关聚合为 null。

连续性采用保守契约：`continue_day_cnt` 为正整数，并与明确 `首板`（要求1）、`N连板` 或 `N天N板` 文本一致才计连续板。`5天4板`、首板计数0、缺文本、数值冲突均标记未确认，不猜测0/1约定。主口径存在未确认连续性时，首板/连板/最高板/板位分布以及依赖它们的热度和晋级保留缺失，涨停参与数仍可用。真实首板计数含义尚须按下述验证步骤核对。

- 涨停数 L；首板数；连续2板及以上数 M；最高实际连续板数。
- 板位为1/2/3/4/5/6/7+，真实最高板不截断。
- 早封率：`limit_up_time ≤ 10:00` 数 / 时间有效数。`config.py::SentimentConfig.early_time` 可配置；只接受合法 `HH:MM` 及竞价/交易时间段，空值和不可解析值不入分母。同步提供有效数量、分子和相对主池覆盖率；UI 只称“涨停时间”，不擅称首次。
- 封单留存：非负 `seal_money / max_seal_money`，要求峰值>0且比值在[0,1]；当前额0有效，峰值0无效，异常不裁剪。市场取有效样本中位数，返回样本数与覆盖率。
- 当前封单额为非负有效金额样本合计；返回金额字段覆盖率。非空池全缺金额时合计 null；合法空池合计0。不是成交额、净流入或主力买入，留存不保证不撤单/不开板。
- 涨停原因按清理首尾空白后的完整文本分组，空值归“未提供原因”；不拆词、不自动对应行业。图展示前12项，可点选过滤明细；完整分组通过 overview 返回。

跌停和炸板只作为上游全池补充，不套用 ST/新股筛选，不进主评分，不假设两池互斥，不计算炸板率或封板成功率。

## 晋级

真实相邻交易日 T-1、T，按代码匹配。1→2、2→3、3→4 及连板总体：以前日相应连续板位（总体为≥2）的主口径集合为分母，今日仍在主口径且连续高度恰为原高度+1为分子。返回来源/目标日期、完整性、分子分母、晋级与未晋级代码。分母0、缺前日完整源、口径或连续性未确认时比例 null。不跨缺口使用前一个“有数据日”。未晋级不等于跌停/亏损。

## 状态规则 v1

规则集中在 `market_sentiment/config.py`，版本 `fa-market-sentiment-v1`。前20个真实交易日须都有完整有效的 L、M，不含当日，不跨缺口或向前填充；不足时热度 null、UNKNOWN，但可保存其他指标。

历史分位 `100 × (小于当前值的历史数 + 0.5 × 等于当前值的历史数) / 20`。
`heat_score = 0.60 × percentile(L) + 0.40 × percentile(M)`，范围0..100。

按以下顺序匹配，不强制阶段迁移：

| 状态 | 条件 |
|---|---|
| UNKNOWN 数据不足 | 必要计数或20日历史不足 |
| ICE 冰点 | 热度≤20 |
| COOLING 退潮 | 前3真实交易日出现热度≥60；较昨日跌≥15分且 L、M 均下降 |
| REPAIR 修复 | 昨日热度≤35；今日升≥15分，L增加、M不降 |
| DIVERGENCE 分歧 | 今日或昨日热度≥60；L不降但M下降，或总体晋级/早封/留存中至少两项较昨日降≥10个百分点 |
| CLIMAX 高潮 | 热度≥85、L和M不低于昨日，且有效早封或留存≥60% |
| ACTIVE 活跃 | 热度≥60 |
| NEUTRAL 平稳 | 其余 |

日比较只认真实相邻交易日；缺条件不会通过。早封/留存用于确认和比较均要求覆盖≥80%；晋级用于比较两日各自分母均须≥5。返回命中原因及规则版本。可选池、天梯、行业强度完全不进热度。

## 存储、迁移和发布

迁移 `0056_market_sentiment` 接在实际 head `0055_industry_history` 后；无网络取数：

- `market_sentiment_source_snapshot`：日期、来源类型、请求日期、源/抓取时间、total、item_count、规范 JSONB 明细、质量及天梯实际窗口；无 Instrument FK。
- `market_sentiment_snapshot`：日期主键、规则版本、状态、生成时间及包含指标/覆盖率/晋级/原因的 JSONB。

同日重跑替换完整 generation；核心失败不写库。可选失败仍发布核心并标记不可用，同日旧补充源不会悄悄拼入新 generation。源与对应聚合在同一事务提交；补旧日后按时间顺序重算所有已保存后续日的晋级、热度和状态。任务独立 advisory lock 防止并行计算；发布另有事务锁。读取不会看到单个事务内的半成品。无新缓存、并发调优或任务编排系统。

天梯无日期请求参数，单独以实际返回窗口的最新日期归档，`requested_trade_date=null`。`as_of` 只选择截至该日已保存窗口，不伪造历史请求、不用今天窗口填过去。每个板位最多4只，展示真实窗口，不推算剩余只数；后验 `seal_nextday` 不进入规范展示源，更不参与当日计算。

## 调度与补数

`market_sentiment_cn` / `scheduled.market_sentiment_cn`：工作日19:20 Asia/Shanghai，`analysis` 队列。复用 `ScheduledTaskDefinition`、`track_task`、任务中心、日志和独立 advisory lock。执行检查实际交易日和收盘；日历不可用时拒绝计算。普通取数错误有最多3次任务重试、间隔600秒；Provider限流另按现有1/2/4秒退避。

管理员可以在任务中心触发最新完整交易日，或页面提交以下 `/run`：

```json
{"trade_date": "2026-09-16"}
```

```json
{"backfill_days": 31, "missing_only": true}
```

两个参数互斥。首次补最近最多31个完整交易日，按日记录完成/失败并继续；默认只补缺失或有可选错误的日期，失败后可重复同一请求。`missing_only=false` 可强制刷新最近窗口。单日可指定任一日历支持的已完成交易日。正常每日不重复下载历史；补数不会从今天的股票池推造过去。结果任务记录里 `status=partial` 表示存在按日失败，不等于全部补齐。无需等行业强度任务成功。

## API / 页面

所有 GET 登录后只读 PostgreSQL：

- `GET /api/v1/market-sentiment/overview?trade_date=`：概览、`expected_trade_date`、同日既有行业强度Top5。
- `GET /history?end_date=&days=30`：真实交易日窗口，缺口对应 null。
- `GET /pool?trade_date=&kind=&board=&q=&page=&size=`：`kind=limit_up|limit_down|limit_break`；板位1..6/7+。可用 `scope=main|all`、完整 `reason` 文本筛选。size最大200。
- `GET /ladder?as_of=`：独立有限样本窗口。
- `GET /dates`：已保存日期。
- `POST /run`：仅管理员提交 Celery，202返回 `task_id`，HTTP不计算。

日期省略才选最新；显式无数据返回该日与 null，不切换日期。未获取池 `available=false,total=null`，完整空池 `available=true,total=0`。

页面在研究导航紧邻行业强度，沿用 ECharts、浅深主题、API错误控件。历史点击联动日期；完整梯队、晋级名单与官方有限天梯分视图；表格筛选不更改顶部固定主口径。明细含原始原因和连板文本、金额/时间/涨幅与ST/新股标记。补充来源及行业Top5均不触发行业计算。

## 验证和上线边界

离线测试覆盖完整分页和失败、合法零、连续性文本、单位、有效分母、代码晋级、周末/春节、状态优先级与质量门槛、原子替换/回滚、补数派生重算、GET只读/鉴权和页面日期联动。独立 PostgreSQL 测试通过 `TEST_POSTGRES_URL` 运行，绝不指向开发/生产库。

有界真实验证命令：

```bash
uv run python scripts/check_market_sentiment_protocol.py
```

复用现有后端配置，最近完整日小页、两个相邻日完整涨停池、官方窗口/上限、跌停与炸板；结果存 `DATA_DIR/tmp/sentiment-protocol-*`，仅打印摘要。密钥不打印、不进入浏览器、不提交。没有配置时退出码2且不发请求。

本次开发环境未配置后端 `FUYAO_API_KEY`，故未完成线上权限/可用性、真实首板0/1与多天多板语义、源就绪时间及历史日期契约核验。离线通过不能替代这些上线检查；对于未确认连续性，本实现保留缺失，需获得真实样本后再确认是否支持其他文本约定。示例HTML不能作为实际行情证据。

本次没有重新修订行业 Universe/指标/状态，没有性能优化、盘中Preview/推送、回测、自动交易或新增用户配置。

本次实际执行结果：后端完整 `ci_gate.sh` 通过（1876 passed、21 skipped、92 subtests），其中市场情绪专项56项全部通过，包含独立 Docker PostgreSQL 16 的真实迁移与原子发布验证。Web Vitest 467项通过，lint 0 errors（仓库既有380 warnings），build成功。新增 Playwright 在1280/1440/1920宽度×浅深主题6项通过，并检查截图。线上验证脚本实际执行后因缺少 `FUYAO_API_KEY` 返回2，未发真实请求。
