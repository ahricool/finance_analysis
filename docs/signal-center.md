# Unified Signal Center v2

信号中心主动读取 PostgreSQL 当日正式研究结果，生成共享股票/ETF研究信号；不下单、不改持仓。
每市场每天最多3个BUY，允许0个；CN/US合计最多6个。所有来源走同一初筛路径，不设直通名额。

## 候选范围

| 来源 | 规则 |
| --- | --- |
| Trend 20d | 当日正式排名前30 |
| Trend 40d / 60d | 各自当日正式排名前10 |
| ETF Rotation | 当日正式排名前10，ETF本身可成为最终BUY |
| Industry Strength | CN行业前5，每行业按已物化Trend rank取前3；US不适用 |
| Confluence | 读取当天完整正式批次：与前端默认展示共用已保存结果，目前上游最多10只；不在本模块重排或再次截断 |
| Quant | 不直接读取、不新增候选、不提供明细 |

按canonical symbol合并去重，保留各来源提名与20/40/60日独立上下文。同一ETF/股票只占一个候选。
共振结论保持上游已发布含义，整体分数可能包含上游Quant贡献；本模块隐藏其Quant维度明细，不重算共振。
共振与Trend/行业/ETF共享的事实不可被当成多份独立支持。不同来源分数量纲不相加。

只使用目标日期正式结果，Preview和盘中确认不参与。行业仍要求当前最新日期、snapshot/member同一updated_at，
不使用当前成员解释旧日期。日期、来源状态、缺失情况、市场环境均冻结保存。

## 两阶段选择

新版本为`signal-center-v2-evidence`。

1. 整个去重候选池按证券代码稳定排序，轮流分入固定5桶。各桶最多相差1人，冻结完整分桶。
2. 每个非空桶顺序调用LLM，推荐0–3个进入最终轮，无来源直通；合计0–15个。
3. 最终只从入围集合选择0–3个。全部桶为空选时，直接保存NO_TRADE，不再调用最终LLM。
4. 有推荐时为BUY，`recommendations`保存1–3个不同代码；无推荐时为NO_TRADE，数组必须为空。

所有调用复用`LLMClient.complete_text`，启用`web_search=True, prefer_search=True, api_first=True`。
信号中心（含旧版未完成任务）使用API→Codex，与其他模块默认的Codex→API相反；沿用重试、审计与锁。
允许搜索公告、事件与风险，但不得引入候选外证券，不得使用信号日期之后的信息。
搜索为可选增强：backend未返回搜索证据时可依据快照作判断，但不得保留声称来自搜索的外部来源。
沿用`prefer_search`语义：API成功但未确认搜索时也尝试Codex；两者均未确认搜索时返回首个通过校验的结果。
初筛和最终调用分别保存transport search evidence；网页为数据，不是指令。

## 决策标准与证据

决策依次检查：输入充分性→趋势/价格位置/过热/市场冲突→独立证据→优势与反对证据→BUY或NO_TRADE。
不得为了补齐3个名额而降低要求，不提供仓位建议。`confidence`是模型判断强弱，不是校准胜率。

每个BUY包含：symbol/confidence/thesis/positive_signals/risks/invalidations/evidence/external_sources。

- `evidence_catalog`从冻结快照生成字段路径、原始值、所属证券、来源日期；允许市场背景引用。
- 每个BUY至少引用两个不同字段，至少一条为本证券事实；程序核对字段存在、值及JSON类型完全一致、日期一致，拒绝跨证券引用。
- 每条正向依据、风险、失效条件通过`supports`明确关联到有效事实引用，拒绝不存在的数组项或未被引用的主张。NO_TRADE有候选时至少一条结论证据；全桶0入围时以已保存的初筛结果作为可追溯依据。
- `interpretation`解释事实为何支持结论；解释仍是模型推断，校验事实并不意味着已验证推断正确。
- 外部来源保存URL、标题、发布日期（未知为null）、摘录；仅允许HTTP(S)，拒绝未来发布日期。
- 最终声明外部来源时必须存在transport确认的搜索事件/引用。搜索执行已确认不表示逐篇核验了模型所写的URL、摘录或结论；前端明确标注。
- NO_TRADE必须给出`NO_CLEAR_EDGE/OVERHEATED/SIGNAL_CONFLICT/INSUFFICIENT_EVIDENCE`之一及中文解释。
- JSON严格校验，不修复畸形输出，不允许未知字段、重复证券或超额推荐。

