# 财经日历后端：双 Provider 合并

本说明对应 `0045_calendar_sources`。继续使用 `FinanceEvent / finance_events / MarketCalendarSync`，不增加表、`instrument_id` FK 或 Earnings Radar；不接入 Quant Event、Trend Following、ETF Rotation、fundamental_snapshot。

## 数据流与调度

```text
UniverseResolver → us_sp500 / cn_csi300 → canonical symbols
                                      ↓
MarketDataService.get_calendar_sources()
  ├─ YFinanceCalendarFetcher：US/CN earnings + US economic events
  └─ LongbridgeCalendarFetcher：US/CN Report + US MacroData
                                      ↓
标准化普通 Python dict + CalendarFetchResult（不泄漏 DataFrame/SDK 对象）
                                      ↓
同批次合并 → Repository 匹配既有事件并合并历史来源 → finance_events
                                      ↓
Timeline UNION 查询 / 新发现及时间变化通知 / LLM 重要性评分
```

只同步 `earnings`、`macro`。每次执行两个 Provider 都请求 US earnings、CN earnings、US macro；不是失败后才请求 Longbridge。一个 Celery 任务完成全部范围，任务名称为“财经日历同步”，保留每天 **07:00 America/New_York** 的原调度、队列和任务 ID。

Universe 使用现有 `UniverseResolver.resolve_universe()`，经过 `UniverseRepository` 读取 `Universe / UniverseMember / Instrument`，支持现有 include 解析。US 固定读取 `us_sp500`，CN 固定读取 `cn_csi300`；没有硬编码股票名单。Universe 缺失时记录错误、该市场 earnings 以空授权集合过滤，绝不扩大为全市场。

## Provider 获取与标准化

Yahoo 使用已安装的 yfinance 1.5.2 公共 `Calendars` API。每个日期分片至多 7 天，每页 `limit=100`，`offset` 按实际行数递增，直到空页或不足 100 行；重复页检测防止无限循环。外部查询终点覆盖同步终点的下一天，最终按事件市场日期再次过滤。每一页 earnings 都显式传 `filter_most_active=False`、`force=True`，没有 market-cap 过滤。US/CN 复用同一次全球 earnings 分页结果，之后分别应用 Universe 映射；不逐个请求 800 个 Ticker。

代码转换复用 `YFinanceProvider.to_yfinance_symbol()`，在 Provider 层从 Universe 构建精确反向映射：`NVDA.US ↔ NVDA`、`BRK.B.US ↔ BRK-B`、`600519.SH ↔ 600519.SS`、`000001.SZ ↔ 000001.SZ`。存储使用 canonical `market + symbol`。

实测 Yahoo earnings 列为 `Company / Event Name / Event Start Date / Timing / EPS Estimate / Reported EPS / Surprise(%)` 等，Symbol 是索引。只有 `Qn YYYY` 这类明确字段才提取 `YYYY-Qn` 报告周期；不把发布年份当财年。

实测 economic events 列为 `Region / Event Time / For / Actual / Expected / Last / Revised`，Event 是索引。只接受明确 `US / USA / UNITED STATES` 的 Region，其余跳过；`For` 仅有月份时不猜年份。宏观数值进入通用 content 与来源审计，不新增独立宏观指标表。

Longbridge 仅请求 `Report` 与 `MacroData`，实现 `next_date` cursor 翻页，检测不前进的 cursor。支持 SDK 的点号日期、Unix 秒/毫秒时间戳；`financial_market_time` 或 `date_type` 中的中英文交易时段由适配层变为 `bmo / amc / during_market / unknown`。旧 `date_type` 数据库列删除，不代表丢掉 SDK 中仍有用的盘前/盘后输入。宏观记录仍要求明确 US market，不能仅凭 USD 或请求参数推断未知国家。

日期使用所属市场时区；有明确时间的跨服务值使用 UTC。Yahoo 午夜占位值作为 date-only，不能伪造准确发布时刻。

官方 API 参数参考：[yfinance Calendars](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Calendars.html)。字段和行为同时核对本地 `yfinance/calendars.py` 及 `longbridge/openapi.pyi`。

## 合并、来源审计与稳定身份

1. Canonical 字段优先 Yahoo 非空值；包括 0 在内的有效数值不会被误当缺失。Longbridge 补缺字段及独有事件。
2. `provider` 是 canonical source；只有 Longbridge 的记录真实写 `longbridge`。`provider_event_id` 只对应 canonical source，不把 Longbridge ID 填成 Yahoo ID。
3. `raw_payload_json` 保存 `yfinance`、`longbridge` 各自的 `normalized`、受控 `raw` 及 `observed_at` 抓取时间；事实字段不一致写入 `conflicts` 并记录 debug 日志。不需要 `source_providers_json` 新列或 Provider mapping 表。
4. 更新也合并数据库已有来源。单次 Yahoo 故障不会清掉已保存 Yahoo 信息，历史 Yahoo 非空值仍优先；因此次源单独的改期不会覆盖已有 Yahoo 日期，必须等 Yahoo 恢复后确认。可从每来源 observed_at 判断上次成功观察时间；来源快照不是无上限历史日志。
5. 日期不同的 Longbridge 精确时间不能拼到 Yahoo 日期上。

