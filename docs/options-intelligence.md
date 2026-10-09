# Options Intelligence

独立美股低频期权研究模块，入口 `/research/options-intelligence`，现有股票详情弹窗新增「期权」Tab。
不预测股价、不下单，不改个股分析、Trade Engine、股票日线维护或现有新闻边界。

## 启用与运行

沿用 Python/SQLAlchemy/Alembic、现有 FastAPI 与 Celery Worker/Beat，无新运行服务或 SDK。

```bash
uv run alembic upgrade head
# 使用原有部署流程启动/重启 server、普通 worker、beat、web
```

迁移 `0070_options_intelligence` 接在 `0069_earnings_outlook` 后，创建：

- `option_contract`：OCC 唯一合约身份、标的、类型、到期日、strike、multiplier。
- `option_quote_snapshot`：每股票/30分钟桶的正式盘后来源隔离链批次；原始标准化数据只保存一次，包含报价时间、成交时间、OI 日期与来源。
- `option_daily_metrics`：每股票/交易日首个有效盘后结果，不由后来发布的 OI 或补充扫描覆盖。
- `option_anomaly_event`：每日股票/合约/事件/来源/feed唯一；初始证据不可变，最新证据和关键变化分开。
- `option_analysis`：关联快照的结构化 LLM 解释、prompt、原始结果与模型，每快照一次。

扫描范围为数据库 `Universe.key=us_nasdaq100` 中当前有效的 Nasdaq-100 股票成分股，加全部用户的美股自选股，规范代码后去重。成分股复用证券主数据维护，不在扫描中联网同步。
读扫描页只显示 Nasdaq-100 与**当前用户自己的**美股自选范围，不泄漏其他用户的监控成员关系。默认六标的与持仓补充池已移除。
历史列表按当前可见范围过滤，未重建历史成分；按所选日期精确查正式结果，缺日不回退旧日期。
详情为共享市场研究事实；普通用户可显式刷新单只美股，管理员可以运行全范围扫描。
首次安装无数据时为空态；点击「刷新期权链」提交 Celery 任务，页面跟踪任务状态后读取已存数据。
需要实际运行 Worker，不在 HTTP GET 中抓取或写入市场数据。

配置位于 `options_intelligence/config.py`，数值初始规则可用同名 `OPTIONS_*` 环境变量覆盖，常用值见 `.env.example`。
默认排除0DTE、90D以上、行权价/现价范围0.7–1.3之外、已知非100股合约和调整OCC根代码。未知乘数可展示报价，标记未确认，不计算权利金。到期日选择优先保留30D两侧及近7/60D，再填充最近到期日。合约预算在选中期限间轮流分配，各期限优先保留同strike ATM Call/Put双边及OTM样本（有Delta时优先近25Δ），避免近月挤掉远期。Yahoo请求期限数不增加；两来源分别遵守期限数和最多2500份合约限制，覆盖记录保存实际期限、双边数量与截断情况。
比率、活动与异常仅代表筛选后的链，不代表整个期权市场；覆盖范围随每次快照保存。
请求顺序执行，加跨任务 PostgreSQL session advisory mutex，避免盘中、盘后与手动扫描同时抓取。
Redis缓存整批源观察900秒，读取缓存保留原始观察时间，缓存故障允许直接读取来源。

## 数据与来源优先级

业务通过 `MarketDataService.get_option_chain` 进入 `integrations/options`，不自行选择股票Provider。
简单Provider协议支持注入离线fake，不增加通用Provider框架。

1. **yfinance优先**：复用已有 symbol 映射、yfinance依赖与公共重试。通过 `Ticker.options` / `option_chain` 读取到期日、Call/Put、OCC、strike、bid/ask、last、lastTradeDate、volume、OI、IV、underlying。
2. **Alpaca回退缺失能力/失败**：复用已有 `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` 与 HTTP错误分类。Market Data `GET /v1beta1/options/snapshots/{underlying}` 明确发送 `feed`，完整分页读取报价/可见最优size、成交及返回时可用的IV/Greeks/dailyBar。
3. 合约/OI来自 **Trading API只读** `GET /v2/options/contracts`，不是 Market Data端点。显式到期日边界覆盖默认近周末限制；保存 `open_interest_date`，读取 `multiplier`/`size`。

