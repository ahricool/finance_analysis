# LLM 调用层

业务只提交 `LLMRequest(prompt, system_prompt, ...)`，读取 `LLMResult.text`。
`LLMClient` 根据 `LLM_BACKEND` 选择一个 backend：

```text
业务 → LLMClient ┬ api → LiteLLM → 配置的 API（如 OpenRouter）
                └ cli → Paramiko SSH → Host AGY / Codex
```

没有跨 backend 或模型 fallback。`LLM_MAX_RETRIES` 默认 3，允许 0–3，重试前分别退避 2、4、8 秒；LiteLLM 的
`num_retries=0`。等待和 JSON 校验失败也使用同一个总时间与重试预算。`LLM_TIMEOUT`（默认 180 秒）
是含 retry 的总时间预算，业务可以通过 request.timeout 覆盖。

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

- 通用：`LLM_BACKEND`、`LLM_MAX_RETRIES`、`LLM_TIMEOUT`、`LLM_LOG_DIR`。
- API：`LLM_MODEL`、`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_TEMPERATURE`。
- CLI：`LLM_CLI_ENGINE`、`LLM_CLI_SSH_HOST`、`LLM_CLI_SSH_PORT`、
  `LLM_CLI_SSH_USERNAME`、`LLM_CLI_SSH_PASSWORD`、`LLM_CLI_REMOTE_WORKDIR`、
  `LLM_CLI_MODEL`、`LLM_CLI_EFFORT`。

API model 使用 LiteLLM 的 `provider/model` 命名，如 `openai/<model>`；默认 base URL 为
`https://openrouter.ai/api/v1`。API key 必须配置。Kimi K2.6 默认 thinking 模式所需的固定 temperature=1
在 `api.py` 中单独处理，无模型部署表或 protocol detection。

CLI 下 API model、key、temperature 不参与调用。CLI 的 model/effort 留空时采用 Host CLI 默认值；
CLI 不提供通用 max_tokens/temperature 参数，因此这两个 request 字段仅对 API 生效。
AGY effort 支持 low/medium/high；Codex 也支持 xhigh，模型是否接受由 Host CLI 判断。

## Docker → Host

1. Host 安装并登录 AGY 或 Codex。用专用 OS 用户提供 SSH 密码登录。
2. AGY 和 Codex 分别固定使用绝对路径 `/usr/local/bin/agy` 和 `/usr/local/bin/codex`，
   确保所选引擎的路径为 SSH 用户可执行的程序或符号链接，不依赖非交互 shell 的 PATH。
3. Docker Desktop 使用 `host.docker.internal:22`；Linux 如需此名称，可在本地 compose override
   为调用 LLM 的 server/worker 增加 `extra_hosts: ["host.docker.internal:host-gateway"]`。
4. 在 `.env` 配置用户名和密码。容器不执行 CLI 登录，不挂载 CLI binary 或 Docker socket。

当前部署固定为可信的本机 Docker → Host SSH，使用 `paramiko.AutoAddPolicy()` 自动接受 Host Key，
无需提前配置 `known_hosts`。

远程命令先创建并进入 `LLM_CLI_REMOTE_WORKDIR`（默认 `/tmp/finance-analysis-llm`）。
不要配置为应用仓库。目录和可选 model/effort 均做 shell quoting，prompt 不进入 SSH command 字符串。
system prompt 与 user prompt 在 backend 内以 `\n\n---\n\n` 拼接后，通过 SSH channel stdin 传输并关闭写端。

### AGY（已实现）

```sh
umask 077; mkdir -p /tmp/finance-analysis-llm && cd /tmp/finance-analysis-llm && exec /usr/local/bin/agy --input-format stream-json --output-format stream-json --sandbox --disable-slash-commands --print-timeout 180s
```

实际 print-timeout 使用连接后剩余预算；可选追加 `--model`、`--effort`。
stdin 发送一条 `{"event":"user","message":{"content":"完整 prompt"}}` JSON 行后关闭写端。
读取唯一 result event 中的 JSON envelope，只接受 SUCCESS 和非空 response；token 来自 CLI usage。
这种输入不受 shell 命令参数长度限制。
参数已按本机 `agy --help` 和 [AGY Headless 官方文档](https://www.agy.dev/docs/cli/headless/) 核对（2026-09-15）。

### Codex（已实现）

```sh
umask 077; mkdir -p /tmp/finance-analysis-llm && cd /tmp/finance-analysis-llm && exec /usr/local/bin/codex exec --json --sandbox read-only --skip-git-repo-check --ephemeral --ignore-user-config --ignore-rules -c approval_policy=never -
```

可选追加 `--model` 和 `-c model_reasoning_effort='"high"'`（在结尾 `-` 之前）。
独立解析 JSONL：取最后一个 `item.completed` assistant message，要求 `turn.completed`，读取其 usage；
error / turn.failed、格式错误或缺少最终文本都失败。缓存输入已包含在 input_tokens 中，不重复计数。
参数已按本机 `codex exec --help` 和 [Codex 非交互官方文档](https://developers.openai.com/codex/noninteractive) 核对。

两个 CLI 均不启用跳过 sandbox/权限的危险选项。SSH 无 PTY，stdout/stderr 同时读取。
超时关闭 channel 和连接；AGY 另有原生 print-timeout。Codex 无对应超时参数，断开 SSH
不保证 Host 上所有派生进程都被杀死，Host 仍需管理其 CLI 进程。CLI sandbox 和独立工作目录
不等于完整 OS 文件隔离；Host 的 CLI 登录态、模型默认值和全局插件由 Host 管理。

## 审计与统计

- `DATA_DIR/logs/llm/YYYY-MM-DD.log`：UTC 按日 JSONL，可用 `LLM_LOG_DIR` 覆盖。
- 每个真实 attempt 一条记录，共用 request_id，attempt 从 1 开始。包含 prompt/system_prompt、
  response、backend/engine/model、usage、耗时、状态和安全错误分类。
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
