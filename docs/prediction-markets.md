# 个股 Polymarket 搜索

市场 → 事件预测目录已退役。个股唯一 StockDetailDialog 的 **Polymarket** 页签支持 CN/US/HK，只有激活时才查询。

## 数据流与排序

登录用户 → FA 后端读取已有 Instrument 名称 → Gamma `GET /public-search`。
分别使用名称（去掉 Inc/Corporation 等英文公司后缀）和不带市场后缀的证券代码查询。
没有名称时只查代码；不翻译、不调用 LLM、不读取用户持仓/自选信息。

每个搜索词取官方首页最多20条未关闭事件；名称结果优先，代码结果补充，按事件ID去重后最多20条。
保留每次官方搜索返回的顺序，不声称是严格的全站热度排名。24小时成交额有值时显示，无值留空。
代码可能存在歧义，尤其 AI/ON 等短代码或纯数字代码；这是关键词检索，不代表股票关联或市场影响判断。
不遍历全站，不补全所有分页，不保存关联关系。部分搜索失败明确标记 partial；全部失败显示不可用。

## API 与缓存

- `GET /api/v1/prediction-markets/stocks/{symbol}`：规范代码，名称/代码搜索。
- `GET /api/v1/prediction-markets/events/{event_id}/live`：Gamma `/events/{id}`；保留 Event/Market/Outcome 层级。
- `GET /api/v1/prediction-markets/events/{event_id}/history`：当前详情验证 market/outcome 归属后访问 Data API `/v2/prices-history`。

接口要求登录，无管理写接口。GET允许只读上游及写可丢弃Redis缓存，不写业务数据库、不派任务、不调用LLM。
共享缓存无uid；搜索键包含查询词版本。并发上限4，同进程相同请求合并。
搜索每个词最多两次尝试，每次6秒超时，长Retry-After直接降级。

配置（没有功能总开关）：

| 环境变量 | 默认 | 用途 |
| --- | --- | --- |
| POLYMARKET_SEARCH_TTL | 300秒 | 搜索结果 |
| POLYMARKET_LIVE_TTL | 60秒 | 选项/概率 |
| POLYMARKET_HISTORY_TTL | 300秒 | 历史曲线 |

另保留最多300秒短期过期缓存以应对上游错误，明确stale及原始fetched_at，命中缓存不改变获取时间。
Redis故障时限并发直连；刷新按钮不绕过共享缓存。关闭弹窗/切股票/切页签取消请求并阻止迟到响应覆盖，无后台轮询。

历史仍使用官方分辨率/分页，不存储概率/历史点。0/1有效，缺失为NULL；无交易占位价格显示暂无。
24h/7d变化来自同一历史系列，单位百分点；历史不足/陈旧不伪造。历史与当前报价可能口径不同，分别标时间。

## 退役迁移

PR #500引入的标签全量目录、规则筛选、手工导入、管理覆盖及目录同步全部移除。
新增 `0092_retire_prediction_catalog`，删除 `prediction_tag`、`prediction_event` 及旧目录同步任务记录。
已发布0091不修改；空库bootstrap只创建当前ORM，不再创建预测目录表。删除的数据不可恢复。
不创建任何新的业务表，也不注册Polymarket定时任务。旧Redis键按短TTL自行过期。

## 验证与上游限制

离线tests/prediction_markets覆盖搜索契约、去重/上限/官方顺序、缓存与故障、只读API、层级与历史。
迁移用专用测试库验证，前端覆盖懒加载、切股竞态、错误/空态及可展开选项。
官方public-search没有协议version筛选，搜索覆盖以官方返回为准；详情兼容已明确标识的V1/V2结果ID。
官方搜索可能遗漏、相关性不精确；中文名称/数字代码命中有限，不进行自动翻译或业务影响推断。

官方参考：https://docs.polymarket.com/api-reference/search/search-markets-events-and-profiles