同一合约不同来源保留不同观察，前端可切来源，绝不字段拼接。Volume/OI、ATM IV优先Yahoo；标准30D IV、近ATM Put IV与每个7/30/60D Skew分别按该能力的可用性回退。Yahoo只有短期限IV不能挡住Alpaca有效30D数据，最近到期日缺Delta时选择容忍区间内真正可用的同到期IV+Delta。
实时可成交风险与流动性异常事件只用有真实时间且新鲜的非Indicative独立报价。页面的 Liquidity Risk 是采集时点的研究代理，允许有效的未知报价时间/Indicative，以及属于该交易日的收盘报价；始终低可信度，不声称实时NBBO。已知属于其他交易日或未来的报价不评分；同合约只选一份完整来源评分（新鲜真实优先），不双重计数。OI确认只用同来源有日期的相邻交易日数据。
Yahoo缺少有效标的现价时，通过注入现有股票行情门面的报价方法取得独立现价及时间，再进行Alpaca筛选；不创建递归的期权门面调用。首次缺价但稍后补价时重新筛选。始终缺价且合约超限时明确报告无法筛选，不按最低strike截断；未超限的原始链可以展示，但ATM、Moneyness等相关指标为N/A。独立现价另存来源限制与时间，不借标的价格伪造缺失Greeks。

Yahoo不提供可靠bid/ask时间、IV时间或OI日期；lastTradeDate不是quote时间。
Yahoo报价和OI可以展示，但实时流动性评分、主动方向、OI次日确认不能据此构造。
Yahoo仅在lastTradeDate的纽约日期与扫描交易日一致时推定Volume日期，保留 `volume_session_inferred` 限制。未知日期或其他交易日成交量不参与当日活动评分；Alpaca未成交合约可能保留前一交易日dailyBar，原始数据仍展示。
Alpaca快照IV时间没有独立字段，也不会用quote时间伪装IV时间；同时刻检查能排除已知报价不同步，但无法证明IV计算时刻，证据等级限制保留。

