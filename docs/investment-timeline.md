# Investment Timeline / 投资时间线

Investment Timeline 展示影响投资判断的财经事件、逐条新闻分析、长期报告与用户笔记。盘中异动只发送 Notification，任务执行统计由 TaskRecord 保存。

## 数据职责与表变化

| 表 | 职责 | 本次变化 |
| --- | --- | --- |
| `calendar` | 旧任务结果集合 | 删除表及全部历史数据，不转换旧记录 |
| `timeline_entries` | 长期投资报告、用户笔记 | 新增 |
| `news_analysis` | 每条新闻的结构化模型判断 | 新增 |
| `news_intel_usage` | 新闻与查询、用途、股票的关联 | 新增，承接现有查询和复盘读取依赖 |
| `news_intel` | 原始新闻事实 | 删除任务/查询/股票上下文字段 |
| `finance_events` | 外部确定性财经事件 | 保持独立，查询时聚合，不复制 |
| `task`（ORM `TaskRecord`） | 任务状态、耗时、错误、结果 | 保持原物理表名；补齐每日分析、盘前分析、盘前新闻的结果返回 |

当前 main 的任务记录物理表叫 `task`，不是 `task_records`。本次沿用已有 TaskRecord 生命周期，没有额外建立另一张任务表。

删除 `CalendarEntry`、`CalendarRepo`、Calendar 分类常量、分类条件、旧 API/schema、CalendarPage、旧 Calendar 前端 API 和分类 Card 组件。没有兼容路由或双写层。

## timeline_entries 最终 schema

| 字段 | PostgreSQL 类型 | 约束/语义 |
| --- | --- | --- |
| `id` | INTEGER | 自增主键 |
| `uid` | INTEGER | 必填；报告与笔记所有者，保留用户隔离 |
| `entry_type` | VARCHAR(32) | 必填；`a_share_pre_close` / `us_premarket` / `us_postmarket` / `manual_note` |
| `market` | VARCHAR(16) | 可空；CN / US，笔记可不限市场 |
| `event_time` | TIMESTAMPTZ | 必填；报告完成时间或笔记时间 |
| `title` | VARCHAR(300) | 必填 |
| `summary` | VARCHAR(500) | 必填；简短业务摘要，不截取完整 Markdown |
| `content` | TEXT | 必填；完整报告/笔记 |
| `importance` | VARCHAR(16) | 必填；low / normal / high / critical |
| `actionability` | VARCHAR(24) | 必填；none / watch / consider / action_required |
| `symbol` | VARCHAR(32) | 可空 |
| `related_symbols` | JSONB | 必填；字符串数组，默认 `[]` |
| `source_task` | VARCHAR(128) | 可空；业务报告的生成任务 |
| `source_run_id` | VARCHAR(64) | 可空；TaskRecord 生命周期的 `task_id` |
| `created_at` / `updated_at` | TIMESTAMPTZ | 必填 |

数据库 CHECK 约束限制 entry_type、importance 和 actionability。uid、entry_type、market、event_time、importance、actionability、source_run_id 有索引。

笔记的创建、更新、删除只操作当前用户的 `manual_note`。笔记接口不能修改报告。每次成功生成报告保存一条；不以旧任务 type 或交易日覆盖报告。

## news_analysis 最终 schema

