# 个股决策分析删除与依赖审计

本文记录当时删除边界；后续盘前新闻及专属依赖已由 `0086_retire_news` 退役，见[新闻退役说明](news-removal.md)。

## 删除范围

- 美股盘前个股分析 `analysis_us_premarket`，包括 Beat 定义、任务注册、期限常量和执行服务。
- 手动单股分析 `analysis.run_stock_analysis`，包括 API/Bot 提交门面、任务元数据、执行服务和专属锁。
- 整个旧 `analysis/` 包：决策仪表盘 Prompt、LLM JSON 解析、评分/建议修正、pipeline、分析历史服务与对比。
- 个股报告 schema、Markdown/Jinja 渲染、模板、NotificationService 中的单股/汇总报告方法及专属配置。
- 个股历史/基本面快照写入和专属数据库查询方法、已无调用方的分析仓储。
- 专属测试、Docker 模板拷贝与路径烟测、Jinja2 直接依赖。

没有新增 A 股替代任务或统一决策仪表盘。

## 会被误伤的共享依赖：已拆开保留

| 原依赖 | 仍在使用的调用方 | 处理 |
| --- | --- | --- |
| StockReportAnalyzer.generate_text | 仅旧手动大盘复盘 | 随旧手动大盘复盘一并删除，无独立文本生成适配器残留 |
| analysis.pipeline_config | 盘前新闻、美股收盘复盘、A 股 14:30 复核 | 仅保留 LLM/报告语言，移至 `reporting/runtime.py`，删除旧复盘市场选择配置 |
| analysis.history.loader/errors | 股票历史 API、美股收盘复盘 | 移至 `stocks/history.py` / `history_errors.py`，保持只读历史与指标公式，删除 pipeline 专属冻结上下文 |
| analysis.technical.indicators | Trend 超跌反弹研究 | 移至 `trend_following/indicators.py`，保持 RSI 公式 |
| NotificationService | 全部研究消息、交易信号、任务错误 | 保留持久化/推送/降噪及图片转换，移除个股报告渲染继承 |
| report language 配置 | 市场复盘与 Longbridge | 保留语言规范化，删除个股报告专属文案/信号本地化 |

盘前新闻、美股收盘复盘、A 股 14:30 复核、Trade Engine、Signal Center、财报前瞻、Trend/ETF/Quant、日线同步和 Streamer 都保留。
`analysis` Celery 队列也继续承载其他研究任务，不能删除。

## 删除后停止生产或失去消费者的项目

| 项目 | 删除后的状态 | 本次处理 |
| --- | --- | --- |
| `analysis_history` | 部署迁移后不再存在 | 迁移 `0084_drop_stock_analysis_archive` 删除整表及全部历史数据，同时移除 ORM 和导出 |
| `fundamental_snapshot` | 部署迁移后不再存在 | 同样由 `0084_drop_stock_analysis_archive` 删除整表及数据，移除 ORM 和导出 |
| 历史 TaskRecord、notification、llm_usage、LLM 私有日志 | 属于历史审计记录，不需要原任务存在 | 保留；任务中心/消息中心仍可读，旧报告正文不重新渲染 |
| 旧任务的 pending / processing / retrying TaskRecord | 执行代码删除后可能永久悬空 | 迁移 `0083_retire_stock_analysis` 仅取消这两类未完成任务，保留已结束记录及结果 |
| Broker 中旧任务消息 | 迁移只更新 PostgreSQL，不清 Redis broker | 正常部署先停止 Beat 并等待旧 worker 退出；残余旧名称消息不再有处理器，新 worker 不会继续生成个股报告；对应既有任务行由迁移取消。不清空共享队列 |
| `MarketDataService.get_fundamental_context` 聚合入口及聚合配置 | 当前已无应用业务调用方；Provider 离线契约测试仍覆盖 | 本次保留为无调度的行情能力，明确列为悬空聚合入口；后续如清理，需要单独核对原始 capability 的其他使用方 |
| 历史 `data/reports/analysis`、导出/图片文件 | 不再由旧个股报告链生成；旧文件可能仍在 | 不删除本地/生产文件；没有新增清理任务 |

