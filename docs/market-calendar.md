# 财经日历后端：双 Provider 合并

对应 PR #277 / `0045_calendar_sources`。继续使用 `FinanceEvent / finance_events / MarketCalendarSync`；不新增表或 instrument_id FK，不修改前端、Trend Following、ETF Rotation、Quant Event。

## Destructive migration：删除全部旧事件

**0045 upgrade 首先执行 `DELETE FROM finance_events`，删除全部旧 earnings、macro、IPO、dividend、split，包括旧 event_key、raw payload、importance、通知状态、first_seen/last_seen 等业务数据。**

部署前如果希望保留旧财经日历历史，**必须备份数据库**。本项目预期行为是部署后从任务中心手动触发“财经日历同步”（或等待原定时任务），重新构建今天至今天 + 30 天的 earnings/macro。首次新建事件不发即时通知。

随后 migration 重命名 financial_market_time 为 market_session，增加 reporting_period 和三个 EPS 字段，删除 activity_type/date_type/star/data_kv_json 及 star 索引，添加类型与市场 CHECK。没有旧数据读取/转换/合并、日期匹配、Universe 查询或 legacy restore。迁移接在 main 的 `0044_crypto_btc` 后，保持单一 head。

删除不可逆；downgrade 显式抛出 RuntimeError，不能恢复历史。此次仅在隔离测试库执行迁移，没有对生产数据库执行写入。

## 最终数据流与 Provider 分工

```text
US earnings: UniverseResolver(us_sp500)
              → Yahoo Calendars primary + Longbridge Report(US) secondary
              → normalize → merge → FinanceEvent

CN earnings: UniverseResolver(cn_csi300)
              → Longbridge Report(SH) + Report(SZ)
              → normalize logical market=CN → Universe filter → FinanceEvent
              Yahoo CN: unsupported best-effort，空结果，不请求 Ticker

US macro: Yahoo Economic Events primary + Longbridge MacroData(US) secondary
              → 明确 US 过滤 → normalize → merge → FinanceEvent

FinanceEvent → Timeline UNION / LLM importance
            → 仅已有事件时间变化通知
```

US earnings 与 US macro 每次执行都请求两源，不是 fallback-only。CN 不假设 Yahoo 公共批量 earnings calendar 能可靠提供沪深300覆盖，因此 adapter 明确返回 unsupported_reason、空 events、零网络请求，不发起 300 个 Ticker 查询，也不引入新国内 Provider。

Longbridge 明确区分 provider market `SH/SZ` 与 logical market `CN`，每个交易所独立分页、独立捕获失败；一边失败保留另一边结果。Provider 层支持带后缀和按请求交易所限定的裸代码，最后按动态 cn_csi300 成员过滤。全 CN 无数据不导致 Calendar Task 失败。

Universe 通过现有 `UniverseResolver → UniverseRepository → Universe/UniverseMember/Instrument` 读取，保留 include 解析；不硬编码成分。US ticker 转换复用 `YFinanceProvider.to_yfinance_symbol()`（例如 NVDA.US ↔ NVDA、BRK.B.US ↔ BRK-B）。所有业务层事件都是普通 Python dict，不泄漏 DataFrame 或 SDK 对象。

## Yahoo 分片与分页

US earnings 保留 `filter_most_active=False`、`limit=100`、offset 按实际行数递增，直到空页或不足一页。每个最多 7 天的分片使用不重叠的闭区间：Sep 1–7、Sep 8–14、Sep 15–21；不额外请求 end + 1。每个自然日仅属于一个 shard，最终严格筛选 start <= 市场 event_date <= end。

yfinance 1.5.2 的查询使用 GTE/LTE，但默认日期解析会把 datetime 截到零点。Provider 内局部 Calendars 子类仅覆盖日期解析，保留 00:00:00 至结束日 23:59:59.999999 的边界；仍调用官方两个 Calendar getter 和分页。离线测试直接拦截已安装 SDK 的查询，检查两类事件的 GTE/LTE，避免只测试 mock factory 而遗漏截断。2026-09-08 的单日真实只读验证返回 222 行、3 页、0 错误。该适配点随 yfinance 升级需由 contract test 继续验证。

后页异常保留前页，继续后续 shard；重复页检测防止死循环。同一次同步仍有批次 cache，CN 路径不再消费 Yahoo 批次。