官方资料：[Option chain](https://docs.alpaca.markets/us/reference/optionchain)、[Contracts](https://docs.alpaca.markets/us/reference/get-options-contracts)、[Options data SDK](https://alpaca.markets/sdks/python/api_reference/data/option/historical.html)。
Indicative报价经过修改、成交延迟，不能称作真实NBBO或真实主动买卖。

### 初始实现的实际检查（2026-10-08）

开发机真实Yahoo AAPL链读取成功，两到期日样本123个合约。
从用户指定部署目录安全读取Alpaca凭据，只读检查返回：

- 合约查询200，包含明确OI日期与multiplier。
- Indicative snapshot 200，包含latestQuote/latestTrade/dailyBar/minuteBar/prevDailyBar；抽样没有IV或Greeks。
- OPRA snapshot 403，因此不启用OPRA逐笔方向能力。
- 历史OPRA trades检查400、历史quotes探测404，未确认可用历史报价端点/权限，不据此宣称已实现Trade/Quote匹配。

双来源归一化和指标引擎也用真实AAPL数据执行。部分Yahoo合约返回零Bid/Ask、零OI与占位IV，因此不构造有效ATM IV或流动性结论；IV默认有效范围为1%–500%，可配置，零/零报价对应IV不参与波动率指标。相关N/A是实际数据限制，不是模拟零分。
最终四到期日检查保留Yahoo285条、Alpaca348条来源观察、279条带日期OI，源错误为空。492条Volume属于目标交易日，其他旧日期或未知日期不用于当日评分。检出6个规则异常，Unusual Activity初始规则分100、证据C，Bearish Demand/Liquidity Risk/30D IV/25Δ Skew不可评分或不可计算；不能将此初始分当作历史异常分位数。这个检查只验证外部读取及指标引擎，没有写入部署数据库。

没有保存或打印凭据。凭据需要继续配置在正常运行进程的环境中，本模块不硬编码读取部署机 `.env`。
OPRA缺失不阻塞Yahoo主链。未来获得权限时可设置 `OPTIONS_FEED=opra` 使用真实快照；此版本仍不启用逐笔主动买卖。

## 指标

- Spread = `(ask-bid)/((ask+bid)/2)`；负数、零ask、crossed、非有限/缺失报价不可用。零bid单独提示。
- Quote Freshness：真实quote timestamp距计算时间≤300秒；未知、未来或过期不参与实时可成交风险/异常。GET保留采集时点的研究评分和报价状态，不用打开页面时的时钟重新覆盖快照。
- 可见size只描述最优报价可见数量，不是完整订单簿。
- Volume/OI：达到默认volume≥100、OI≥100才用于评分/异常，避免小分母。
- Premium估算 = `mid × volume × multiplier`，明确标为估算，不是真实成交权利金，latest trade不能代替全日VWAP。
- 若真实OPRA快照提供**同交易日**dailyBar VWAP和volume，可计算实际报告聚合权利金 `VWAP × volume × multiplier`，不据此推断主动方向。没有则N/A。
- 异常Volume历史按相同标的、Put/Call、DTE分桶、Moneyness分桶、来源/feed和采样时段比较；不按固定strike。至少20个**不同历史交易日**才给历史分位数，midrank处理相同值。
- Put/Call Volume与OI按1–7/8–21/22–45/46–90D分别展示。Volume仅使用同来源/feed、有效非负值且日期为当前交易日的合约，排除旧日期、未知日期及重复样本，个别无效合约不使整组比率失效。无有效Put、无有效Call或Call分母零时为N/A；coverage记录双边有效数量、比例与排除的重复数，部分覆盖的可用比率明确降低可信度及证据等级。OI仍要求双边字段完整。
- 25Δ Skew = `IV(25Δ Put)-IV(25Δ Call)`：同到期/同来源/feed，有效Delta包围目标才插值，不能外推或跨来源拼接；已知时间差≤120秒。展示7/30/60D目标及实际可用期限，选近期限有容忍界限；缺Delta不由strike伪造。
- Skew Change仅与同来源、**同实际到期日**先前观察比较，避免换月跳变。
- ATM IV：同strike近ATM Call/Put均值；标准30D在两侧期限之间以总方差线性插值，再除以30D并开方。无包围期限不伪装30D。
- IV Percentile：同来源/同采样时段标准30D历史≥20日才计算，保留样本数。
- RV：20个完整、精确交易日对数收益的样本标准差×√252。IV/RV使用一致无量纲年化率；IV到期时间ACT/365，不将日历日当作交易日。
- Term Structure按实际期限选择完整的同来源计算结果，Yahoo有效ATM IV优先，缺失时回退Alpaca；独立Provider期限数据保留在coverage。标准30D按同一能力优先级选择，有效插值两端必须同来源/feed，其支撑期限在曲线中展示并记录实际来源。倒挂事件只比较同来源/feed的有效期限，不跨来源比较近远月。
- Expected Move优先新鲜同strikeATM Straddle Mid，否则明确模型 `spot × IV × √(DTE/365)`。保留方法与实际期限；不附带预测保证或置信度概率。
  新鲜真实ATM Call/Put报价足以计算Straddle Mid，不依赖Provider另行返回IV。

## 三个评分、等级与事件

三个0–100评分独立，不生成总分，不等价于股价下跌概率。

- Bearish Demand：可用Put/Call Volume、相似DTE/Moneyness Put IV、25Δ Skew的历史分位数，Skew变化、Put权利金估算活跃度及发布后的OI佐证。预热期间允许绝对规则：22–45D当日双边有效成交总量≥`min_volume`时，Put/Call比率÷`OPTIONS_PUT_CALL_DEMAND_REFERENCE`×50（默认比率1对应50）；有效Skew的正值÷`skew_alert`×`activity_rule_level`。封顶100，无相应证据仍N/A。历史分位数足够时优先采用；绝对规则参与的评分明确low，不伪造历史。按可用独立分量归一权重。
- Unusual Activity：同类Volume历史分位数、满足绝对门槛的Volume/OI、权利金估算分位数、OI佐证及同类型多合约共同出现。历史不足时仅有明确门槛的绝对证据可给初始规则分，否则N/A。
- Liquidity Risk：观察报价研究代理，使用价差、当日volume、OI、最优size的可用分量，不把报价年龄当作历史流动性风险。实时合约 `risk` 另含时效且要求新鲜真实报价，`observed_risk` 为研究代理。Spread容忍值随权利金、DTE、Moneyness变化；极低权利金、深价外、近到期、零bid单独提示。初始规则尚未按标的历史流动性校准，可信度low。

方法、证据数量、方向、confidence、evidence_grade分开存储。
A要求有效OPRA、明确IV时间与充足历史；当前Alpaca快照不提供IV时间，不能自动获得A。
B是有效日度链和足够历史但无可靠逐笔方向；C覆盖预热、Indicative相关证据及关键缺失。
选用某项Indicative Skew/IV时，相应事件证据C；不把另一个来源的历史基线转借给它。

事件支持 PUT_VOLUME_SPIKE、CALL_VOLUME_SPIKE、VOLUME_OI_ANOMALY、LARGE_PREMIUM_ACTIVITY（可能为估算）、BEARISH_SKEW_SPIKE、IV_SPIKE、IV_TERM_INVERSION、LIQUIDITY_DRY_UP、WIDE_BID_ASK_SPREAD、OI_BUILDUP_CONFIRMED。
每日来源+feed维度唯一约束防重复，初始证据不可改，原值、严重程度、参考基线、证据等级等关键变化单独保留（最多48个）；仍有效的事件更新最新证据时间。
OI有明确日期、同来源且相邻有效交易日才比较；变化于网络完成/计算时才可知。
更新被验证交易日相关事件的validation，不修改原始评分/发生时间；无增长也保存验证结果。OI增长不证明看空或实时开仓。

事后评价在GET中批量只读股票DB前复权日线：以首次可知时间`occurred_at`后的首个有效NYSE开盘为基准。交易日盘前使用当天开盘，盘中/盘后使用下一交易日，周末/假期使用下个有效交易日；真实日历处理夏令时及提前收盘。计算1/3/5D收益、前5D最大不利low变化、后续20D RV及其变化、SPY/QQQ同步基准。
使用交易日历精确对齐，缺日不顺延；原始信号永远不接收这些事后结果。

## 调度与API

`options_intelligence_intraday`：纽约时区工作日9–15点，0/30分触发；执行时严格检查真实NYSE开闭市，过滤假期、盘前与提前收盘后的时段。
`options_intelligence_daily`：纽约14:00/17:00检查，收盘至少30分钟后执行；14:00覆盖13:00提前收盘，17:00覆盖常规16:00收盘。日度基线每交易日只保存一次，后来OI仍可更新独立事件验证。
复用ingestion队列与TaskRecord生命周期，不创建新的Worker。

`intraday` 仅写Redis：摘要键 `options_intelligence:preview:v2:US`，单股详情键附加纽约交易日和symbol。
摘要与详情同一Redis事务发布，在纽约午夜过期，GET拒绝旧日期。只保留最新盘中状态；单股刷新合并同日已有摘要，全范围扫描重新发布本轮成功股票。全部失败保留上轮结果并报错；部分失败在TaskRecord摘要中明确数量，失败股票不会回填正式数据。Redis写入失败让任务失败。
`daily` 写 PostgreSQL，并使用现有独立日度基线；同一标的/交易日的首个基线不覆盖。禁止将收盘前缓存链转成正式日度数据，也禁止仓储保存非daily结果。历史盘中记录不删除，但正式GET通过日度基线关联读取，避免与旧盘中链混合。读取历史评分不随当前时间重新判过期。
盘中成交累计不能与正式全天成交直接比较，所以preview历史成交分位数仍为N/A；可用绝对规则照常计算。IV/Skew可对比先前正式收盘观察，显式标记`volatility_comparison=prior_daily_closes`并保持看跌评分低可信度，`volume_history_days`单独报告。
前端扫描页和股票期权Tab都有「盘中预演 / 正式收盘」与正式日期选择，列表打开详情继承当前模式/日期。预演缺失独立显示空态，不回退正式结果。正式LLM解读可指定所选日期；preview不自动写LLM/异常事件表。
规则版本 `options-v2` 从新扫描起生效，已有正式评分保留，不自动重写历史。

| API | 行为 |
| --- | --- |
| GET `/api/v1/options-intelligence` | `view=official|preview`；`trade_date=YYYY-MM-DD`选择精确正式日期；返回available_dates与摘要 |
| GET `/api/v1/options-intelligence/{symbol}` | 同样支持view/trade_date；返回对应链、指标、截至日期的日度历史、事件与事后评价、LLM历史；history_limit≤120 |
| POST `/api/v1/options-intelligence/{symbol}/refresh` | 显式异步单股刷新，body可选view；仅符合所选模式的时段可执行，返回task_id |
| POST `/api/v1/options-intelligence/{symbol}/explain` | 已有正式快照的用户主动LLM解释，可选trade_date |
| POST `/api/v1/options-intelligence/run` | 管理员异步扫描，body可选symbol和view |

GET不拉远程行情；按view只读Redis预演或PostgreSQL正式结果。所有接口受既有Cookie/JWT会话保护，手动任务归属当前uid，可在任务中心跟踪。

LLM沿用LLMClient，仅显式请求或配置自动重要异常时调用，自动解释按快照所属交易日每标的最多一次，跨日盘前刷新也不会重复自动解释上一交易日。
提供已算分数、来源、异常合约、IV/Skew、DB近期价格、已持久化Longbridge新闻与财经日历。解释所选历史快照时，新闻/日历可知时间与日线截止均限制在快照计算时点，不能借用后续事实。
不启用通用Web Search：仓库现有信息边界只允许earnings_outlook做联网研究例外。
2026-10-09 Review只读抽取生产AAPL既有日度链1770条观察，在开发环境纯计算重放（未写生产数据）。零历史样本下v2得到Bearish Demand 24.6、Liquidity Risk 50.2，均为low；历史分位数仍不可用。旧前端同时有IV与Skew图时，在离线浏览器mock中1.5秒内高度从140px增长到700px；v2用固定224px父容器和绝对定位图表阻断百分比高度/自动resize反馈。

结构化解释包含关注原因、可能催化剂、保护需求与方向证据区分、其他解释、数据限制与交易风险。
LLM失败不撤销已成功存储的期权数据。

## 验证与边界

```bash
uv run pytest tests/options_intelligence tests/test_celery_schedule.py tests/test_celery_task_structure.py tests/test_task_advisory_lock.py -q
cd web
pnpm exec vitest run src/components/options-intelligence/__tests__ src/api/__tests__/optionsIntelligence.test.ts src/config/__tests__/mainNav.test.ts
pnpm run build
FA_WEB_SMOKE_BACKEND_CMD='uv run uvicorn finance_analysis.interfaces.api.app:app --host 127.0.0.1 --port 8000' pnpm exec playwright test options-intelligence.spec.ts
```

离线单测覆盖公式、无效/旧报价、极小OI、来源归一化与回退、历史预热、次日OI不污染原始信号、事件去重、迁移上下行、API权限/异步归属和事后交易日对齐。
前端冒烟测试使用明确mock，验证应用路由、详情Tab、空值、模式继承、指标hint、连续resize周期图表尺寸稳定及390/768/1024/1280/1440/1920px深浅色布局；不把Mock冒烟测试当作真实市场验证。
初始实现审查后聚焦后端111项、前端单测6项、浏览器12项通过；Vue构建、后端syntax/flake8和修改文件ESLint通过。全量后端2622通过、39个失败/4个错误；全量前端664通过、38个失败。失败列表与修改前基线完全一致，全量lint既有3个错误也在基线复现，未宣称全量门禁全绿。迁移在临时SQLite执行上下行并对齐模型/唯一约束；开发机PostgreSQL测试连接不可用，未执行生产迁移或生产部署。

提交前自审修复了期限能力回退、缺失Delta到期日选择、Call-only OI导致无依据看跌零分、OI纽约日期边界、多来源OI重复计数、事件参考基线变化遗漏、合约乘数补全、跨日自动解释去重、无IV时真实Straddle计算以及前端到期日刷新；对应行为有离线回归测试。

本版不包含OPRA逐笔方向/大单识别、0DTE高频监控、全市场历史链补采、标的流动性历史校准或交易执行。
没有完整历史时正常展示原始指标和明确初始规则/N/A，通过实际日度采样积累历史，不用未来OI回填过去评分。

PR #383遗留问题修复仅在本地执行离线验证，新增37项回归用例，覆盖密集近月合约预算、现价早期/晚期回退及请求完成时间、Volume日期及覆盖、独立来源期限/30D插值、盘前和夏令时评价。全部期权测试101项、相关行情/API/Celery/任务生命周期测试190项、前端单测6项通过，失败0项；后端syntax/flake8、修改文件严格F检查、组件ESLint及TypeScript/Vue构建通过。本轮未重跑全量门禁或浏览器冒烟，不改变数据库结构、公共API契约、评分阈值或权重，也没有重新访问生产环境或验证外部行情权限。
