# 事件预测 / Polymarket

市场页面 `/market/prediction-events` 展示经过规则筛选的 Polymarket 话题、选项、隐含概率和历史。
本期只做公开数据拉取与展示，不提供股票匹配、证券关联或个股详情页签，不调用 LLM。
它是公共事件研究，不交易、不接钱包、不通知，不影响任何策略评分、finance_events 或投资时间线。

## 运行

功能与目录同步任务始终开启，无需配置功能开关。旧环境中的 `POLYMARKET_ENABLED` 不再读取，可以删除。
部署后 Beat 按周期发布目录同步任务，也可由管理员手动启动首次同步。
迁移 `0091_prediction_markets` 接续 `0090_trend_ten_day`，遵循现有空库 bootstrap。
管理员可在共享配置管理区或任务中心启动目录同步。配置修改影响所有用户，不增加个人收藏或关注来源展示。

- `scheduled.polymarket_catalog_sync`：上海时间每6小时第10分钟，ingestion；枚举标签、发现事件、刷新已存事件明确状态、重算规则。使用 PostgreSQL session advisory lock 19，外部请求不占业务写事务。
- `POLYMARKET_LIVE_TTL=60`、`POLYMARKET_HISTORY_TTL=300`；过期后最多额外保留300秒用于标明 stale 的故障降级，不作为长期历史。

任务结果统计扫描、重复、保留、排除、更新、失败、官方/可见标签数量，目录执行结果。
分页或单项失败记录 partial/failed，不把未扫描条目当作删除/关闭。404、超时、超过截止日期都不会关闭话题。

## 数据边界

`integrations/polymarket/` 封装固定公开域名 HTTP、分页、有限重试；不接股票 Provider 链。
`prediction_markets/` 放规则、目录同步和按需数据；repository 负责事务。

仅两张表：

| 表 | 内容 |
| --- | --- |
| prediction_tag | 全量官方 tag ID/slug/label，规则分组、显示/人工覆盖、成功同步时间 |
| prediction_event | 事件级标题、最多6000字符说明、tag IDs、日期/明确状态、规则/人工保留、规则版本和成功同步时间 |

**不保存** market、outcome、token/position 映射、赔率、盘口、成交量序列、价格历史或原始 Gamma payload。
事件公开链接由已存 slug 构建。所有上游 ID 为字符串；持久时间为 aware UTC。
事件同步即使收到嵌套 markets 也只投影事件级字段。不读取自选、持仓或证券画像。

## 规则

标签全分页枚举，但普通界面只展示规则/管理员允许的官方标签。ID 从目录解析，不猜测数字 ID。
规则集中在 `prediction_markets/rules.py`，使用明确 slug 集合：

- 金融：finance、financials、stocks、stock-market、markets、fed、interest-rates。
- 商业：business、ipos、ipo、earnings、companies、mergers。
- 经济：economy、economics、inflation、recession、gdp、unemployment。
- 科技：tech、technology、ai、artificial-intelligence、semiconductors。
- 经济政策：tariffs、trade-war、regulation、economic-policy、monetary-policy、fiscal-policy。

只匹配上游实际存在的标签。政治大类不默认放开；纯政策标签事件还需经济政策关键词。
排除明确体育/娱乐标签与分钟币价模板，价格预测可保留但标记。规则偏宽松，接受漏失/误筛。
**整个模块不调用 LLM，标签分类、话题保留/排除均使用规则。** 标题和标签保持官方原文。
手动 URL/slug 导入只向固定 Gamma API 请求，可绕过话题规则，但不会放开其其他标签。
人工开关在同步后保留；恢复规则解除覆盖。已有话题改为排除时保留历史记录。

## 动态 API / 缓存

登录保护的读接口：

- `GET /api/v1/prediction-markets/tags`：可见标签及计数。
- `GET /events`：DB话题，分页、关键词、tag_ids OR并集、closed、全局 updated/deadline/title 排序。
- `GET /events/{id}/live`：已存且保留的事件动态详情。
- `GET /events/{id}/history?market_id=&outcome_id=&window=1d|1w|1m|max`：先确认结果属于当前事件。

以上路径均相对于 `/api/v1/prediction-markets`。动态 GET **允许只读上游和短缓存写入**，不写业务表、不调用LLM、不派任务。
管理员：`GET /admin/tags|events`、`PATCH /admin/tags/{id}`、`PATCH /admin/events/{id}`、`POST /admin/run`。
任务型导入/同步返回202和task_id，直接配置修改同步完成。

缓存键含协议、结果ID、窗口和粒度，不含uid。进程内同键合并在途请求，最多4个上游加载同时进行，HTTP连接池复用；Redis失败有限并发直连并记录诊断。
缓存命中保持原 fetched_at，stale 标明原时间；无缓存且上游失败返回 unavailable，不伪造0%。
前端每页最多10个话题请求 live，只有展开指定结果才请求历史，无轮询、WS/SSE、后台赔率任务。

Event → Market → Outcome 层级保留，所有问题/选项可展开；不假设首项为YES，不计算事件“总概率”。
当前概率来自 Gamma outcomePrices，标注价格类型；无成交证据的占位值保守为未知。0和1有效。
上游未知报价观察时间保持null，不用updatedAt冒充；fetched_at仅表示读取时间。关闭/结算独立展示，不把结算值当公告前概率。

## 官方契约与能力限制

实施核对（2026-11-13）：

- [官方目录](https://docs.polymarket.com/llms.txt)、[发现事件](https://docs.polymarket.com/market-data/discover-markets)。
- [标签分页](https://docs.polymarket.com/api-reference/tags/list-tags)：limit/offset，持续到空页。
- [事件 keyset](https://docs.polymarket.com/api-reference/events/list-events-keyset-pagination)：next_cursor→after_cursor。
  事件集合未声明 version 参数；额外枚举市场 keyset，显式 `version=v1&version=v2`，按父事件去重补齐发现。不能把省略 version 的市场结果称为全站覆盖。
- [结果标识与报价](https://docs.polymarket.com/market-data/prices-order-books)：V1 clobTokenIds、V2 positionIds 按原顺序对应 outcomes；Data API token_id 是统一 asset ID，不因参数名排除V2。
- [Data API v2历史](https://docs.polymarket.com/api-reference/markets/get-a-tokens-price-history)：`/v2/prices-history`，token_id、interval 或 start/end 或 as_of（三选一），秒级时间，cursor分页到 next_cursor=null。短/空页仍继续；重复cursor视为失败。
  显式范围每段≤15天，长范围分段去重；max使用官方全生命周期窗口。bucket_seconds可指定，默认交给上游选择可用粒度。

原样保留每点 timestamp / resolution_seconds，不假设均匀采样或插值。深历史可能只有3小时/12小时粒度；空历史正常。
24h/7d使用同一历史序列最新点减目标时点或之前的观察，乘100（百分点）。最新允许15分钟，基线偏离/粒度允许1小时；不满足返回null和原因。
当前报价不和历史价格硬相减。历史变化注明自身截至时间；关闭/结算市场不计算变化。
Data API resolution_seconds=0既可能是末端真实tick也可能是结算点，本身不能证明未结算。

未保证全站所有事件都被规则发现，不承诺永久精细回放或断网长期行情可用性。官方API失败与规则遗漏需区分。
离线 fixtures 不等于真实API验证；测试数据库使用独立 `PREDICTION_TEST_DATABASE_URL`。