| 字段 | PostgreSQL 类型 | 约束/语义 |
| --- | --- | --- |
| `id` | INTEGER | 自增主键 |
| `news_intel_id` | INTEGER | 必填；外键，原新闻删除时级联删除 |
| `analysis_type` | VARCHAR(32) | 必填；当前 `premarket` |
| `importance_score` | INTEGER | 必填，0–10 |
| `importance_reason` | TEXT | 重要性依据 |
| `event_type` | VARCHAR(64) | 事件类型 |
| `time_sensitivity` | VARCHAR(32) | 时效性 |
| `importance_confidence` | DOUBLE PRECISION | 第一阶段置信度 |
| `impact` | VARCHAR(32) | bullish / bearish / neutral / mixed / unclear |
| `impact_score` | INTEGER | 第二阶段归一化到 -5–5 |
| `impact_reason` | TEXT | 影响依据 |
| `impact_confidence` | DOUBLE PRECISION | 第二阶段置信度 |
| `related_symbols` | JSONB | 必填；合并两阶段相关标的，默认 `[]` |
| `watch_points` / `risk_notes` | JSONB | 必填；字符串数组，默认 `[]` |
| `importance` | VARCHAR(16) | 必填，统一重要度 |
| `actionability` | VARCHAR(24) | 必填，统一行动等级 |
| `model` | VARCHAR(128) | 实际 LLM 响应的 model_used；第二阶段有响应时使用其模型 |
| `prompt_version` | VARCHAR(64) | 必填；当前 `premarket-v1`，对应现有两阶段 prompt |
| `analyzed_at` / `created_at` / `updated_at` | TIMESTAMPTZ | 必填 |

唯一约束为 `(news_intel_id, analysis_type)`；PostgreSQL `ON CONFLICT DO UPDATE` 保证重复执行更新而不重复插入。未知/模型虚构的新闻 URL 不会创建分析行。原始新闻标题、来源、URL 始终来自 NewsIntel。

重要度映射：9–10 → critical，7–8 → high，4–6 → normal，0–3 → low。高重要度新闻行动等级为 watch，其余 none；模型方向不直接转换成买卖指令。

## news_intel 与使用关联

NewsIntel 仅保留 `id / title / snippet / url / source / published_date / provider / fetched_at`。删除 `uid / query_id / code / name / dimension / query / query_source / requester_*` 及其索引。

新闻按 URL 全局唯一；无 URL 时按 title/source/published_date 生成稳定键，不再包含单一股票代码。重复抓取不覆盖原始新闻事实或发布时间，观察时间写入 usage。

`news_intel_usage` 字段：`id INTEGER`、`news_intel_id INTEGER FK`、`usage_type VARCHAR(32)`、`query_id VARCHAR(64)`、`symbol VARCHAR(32)`、`uid INTEGER nullable`、`observed_at TIMESTAMPTZ`。唯一约束为 `(news_intel_id, usage_type, query_id, symbol)`。

引入这个小关系表是因为当前业务确实按 query_id 读取历史新闻、按股票读取复盘上下文。现在同一个 URL 可以被多个查询、多个股票使用，不会覆盖第一条关联。历史查询与 A 股/美股复盘的读取同步改为使用关系表。存储 API 使用明确的 `usage_type`，不保留旧 dimension 参数。

原始抓取关联由 usage 保存；LLM 判断的相关标的由 news_analysis 保存。新闻任务不会创建 timeline_entries。

## TimelineService 与时间规范

数据库 `UNION ALL` 聚合 finance_events、news_analysis JOIN news_intel、timeline_entries 的公共投影。统一应用日期与 market/category/importance/actionability 条件，数据库完成排序、分页、计数。只批量读取当前页详情，最多三次来源详情查询。Summary 在数据库按展示时区的日期和业务 category/重要度聚合。

时间规则：

- 报告：`finished_at` → `event_time`。
- 新闻：`published_date`，缺失则 `news_analysis.analyzed_at`；有发布时间的旧新闻不会因重新观察而刷新到当天。
- 财经事件：`event_datetime`；仅有日期时，以市场当地午夜作为排序锚点（US: America/New_York；其他现有市场: Asia/Shanghai），详情保留原始 `event_date` 和 `all_day`。
- TIMESTAMPTZ 保存绝对时间，DTO 的 event_time 统一 UTC。前端按用户的 Asia/Shanghai 或 America/New_York 展示，列表与 Summary 使用同一日期边界。
- 全天事件显示“全天”，原始市场日期仍在 detail_payload；跨时区归属日按同一个 UTC 锚点计算。

默认查询 today − 7 天至 today（按展示时区，包含两端日期）。所有类型按 event_time DESC，再按 source_type ASC、source_id DESC 稳定分页；重要度仅用于展示和筛选。本次不增加 Upcoming UI，未来财经事件仍可通过单日或日期范围查询（最多 367 天）。