Earnings 匹配范围为同 `calendar_type + market + canonical symbol`，匹配优先级：

- 双方明确报告周期相同：最高优先级；日期可跨较大范围修正。双方明确周期不同：不匹配。
- 同一 Provider source ID：在日期相差不超过 45 天时匹配，避免循环使用的非周期 ID 无限跨季度关联。
- 无充分周期信息：日期相差不超过 21 天，且较早日期不早于本次同步日期前 7 天。这个短宽限用于跨发布日的迟到记录/改期。
- 多个同优先级候选不猜测；仓储报告歧义，由任务记录单事件错误并继续其他事件。

新事件分配不含 Provider 或日期的 UUID `event_key`。后续匹配 UPDATE 原行，保留 `id / event_key / first_seen_at / created_at`。已有旧 Provider 风格 key 不重写，仅作为不透明既有标识使用；不保留旧 key 生成逻辑。查找与插入在同一事务，并用 PostgreSQL advisory transaction lock 串行化同一逻辑范围，真实并发测试验证两源仅插入一行。

无报告周期和可靠 source ID，且变动超过邻近边界时，不能保证识别同一周期；不会用日期推造永久报告周期。此限制避免把下一季度误覆盖到本季度。

Macro 使用规范化事件类型 + US + 发布日期；显式同报告期间支持 7 天内日期修正。CPI、非农、FOMC 利率决议、PCE 和 GDP 有中英文别名，保留 core、同比/环比、初值/修正/终值差异。没有期间时要求同市场日期；双方明确时间相差超过 2 小时则不合并，避免同日重复讲话被吞并。未知名称仅做标准化文本匹配，不用模糊相似度猜测。未收录的跨语言别名可能仍需后续按实际样本扩充。

## finance_events 最终字段

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
| `eps_estimate` | 新增；Yahoo Calendar EPS Estimate |
| `reported_eps` | 新增；Yahoo Calendar Reported EPS |
| `eps_surprise_pct` | 新增；Yahoo Calendar Surprise(%)，百分数而非小数比例 |
| `title` | Timeline/通知事件标题 |
| `content` | Provider-neutral 描述及可用宏观数值 |
| `currency` | 来源明确提供的货币信息；不猜 EPS 币种 |
| `raw_payload_json` | 双来源快照、原始明细、事实冲突和迁移审计 |
| `importance_score` | LLM 市场重要性 |
| `importance_reason` | 评分理由，Timeline 展示 |
| `importance_confidence` | 评分置信度 |
| `importance_model` | 模型审计 |
| `importance_prompt_version` | Prompt 版本，当前 v2 |
| `importance_input_hash` | 去重评分输入摘要 |
| `importance_scored_at` | 评分 UTC 时间 |
| `first_seen_at` | 首次发现时间，更新保留 |
| `last_seen_at` | 最近观察时间 |
| `notified_at` | 最近成功通知标记 |
| `notification_fingerprint` | 日期、准确时间、session 等有意义变化的摘要 |
| `created_at` | 原行创建时间 |
| `updated_at` | 原行最近更新时间 |

不新增 revenue 字段：当前 Calendar 返回不足以支撑稳定结构化收入字段。EPS 缺失正常保存 NULL；yfinance 1.5.2 自身会将这些列中的 0 转成 NaN，适配器无法恢复上游丢失的零值，不伪造补齐。

## 删除与重命名审计

| 删除字段 | 原用途 | 原调用方 | 原因及替代 |
| --- | --- | --- | --- |
| `activity_type` | Longbridge 活动类型码 | Longbridge normalizer、Repository values/key/fingerprint、Domain 评分候选、Importance payload/hash、对应 tests | 与日历分类/中立子类型重复；由 calendar_type/event_type 替代，旧值仅留迁移审计 |
| `date_type` | SDK 日期/时段标签 | Longbridge normalizer、Repository、ORM | 没有独立稳定领域语义；其中盘前/盘后价值归入 market_session，SDK 输入仍由 Provider 适配 |
| `star` | Longbridge 0–3 星评级 | Longbridge 文案/normalizer、Repository 排序/fingerprint、Domain 排序/通知、Importance payload/hash、Timeline importance SQL、tests | 不应成为中立重要性的隐性偏置；由现有 LLM importance_score/理由/置信度替代，Timeline 不再以 star 提权 |
| `data_kv_json` | Longbridge key/value 的重复存储 | Longbridge normalizer、Repository、Domain 评分候选、Importance payload/hash、fixtures | 与 raw payload 重复且 SDK 结构泄漏；EPS 用稳定字段，宏观数值用 content，详细 KV 留每来源 raw 审计 |

`financial_market_time → market_session` 是重命名，不是丢掉 BMO/AMC。旧字符串在迁移/适配层统一映射。未删除 `event_type`、`currency`、`provider_event_id`、`raw_payload_json`：它们仍服务去重、展示、合并或审计。

