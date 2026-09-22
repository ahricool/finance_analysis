# LLM 调用层

业务只提交 `LLMRequest(prompt, system_prompt, ...)`，读取 `LLMResult.text`。
`LLM_FALLBACK_CHAIN=agy,codex,api` 显式启用固定顺序：

```text
业务 → LLMClient → AGY → Codex → API（LiteLLM）
                   成功且通过业务 validator 即返回
```

留空时兼容原 `LLM_BACKEND=api|cli` / `LLM_CLI_ENGINE=agy|codex` 单渠道配置。
所有渠道使用相同 request、system prompt 与 validator；调用方负责冻结业务输入。
没有并行竞争、回头循环或自动改变候选/模型参数。缺配置渠道记录 skipped，不计入实际调用次数。

每渠道首次调用后最多重试三次（`LLM_MAX_RETRIES=3`），退避 **2、4、8 秒**。规则：

| 错误 | 行为 |
| --- | --- |
| 明确 quota exhausted、认证失败、模型不可用、CLI 未安装 | 不重试，切下一渠道 |
| 临时限流、网络连接失败、服务端 5xx、CLI 非零退出 | 重试三次后切换 |
| 空文本、输出解析/业务 ValueError 校验失败 | 重试三次后切换 |
| 单次 timeout（已确认 CLI 清理） | 直接切换 |
| 输入非法、程序异常、锁等待耗尽、CLI 清理未确认 | 终止整条调用，不切换 |

LiteLLM `num_retries=0`，避免 SDK 再叠加重试。API Retry-After 数字秒有效时取其与退避值的较大者；
超出本渠道预算直接切换，不把秒级限流与长期额度耗尽混淆。AGY 原生日志的明确限流/额度错误会中断本次
CLI，交还 LLMClient 决定重试或切换。无法识别的 CLI 内部重试仍受单次 deadline 限制。

`LLM_TIMEOUT` / request.timeout 仍是**整条调用**总预算，包含锁等待、SSH、模型、清理和退避；
默认保留 180 秒，链模式生产建议 600 秒。`LLM_ATTEMPT_TIMEOUT=180` 限制链模式每次 attempt。
进入每个渠道时，给剩余已配置渠道分别预留 `min(attempt_timeout, 剩余总预算/剩余渠道数)` 秒；
当前渠道重试只能使用预留之外的时间。预算不足可以少于三次重试。90秒总预算且三个渠道均超时时，
依次各得30秒；600秒总预算时首次三个 attempt 各最多180秒。

Signal Center 没有独立 Celery time limit，每个 bucket/final 各走上述预算；已完成的桶仍可恢复。
Trade Engine 有540秒任务 soft limit，保留每用户 LLM 最多180秒（配置更短则从短），避免启用600秒链
直接侵占整个任务。多用户任务原有整体时限仍生效。盘前复核已有 request.timeout 剩余任务预算继续有效。

所有 CLI 请求在 `LLMClient._complete_cli()` 中使用同一把 PostgreSQL session-level advisory lock
（固定 bigint key `0x46415F4C4C4D434C`），跨 AGY/Codex、用户与进程串行执行。
每次 attempt 独立获取连接，以 `pg_try_advisory_lock()` 每 1 秒轮询；等待计入原 deadline，
获取锁后仅把剩余 timeout 传给 SSH CLI。获取和 finally 解锁使用同一个连接，期间采用 AUTOCOMMIT，
不保持空闲事务；锁 SQL 失败会 invalidate 连接，避免持锁连接回到连接池。重试前先释放锁。
所有实例必须连接同一个 PostgreSQL 数据库；API backend 不获取此锁。

普通分析保留原有交易规则、报告解析、完整性占位补全和通知路径。报告完整性不再发起额外 LLM 请求。
收盘前复核只输入确定性行情、板块、持仓和已有复核上下文，直接生成 decision；没有新闻研究或新闻覆盖门槛。
行情完整性门槛、持仓比例约束和模型失败后的保守确定性建议继续保留。

## 配置

完整字段见 `.env.example`。

