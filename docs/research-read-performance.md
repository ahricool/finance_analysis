# Trend Following / ETF Rotation 读取性能

2026-09-11，基于 `9314fd3` 对比本次读取优化。策略公式、状态机、信号生成和数据库 schema 均未修改。

## 请求链路

下面的 SQL 数量不含公共鉴权、连接池 pre-ping；假定当前和上一交易日都有数据。Preview 读取 Redis。

| 操作 | 修改前 | 修改后 |
| --- | --- | --- |
| Trend 首次进入 / 切换市场 | latest ranking + dates + preview；再 candidates + portfolio | latest ranking + dates + preview；ranking 已含轻量 candidates 和 portfolio |
| Trend 选择历史日期 D | latest ranking + preview；再 ranking(D) + candidates(D) + portfolio(D) | 仅 ranking(D) |
| ETF 首次进入 / 切换市场 | latest ranking + dates + preview；再 candidates | latest ranking + dates + preview；前端从 ranking.items 派生 candidates / exits |
| ETF 选择历史日期 D | latest ranking + preview；再 ranking(D) + candidates(D) | 仅 ranking(D) |
| 两页刷新 | latest ranking + dates + preview；历史模式再 ranking(D)，以及候选/组合接口 | ranking(selectedDate) + dates + preview，保持选定日期 |
| official → preview | 使用已加载 Preview | 使用已加载 Preview |
| preview → official | 重新加载 ranking / preview / candidates 等 | 使用已加载的 officialSelected，无额外请求；尚无结果时才请求选定日期 |
| 历史详情 | Trend 已带日期；ETF 取最新历史 | 两页均明确带 trade_date；ETF 在 SQL 中先过滤 as_of，再 LIMIT |

首次加载后，`selectedDate` 取 ranking 返回的 `tradeDate`。辅助 dates / preview 独立更新，慢 Preview 不再阻止正式结果展示。请求序号保护跨市场/日期的异步结果；用户手动选择模式后，迟到的 Preview 不覆盖选择。

Trend 首次 official 页面由 13 条领域 SQL 降到 9 条（冷缓存）/ 2 条（热缓存，含 dates）；选择历史日期由 19 条降到 7 条 / 0 条。

ETF 在本次 42 只标的样本上，首次 official 页面由约 106 条领域 SQL 降到 10 条 / 2 条。指定历史日期的 ranking 不再额外请求 latest；冷缓存自身为 8 条 SQL，命中为 0 条。

## API 与数据库

- Trend 当前日 `dashboard_rows()` 仅投影表格/排序、生命周期卡片、组合需要的标量，JSON features 只提取 5 个用于排序/展示的值；不构造完整 Snapshot ORM，也不触发额外 Instrument eager join。
- 表格排序菜单已有的价格、ATR、信号日期和风险线排序保留，因此这些必要标量仍在 ranking items 中。完整 features、score_breakdown、reasons、其他持仓内部状态只在 detail / 原兼容接口返回。
- 同一批当前日投影派生 ranking、candidates（保持原 100 条上限）和 portfolio。原 candidates / portfolio API 保留兼容，页面不再调用。
- Trend previous changes 只取 code、state、action、pending_action、rank 和三项分数，共 8 列。
- 两个 API 的 changes 都已删除完整 `current` 对象，改为 code/name、前后状态/动作/排名以及差值。Dashboard 组件同步使用轻量字段。Preview 的本地比较对象不属于 API changes，仍可引用内存中的行。
- ETF `_metadata_by_code()` 在一次 ranking 中只调用一次；其结果复用于 summary、changes、items。原先每只 ETF 都执行 `_enrich([row], market)`，反复加载 Universe。
- ETF 当日 market_snapshot 只查询一次，再传给 `_changes()`；previous changes 也改为标量投影。
- 同步 SQLAlchemy 和同步 Redis / Celery 操作使用普通 `def` 路由，在线程池运行。没有引入 AsyncSession。

## 缓存

日期缓存 key：

- `trend_following:ranking:{market}:{trade_date}`
- `etf_rotation:ranking:{market}:{trade_date}`

缓存完整默认排序响应的序列化 JSON；不同 sort_by 或带 limit 的兼容请求绕过缓存，避免污染默认结果。latest 先用一条 SQL 解析日期，再查 Redis；指定日期命中不查询 DB。404 / 数据覆盖不足不写缓存，ETF 还要求 market snapshot 和 rankable coverage 合格。

写入成功提交后主动失效：Trend 的 replace_day、upsert_snapshots、upsert_summary、invalidate_from；ETF 的 upsert_market_snapshot、upsert_snapshots。因为 changes / 历史排名依赖更早日期，保守清理整个对应市场的日期缓存，另一市场不受影响。

每个 domain + market 另有递增 `ranking_revision`。失效先递增版本，再删除日期 key；响应带 schema/generation 前缀。请求使用 MGET 原子读取版本和值，回填用 Lua 比较版本，防止重算前开始的旧请求在失效后回填旧结果。

TTL 为 24 小时兜底。Redis 连接/读写超时为 200 ms，失败记录日志并回退 DB，不影响已提交的策略结果。若失效期间 Redis 不可用，已有缓存可能存活至 TTL，日志应作为运维检查依据。

## 测量

生产容器内启动独立诊断解释器，SQLAlchemy 连接显式设置 `default_transaction_read_only=on`，绕过会自动迁移的 DatabaseManager 初始化。通过临时 ASGI app 执行相同端点、真实 ORM 查询和响应序列化，鉴权使用测试依赖替换；不包含公网/CDN或鉴权耗时。新代码只加载到诊断解释器，不替换生产文件或重启服务。