`stock_daily`、Instrument、Universe、自选股和持仓不是这条任务独有的数据源，继续被行情、研究和交易引擎使用。
扶摇原始财报/资金流/行业能力、Longbridge 新闻及共享 LLM 调用层也不随本任务删除。

## 发布与回滚

按 `docs/deployment.md` 使用标准部署流程，不直接向正在运行的 worker 热替换代码。
迁移 `0083_retire_stock_analysis` 取消未完成旧任务；随后 `0084_drop_stock_analysis_archive` 删除 `analysis_history`、`fundamental_snapshot` 两张表及数据。
后者为不可逆删除，downgrade 明确报错；前者不自动恢复被取消的工作，也不重新发布任务。
空库 metadata bootstrap 不再创建两张历史存档表；已有库执行取消任务及删表迁移。

## 验证重点

- 任务不再出现在 Beat、Celery 注册表和手动提交入口。
- 所有保留模块不再 import 已删除的 analysis 包。
- 盘前新闻、定时美股收盘复盘、历史行情与 RSI 的原有测试继续执行。
- 数据迁移只取消未完成的旧个股任务，不误伤盘前新闻、复盘或已完成历史。
- Docker 不再引用已删除模板。

## 简单 code review 结果

已检查删除入口、共享 import、任务注册/路由、Docker 文件引用、数据迁移范围及存档删除边界。
发现并修复了共享大盘复盘类依赖、模板路径烟测和未完成旧任务悬空问题；未发现其他阻塞问题。

在独立临时 PostgreSQL 16 上执行完整后端门禁：syntax、flake8、deterministic 均通过；
离线测试 3114 passed、57 skipped、2 deselected，另有 88 subtests passed。
退役及删表迁移通过 SQLite 与 PostgreSQL 验证：覆盖幂等取消、存档表全部/部分/均不存在、新库 metadata 不建表，以及保留其他任务/通知/新闻/日线数据。
上述为独立测试库验证结果；尚未部署生产，生产存档删除将在部署迁移时执行。

## 旧手动大盘复盘一并删除

`analysis.run_market_review` 与纽约22:00的 `scheduled.analysis_us_postmarket_review` 是不同任务。
删除前者的任务注册、执行适配、通用 CN/HK/US Prompt、策略蓝图、模板降级、数据模型、
市场选择配置，以及没有其他调用方的 Bot payload/消息兼容层和日历市场子集辅助函数。
`market_review/` 仅保留多模块仍使用的交易日历、涨跌停规则和美股基准/行业ETF常量。

迁移 `0085_retire_market_review` 不保留该任务的业务历史：

- 删除 `task_type=market_review` 的全部 TaskRecord，包含已结束和未结束记录。
- 删除由任务结果关联的站内消息、旧复盘专属中英文标题报告及明确标记旧任务类型的错误通知。
- 删除 `call_type=market_review` 的 LLM 用量和当前配置审计目录中对应的 JSONL 记录。
- 删除日志根目录内该任务记录关联/专属命名的任务日志；拒绝删除日志根目录外的路径。
- 保留定时美股收盘复盘的任务、通知、用量及日志，以及共享文件中其他任务的审计行。

该迁移同时修改数据库与已识别的日志文件，删除不可逆；重跑安全，不会恢复历史或重新提交任务。
不清空共享 Redis 队列，不按“market_review”子串批量删除其他任务。
标准部署使用在线迁移执行日志清理；离线 SQL 导出只能清数据库记录，无法删除文件。

追加 review 已确认两条复盘的执行主体与 Prompt 独立；仅共享配置提取到 reporting，
新增删除测试覆盖 PostgreSQL/SQLite、站内消息关联、独立审计目录、混合 JSONL 保留及日志路径越界保护。
离线 PostgreSQL 清理 SQL 也已在独立测试 schema 实际执行，未误删定时美股复盘记录。
