# 自选股市场与分组

页面 `/market/watch-list` 提供美股、A股切换，默认 A 股，与投资组合一致。
“全部”固定在分组筛选第一位，显示当前市场所有股票；“未分组”仅显示无标签股票。
用户标签跨市场共用，空标签也保留在筛选区；切市场不重置当前分组。
历史港股记录与底层 HK 类型保留，页面暂不提供港股入口。

标签名称去除首尾空白后为 1–32 个字符，按 Python `casefold()` 在用户内唯一。
股票最多关联 50 个标签；单股移除关联、删除股票均保留标签定义。
管理标签的删除操作移除全部关联，不删除股票。

## 接口

所有操作沿用当前会话 uid，不接受客户端指定用户。

- `GET /api/v1/watch-list?market=CN|US|HK&tag_id=<id>`：按市场与标签组合筛选。
- `GET /api/v1/watch-list?market=CN|US|HK&ungrouped=true`：筛选未分组股票。
- 未传分组条件表示“全部”；`tag_id` 与 `ungrouped=true` 不能同时使用。
- 响应 `items` 是筛选后的股票，`total` 是当前市场总数（未传市场则是用户全部股票总数），用于“显示 X / Y 只”。
- 股票列表、创建和修改响应均包含 `tags: [{id, name}]`，列表批量加载关联。
- `POST /api/v1/watch-list` 与 `PUT /api/v1/watch-list/{id}` 支持完整 `tags` 集合：已有标签用 `{id}`，新标签用 `{name}`，每项只能提供其中一个。
- 更新未传 `tags` 保留原关联，`tags: []` 清空关联，`tags: null` 拒绝。
- 新标签按当前用户解析或创建，与股票及其关联在同一事务保存；取消股票弹窗不会创建标签。
- `GET/POST /api/v1/watch-list/tags`：列出/创建用户标签。
- `PUT/DELETE /api/v1/watch-list/tags/{id}`：重命名/删除用户标签。

SSE `/api/v1/market-data/events` 与 WS `/api/v1/market-data/ws` 的自选 scope
接受相同 `market`、`tag_id`、`ungrouped` 条件，在查询用户股票后仅获取与发送符合条件的行情。
页面切换市场或分组会取消旧列表请求并重建实时连接，旧响应不会覆盖新筛选。
不带条件的实时接口仍保留全部用户自选股行为；持仓 scope 保持原有逻辑。
标签不改变后台 Streamer 订阅、行情维护、个股分析或定时任务范围。

证券补全沿用 `/api/v1/stocks/search`，可选 `market=CN|US|HK` 透传到既有主数据搜索，
在 limit 之前限制市场；未提供市场的调用保持原行为。

## 数据迁移与验证

`0075_watch_list_tags` 接在 `0074_industry_reference` 后，仅新增 `watch_list_tag`、
`watch_list_tag_link`，不改已有股票与唯一键；已有股票默认无关联。
部署沿用启动迁移，手动执行为 `uv run alembic upgrade head`。
回滚该 revision 只移除标签与关联表，不删除股票。

后端测试：`tests/test_watch_list_tags.py`、`tests/test_watch_list_api.py`、
`tests/test_watch_list_repo.py` 与 `tests/test_realtime_market_websocket.py`。
前端覆盖市场/分组组合、空态、草稿取消、保存回显、管理标签与旧连接隔离。