Redis 命中测试只使用随机 `diagnostic:*` 前缀，完成后删除这些临时 key。没有写业务数据或正式缓存。

| CN ranking | SQL | 服务端时间 | 原始字节 | gzip level 5 字节 | items | changes 条目（跨分类计数） |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Trend 修改前 | 8 | 1,876 ms | 13,676,825 | 2,303,774 | 3,794 | 891 |
| Trend 修改后 miss | 8 | 299 ms | 3,029,928 | 511,269 | 3,794 | 891 |
| Trend 修改后 hit | 1 | 5 ms | 3,029,928 | 511,269 | 3,794 | 891 |
| ETF 修改前 | 96 | 166 ms | 174,014 | 36,503 | 42 | 20 |
| ETF 修改后 miss | 9 | 23 ms | 121,365 | 26,917 | 42 | 20 |
| ETF 修改后 hit | 1 | 1.7 ms | 121,365 | 26,917 | 42 | 20 |

时间为单次开发诊断样本，非压测 SLA。Trend 冷缓存 SQL 数量不变，但从两次完整 Snapshot 加载变成轻量投影；页面又省掉两个独立 API 的 4 条 SQL。

Nginx 配置开启 JSON/CSS/JS/XML/plain text gzip，保留 30s Axios timeout。用生产同款 Web image 启动临时容器，挂载修改后的配置和本次响应，实际 HTTP GET 返回 `Content-Encoding: gzip`、`Vary: Accept-Encoding`；压缩响应为 511,269 字节，解压后 3,029,928 字节。生产配置尚未部署。

## 前端 formatting 与渲染

Trend ranking 使用只遍历 DTO 已知容器的浅字段转换，其他 API 的通用 `toCamelCase` 不变。对真实响应做 10 次 Node 测量的平均值：

| 处理 | JSON.parse | camel-case mapping |
| --- | ---: | ---: |
| 原 Trend 全响应 deep | 26.97 ms | 146.48 ms |
| 瘦身后 Trend 仍用 deep（对照） | 5.26 ms | 27.96 ms |
| 瘦身后 Trend DTO mapping | 5.15 ms | 10.58 ms |
| 瘦身后 ETF deep | 0.25 ms | 1.02 ms |

ETF 没有明显 mapping 热点，按要求保留 `toCamelCase`。Trend Preview 仍返回完整快照供盘中详情使用，约 10 MB，仍可能有 deep mapping 开销；本次未改变 Preview 数据契约/计算，通过 gzip 和独立加载降低其对正式首屏的影响。

实际 CN Universe 有约 3,800 行。Chromium mock 请求测量，一次创建完整表格约 3,015 ms；虚拟表格约 161 ms（包括校验滚动末尾）。大于 300 行时只挂载 28 行和占位空间，所有数据仍一次加载、全量排序，没有业务分页。较小结果直接显示全部行。

搜索框按名称或代码进行大小写不敏感过滤，覆盖全部已加载记录；先过滤再排序再虚拟渲染，支持空结果提示，排序/搜索会回到顶部，不产生 API 请求。

## 验证

- 完整后端 `ci_gate.sh`：使用独立临时 PostgreSQL 测试容器，2,129 passed、19 skipped、104 subtests passed；语法、flake8 和 deterministic 阶段通过。
- 前端 Vitest：61 个文件、500 tests passed。
- `vue-tsc -b` 通过；Vite build 输出到临时目录，未修改 `static/`。
- Playwright：14 passed，包含两页详情、Dashboard、虚拟滚动末尾、全量排序、名称/代码搜索。
- 离线回归覆盖缓存 hit/miss、市场/日期隔离、提交后失效、旧请求回填保护、轻量 changes、Universe 单次加载、历史日期直达和 detail as_of。
- 首次全门禁使用默认本机 DB 凭据时失败；随后在隔离测试库完整重跑通过。

## 涉及文件

- 共享缓存：[core/snapshot_cache.py](../src/finance_analysis/core/snapshot_cache.py)，两个领域各自的 `ranking_cache.py`。
- Trend 投影 DTO：[read_models.py](../src/finance_analysis/trend_following/read_models.py)。
- API：[trend_following.py](../src/finance_analysis/interfaces/api/v1/endpoints/trend_following.py)、[etf_rotation.py](../src/finance_analysis/interfaces/api/v1/endpoints/etf_rotation.py)。
- 仓储：[trend_following.py](../src/finance_analysis/database/repositories/trend_following.py)、[etf_rotation.py](../src/finance_analysis/database/repositories/etf_rotation.py)。
- 页面：[TrendFollowingPage.vue](../web/src/pages/market/TrendFollowingPage.vue)、[ETFRotationPage.vue](../web/src/pages/market/ETFRotationPage.vue)。
- 两个领域的 `web/src/api/` 客户端、`web/src/types/` 类型，以及 Dashboard 的 `StrategyChanges.vue` / `dashboardFormat.ts`。
- 部署配置：[docker/nginx.conf](../docker/nginx.conf)。
- 更新两领域 API / repository / preview 现有测试和前端 API / page 测试；新增缓存离线测试，扩展 Trend Playwright 用例。

生产数据的 changes 六类/五类分别逐项对照，分类内代码顺序和所有差值均与修改前一致；891 / 20 条分类条目没有丢失。