- 通用：`LLM_FALLBACK_CHAIN`、`LLM_BACKEND`、`LLM_MAX_RETRIES`、`LLM_TIMEOUT`、`LLM_ATTEMPT_TIMEOUT`、`LLM_LOG_DIR`。
- 链模式模型：`LLM_AGY_MODEL/EFFORT`、`LLM_CODEX_MODEL/EFFORT`。互不共享；旧 CLI_MODEL/EFFORT 仅单渠道使用。
- Host 可执行路径：`LLM_CLI_AGY_PATH`、`LLM_CLI_CODEX_PATH`、`LLM_CLI_PYTHON_PATH`（Python 3.9+ 标准库）。
- API：`LLM_MODEL`、`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_TEMPERATURE`。
- CLI：`LLM_CLI_ENGINE`、`LLM_CLI_SSH_HOST`、`LLM_CLI_SSH_PORT`、
  `LLM_CLI_SSH_USERNAME`、`LLM_CLI_SSH_PASSWORD`、`LLM_CLI_REMOTE_WORKDIR`、
  `LLM_CLI_MODEL`、`LLM_CLI_EFFORT`。

API model 使用 LiteLLM 的 `provider/model` 命名，如 `openai/<model>`；默认 base URL 为
`https://openrouter.ai/api/v1`。API key 必须配置。Kimi K2.6 默认 thinking 模式所需的固定 temperature=1
在 `api.py` 中单独处理，无模型部署表或 protocol detection。

单渠道 CLI 下 API model、key、temperature 不参与调用；链模式 API fallback 时使用这些配置。CLI 的 model/effort 留空时采用 Host CLI 默认值；
CLI 不提供通用 max_tokens/temperature 参数，因此这两个 request 字段仅对 API 生效。
AGY effort 支持 low/medium/high；Codex 也支持 xhigh，模型是否接受由 Host CLI 判断。

## Docker → Host

1. Host 安装并登录 AGY 或 Codex。用专用 OS 用户提供 SSH 密码登录。
2. AGY 和 Codex 默认绝对路径 `/usr/local/bin/agy` 和 `/usr/local/bin/codex`，可通过上述 PATH 配置覆盖，
   确保所选引擎的路径为 SSH 用户可执行的程序或符号链接，不依赖非交互 shell 的 PATH。
   npm/nvm 安装的 Codex 脚本依赖 node；建议配置其安装包内原生 bin/codex 的绝对路径，升级后核对路径。
3. Docker Desktop 使用 `host.docker.internal:22`；Linux 如需此名称，可在本地 compose override
   为调用 LLM 的 server/worker 增加 `extra_hosts: ["host.docker.internal:host-gateway"]`。
4. 在 `.env` 配置用户名和密码。容器不执行 CLI 登录，不挂载 CLI binary 或 Docker socket。

当前部署固定为可信的本机 Docker → Host SSH，使用 `paramiko.AutoAddPolicy()` 自动接受 Host Key，
无需提前配置 `known_hosts`。

supervisor 创建并进入 `LLM_CLI_REMOTE_WORKDIR`（默认 `/tmp/finance-analysis-llm`）。
不要配置为应用仓库。目录和可选 model/effort 均做 shell quoting，prompt 不进入 SSH command 字符串。
system prompt 与 user prompt 在 backend 内以 `\n\n---\n\n` 拼接后，通过 SSH channel stdin 传输并关闭写端。

### AGY（已实现）

```sh
umask 077; mkdir -p /tmp/finance-analysis-llm && cd /tmp/finance-analysis-llm && exec /usr/local/bin/agy --input-format stream-json --output-format stream-json --sandbox --disable-slash-commands --print-timeout 180s
```

