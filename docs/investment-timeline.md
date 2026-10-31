# Investment Timeline / 投资时间线

投资时间线是公共市场信息看板，所有用户读取相同内容；只展示宏观事件与财报日历及财报前瞻。
新闻抓取、分析、历史存储和新闻页签已退役。市场报告在[消息中心](notifications.md)查看。

## 数据与 API

唯一事件源为 `finance_events`，`calendar_type` 为 `earnings` 或 `macro`。
财报前瞻继续关联 `earnings_outlook` 的状态、研究版本和首日股价验证；相关表不受新闻退役影响。
`timeline_entries` 是已停用的旧表，不读写。

`GET /api/v1/timeline` 支持 `end_date`、`timezone`、`market`、`category=event`、
`calendar_type=earnings|macro`、`importance`、`high_confidence`、`cursor` 和 `limit`。
旧 `category=news|analysis` 及旧新闻游标返回422，不查询已删除新闻表。

响应只包含 `source_type=finance_event`、`category=event` 的条目。
`detail_payload` 保留内容、事件日期、准确时间/全天标识、公司、盘前/盘后时段、报告期、币种、
实际贡献来源、EPS预期/实际/惊喜比例及重要性依据。财报前瞻详情与管理员刷新接口保持不变。

## 排序、时间与分页

排序固定为 `event_time DESC, source_type ASC, source_id DESC`。
未来财报和宏观事件也按此顺序排列，前端保持API顺序，仅按展示日期分组。
游标保存时间、来源及ID，按严格seek取下一页，顶部插入或删除已读锚点不影响翻页。

准确时间使用 `event_datetime`，仅有日期时以市场当地午夜为锚点：US为America/New_York，其余为Asia/Shanghai。
持久化与DTO使用UTC，前端按用户展示时区渲染。
CPI/FOMC、非农和利率决议等核心宏观事件为critical，其他事件复用重要性评分。
重要性过滤包含所选等级及以上，不改变时间排序。

`end_date` 是截止日期，包含展示时区当天及更早事件，不限制历史起点；省略时保留全部未来事件。
页面默认截止今天，提供未来7/14/30天和自定义日期。切换时区重算快捷日期，自定义日期保留。
筛选或时区变化清空游标重新加载，后续使用IntersectionObserver追加服务端返回的页面。

## 前端

`/timeline` 仅保留“全部 / 财报 / 宏观”。财报和宏观分别使用
`TimelineEarningsCard`、`TimelineMacroCard`，共享卡片外壳与现有详情Dialog。
财报详情保留来源、EPS、研究证据、高置信度筛选和手动刷新；宏观详情继续展示事件内容。
市场沿用全局开关；布局沿用响应式CSS columns，保持DOM与API顺序。
Dashboard读取相同事件接口，不再展示新闻。

## 迁移与边界

`0086_retire_news` 删除新闻三张表及其数据、盘前新闻任务/通知/LLM用量和专属日志。
宏观、财报、财报研究及其审计记录保留。详细范围与部署语义见[新闻退役说明](news-removal.md)。
Longbridge行情和财经日历能力继续使用；财报与信号研究原有的专用联网证据流程保持不变。
定时美股收盘复盘只使用自身结构化行情输入，不再读取新闻。

## 验证

覆盖宏观/财报过滤、时区边界、未来事件、重要性、游标分页、财报详情和新闻退役迁移。
离线测试与前端构建命令见仓库AGENTS指南。

## 美股财报前瞻与首日预测

`earnings_outlook/` 是财报专用研究模块，是上述禁止通用互联网研究规则的明确例外。
其他模块的信息输入边界不变。不产生 TradeSignal，不修改持仓/现金，不发送消息。
宏观和 A 股继续原有同步及重要性评分；重要性分数不参与两类预测置信度。

### 覆盖、任务与成本

- 财经日历美股同步和前瞻统一只使用 `UniverseResolver.resolve_universe("us_nasdaq100")`
  当前有效 STOCK 成员（QQQ 对应的 Nasdaq-100 股票成分），按 Instrument ID 去重。
  成员列表空或失败会记录异常，不回退到 S&P 500、自选股、ETF 或其他 Universe。
  仅收缩本流程；其他模块的 S&P 500 股票池不变。历史事件与成功版本保留，移出成员不能作为有效前瞻或高亮。