Yahoo earnings 使用 Symbol 索引以及 Event Name、Event Start Date、Timing、EPS Estimate、Reported EPS、Surprise(%)；仅从明确 Qn YYYY 提取 YYYY-Qn 周期，不猜财年。US macro 使用 Event 索引以及 Region、Event Time、For、Actual/Expected/Last/Revised；仅接受明确 US/USA/UNITED STATES，不凭 currency 或请求参数猜国家，For 只有月份时不猜年份。

官方参数参考：[yfinance Calendars](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Calendars.html)，实现同时核对本地 yfinance 1.5.2 源码。Yahoo 午夜占位作为 date-only，其余明确时间统一 UTC，并以市场时区判断事件日期。

## Longbridge 真实 sample 与 EPS enrichment

2026-09-08 使用本机生产配置的 Longbridge 凭据执行了 **两个只读 US Report 请求**：2026-09-05..08（6 条）及 2026-09-03..04（43 条）。没有操作生产数据库、发送通知或执行交易，也没有输出凭据。

实际样本 `data_kv.key` 均为空字符串；有意义且稳定的分类是 **value_type**，不能猜测英文/中文 display key：

| 实际 value_type | 实际 value_raw 示例（IOT.US） | 结构化映射 |
| --- | --- | --- |
| estimate_eps | 0.012430 | eps_estimate |
| actual_eps | 0.030000 | reported_eps |
| estimate_revenue | 483296990.000000 | 不增加收入字段，仅保存 raw/content |
| actual_revenue | 508437000.000000 | 不增加收入字段，仅保存 raw/content |

SDK CalendarDataKv 的 value_type 文档也明确给出了 estimate_eps 示例。显式 mapping 仅包含确认的 estimate_eps / actual_eps，从 value_raw 读取有限数值，保留 0 与负数；TBA、--、NULL、NaN/Infinity 不写结构化 EPS。没有观察到稳定 Surprise 类型，因此 Longbridge 不填 eps_surprise_pct，也不推导或伪造映射；该字段仍可来自 Yahoo。

脱敏后的公开行情样本见 `tests/fixtures/market_calendar/longbridge_report_sample.json`（IOT 与 CAN）。CAN 的 actual_eps 为 TBA/NULL，测试覆盖正常跳过。未知 KV 连同 key/value/value_raw/value_type 保留来源审计并可渲染 content。

## 合并与稳定身份

Yahoo 非空 canonical 字段优先，Longbridge 补齐缺失事件与字段（包括上述已验证 EPS）。实际只有 Longbridge 的事件写 provider=longbridge。raw_payload_json 按 yfinance/longbridge 保存 normalized、受控 raw 和 observed_at，事实冲突写 conflicts；provider_event_id 只对应 canonical source，辅助来源 ID 保留在各自审计中。

同一来源更新保留已有非空信息；Yahoo 某次不可用时，历史 Yahoo canonical 字段继续优先，来源 observed_at 可判断新鲜度。Longbridge 日期不一致时，其精确时间不能拼接到 Yahoo 日期。不存在旧数据库行/key 的转换兼容要求。

Earnings 在相同类型、市场、canonical symbol 下按优先级匹配：明确相同报告周期；同 Provider ID（日期差 <=45 天）；否则使用 <=21 天邻近窗口，较早日期不早于同步日期前 7 天。明确不同报告周期绝不合并，多个同级候选记录歧义并跳过该项。

新事件分配 UUID event_key，随后日期/session 变化 UPDATE 原行并保持 id/event_key/首次发现/创建时间。PostgreSQL advisory transaction lock 保留，防止两个并发同步创建重复逻辑事件。

Macro 按中立名称类型、明确 US、日期/时间及可用报告期间匹配，支持 CPI、FOMC、非农、PCE、GDP 有限中英文别名，保留核心/非核心、同比/环比、初值/终值差异。明确同报告期间允许 7 天内改期；无期间要求同市场日期，明确时间相差超过 2 小时不合并。

非阻塞限制：没有周期/可靠来源 ID 且改期超出邻近范围时，无法保证关联；未知宏观跨语言名称可能需要后续样本扩充；CN 不保证覆盖率。本次不扩大匹配、提醒或 Provider 设计。

## Notification / Importance / Timeline

**created=True 仅持久化、进入 Timeline 并提交 importance scoring，不立即通知。** 只有已有事件的 event_date、event_datetime、market_session 实质变化才进入 Calendar Change Notification；EPS、Provider、content、公司名、币种或审计补充不触发。时间范围仍为今天至今天 + 30 天，文案明确写“时间调整”。不实现 T-3/T-1。

