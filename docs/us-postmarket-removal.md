# 美股收盘复盘退役

`analysis_us_postmarket_review`（原纽约22:00）已删除，不再采集复盘输入、调用该任务的 LLM 或生成日报通知。
删除 Beat 定义、任务注册/路由、执行包、专属 Prompt、模型、历史读取器和报告发送器。
无其他调用方的 `reporting/runtime.py` 与 `report_delivery_outcome` 同步移除。

## 历史清理

迁移 `0089_retire_us_postmarket` 接在 `0088_holdings_review` 后，清理：

- `scheduled_us_postmarket_review` / `analysis_us_postmarket_review` 的全部任务记录，包含未完成记录。
- 任务结果关联的 notification、明确属于收盘复盘的报告和错误通知。
- 旧 `timeline_entries.entry_type=us_postmarket` 报告存档。
- `call_type=us_postmarket_review` 的 LLM 用量及当前审计目录内对应 JSONL 行。
- 日志根目录内关联的任务日志，以及该任务专属命名的日志；不删除根目录外文件，不跟随扫描到的符号链接。
- 旧版本保存于 `data/reports/analysis/us_postmarket_review_YYYYMMDD.md` 的报告文件；仅匹配8位日期命名，保留其他报告和符号链接目标，目录不能解析到 DATA_DIR 外。

混合审计文件保留其他调用和无法识别的行。`LLM_LOG_DIR` 支持独立目录及 `~`。
迁移可重复运行，兼容有关表部分或全部不存在；历史删除不可逆，downgrade 明确拒绝。
离线 PostgreSQL SQL 只清数据库；日志及旧报告文件清理需要正常在线 Alembic 执行。

## 共享数据保留

任务本身不维护行情表。历史上为它添加的4只基准 ETF（SPY、QQQ、DIA、IWM）和11只板块 ETF
仍服务财报前瞻和核心指数覆盖，保留证券、日线和同步成员，不扩大 ETF / Trend 候选池。
常量及初始化改为 `market_review/us_research_symbols.py` 和 `database/us_research.py`；
`us_daily_sync` 中原 `US_POSTMARKET_REVIEW` 成员来源改为 `US_RESEARCH_CONTEXT`，其他范围和来源不变。
`database/us_postmarket.py` 仅供已发布的历史迁移0068兼容导入，当前启动 seed 不再调用它。

双市场持仓复盘、实际持仓及买卖、财报/宏观事件、财报研究、Signal Center、Quant、ETF、Trend、
日线同步与 Streamer 均保留，不读取或依赖已删除的报告结果。

## 发布与验证

按标准部署暂停 Beat 并等待旧 worker 退出，再部署并执行迁移。不清空共享 Redis broker；
残留旧任务名称在新 worker 上没有处理器。新增数据库无需创建该任务或其业务历史。
代码提交不代表生产迁移已执行，不在开发环境直接清理生产数据库。

测试覆盖注册/调度删除、SQLite/PostgreSQL 及离线 SQL 清理、重复运行、部分表缺失、
通知归属、混合审计、旧报告文件清理与路径边界，以及共享 ETF 同步与财报/持仓复盘的保留。
