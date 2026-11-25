# Independent Trader

`finance-analysis-trader` 是与 `finance-analysis-stream` 并列的常驻进程（Compose 服务 `trader`）。
复用主后端镜像、Redis、PostgreSQL 和现有服务端密钥；不新增交易所、队列、调度器或数据库迁移。

## 责任边界

- Streamer：CN/US/HK 与 Binance 公共行情、分钟 K、通用趋势/形态、Kronos 推理调度。继续订阅自选、持仓、日内策略观察池及未退出旧标的。
- Trader：日内期权模拟交易、Binance Demo 账户与已注册策略、Live 只读账户监控；策略通知及实际交易事实仍保存于原 DB 表。Live 不新增任何策略或写入路径。
- REST/SSE/WS API 只读已发布的行情/策略结果；管理员的 Demo 意图和开关仍写 DB，由 Trader 消费。

第一阶段不改变信号阈值、账户风险限制、5 秒期权循环或 5m 合约决策窗口，不提前重构秒级风控与历史对账。暂不引入 Pub/Sub，现有轮询 cadence 保持不变。

## 数据交换

股票 Redis 原闭合分钟 hash/index 增加 `rt:bars:1m:{symbol}:revision`；Streamer 在同一事务保存闭合数据和新 revision。
Trader 每5秒批量读取 revision 与最新报价，只重载变化标的；启动及每60秒全量校准，兼容旧 Redis 缓存、Redis 重启和过期。
每轮冻结同一份标的/基准/peer 快照再分发到原6线程策略池；无闭合数据或有效报价不得新进场，仍按原规则管理已有模拟仓位。
分钟数据读取失败不复用此前 Trader 的缓存。形成中的 K 不参与期权信号。合约策略继续直接读取原 Redis 合约分钟窗口和 DB 日线，
Demo 实际报价/标记价与成交来源保持原有执行层定义，不能用生产行情冒充 Demo 成交。

## 生命周期与部署

- 独立 Redis `lock:trader:leader` 保证一位 Trader；每10秒续约，失锁退出。Paper Trade 执行前再次确认此 lease。
- `rt:trader:heartbeat`（30秒过期）记录实例、模块状态、时间；Compose 健康检查验证当前容器 hostname 和 leader lease。
- 未配置 Demo/Live 密钥时对应模块不运行，不影响期权模拟和 Trader 健康；单个模块异常重试，与其他模块隔离。
- Trader 不依赖 Streamer 进程存活才能启动。行情缺失/过期时阻止基于生产行情的新信号，交易所已存在的保护单、账户同步和可执行的已有仓位管理不依赖浏览器。
- 首次升级必须停止旧 Streamer（旧版本同时执行交易）；标准 `bash deploy.sh` 先优雅停止旧 Trader/Streamer 再迁移和启动新服务。
  若旧版 Streamer 仍持有 leader 且未发布 `trading_owner=trader`，新 Trader 等待交接，不启动第二个交易执行器。
- 正常退出停止交易所 I/O、等待旧期权工作池完成；不确定交易请求仍依既有持久化意图核对，禁止盲目重试。
- 本地可用 `uv run finance-analysis-trader`，生产通过 Compose 独立启动。更改 Demo/Live 环境变量后重启 Trader。

验证：`uv run pytest tests/trader tests/market_stream tests/intraday_options tests/paper_trade tests/live_trade tests/test_deploy.py -q`。