全局调用链核对发现：旧 `/api/v1/calendar` 已在前一轮 Timeline 改造中删除，不应恢复。当前 API 为 `/api/v1/timeline`，通过通用 detail_payload 增加 market_session、reporting_period、provider 和 EPS 字段；不修改前端，也不复制 FinanceEvent 到 timeline_entries。

## 通知、评分与容错

新发现和日期/准确时间/session 变化才进入通知候选；Provider、公司名、EPS、币种、raw 补齐不重复提醒。指纹不含这些噪音字段，同一合并事件只选一次。通知文案显示实际起止日期（今天至今天 + 30 天），不再硬写“未来14天”。通知去重/冷却 key 使用事件 ID 和变化指纹摘要；发送失败不标记，单次标记异常不回滚已存事件。不实现 T-3/T-1 Reminder。

LLM 评分保留全部 importance_*，Prompt 升到 v2，移除 star/旧 KV，支持 US/CN 公司影响力和美国宏观全市场影响，不按 Provider 加减分。市值区分 US USD / CN CNY，不再把 A 股市值写成美元。价格/市值仍经统一 MarketDataService 获取。

Provider、市场、单行、单页及单次入库失败分别隔离。后页失败保留前页，Yahoo 继续后续分片；CN 没数据正常跳过。所有 US 核心接口无可用页且没有其他市场可用事件，才判定全源不可用；CN 有数据也能独立成功。所有待存事件写入失败时明确失败，防止伪报同步成功。

summary.source_stats 以 `provider:type:market` 为键，包含 fetched、accepted、skipped、pages_succeeded、merged、inserted、updated、errors、universe_size。Yahoo 的 fetched 是共享全球批次行数，accepted 才是对应 Universe 数量；两来源的 inserted/updated 是参与贡献计数，不能相加当作独立事件数。独立逻辑事件数见顶层 merged_count/inserted_count/updated_count。

## 迁移与兼容影响

`0045_calendar_sources` 接在最新 main 的 `0044_crypto_btc` 后：删除不支持类型和市场的历史日历行；保留 earnings/macro 历史；规范 US canonical symbol；迁移 session；新增报告期间和三个 EPS 字段；删除四旧列及 star 索引；增加类型/市场 CHECK。既有重复事件合并时保留较早行 ID/event_key、采用最新观察信息。旧元数据在 raw_payload_json 的 legacy_metadata 审计中保留，不参与运行时兼容逻辑。

旧星级参与过的评分清空，由后续同步提交 v2 重评。已有通知标记重新计算中立指纹，减少迁移后重复通知。历史数据不强制按今天 Universe 成员删除，以免抹掉正常成分变动前的历史事件；新同步严格按动态成员过滤。

这是含数据删除/合并的不可逆迁移，downgrade 显式拒绝恢复伪造数据。回滚需迁移前备份。此次仅在隔离测试 PostgreSQL 上执行验证，没有迁移业务库。空库仍沿用仓库 metadata bootstrap + stamp head。

## 实测覆盖及已知限制

2026-09-08 执行只读查询，窗口 2026-09-08 至 2026-09-15：

- Yahoo earnings 完成 5 页，原始 401 行，分页错误 0；其中 `.SS/.SZ` 行数为 0。
- Yahoo macro 完成 5 页，原始 460 行，筛选后 US 60 条，分页错误 0。
- 本环境未配置 DATABASE_URL 与 Longbridge 凭据，无法读取真实两指数成员或验证 Longbridge 实时覆盖；不能把上述结果宣称为指数覆盖率。US/CN Universe 映射和真实仓储行为由离线/隔离数据库测试验证。
- A 股只做 best-effort；没有数据不视为任务失败，也未引入国内新 Provider。

修复的遗留问题包括：Provider/date 参与旧身份导致重复；Longbridge 漏翻页；SDK 点号日期与 Unix 时间戳解析遗漏；date_type 中的时段信息未统一；star 干预评分/Timeline；通知窗口与文案不一致；使用事件数量做通知去重 key 易碰撞；评分默认所有市值都按美元理解；根指南仍描述已删除的 Calendar API。

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

## 最终验证结果

2026-09-08，在显式指定的独立 PostgreSQL 16 测试容器上运行；`ENV_FILE=/dev/null`，清除 LLM 三项环境变量，并将 DATABASE_URL / CALENDAR_TEST_DATABASE_URL 指向该测试库。

- `uv run ./scripts/ci_gate.sh` 完整通过：syntax、flake8、deterministic（13 passed）、offline-tests。
- 完整后端测试：**1988 passed，17 skipped，2 deselected，104 subtests passed**。83 条 warning 为既有依赖/弃用提示。
- 最终聚焦回归：**127 passed**，覆盖 Calendar provider/repository/task/importance/migration、Timeline、Celery service/schedule。
- PostgreSQL 真实迁移与双线程并发 source 去重均通过；SQLite 验证作为额外离线覆盖。
- `git diff --check` 及本次修改文件的未使用/未定义名称检查通过。
- 测试容器已停止并自动删除；业务数据库未执行迁移，没有发送真实通知。
