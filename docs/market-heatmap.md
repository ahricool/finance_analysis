# 市场热力图

页面 `/market/heatmap?market=CN|US`，接口 `GET /api/v1/market-heatmap?market=CN|US`。
页面按行业纵向分区、红涨绿跌，完整展示股票名称、canonical code、涨跌幅及真实总市值。
股票块保留最小阅读空间，名称自动换行，页面自然向下滚动，不再把全市场挤入固定高度的 Canvas。
支持名称/代码搜索和行业筛选；点击股票使用 App 唯一的统一详情 Host，键盘 Enter/Space 同样可打开。

## 展示口径

- 仅展示 DB 中 ACTIVE / STOCK 证券。A 股总市值至少100亿元，美股至少20亿美元。
- 缺市值不生成方块，缺涨跌幅保留灰色，不把缺失当作平盘。ETF、指数不参与。
- 市值权重由平方根提高为0.75次幂。相对整份快照最大权重，将股票块分为
  1×1、2×1、2×2、3×2、3×3五档；窄屏限制跨列及最多两行，避免巨头占满屏幕。
  每个阅读单元至少160px宽、124px高；空间不足时降为一列，长名称可撑高行，禁止省略号裁切。
  这是兼顾标签阅读的相对市值示意，不宣称面积严格等于真实市值占比。
  筛选使用完整快照的权重，避免搜索后小股票突然变成最大块；块内总市值始终显示真实值。
- 行业按总市值降序，股票按市值降序并按代码打平；行业保留单一归属。
- 标签使用原生按钮内的完整文本，可用 Tab/Enter/Space；各档颜色与白字对比度至少4.5:1。
- CN 只读 `industry_catalog / industry_membership`。同花顺目录混合宽行业与细分类，未提供可靠父子关系；
  多归属股票优先选择成分数量较多的行业，按行业代码打平，确保每只股票只计一次。不虚构行业层级。
- US 只读 `instrument.metadata.classification.sector`，使用 Yahoo 分类，未分类独立展示。

## 数据刷新

两个独立 Beat 任务 `market_heatmap_cn/us` 全天每15分钟在 ingestion 队列运行，使用独立非阻塞任务锁。
任务定义在 `tasks/celery/schedule/definitions.py`；可在任务中心由管理员手动触发。

业务仅调用 `MarketDataService`：CN 显式指定 easyquotation 腾讯全市场快照，
将其总市值/流通市值从亿元转换为统一模型中的元；US 指定 yfinance Screener，按美国上市交易所、
市值门槛筛选，以 ticker 排序每250条完整分页。每条再次检查 EQUITY 类型，不能只信上游筛选。
Yahoo 的 `BRK-B` 等股类代码转回 `BRK.B.US`。不调用 Alpaca，不扩大 Streamer 采集池。

最新快照以 Redis `market_heatmap:v1:CN|US` 的单次 SET 原子发布，TTL七天；不保存行情历史或写日线。
分页缺失、重复、总量漂移、空结果以及相对上次股票数量跌破80%时不覆盖旧快照。
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