删除误导性的 is_important_for_notification，不再用 watchlist/importance 做通知资格判断；watchlist 只保留 focus_events 排序价值。时间变化提醒先写 notification，再由原有 Noise Control 控制外部推送；FinanceEvent 不保存发送状态或去重指纹。新系统重要性评分沿用中立 v2 Prompt、US/CN 市值币种与全市场宏观影响，不依赖 star，不按 Provider 加减分；没有历史 importance 迁移。

Timeline 保留 FinanceEvent + News UNION，不写 timeline_entries；现有 detail payload 保留 market_session、reporting_period、provider 和三个 EPS 字段。旧 Calendar API 不恢复，前端不变。

Provider、交易所、市场、页、单行及单次写入失败分别隔离。summary.source_stats 按 provider:type:market 给出 fetched/accepted/skipped/pages_succeeded/merged/inserted/updated/errors/universe_size，Yahoo CN 附 unsupported_reason。新事件不通知不影响 importance_candidate_ids。

## finance_events 最终 schema

不再做额外 schema 大改；保留 currency（明确币种）、provider_event_id（来源身份）、raw_payload_json（双源审计及 KV）。

| 字段 | 用途 |
| --- | --- |
| `id` | 数据库主键，Timeline source ID |
| `provider` | canonical source，Yahoo 优先，真实表达单源情况 |
| `provider_event_id` | canonical source 的外部 ID；辅助来源 ID 保存在审计中 |
| `event_key` | 创建后不变的唯一逻辑标识 |
| `calendar_type` | earnings 或 macro；数据库 CHECK 限制 |
| `market` | earnings US/CN，macro US；数据库 CHECK 限制 |
| `symbol` | canonical 证券代码；macro 为空，不增加 FK |
| `counter_name` | 公司名称，展示/评分 |
| `event_type` | 中立子类型；earnings_release 或标准化宏观类型 |
| `event_date` | 可变市场日期 |
| `event_datetime` | 可空的准确 UTC 时间 |
| `market_session` | 统一 bmo/amc/during_market/unknown |
| `reporting_period` | 新增；实际明确的报告周期，支持稳定匹配 |
| `eps_estimate` | 新增；Yahoo EPS Estimate 优先，Longbridge estimate_eps 补齐 |
| `reported_eps` | 新增；Yahoo Reported EPS 优先，Longbridge actual_eps 补齐 |
| `eps_surprise_pct` | 新增；Yahoo Calendar Surprise(%)，百分数而非小数比例 |
| `title` | Timeline/通知事件标题 |
| `content` | Provider-neutral 描述及可用宏观数值 |
| `currency` | 来源明确提供的货币信息；不猜 EPS 币种 |
| `raw_payload_json` | 双来源快照、原始明细、事实冲突；不保留旧行迁移审计 |
| `importance_score` | LLM 市场重要性 |
| `importance_reason` | 评分理由，Timeline 展示 |
| `importance_confidence` | 评分置信度 |
| `importance_model` | 模型审计 |
| `importance_prompt_version` | Prompt 版本，当前 v2 |
| `importance_input_hash` | 去重评分输入摘要 |
| `importance_scored_at` | 评分 UTC 时间 |
| `first_seen_at` | 首次发现时间，更新保留 |
| `last_seen_at` | 最近观察时间 |
| `created_at` | 原行创建时间 |
| `updated_at` | 原行最近更新时间 |


新增字段仍为 reporting_period、eps_estimate、reported_eps、eps_surprise_pct；重命名 financial_market_time → market_session（bmo/amc/during_market/unknown）。删除 activity_type/date_type/star/data_kv_json；旧值随整表数据一同删除。Provider 当前请求中的 date_type 仍可作为时段输入，但不存在旧数据库列的兼容代码。

| 删除字段 | 原用途 | 原调用方 | 原因及替代 |
| --- | --- | --- | --- |
| `activity_type` | Longbridge 活动类型码 | Longbridge normalizer、Repository values/key/fingerprint、Domain 评分候选、Importance payload/hash、对应 tests | 与日历分类/中立子类型重复；由 calendar_type/event_type 替代；旧值随整表数据删除 |
| `date_type` | SDK 日期/时段标签 | Longbridge normalizer、Repository、ORM | 没有独立稳定领域语义；其中盘前/盘后价值归入 market_session，SDK 输入仍由 Provider 适配 |
| `star` | Longbridge 0–3 星评级 | Longbridge 文案/normalizer、Repository 排序/fingerprint、Domain 排序/通知、Importance payload/hash、Timeline importance SQL、tests | 不应成为中立重要性的隐性偏置；由现有 LLM importance_score/理由/置信度替代，Timeline 不再以 star 提权 |
| `data_kv_json` | Longbridge key/value 的重复存储 | Longbridge normalizer、Repository、Domain 评分候选、Importance payload/hash、fixtures | 与 raw payload 重复且 SDK 结构泄漏；EPS 用稳定字段，宏观数值用 content，详细 KV 留每来源 raw 审计 |