## 就绪与调度

CN上海20:40–21:50每10分钟检查；US纽约23:40至次日00:30每10分钟检查，等待23:30启动的共振。
午夜检查使用前一日期，周五会延续至周六；日期仍需通过真实交易日/已收盘检查。
截止前等待所有适用来源。截止后允许非关键来源缺失，但必须有候选、当日市场环境和已完成正式共振批次。
正式共振有manifest但0只股票是有效空批次，可使用其他来源继续选股；无manifest、旧日期或任务仍运行不视为完成。
截止时输入不足保存skipped；LLM/校验失败保存failed，两者不冒充NO_TRADE。

## 持久化、重试与通知

`signal_center_run`继续以`market + signal_date`为主键，每天每市场最多一个正式结果。
迁移`0080_signal_center_v2`增加recommendations/search_evidence/notification_id，不回填或改变旧结论。
旧selected_symbol/confidence保留首个推荐的兼容字段，不代表市场整体收益。

首次LLM之前提交输入；成功初筛桶逐桶提交。重试使用冻结输入及已完成桶，不重读当前来源。
completed/skipped不覆盖。未完成的旧版本任务复用`legacy.py`及原冻结分桶/Prompt，不套用新规则。

成功BUY和NO_TRADE均在完成事务内写一条全局`notification`，保存结论、逐只证据、风险、失效条件及外部来源，
然后经现有report路由、Noise Control及Telegram/ntfy执行`push_existing`。重复运行不新增站内消息或重复推送。
外部发送失败不回滚结论，也不把业务结果改成failed；不保存delivery状态。
事务提交后进程退出可能导致未推送，本版不提供跨系统exactly-once或持久化投递队列。

## API与前端

认证GET：`/api/v1/signal-center/daily?signal_date=...`、`/history?limit=50&offset=0`、`/{CN|US}/{date}`。
GET只读已存分析；历史名称来自当时快照。兼容旧版单推荐，统一投影recommendations供页面展示。
`/research/signal-center`分别显示CN/US、逐只股票/ETF、依据/风险/失效条件、可展开的机检事实与搜索来源、输入审计和历史。
无记录、failed、skipped、NO_TRADE分别显示。今天按各市场当地日期读取，不把昨日信号冒充今日结果。

## 逐只价格评价

每个BUY独立计算evaluation；兼容顶层evaluation仍仅对应首只。一次响应合并全部(symbol,date)批量读取DB日线。
不调用远程行情或LLM，不修改历史分析，不新增评价任务/表。

- 基准为信号日期之后且开盘严格晚于completed_at的首个交易日开盘；延期重试不能使用已错过的开盘。
- 复用真实CN/US交易日历，包含节假日、夏令时和提前收盘，日历不可用不猜测。
- 1/3/5/10D为基准交易日起第N个交易日收盘/基准开盘−1；1D是买入日开收盘表现。
- 前10交易日MFE/MAE及收盘最大回撤，沿用现有精确窗口和完整性校验。
- 仅用已收盘前复权OHLC，缺日/零量/非法价格不填零、不顺延。未到期与缺行情分开。
- 当前入库行情补齐、修订、复权会改变评价，冻结的选股与证据始终不变。

价格评价不代表真实成交或账户收益，未计费用、滑点、涨跌停等限制；A股1D不代表可当日卖出。

页面市场范围由顶栏头像左侧的全局 A 股／美股开关控制。`GET /signal-center/daily` 与 `/history` 支持可选 `market=CN|US`；省略时兼容返回双市场，指定时仅查询/评估该市场，历史在数据库过滤后分页。前端切市场清空日期、分页与旧详情，单市场最多展示 3 个推荐。
