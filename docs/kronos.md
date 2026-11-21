# Kronos 分钟线预测

Finance Analysis 的 Streamer 与宿主机 Kronos 是两套进程。Streamer 是唯一的行情和预测调度入口，macOS 原生 Python 3.12 进程只接收 OHLCV 批次并用 PyTorch MPS 推理。部署发布时模型默认为 **Kronos Small**。

## 数据、图表和验证

- 股票池是 Streamer 当前目标并集，包含各用户的自选、持仓及日内期权固定池。按标的去重，覆盖现有 CN/HK/US 采集目标。BTCUSDT 额外从 Binance Spot 请求原生 `1m`，独立于 15m/1h 策略开关。
- 以最后一根已确认、已收盘的原生分钟线作为预测基准。每个窗口使用最多 240 根、至少 30 根真实线，股票只用同一交易日，缺失分钟保留时间间隔。目标为当前分钟起的未来最多 10 根，按交易所日历截断午休、提前收市和收盘。BTC 用 UTC 连续分钟。股票重试可等待迟到的确认线，跨过第一个目标收盘的结果会被丢弃。
- 相同窗口长度和目标数的标的最多每批 10 个，采样一条路径。模型输出四价在发布前校验，独立解码的高低点修正到包住开收盘。Redis 保留最新预测和最多 16 次冻结快照，最后更新后 15 分钟过期。该缓存适合盘中观察与近端对照。
- 自选、持仓、日内期权和 BTC 使用同一个共享 `MarketKLineChart`。原图右侧蓝色虚线是预测收盘价，`1m` 图下方统一展示最后一个预测收盘价、最近误差与今日平均误差，可展开查看 OHLC 和各步长误差。预测通过独立覆盖物绘制，行情和技术指标继续读取原始交易数据。
- 预测窗口到期后用同一分钟的已确认原生收盘价核对。缺数据时最多等两分钟，只累计有真线的样本。每个预测步长计一个样本，模型与沿用起点收盘价的基线使用相同样本。平均按样本数加权，按标的、模型、预测发出日期隔离，股票使用交易所时区，BTC 使用 UTC。待核对记录、最近结果及日累计保留三天，日累计从启用本版本后的实时预测开始。
- API `GET /api/v1/market-data/minute-forecast/{symbol}` 使用现有会话与股票分钟图的授权边界。BTC 为登录后的共享标的。读取只查 Redis，模型暂时离线时仍可使用原图。
- 运维可单独补存股票收盘试算。原分钟图在最后一根行情与试算基准一致、无实时预测时显示「收盘试算」，用于查看常规盘收盘后最多 10 个模型步长，已缓存的 5 步试算仍可读取。收盘试算不纳入实时误差统计。

## Apple Silicon 部署

正常发布仍用 `bash deploy.sh`。第一次安装时先同步生产 checkout，使宿主机先加载新版发布脚本，再执行正常发布：

```sh
cd ~/svr/finance_analysis
git pull --ff-only origin main
bash deploy.sh
```

Apple Silicon 主机需要 `uv` 和已登录的 macOS 用户会话。脚本在暂停 Beat 前校验并下载固定版本的源代码、tokenizer 和权重，建独立 Python 环境，用 `launchd` 用户代理启动 Small 并预热 MPS。默认仅监听 `127.0.0.1:18081`。容器通过 `host.docker.internal:18081` 调用。应用 SHA 镜像及依赖保持原有发布流程，恢复 Beat 前从新 Streamer 容器再核对就绪状态、模型及发布版本。运行工件和推理日志位于 `.git/finance-deploy/kronos/`。

- `KRONOS_MODEL=base` 使用固定版本的公开 Base 权重，沿用相同协议。切换时在一次发布中同步宿主服务和容器配置。
- `KRONOS_MODEL=large` 需另行提供兼容的完整 `config.json` 与 `model.safetensors`，以 `KRONOS_LARGE_CHECKPOINT` 指向目录。默认注册表只自动下载 Small、Base 和共享 tokenizer。
- `KRONOS_HOST_PORT` 可改宿主机端口。已自行托管 MPS 时，在 Compose 环境填 `KRONOS_URL` 并设置匹配的 `KRONOS_MODEL`。独立开发默认关闭，生产发布可用 `DEPLOY_KRONOS_HOST=off` 取消自动接入。
- 用 `bash deploy.sh --status` 查看最近发布的 Kronos 版本。可在宿主机请求 `curl -fsS http://127.0.0.1:18081/healthz`，响应中的 `device` 应为 `mps`。启动失败时检查宿主日志，修复后从正常发布入口重试。
