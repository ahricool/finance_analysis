# Kronos K 线预测

Finance Analysis 的 Streamer 调度分钟线预测，Celery Worker 在日线同步后调度日 K 预测。两者调用同一 macOS 原生 Python 3.12 宿主服务，将 OHLCV 批次交给 PyTorch MPS 推理。部署发布时模型默认为 **Kronos Small**。

## 数据、图表和验证

- 股票池是 Streamer 当前目标并集，包含各用户的自选、持仓及日内期权固定池。按标的去重，覆盖现有 CN/HK/US 采集目标。BTCUSDT 额外从 Binance Spot 请求原生 `1m`，独立于 15m/1h 策略开关。
- 以最后一根已确认、已收盘的原生分钟线作为预测基准。每个窗口使用最多 240 根、至少 15 根真实线，股票只用同一交易日。以 09:30 开盘为例，最早在 09:45 收到第 15 根确认线后进行推理。缺失分钟保留时间间隔。目标为当前分钟起的未来最多 10 根，按交易所日历截断午休、提前收市和收盘。BTC 用 UTC 连续分钟。股票重试可等待迟到的确认线，跨过第一个目标收盘的结果会被丢弃。
- 相同窗口长度和目标数的标的最多每批 10 个，采样一条路径。模型输出四价在发布前校验，独立解码的高低点修正到包住开收盘。Redis 保留最新预测和最多 16 次冻结快照，最后更新后 15 分钟过期。该缓存适合盘中观察与近端对照。
- 自选、持仓、日内期权和 BTC 使用同一个共享 `MarketKLineChart`。分钟和日 K 预测以同色的空心虚边蜡烛展示开高低收，预测通过独立覆盖物绘制，行情和技术指标继续读取原始交易数据。`1m` 图下方统一展示最后一个预测收盘价、最近误差与今日平均误差，可展开查看 OHLC 和各步长误差。
- 预测窗口到期后用同一分钟的已确认原生收盘价核对。缺数据时最多等两分钟，只累计有真线的样本。每个预测步长计一个样本，模型与沿用起点收盘价的基线使用相同样本。平均按样本数加权，按标的、模型、预测发出日期隔离，股票使用交易所时区，BTC 使用 UTC。待核对记录、最近结果及日累计保留三天，日累计从启用本版本后的实时预测开始。
- API `GET /api/v1/market-data/minute-forecast/{symbol}` 使用现有会话与股票分钟图的授权边界。BTC 为登录后的共享标的。读取只查 Redis，模型暂时离线时仍可使用原图。
- 运维可单独补存股票收盘试算。原分钟图在最后一根行情与试算基准一致、无实时预测时显示「收盘试算」，用于查看常规盘收盘后最多 10 个模型步长，已缓存的 5 步试算仍可读取。收盘试算不纳入实时误差统计。

## CN / US 日 K

- 日线同步完成写库和缺数重试后，为对应市场入队 `analysis.kronos_daily_forecast`。工作日增量、月度全量和手动日线同步均走同一路径，部分同步成功时使用已存当日闭合线。任务复用 `cn_daily_sync` / `us_daily_sync` 完整证券范围和原有前复权数据。
- 使用截至本次同步交易日的最近 15–240 根前复权日线，预测未来最多 10 个交易日。市场交易日历决定日期，日历边界只使用已知交易日。GPU 单槽在拥塞时给分钟推理留出重试窗口。
- PostgreSQL `daily_forecast_snapshot` 按市场事务替换，一只标的只有一行最新快照。接口出错或模型在批次中途更换权重时保留上一批。缺少同步日收盘线、历史不足或单只预测无效的证券在新批次中省略；当批次传输成功时，任务结果记录预测覆盖率。迁移为 `0094_daily_kronos_forecast`。
- 已鉴权的 `GET /api/v1/market-data/daily-bars/{symbol}` 在同一响应的 `forecast` 字段附带最新预测，要求实线范围含基准交易日。前端共享日 K 图用于个股详情、持仓和趋势研究，绘制实际日线之后的交易日预测，可展开查看预测开高低收。

## Apple Silicon 部署

正常发布仍用 `bash deploy.sh`。第一次安装时先同步生产 checkout，使宿主机先加载新版发布脚本，再执行正常发布：

```sh
cd ~/svr/finance_analysis
git pull --ff-only origin main
bash deploy.sh
```

Apple Silicon 主机需要 `uv` 和已登录的 macOS 用户会话。脚本在暂停 Beat 前校验并下载固定版本的源代码、tokenizer 和权重，建独立 Python 环境，用 `launchd` 用户代理启动 Small 并预热 MPS。默认仅监听 `127.0.0.1:18081`。容器通过 `host.docker.internal:18081` 调用。应用 SHA 镜像及依赖保持原有发布流程，恢复 Beat 前从新 Streamer 和 Worker 容器核对就绪状态、模型及发布版本。运行工件和推理日志位于 `.git/finance-deploy/kronos/`。

- `KRONOS_MODEL=base` 使用固定版本的公开 Base 权重，沿用相同协议。切换时在一次发布中同步宿主服务和容器配置。
- `KRONOS_MODEL=large` 需另行提供兼容的完整 `config.json` 与 `model.safetensors`，以 `KRONOS_LARGE_CHECKPOINT` 指向目录。默认注册表只自动下载 Small、Base 和共享 tokenizer。
- `KRONOS_HOST_PORT` 可改宿主机端口。已自行托管 MPS 时，在 Compose 环境填 `KRONOS_URL` 并设置匹配的 `KRONOS_MODEL`，宿主 `/healthz` 应报告 `1m` 和 `1d` 两个周期。独立开发默认关闭，生产发布可用 `DEPLOY_KRONOS_HOST=off` 取消自动接入。
- 用 `bash deploy.sh --status` 查看最近发布的 Kronos 版本。可在宿主机请求 `curl -fsS http://127.0.0.1:18081/healthz`，响应中的 `device` 应为 `mps`。启动失败时检查宿主日志，修复后从正常发布入口重试。
