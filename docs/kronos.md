# Kronos K 线预测

Finance Analysis 的 Streamer 调度分钟线预测，Celery Worker 在日线同步后调度日 K 预测。两者调用同一 macOS 原生 Python 3.12 宿主服务，将 OHLCV 批次交给 PyTorch MPS 推理。部署发布时模型默认为 **Kronos Small**。

## 数据、图表和验证

- 分钟预测默认全部关闭。个股详情「行业」页可由管理员设置全站共享的单标的开关（PostgreSQL `minute_forecast_preference`，迁移 `0100_minute_forecast_optin`；无记录即关闭）。Streamer 每轮约 3 秒刷新开关，仅对已开启且有现有原生分钟线的 CN/HK/US 订阅标的预测；不扩大行情采集范围，无分钟数据直接跳过。关闭后不再调度且 API 不返回预测。
- 股票实时预测从开盘以来的全部已确认原生分钟线出发，预测当前分钟起最多 60 个交易分钟，不跨当日实际收盘；提前收市按交易所日历缩短。午休跳过，下午开盘可直接以上午最后一根确认线为基准。开盘积满至少 15 根才开始，缺失或未确认的历史分钟等行情补齐后再生成本轮。
- 相同窗口长度和目标数的标的最多每批 10 个，采样一条路径。长分钟预测复用自回归步骤的注意力 KV 缓存，单台 MPS 服务同时容纳一个批次。发布须在第一个目标分钟收盘前完成，超时批次丢弃，下一分钟优先处理等待时间较久的标的。模型输出四价在发布前校验，高低点修正到包住开收盘。Redis 最新股票预测至少保留到当日收盘，短预测及最多 16 次近期对照按 15 分钟 TTL 保存。
- 自选、持仓、日内期权使用同一个共享 `MarketKLineChart`。分钟和日 K 预测以同色的空心实边蜡烛展示开高低收，预测通过独立覆盖物绘制，行情和技术指标继续读取原始交易数据。`1m` 图下方统一展示最后一个预测收盘价、最近误差与今日平均误差，可展开查看 OHLC 和各步长误差。
- 逐步误差继续核对每轮前 10 根，等最后一个核对目标到期后用同一分钟的已确认原生收盘价结算。缺数据时最多等两分钟，只累计有真线的样本。每步计一个样本，模型与沿用起点收盘价的基线使用相同样本。平均按样本数加权，按标的、模型、预测发出日期隔离，股票使用交易所时区。待核对记录、最近结果及日累计保留三天。
- API `GET /api/v1/market-data/minute-forecast/{symbol}` 使用现有会话与股票分钟图的授权边界，先检查共享开关，再只读 Redis 预测缓存。设置通过 `GET/PUT /api/v1/market-data/minute-forecast/{symbol}/preference` 读取/修改（PUT 仅管理员）。模型暂时离线时仍可使用原图。日 K 预测由同步任务触发，不受开关影响。
- 运维可单独补存股票收盘试算。原分钟图在最后一根行情与试算基准一致、无实时预测时显示「收盘试算」，用于查看常规盘收盘后最多 10 个模型步长，已缓存的 5 步试算仍可读取。收盘试算不纳入实时误差统计。

## CN / US 日 K

- 日线同步完成写库和缺数重试后，为对应市场入队 `analysis.kronos_daily_forecast`。工作日增量、月度全量和手动日线同步均走同一路径，部分同步成功时使用已存当日闭合线。任务复用 `cn_daily_sync` / `us_daily_sync` 完整证券范围和原有前复权数据。
- 使用截至本次同步交易日的最近 15–240 根前复权日线，预测未来最多 10 个交易日。市场交易日历决定日期，日历边界只使用已知交易日。GPU 单槽在拥塞时给分钟推理留出重试窗口。
- PostgreSQL `daily_forecast_snapshot` 按市场事务替换，一只标的只有一行最新快照。接口出错或模型在批次中途更换权重时保留上一批。缺少同步日收盘线、历史不足或单只预测无效的证券在新批次中省略；当批次传输成功时，任务结果记录预测覆盖率。迁移为 `0094_daily_kronos_forecast`。
- 最新批次替换前，使用已确认的下一交易日收盘价核对上一批的第一步。预测须在目标日开市前生成，按 DB 中最新前复权基准收盘价调整比较口径。同一标的同一目标日只累计一次，模型和权重切换后重新统计。PostgreSQL `daily_forecast_accuracy` 保存每只标的最近一次误差、累计样本数及误差总和，迁移为 `0095_daily_forecast_accuracy`。
- 已鉴权的 `GET /api/v1/market-data/daily-bars/{symbol}` 在 `forecast` 字段附带最新预测及误差统计，日线范围须包含基准交易日。预测蜡烛按交易日连续排列，横轴显示实际目标日期。日线与分钟线共用 Kronos 面板，可展开查看预测开高低收和误差。

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
- `KRONOS_HOST_PORT` 可改宿主机端口。已自行托管 MPS 时，在 Compose 环境填 `KRONOS_URL` 并设置匹配的 `KRONOS_MODEL`，宿主 `/healthz` 应报告 `1m` 和 `1d` 两个周期。60 根分钟预测兼容现有宿主协议。独立开发默认关闭，生产发布可用 `DEPLOY_KRONOS_HOST=off` 取消自动接入。
- 用 `bash deploy.sh --status` 查看最近发布的 Kronos 版本。可在宿主机请求 `curl -fsS http://127.0.0.1:18081/healthz`，响应中的 `device` 应为 `mps`。启动失败时检查宿主日志，修复后从正常发布入口重试。
- 更换本机 LaunchAgent 时，部署在注册新版前等待 `launchd` 移除旧服务。对服务尚未注册时的短暂 `bootstrap` I/O 错误做限时重试。若新版启动失败，恢复旧启动项前同样等待卸载完成。这些操作在暂停 Beat 前执行。
