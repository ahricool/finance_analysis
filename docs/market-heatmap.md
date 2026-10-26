# 市场热力图

页面 `/market/heatmap?market=CN|US`，接口 `GET /api/v1/market-heatmap?market=CN|US`。
页面按行业纵向浏览紧密拼接的矩形热力图，红涨绿跌；宽屏两列行业、窄屏单列。
展示快照内全部股票，不按市值截断。块内 A 股显示名称、美股显示 ticker，另显示涨跌幅；字号在16–5px之间按实际空间动态适配。
完整名称、canonical code 和真实市值放在悬浮提示与无障碍标签中。
支持名称/代码搜索和行业筛选；点击股票使用 App 唯一的统一详情 Host，键盘 Enter/Space 同样可打开。

## 展示口径

- 仅展示 DB 中 ACTIVE / STOCK 证券。A 股总市值至少100亿元，美股至少20亿美元。
- 缺市值不生成方块，缺涨跌幅保留灰色，不把缺失当作平盘。ETF、指数不参与。
- 每行业包含快照内全部股票，搜索/行业筛选仅过滤匹配结果，不设置数量或市值覆盖率上限。
- 市值采用0.75次幂权重，以最大权重的1/100作为面积下限，沿长边按权重二分铺满行业矩形。
  密集行业按股票数量增加高度，保留每个方块；标签按实际宽高从16px缩小至5px，优先显示名称和涨跌幅；仍放不下时只显示名称，名称在5px也放不下才隐藏。
  窗口、内容和字体加载变化后重新测量，悬浮和点击始终可用。
  不宣称面积严格等于真实市值占比，行业头部显示实际股票数量。
- 行业按候选总市值降序，股票按市值降序并按代码打平；行业保留单一归属。
- 标签使用原生按钮，可用 Tab/Enter/Space；各档颜色与白字对比度至少4.5:1。
- CN 只读 `industry_catalog / industry_membership`。同花顺目录混合宽行业与细分类，未提供可靠父子关系；
  多归属股票优先选择成分数量较多的行业，按行业代码打平，确保每只股票只计一次。不虚构行业层级。
- US 只读 `instrument.metadata.classification.sector`，使用 Yahoo 分类，未分类独立展示。

## 数据刷新

两个独立 Beat 任务 `market_heatmap_cn/us` 全天每15分钟在 ingestion 队列运行，使用独立非阻塞任务锁。
任务定义在 `tasks/celery/schedule/definitions.py`；可在任务中心由管理员手动触发。

业务仅调用 `MarketDataService`：CN 显式指定 easyquotation 腾讯全市场快照，
将其总市值/流通市值从亿元转换为统一模型中的元；US 指定 yfinance Screener，按美国上市交易所、
市值门槛筛选，以 ticker 排序每250条尽力分页。盘中total变化不再导致整批失败，跨页股票按symbol去重、保留首次观测；
跳过无代码/无效记录，继续获取后续页。遇孤立失败页，在已取得数据且上游指示还有后续页时跳过；
连续两次失败、连续两页无新增、空页/已到末尾的短页或最多200页时结束，保留已取得的数据。
单页仍复用既有有限重试，不逐股补请求、不无限重跑整轮。每条再次检查 EQUITY 类型，不能只信上游筛选。
Yahoo 的 `BRK-B` 等股类代码转回 `BRK.B.US`。不调用 Alpaca，不扩大 Streamer 采集池。

最新快照以 Redis `market_heatmap:v1:CN|US` 的单次 SET 原子发布，TTL七天；不保存行情历史或写日线。
分页总量漂移、重复或局部失败不再直接拒绝美股热力图；有效结果可发布。
仍保留空结果及相对上次股票数量跌破80%的保护，不用严重残缺的新结果覆盖旧快照。
首次没有缓存时可发布非空有效结果，因此不保证是全市场同一时刻的完整截面；日志记录页码、条数变化、
重复/无效数量和提前结束原因。行业周同步仍使用原来的严格分页，避免部分分类替换主数据。
GET只读缓存，不请求 Provider、不派发任务。无缓存返回 empty；生成时间超过30分钟返回 stale 并保留旧图。
前端每15分钟重新读取一次，手动重新加载同样只读缓存。展示行情时间与快照生成时间，避免混淆。

## 美股行业周同步

现有 `reference_data_sync`（周日上海08:00）在证券目录与指数成分同步后，增加美股行业阶段。
通过 `MarketDataService.get_stock_classifications('US')`，按 Yahoo 的145个行业完整分页采集，
将 sector、industry、source、observed_at 保存到已存在的美股 STOCK 的 `instrument.metadata.classification`。
不因行业接口创建证券；保留其他 metadata，证券目录/指数成员 upsert 也合并 metadata，防止抹掉分类。
分类网络采集在事务外；全部行业完成后单事务替换，异常或已分类证券覆盖下降超过20%保留上一代。
分类失败在周任务结果中标记 partial，不回滚已成功的证券/指数同步。
个股 `/stocks/{code}/classification` 和详情行业标签同时复用这些只读数据。

首次上线建议管理员手动运行一次「证券主数据与指数成分同步」，再运行两个热力图任务；
未运行行业同步时，美股仍展示行情并归入“未分类”，下次周同步后自动补齐分组。
当前行业是观测到的最新分类，不提供历史行业归属。

## 验证

后端：`uv run pytest tests/test_market_heatmap.py tests/test_celery_schedule.py tests/test_celery_task_structure.py -q`。
前端：热力图尺寸/颜色/筛选与页面单测，以及 `web/e2e/market-heatmap.spec.ts` 的六种视口、明暗主题冒烟。
浏览器断言逐块标签无溢出，鼠标及键盘打开详情只存在一个 dialog，Escape关闭后无残留。
生产数据验收只读现有 Redis 快照，在本地页面注入原始响应，不改生产缓存、任务或用户数据。

## 本地布局评审

运行 `pnpm --dir web dev` 后打开 `http://localhost:5173/heatmap-demo.html`。
独立 demo 入口复用正式 `HeatmapChart`，包含 A 股/美股模拟数据、搜索、行业筛选与明暗主题；
无需登录或后端，不写数据库/Redis，也不纳入默认生产构建入口。示例数值不代表真实行情。