CPI/FOMC、非农和利率决议等核心宏观标题映射为 critical/watch；其他财经事件参考已有 importance_score/star，未评分事件为 normal/watch。不引入新的评分系统。

## API

- `GET /api/v1/timeline`：date 或 start_date/end_date，market，category，importance，actionability，cursor，limit，timezone。
- `GET /api/v1/timeline/summary`：相同筛选与日期条件，返回每日 total、critical、high、event_count、news_count、analysis_count、note_count。
- `POST /api/v1/timeline/notes`。
- `PUT /api/v1/timeline/notes/{id}`。
- `DELETE /api/v1/timeline/notes/{id}`。

统一 item 字段：id、source_type、source_id、event_time、category、market、title、summary、symbol、related_symbols、importance、actionability、importance_score、impact、impact_score、event_type、detail_type、detail_payload。前端只渲染业务 category 与 detail_type。

所有旧 `/api/v1/calendar` 路由及 events/summary 子接口删除。新笔记必须提供带时区的时间，验证错误返回 422。

## 任务写入矩阵

| 任务 | 长期业务写入 | 执行信息/通知 |
| --- | --- | --- |
| `analysis_a_share_pre_close_review` | timeline_entries：a_share_pre_close，CN，high/consider | TaskRecord + 原聚合通知 |
| `analysis_us_premarket` | timeline_entries：us_premarket，US，high/consider | TaskRecord + 原分析流程通知 |
| `analysis_us_postmarket_review` | timeline_entries：us_postmarket，US，high/watch | TaskRecord + 原报告通知 |
| A股盘中 | 不保存盘中业务结果 | TaskRecord + Notification + 原有 state/dedup |
| 美股盘中 | 不保存盘中业务结果，新闻上下文也只抓取 | TaskRecord + Notification + 原有 state/dedup |
| 财经同步/重要度任务 | finance_events | TaskRecord；原财经事件通知保留，同步摘要不进入 Timeline |
| `analysis_us_premarket_news` | news_intel + usage + news_analysis | TaskRecord 统计 + Top 新闻通知 |
| `analysis_daily` | 不新增 Timeline 报告；原个股分析历史/新闻保存流程不变 | 执行摘要只进 TaskRecord |

三个报告任务记录生命周期 run ID。盘中不新增 signal 表或其他数据库实体；未改变规则、LLM 判断阈值、状态去重或通知条件。Celery 的 scheduled_* task_type 仍属于 TaskRecord，不是 Timeline 业务类型。

## 前端 Feed

`/timeline` 为类似 X 的单列 Feed：连续条目、细分隔线、日期分组、紧凑的类型/市场/时间/标题/短摘要/重要度/行动等级/标的/影响方向。顶部市场与类型、重要度、行动筛选独立组合。分页通过“加载更多”，传递后端返回的 opaque cursor。没有日历网格和按表拆分的分类 Card。

每条 Top 新闻独立呈现；详情显示原文链接、来源、发布时间、两阶段分析理由、评分、置信度、观察点与风险。报告完整 Markdown 只在详情中展示，使用既有 DOMPurify 渲染工具。笔记支持创建、编辑和删除。

以下是 Playwright 使用明确测试数据生成的布局截图，不代表真实财经信息：

![Desktop feed](images/investment-timeline-desktop.png)

[360px 移动端截图](images/investment-timeline-mobile.png)

## 迁移与验证

新 migration：`0043_investment_timeline`，父 revision：`0042_merge_reference_heads`。未修改历史 migration。

新建三表 → 将旧新闻的已有单一上下文保存为 usage → 删除 news_intel 旧上下文字段 → DROP calendar。旧 Calendar 包括手工记录全部丢弃，不做数据转换。破坏性迁移不提供伪恢复 downgrade；回滚须恢复迁移前备份。

迁移已在本机运行数据库的独立 schema 副本验证：从 `0038_remove_legacy_minute` 直接 `alembic upgrade head` 成功。原运行数据库未更改。另有隔离 PostgreSQL schema 测试验证真实旧新闻关联迁移、Calendar 删除、表创建幂等和最终 ORM/schema 一致。

