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
| 明确 quota exhausted、HTTP 402 余额不足、认证失败、模型不可用、CLI 未安装 | 不重试，切下一渠道 |
| 临时限流、网络连接失败、服务端 5xx、CLI 非零退出 | 重试三次后切换 |
| 空文本、输出解析/业务 ValueError 校验失败 | 重试三次后切换 |
| 单次 timeout（已确认 CLI 清理） | 直接切换 |
| 输入非法、程序异常、CLI 清理未确认 | 终止整条调用，不切换 |

LiteLLM `num_retries=0`，避免 SDK 再叠加重试。API Retry-After 数字秒有效时取其与退避值的较大者；
超出本渠道预算直接切换，不把秒级限流与长期额度耗尽混淆。AGY 原生日志的明确限流/额度错误会中断本次
CLI，交还 LLMClient 决定重试或切换。无法识别的 CLI 内部重试仍受单次 deadline 限制。

`LLM_TIMEOUT` / request.timeout 仍是**整条调用**总预算，包含 SSH、模型、清理和退避；
默认保留 180 秒，链模式生产建议 600 秒。`LLM_ATTEMPT_TIMEOUT=180` 限制链模式每次 attempt。
进入每个渠道时，给剩余已配置渠道分别预留 `min(attempt_timeout, 剩余总预算/剩余渠道数)` 秒；
当前渠道重试只能使用预留之外的时间。预算不足可以少于三次重试。90秒总预算且三个渠道均超时时，
依次各得30秒；600秒总预算时首次三个 attempt 各最多180秒。

财报搜索一次只处理一个公司/财报事件；搜索输入不携带第二阶段价格预测所需的完整行情。
若精简输入后仍频繁触及单次180秒上限，可统一配置 `LLM_ATTEMPT_TIMEOUT=300` 与 `LLM_TIMEOUT=900` 后观察。
只增加总预算不会突破单次 attempt 上限；两项均是全局配置，会影响其他 LLM 任务。
`quota_exhausted` / `insufficient_credits` 需要恢复渠道额度，增加时间预算不能解决。

所有业务调用统一使用全局 `LLM_TIMEOUT`，不再在美股收盘复盘、Trade Engine 或 A 股收盘前复核中覆盖。
Signal Center 每个 bucket/final、Trade Engine 每个用户的市场分析各有独立的全局调用预算。
这些 LLM 任务不设置固定 Celery soft/hard time limit，A 股收盘前复核也不再以任务剩余时间压缩 LLM。
多用户/多桶任务总耗时可以超过单次调用预算；防重入锁和已完成结果恢复机制保持不变。
传输层仍使用内部剩余 timeout，以保证重试和渠道切换共享同一个 deadline。

AGY / Codex CLI attempts may execute concurrently.
Each attempt is independently bounded by LLM_ATTEMPT_TIMEOUT and the shared request deadline.
上述 attempt 上限用于 fallback chain 模式；兼容单渠道模式仍使用请求剩余预算。
`_complete_cli()` 直接把当前 attempt deadline 的剩余时间传给 SSH CLI，无全局互斥。
API 调用同样可并发；SSH 超时、远端进程清理、重试和渠道切换机制保持不变。

Trade Engine 定时任务使用独立的 CN / US task-level mutex，按市场防止整轮多用户任务跨周期重叠。
同市场已有任务执行时，新一轮直接通过 `TaskSkipped` 记录 skipped，不阻塞等待；CN / US 互不阻塞。
原有 uid + market advisory lock 继续保护手工入口与用户决策；不设置旧 Celery soft/hard time limit。

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
- JSONL 的 `diagnostics` 保存总预算、当前剩余预算、attempt 预算（毫秒），以及实际到达阶段的
  `ssh_ms`、`cli_execution_ms` 或 `api_ms`。失败也保留已采集数据。
  每个 provider attempt 独立创建 diagnostics，skipped provider 使用空 diagnostics。
  `stdout_received` / `stdout_bytes` 只表示 CLI 协议输出，不代表已有最终答案；不保存部分输出或 stderr。
  HTTP 402 分类为 `insufficient_credits`，不重试，不记录服务商原始错误。
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

## 财报专用搜索

`earnings_outlook/`是财报信息研究的明确例外，不给其他业务增加自动搜索。
`earnings_research`设置`web_search=True, prefer_search=True`：只对此请求将已配置且声明支持搜索的渠道优先，
无执行证据时尝试现有链中后续渠道；仍共享统一deadline、重试、日志和usage。
普通请求的AGY→Codex→API fallback顺序不变。`earnings_outlook`阶段不搜索。

| 渠道 | 支持与执行证据 |
| --- | --- |
| Codex CLI | `exec --json ... -c 'web_search="live"'`；仅完成的`web_search` item确认执行。无工具事件为unverified。 |
| API / LiteLLM Chat Completions | `LLM_API_SEARCH_MODE=chat_completions`显式声明模型及网关支持，发送web_search_options；响应message.annotations中的url_citation保存为传输证据。只有开关没有citation是unverified。默认unavailable，不盲发不受支持参数。 |
| AGY CLI | 本次已安装1.2.3的help没有可核验的搜索开关，stream-json结果也没有本实现能验证的搜索契约，标unavailable；不根据response内来源列表宣称执行。 |

本地检查Codex 0.159.3支持`exec --json`与`-c`覆盖；没有执行付费模型请求。
SSH Host实际版本、账号/工作区权限、自定义模型提供商仍可能限制搜索，部署时需核对Host版本。
OpenAI官方说明Codex搜索模式及JSON事件：[Web search](https://learn.chatgpt.com/docs/web-search)。
API参数、模型限制和citation字段：[OpenAI web search](https://developers.openai.com/api/docs/guides/tools-web-search)。
当前文档的Chat Completions示例为gpt-5-search-api；普通模型/兼容网关不因接受参数就具有搜索能力。
未为用户更换LLM模型或新增搜索供应商。

`LLMResult.search_evidence`保存`requested`、`configured_support`、`status`和可获取的citations/tool_events，
同时进入统一审计。confirmed只证明工具执行，不能证明每个模型陈述都真实。来源/发布日期仍需按业务cutoff过滤。
无执行证据的模型来源不作新增可信资料；基于已有结构化数据继续受限分析，不伪造URL或实时数字。