以上为 supervisor 内实际子命令，外层通过 SSH `python -c` 执行仓库 `cli_runner.py` 源码，不要求 Host 安装项目。
实际 print-timeout 使用连接后剩余预算；可选追加 `--model`、`--effort`。
AGY 另加本请求临时 `--log-file`：目录0700、文件随请求删除；只匹配 Run attempt 失败行的白名单
错误与模型名称，不扫描全局旧日志，不把启动阶段常见的未登录 cache 警告误判为请求认证失败。
stdin 发送一条 `{"event":"user","message":{"content":"完整 prompt"}}` JSON 行后关闭写端。
读取唯一 result event 中的 JSON envelope，只接受 SUCCESS 和非空 response；token 来自 CLI usage。
这种输入不受 shell 命令参数长度限制。
参数已按本机 `agy --help` 和 [AGY Headless 官方文档](https://www.agy.dev/docs/cli/headless/) 核对（2026-09-23）。

### Codex（已实现）

```sh
umask 077; mkdir -p /tmp/finance-analysis-llm && cd /tmp/finance-analysis-llm && exec /usr/local/bin/codex exec --json --sandbox read-only --skip-git-repo-check --ephemeral --ignore-user-config --ignore-rules -c approval_policy=never -
```

可选追加 `--model` 和 `-c model_reasoning_effort='"high"'`（在结尾 `-` 之前）。
独立解析 JSONL：取最后一个 `item.completed` assistant message，要求 `turn.completed`，读取其 usage；
error / turn.failed、格式错误或缺少最终文本都失败。缓存输入已包含在 input_tokens 中，不重复计数。
参数已按本机 `codex exec --help` 和 [Codex 非交互官方文档](https://learn.chatgpt.com/docs/non-interactive-mode) 核对。

两个 CLI 均不启用跳过 sandbox/权限的危险选项。SSH 无 PTY；supervisor 同时读取 stdout/stderr。
两个 CLI 均由同一个 stdlib Python 请求级 supervisor 启动独立进程组；SSH stdin 直接传给子进程。
supervisor 为退出清理预留最多2秒，TERM 后必要时 KILL 并确认进程组消失，才返回安全 receipt；
失败也必须确认清理后才能释放本次调用并 fallback。SSH 断开时处理 HUP；无法收到清理 receipt 则终止调用链，
避免盲目启动下一 CLI。仅清理本请求进程组，不使用全局 pkill；主动脱离进程组的 daemon 不在此保证范围内。
CLI sandbox 和独立工作目录
不等于完整 OS 文件隔离；Host 的 CLI 登录态、模型默认值和全局插件由 Host 管理。

## 审计与统计

- `DATA_DIR/logs/llm/YYYY-MM-DD.log`：UTC 按日 JSONL，可用 `LLM_LOG_DIR` 覆盖。
- 每个真实 attempt 一条记录，共用 request_id，attempt 从 1 开始。包含 prompt/system_prompt、
  response、实际 backend/engine/model、usage、耗时、状态和安全错误分类。fallback 的 attempt 连续编号。
  配置缺失仅写 skipped 审计行，不写 llm_usage；完整失败消息保留安全的渠道/错误链。
  Signal Center screening 与最终结果保存实际 backend（cli/agy、cli/codex 或 api）和模型；
  AGY 默认模型从本次原生日志取值，无法获知的 CLI 模型仍标记 unreported，绝不猜测。
- 文件使用进程锁防止 Celery 并发写交错；新文件权限 0600。prompt/response 会保存，应按业务数据管理。
- 不记录配置、API key、Authorization、SSH 密码、CLI stderr 或 vendor traceback。
  已配置密钥即使出现在 prompt/response 中也会替换。
- `llm_usage` 每个 attempt 一行，保存 uid、call_type、backend、engine、model、status、
  input/output/total tokens、duration_ms、error、called_at；未知 tokens 为 0，未知 CLI model 为 NULL。
- usage API 保持原 summary 格式；calls 现在包含失败 attempt。指定 uid 时只统计本人数据。
  日志/统计存储失败只警告，不触发新的模型调用。

## Migration 0052

删除旧聊天表及所有会话数据，移除 usage 的 stock_code；token 列重命名为 input_tokens/output_tokens。
旧 usage 行保留并标记 backend=api、status=success、duration_ms=0（旧记录没有这些元数据）。
新增 engine/error 可空，model 允许 NULL。

downgrade 恢复旧表结构和 token 列名，**无法恢复删除的聊天内容或 stock_code**。
空库仍通过当前 ORM metadata bootstrap；已有库执行迁移。部署前应备份需要留存的旧会话数据。

## 启用与验收

合入后在生产 `.env` 设置（key/模型继续使用已有配置，不写入仓库）：

```dotenv
LLM_FALLBACK_CHAIN=agy,codex,api
LLM_TIMEOUT=600
LLM_ATTEMPT_TIMEOUT=180
LLM_MAX_RETRIES=3
```

先确认 SSH 用户可运行两种 CLI、Host Python 路径及 API 配置；部署使用现有 `bash deploy.sh`。
回滚路由只需清空 LLM_FALLBACK_CHAIN、恢复 LLM_TIMEOUT=180 并重建相关容器。
本变更不新增 DB schema。离线验收：

```bash
uv run pytest tests/test_llm_client.py tests/test_llm_fallback.py tests/test_llm_cli_runner.py tests/signal_center -q
```