验证命令使用独立 PostgreSQL 测试库、`TZ=UTC`，并移除 LLM_MODEL/LLM_API_KEY/LLM_BASE_URL 的环境注入：

```bash
uv run bash scripts/ci_gate.sh
cd web
pnpm run build
pnpm run lint
pnpm run test
pnpm exec playwright test --grep 'investment feed|timeline note|shell remains|root keeps|header dropdown|mobile shell'
```

关键覆盖：笔记 CRUD 与用户隔离；三类报告写入；盘中无持久化；新闻实际任务写入、去重和多股票关联；三源聚合、筛选、分页、新闻时间排序、Summary；UTC 与美东/北京跨日及全天事件；API 校验和旧路由移除；桌面/移动端 Feed、详情、筛选与笔记操作。

发现的既有架构问题：TaskRecord 实际表名为 task；部分服务原本返回 None 导致 record_result 无内容（已修复）；news_intel 混入单一业务上下文（已拆分）；美股盘中新闻抓取隐含数据库写入（已改只读）；历史 baseline 动态读取当前 ORM 的新库 bootstrap 问题仍属于既有迁移链，未修改历史迁移。数据库连接原先在隐式事务内 SET UTC，池回滚会恢复服务器时区（已改为 autocommit 初始化，并验证回滚后仍为 UTC）。LLM 统计测试还使用无时区本地时间，验证时统一以 UTC 运行。

最终验证结果：后端 CI gate（语法、critical flake8、路径测试及离线 pytest）通过；离线 pytest 为 **1936 passed、16 skipped、2 deselected、104 subtests passed**。前端 build/typecheck 通过；ESLint **0 errors**（保留现有风格及安全提示 warnings）；Vitest **387 passed**；本轮 Timeline Playwright **2 passed**。运行时代码全局检索无旧 Calendar ORM/Repo/persistence/API 残留；历史迁移测试中的旧表 fixture 和 TaskRecord 的 scheduled_* 标识按职责保留。

新闻时间约定：`fetched_at` 是 URL 首次入库时间；`observed_at` 是 usage 唯一键最近观察时间。最近新闻和历史上下文排序优先使用发布时间，缺失时使用相关 symbol/query/usage_type 的最近观察时间。已发布的过期新闻不会因重复观察重新进入新鲜度窗口。

此前已修正新闻时间、Feed 默认范围/时间排序，并 rebase 至 main `a20ce9b`。保留报告 create/幂等行为以及两处复盘 JOIN 的重复结果；未修改策略、通知或 LLM prompts。新增回归覆盖 first seen/观察时间、旧新闻不复活、相关 usage 隔离、分析时间 fallback、默认日期范围及跨页顺序。

Timeline Feed 使用无状态 keyset 分页，不再使用 OFFSET。响应为 `items / total / limit / next_cursor / has_more`；total 保留原范围 COUNT，仅用于展示。Cursor 为 `event_time / source_type / source_id` 的 JSON → base64url token，校验格式、带时区时间、来源和正整数 ID；非法 token 返回 422。

排序保持 `event_time DESC, source_type ASC, source_id DESC`。后续查询使用严格 seek：时间更早，或同时间且来源更大，或同时间同来源且 ID 更小。取 limit + 1 判断 has_more，有下一批时从本批最后一条生成 cursor，否则返回 null。顶部插入不会推动已加载位置，同时间戳由完整排序键区分。前端在全部筛选或展示时区变化时清空 items/cursor，保留 loading/requestId 防重复和过期响应保护。Summary、Note CRUD 和其他 review 问题不变。

Cursor 回归测试覆盖：普通连续读取、顶部插入后继续、删除已读边界记录后继续、同时间戳跨来源/ID、微秒精度、非法 token 422、末批与空批、前端追加与所有筛选重置、双击/过期响应保护。PostgreSQL 执行语句验证无 OFFSET；本轮仅改分页，不改变报告幂等、复盘 JOIN、发布时间补全、当天未来事件或业务数据库结构。
