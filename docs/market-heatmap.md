# 市场热力图

页面 `/market/heatmap?market=CN|US`，接口 `GET /api/v1/market-heatmap?market=CN|US`。
页面按行业分区、红涨绿跌，展示股票名称、canonical code 和涨跌幅，悬浮显示真实总市值；
点击行业放大、点击股票打开统一详情，全景按钮恢复整个市场。

## 展示口径

- 仅展示 DB 中 ACTIVE / STOCK 证券。A 股总市值至少100亿元，美股至少20亿美元。
- 缺市值不生成方块，缺涨跌幅保留灰色，不把缺失当作平盘。ETF、指数不参与。
- 面积权重先对总市值取平方根，再以全市场3%上限迭代分配；不足34只时，上限至少为
  `1 / 股票数`，以保证可布局。行业面积为股票显示权重之和，不宣称是行业真实市值占比。
  点击行业放大后会在该行业内重新铺满画布。提示中的市值始终是未经压缩的真实值。
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
前端：热力图面积/颜色与页面单测，以及 `web/e2e/market-heatmap.spec.ts` 的六种视口、明暗主题冒烟。