- 日历保持今天到未来30天。每天纽约07:00同步完成后仍异步投递 `analysis.earnings_outlook`
  （analysis 队列），`stage=daily` 作为兼容的自动扫描入口，新增成功版本只保存以下三个自动阶段：
  - `initial` 初版：发现事件且该适用日程没有成功自动前瞻时执行一次，普通字段补全和每天同步不重复执行。
  - `near` 临近版：按纽约日期，距离公布日还有1–3个**日历天**时执行一次；窗口不是每日刷新。
    首次分析已进入窗口时直接生成 near，同时满足初版资格，只执行一轮 research＋outlook。
  - `final` 最终版：保留纽约16:10下一交易日扫描。该阶段成功后，同一适用日程不再自动执行。
  取消财报前7天每日刷新。较晚发现时允许阶段合并，near 满足 initial，final 满足 initial/near，
  不为凑三轮补调较早阶段。正常提前发现有三轮，每轮仍有 research 与 outlook 两个调用步骤。
  日历不等待研究，重要性任务独立；所有阶段重新采集最新价格和公共市场输入。
- `scheduled.earnings_outlook_final` 每个美股交易日纽约16:10扫描**下一交易日**财报，BMO优先，再AMC。
  当前日AMC依靠前一交易日最终版，16:10不做当天AMC事前预测；执行/保存均检查发布截止。
  周末/节假日用项目XNYS交易日历；缺少真实日历时失败关闭，不能以自然日代替。
- `scheduled.earnings_outlook_review` 每天纽约23:30更新财报后首日股价验证。正常交易日收盘（含提前收盘）后，
  只读目标交易日及前一交易日的DB前复权日线，不请求LLM、外部财报、日历或其他外部数据。
  未收盘或缺精确交易日日线时保持pending，任务中心显示部分完成；数据库异常按失败记录。
- `POST /api/v1/timeline/earnings/{event_id}/outlook/refresh` 为管理员异步手工刷新，返回task_id。
  同事件使用非阻塞 PostgreSQL session advisory lock；多个worker共享默认2个研究槽位，可配置1–8。
  前瞻槽位只包住每次 LLMClient 调用（包括其回退/重试），资格/阶段判断、上下文采集和业务写库不占槽位。
  两阶段之间释放槽位；竞争时状态恢复pending，保留上一成功预测及已保存研究，延后重试复用同阶段有效研究。事件锁仍覆盖整轮，
  防止手工/定时重复执行；股价验证仅保留事件锁，不占用LLM研究槽位。
  槽位或事件锁忙时按原event_id/阶段60秒内延后投递，跨日不重新扫描下一日；消息在发布截止时间过期，
  执行及保存仍重新检查截止时间，避免最终刷新被静默丢弃。
  网络调用期间没有DB写事务；失败记录状态/原因，原成功版本和展示指针保留。
- 研究TTL默认24h，key含**阶段**、Instrument、event_id、季度、事件日程、结构化预期/指引和prompt版本。
  near/final 必须重新搜索，不复用其他阶段的研究；同阶段 outlook 失败重试可复用尚有效的本阶段研究。
  价格变化不强制研究；资料过期、已知预期/指引或日程变化使研究缓存失效。
  自动成功去重先于资料/行情采集，按**事件＋适用日程＋阶段**判断，与运行日期、研究TTL及预期字段更新无关。
  失败不计为成功；手工 manual 为显式例外，不消耗或重置自动阶段资格。相同阶段input_hash仍有数据库唯一约束。
  公共SPY/QQQ和既有板块ETF走势、市场结构、宏观日历按批次惰性复用，无需新阶段时不采集公共上下文。
  旧 `EARNINGS_OUTLOOK_LOOKAHEAD_DAYS` 不再使用，前瞻候选范围固定30天，与日历范围保持一致。

配置见 `.env.example` 的 `EARNINGS_OUTLOOK_*`。没有新增必需付费服务。
技术上下文最多30个完整交易日，包括OHLCV、区间涨幅、收益波动、ATR14；历史财报最多4季，是事件样本。
证券到行业基准没有可靠映射时明确缺失，提供公共板块ETF表现。分析师修正、期权覆盖范围、历史财报价格反应
仅使用已有结构化资料，不为缺项引入采集系统。报价时间用于判断会话，缺失时间的价格不作预测参考。

### 两阶段与搜索证据