不新增收入字段。yfinance 1.5.2 自身可能把 EPS 0 转为 NaN；Longbridge 有实际有限数值时可补齐，其他情况不伪造。

## 修改文件

- `src/finance_analysis/market_calendar/__init__.py`、`events.py`：中立事件规则。
- `src/finance_analysis/integrations/market_data/calendar.py`：结果契约。
- `src/finance_analysis/integrations/market_data/providers/yfinance_calendar.py`：Yahoo Calendar adapter；复用既有 yfinance.py ticker 转换，不改其 Corporate Action 能力。
- `src/finance_analysis/integrations/market_data/providers/longbridge/calendar.py`：精简分类、标准化及翻页。
- `src/finance_analysis/integrations/market_data/service.py`：双来源获取入口。
- `src/finance_analysis/database/models/market_calendar.py`、`database/repositories/market_calendar_event.py`：schema、稳定匹配、事务合并。
- `src/finance_analysis/tasks/celery/jobs/market_calendar_sync/domain_service.py`、`importance.py`、`service.py`：编排、通知、评分及任务结果。
- `src/finance_analysis/tasks/celery/schedule/definitions.py`：名称和描述；不改 cron。
- `src/finance_analysis/timeline/service.py`：去 star，补中立详情字段。
- `alembic/versions/0045_calendar_sources.py`：迁移。
- `tests/test_market_calendar_event_repo.py`、`test_market_calendar_task.py`、`test_market_calendar_importance.py`、`test_longbridge_calendar_fetcher.py`、`test_yfinance_calendar_fetcher.py`、`test_market_calendar_migration.py`、`test_celery_job_services.py`：更新/新增回归测试。
- `tests/crypto/test_migration.py`：将写死的当前 head 检查改为单一 head 与 BTC revision 祖先检查，允许新增迁移；不改变 BTC 业务。
- `docs/market-calendar.md`：本说明。

IPO/dividend/split 只从财经日历类别映射、fetch 方法、通知/排序规则、评分文案及旧测试中移除。行情复权、Corporate Action 和其他独立业务的 dividend/split 保留。工作区原有 Trend Following/前端改动未纳入本次实现。

## 本轮 review 文件与验证

原 PR 涉及中立 events、两 Provider、MarketDataService 入口、FinanceEvent ORM/Repository、同步 Domain/Notification/Importance、Timeline、调度文案与相关测试。本轮 review 修复仅涉及：

- alembic/versions/0045_calendar_sources.py
- integrations/market_data/calendar.py
- providers/yfinance_calendar.py、providers/longbridge/calendar.py
- tasks/celery/jobs/market_calendar_sync/domain_service.py
- tests/test_market_calendar_migration.py、test_yfinance_calendar_fetcher.py、test_longbridge_calendar_fetcher.py、test_market_calendar_task.py
- tests/fixtures/market_calendar/longbridge_report_sample.json
- docs/market-calendar.md

测试明确验证所有旧类型/重复事件/评分/通知状态在 migration 后清空且 schema 正确；SH/SZ 独立请求、logical CN、Universe 过滤及单边失败；Yahoo CN 无请求；offset 0/100/200、异常页、重复页、无交叠日期；created 不通知及各类时间/非时间变化；真实 KV EPS 补齐。

2026-09-08，在独立 PostgreSQL 16 测试容器执行完整 `uv run ./scripts/ci_gate.sh`：**2012 passed、17 skipped、2 deselected、104 subtests passed**；83 条 warning 为既有依赖/弃用提示。syntax、flake8、deterministic（13 passed）均通过。显式设置 `ENV_FILE=/dev/null`，清除 LLM 环境变量，DATABASE_URL 与 CALENDAR_TEST_DATABASE_URL 均指向隔离测试库。

PostgreSQL 真实迁移和 advisory lock 并发去重测试实际执行通过，未跳过；另有 SQLite 迁移覆盖。`alembic heads` 为唯一 `0045_calendar_sources`，`git diff --check` 通过。生产数据库未迁移，没有发送真实通知或执行交易。

通知持久化与本次迁移边界见 [消息中心](notifications.md)。