1. `earnings_research`：逐个事件研究，查询必须含公司名、代码、季度及财报词。
   输入只保留事件身份、公司、截止时间、预期、指引、分析师修正与历史财报；不携带股价、原始K线或大盘行情。
   第二阶段 `earnings_outlook` 保留个股最多30日完整K线；公共SPY/QQQ和板块ETF只传既有
   return_pct、volatility、atr14、sessions、as_of等摘要，去掉重复公共OHLCV数组。
   宏观、市场结构、缺失说明和来源不裁剪。压缩后的上下文同时用于模型输入、input_hash和预测快照，
   不修改线程间共享公共快照，也不减少批次事件数或提高并发上限。
   通常只用近30天资料，最近一季官方指引可更早。保存来源、发布时间、检索时间、事实引用及冲突采用理由。
   一致预期与个别分析师观点分开，不平均混合季度/单位/GAAP口径。
2. `earnings_outlook`：不搜索，输入冻结的context和research bundle，分别判断经营表现与价格反应。
   EPS/营收不能根据大盘和涨幅推断。可以beat且下跌，也可以meet但强指引上涨。

传输层保存 requested、configured_support、status、citations、tool_events。
`confirmed`只表示传输层确认搜索执行，不意味着每个事实都已验证；`unverified`是请求但未确认，
`unavailable`是未配置/不支持。模型自行写出的sources不算执行证据；没有确认的外部事实不作为新增可信输入，
但高质量既有结构化资料仍可用于受限分析。渠道及版本核验见[LLM文档](llm.md#财报专用搜索)。

来源发布晚于研究开始的data_cutoff时排除；日期不明的资料明确标记，相关预测不能高置信度。
可信官方资料已经报告目标季度时冻结。有reported_eps（包括0）或提供方原始实际营收/EPS时直接冻结。
AMC最迟在当天正常收盘冻结；BMO有明确时间时取该时间与开盘的较早值，无明确时间时在事件日纽约零点冻结。
会话未知也在纽约零点冻结。网络调用结束保存前再次检查发布时间和事件日程，过期结果不写成事前成功预测。

### 比较口径与价格

EPS与营收分别比较分析时点的一致预期，保存季度、币种、单位、来源、时间；EPS另要求gaap/adjusted。
读取日历EPS以及Longbridge原始details中的营收预期/实际值。提供方缺失的季度、币种、EPS口径和预期时间保持null，
不把`last_seen_at`或来源检索时间当作一致预期更新时间；不可比较时unknown。
明确的结构化输入或有效research可补齐。日历缺季度时，只接受有日期官方IR来源明确绑定公司代码、
本次发布日期及财季；保存到研究与冻结输入，不按发布日期猜季度，不改原始日历身份/版本哈希。
后续提供方补全已确认的同一季度不使预测失效。财报后的验证只评价股价，
不采集、搜索或比较实际EPS/营收；上述财报比较口径仅用于公布前预测。

- EPS meet容差：`max(abs(预期)*2%, 0.01 USD)`；非USD不强套美元绝对值。负EPS仍用绝对值算容差，数值越高越好。
- 营收meet容差：`abs(预期)*1%`。上述值可配置，仅用于公布前预测，快照保留当时配置。
- 置信度为模型证据评分，非胜率：0–3资料不足/冲突，4–6有依据但不确定，7较充分，8–10证据新鲜且互相支持。
  两类分数与理由独立。预期缺失/过期限制财报评分；价格不可用则只保留财报判断。会话暂定或关键资料不确定限制走势评分。
- BMO目标为发布日正常交易日；AMC为下一个正常交易日；会话未知暂按下一交易日并显示provisional及假设。
- 预测含reference_price/time/session、expected_close、intraday_low/high。涨跌幅由代码计算。
  方向up/down采用相对参考价超过±1%，否则flat；价格无效则uncertain。该阈值也用于复盘。
- 区间必须`0 < low <= close <= high`，错误只降级价格部分，不影响财经事件。乐观/基准/悲观情景不编造概率。
  区间不包含夜盘，不是保证或有指定覆盖率的统计置信区间。

### 存储、查询与展示

`0069_earnings_outlook`新增3表：`earnings_research`（资料/传输证据）、`earnings_prediction`
（不可变成功预测、完整输入及模型元数据）、`earnings_outlook_state`（状态、最新成功指针、精简摘要和独立actual）。
JSONB保存研究/预测，成功版本保留。事件日程变化时旧版本superseded；失去指数资格时ineligible；GET也即时检查适用性。
历史详情保留不适用版本，但不能继续作为当前有效目标日预测。
日程适用性比较发布日期、明确时间、BMO/AMC 与证券身份；季度由缺失补为已知不算改期，两个已知季度冲突仍失效。
真正改期后旧版本不抵扣新日程阶段；按新日期重新选择 initial/near/final。

无需数据迁移，不重写成功历史：旧 `daily` 在适用日程下满足 initial；若其生成时纽约日期距离公布日1–3天，
同时满足 near。窗口外 daily 不抵扣 near。旧 final 满足三阶段，manual 不抵扣任何自动阶段。
按所有适用成功版本判断，不只看最新指针，所以新阶段失败或后续手工刷新不会丢失已完成资格。

列表增加可空`outlook`，按页批量读取精简摘要，不逐卡请求；仍保持event_time DESC、cutoff和cursor分页。
最近成功版本在事件仍适用且未到发布截止前持续展示，超过24h不会整份失效，新阶段失败保留上一成功版本。
`expires_at` 对新版本保存发布截止；摘要增加 `fresh_until`/`freshness`，与 `status=current/frozen` 的适用性分开。
资料新鲜截止取研究TTL、当前行情上下文24h及发布截止的最早值；旧摘要沿用原 `expires_at` 仅作新鲜度截止。
陈旧时仍显示预测、生成时间和阶段，并标“资料待更新”；旧 daily 仍显示“历史每日版”。
`high_confidence=true`在后端分页前执行，匹配当前有效、资料新鲜且至少一种非unknown判断达到8分的事件。
卡片与筛选共用同一适用性/高置信度判定；公布后改标“公布前预测”，取消高亮。
`GET /api/v1/timeline/earnings/{event_id}/outlook`按需返回资料、情景、输入、最近100个成功版本及实际对照。

股价验证保存在独立actual JSON（`review_kind=price_v1`），包含精确目标交易日OHLC与前一交易日收盘价。
首日涨跌幅为`(目标日收盘/前一交易日收盘-1)*100`；预测命中另按冻结reference_price计算实际涨跌与方向，
避免把预测前已经发生的价格变化混成首日涨跌。方向阈值沿用±1%（边界为flat），同时保存收盘误差（预测减实际）、
相对实际收盘的百分比误差及区间是否同时包含实际high/low。缺日不顺延，不请求实时行情或外部日线。
已有完整日线即可completed；原预测无有效参考价/方向/价格区间时，对应比较字段缺省并说明无法比较，
不因EPS、营收或预测缺项永久pending。行情为前复权DB日线；长期复权基准变化可能影响冻结绝对价格对照。
原预测版本不改写，不新增表或迁移。旧金融复盘的EPS/营收在GET中不再返回，GET只投影已存价格、不写库；
旧pending及completed在下一次23:30任务中重新按股价规则计算一次，新版completed后跳过采集。

### 部署与验证

1. 更新代码并同步依赖（现有exchange-calendars、LiteLLM，无新增付费依赖）。
2. 备份数据库，在目标环境按标准流程运行 `uv run alembic upgrade head`；server启动也会迁移。
3. 更新server、普通worker和beat，启用已有analysis队列。前端运行`cd web && pnpm run build`。
4. 若使用API搜索，核验模型/网关后配置`LLM_API_SEARCH_MODE=chat_completions`；否则保持unavailable，
   已配置Codex在财报研究调用中优先。不要仅凭配置或模型自述判断已搜索。
5. 管理员可按event_id手工提交任务；任务中心和详情记录状态。此实现不自动部署、不触发真实通知。

离线测试：`uv run pytest tests/earnings_outlook tests/test_market_calendar_task.py tests/test_llm_client.py tests/test_llm_fallback.py -q`。
本地验证使用独立PostgreSQL副本复制公开证券/股票池/财报/日线，不复制账户数据；LLM、搜索和实时价格均mock。

### 前瞻执行耗时诊断

服务日志按 event_id 输出 context、earnings_research、earnings_outlook、total 的 duration_ms，
异常退出也记录；模型调用额外记录 prompt_chars，不额外输出研究正文。
context 包含公共快照首次采集/等待；两类LLM阶段耗时包含槽位获取以及LLMClient内部回退、审计；
total还包含事件锁连接、资格判断与业务持久化。这些阶段耗时有包含关系，不能直接全部相加。
结合现有LLM JSONL的attempt、search_evidence、ssh_ms、cli_execution_ms、api_ms定位瓶颈。
本次保持模型回退和搜索证据要求，不基于模型自述判定搜索成功。实际生产加速幅度需由日志确认。

### 个股决策分析已退役

美股盘前个股分析、手动单股分析及决策仪表盘 Prompt/pipeline 已删除，不再生成新结果。
美股收盘复盘继续运行；盘前新闻及其历史由 `0086_retire_news` 删除。历史数据删除与共享依赖处置见 [删除清单](stock-analysis-removal.md)。
