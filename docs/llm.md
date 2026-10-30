# LLM 调用层

业务统一调用 `LLMClient.complete_text(LLMRequest(...))`。渠道固定为 **Codex → API（LiteLLM）**，
成功且通过业务 validator 即返回；渠道未配置时记录 skipped，继续下一渠道。
没有单渠道路由开关、并行竞争或回头循环。不同请求可以并发执行。

## 时间与重试

`LLM_ATTEMPT_TIMEOUT=300`：每次尝试最多300秒，包含 SSH 连接、CLI执行与退出清理。
不再设置整条调用总预算，也不为下一渠道预留时间。每次重试、切换到API都会取得独立的300秒预算。
`LLMRequest.timeout` 仅为内部传输剩余时间，业务不能用它覆盖调用策略。

每渠道首次调用后最多重试三次（`LLM_MAX_RETRIES=3`），退避2、4、8秒。

| 错误 | 行为 |
| --- | --- |
| 单次超时、额度耗尽、HTTP 402余额不足、认证失败、模型不可用、CLI未安装 | 直接切下一渠道 |
| 临时限流、网络连接失败、5xx、CLI非零退出、空响应或业务校验ValueError | 最多重试三次后切换 |
| 非法请求、程序错误、远端进程清理未确认 | 立即终止整条调用 |

API SDK `num_retries=0`，重试只由LLMClient管理。数字Retry-After与退避取较大值，
超过单次上限的Retry-After不在worker内长时间等待，改切下一渠道。
LLM任务没有固定Celery软/硬时限；多事件、多桶和重试会使整任务超过10分钟，单次尝试上限不等于任务上限。

## 配置

- 通用：`LLM_ATTEMPT_TIMEOUT`、`LLM_MAX_RETRIES`、`LLM_LOG_DIR`。
- Codex：`LLM_CODEX_MODEL`、`LLM_CODEX_EFFORT`（low/medium/high/xhigh）；留空使用Host默认模型。
- Host：`LLM_CLI_CODEX_PATH`、`LLM_CLI_PYTHON_PATH`、`LLM_CLI_SSH_HOST/PORT/USERNAME/PASSWORD`、
  `LLM_CLI_REMOTE_WORKDIR`。Codex及Python使用绝对路径，Python仅需要标准库。
- API：`LLM_MODEL`、`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_API_EFFORT`、`LLM_API_SEARCH_MODE`。
  默认地址为 OpenAI 官方 `https://api.openai.com/v1`，其他兼容服务仍可覆盖地址。
  例如 `LLM_MODEL=openai/gpt-6.1-sol`、`LLM_API_EFFORT=medium`；effort 留空不发送，
  支持 none/minimal/low/medium/high/xhigh/max，具体取值须由模型支持。
  不配置或发送 temperature、max_tokens/max_completion_tokens/max_output_tokens，使用 LiteLLM / 模型默认行为。
  旧 `LLM_TEMPERATURE` 等采样/输出额度环境变量不再读取，业务 request 也不保留这些参数。

生产升级时将现有 `LLM_ATTEMPT_TIMEOUT` 更新为300，移除旧总预算、路由及单渠道模型配置；
这些旧变量不再被读取。凭据继续使用现有私有环境配置，不写入仓库。本改动不需要数据库迁移。
按 `docs/deployment.md` 使用生产部署入口，不直接替换正在运行的worker。

## SSH与清理

Host安装并登录Codex，容器通过SSH密码认证运行专用目录下的CLI。Prompt仅经stdin传入，不进入shell参数。
实际命令由 `remote_cli.py` 构建，使用 `exec --json --sandbox read-only --skip-git-repo-check --ephemeral`
及独立配置，不启用绕过sandbox的选项。

远端标准库supervisor启动独立进程组，同时读取stdout/stderr；为清理预留最多2秒，
先TERM、必要时KILL，确认进程组消失后返回安全回执。SSH断开时处理HUP。
清理未确认时停止调用链，避免旧进程仍运行时启动下一渠道。仅清理本次进程组，不使用全局pkill；
主动脱离进程组的daemon不在保证范围内。工作目录与sandbox不代替OS权限隔离。

Codex JSONL要求最终 `turn.completed`，取最后一条agent_message，读取usage。
收到部分输出不代表完成，也不会重置超时。错误事件或不完整输出不得当作成功报告。

## 耗时报告与审计

每次逻辑请求记录request_id、业务call_type、每次尝试的渠道/序号/耗时/结果、累计退避等待和总耗时。
总耗时包含重试、审计与切换开销；并发请求的耗时不能直接相加作为任务耗时。
任务中心结果的 `llm_timings` 保留全部明细，包括失败请求；独立于业务摘要截断。
任务详情显示可读的耗时列表。最终站内消息与推送报告附加耗时说明，个股报告保存自己的调用明细，
历史重新渲染也能展示。报告生成时只列已结束的调用，不猜测尚未完成的耗时。
线程池复制请求上下文，任务结束后释放collector，不串入其他任务。

- `DATA_DIR/logs/llm/YYYY-MM-DD.log`：UTC按日JSONL，`LLM_LOG_DIR`可覆盖。
- 每次真实尝试一行，包含request_id、attempt、backend/engine/model、usage、duration_ms、status和安全错误分类。
- diagnostics包含attempt_budget_ms及ssh_ms、cli_execution_ms、api_ms等已到达阶段的测量值。
- stdout_received/bytes仅说明收到协议数据，不保存部分文本或stderr。HTTP402归类insufficient_credits。
- prompt/system_prompt/response保存在私有日志；配置密钥和Authorization会脱敏。文件权限0600，进程锁防并发交错。
- llm_usage每次真实尝试一行；skipped不计usage。日志/usage存储失败不重试模型。
- 耗时报告不包含prompt、凭据或供应商原始错误，只展示安全分类。

## 财报搜索

`earnings_research` 使用 `web_search=True, prefer_search=True`，顺序仍固定Codex→API。
Codex显式开启live search，只以完成的web_search事件作为执行证据。OpenAI 设置
`LLM_API_SEARCH_MODE=responses` 时，联网请求走 LiteLLM Responses API 的 `web_search` 工具，
`search_context_size=medium`、`reasoning.effort` 复用 `LLM_API_EFFORT`；普通请求仍走 Chat Completions。
Responses 不保存服务端状态（store=false），只有 completed 响应可以成功返回；
已完成 web_search_call 或接口 url_citation 才能确认搜索，模型自行生成的来源列表不算证据。
旧搜索模型仍可显式设置 `chat_completions` 使用 web_search_options；`unavailable` 不发送搜索参数。
没有证据时尝试后续渠道；均无证据但有可用文本时返回unverified结果，由业务层保留缺失语义。
`earnings_outlook`价格预测阶段关闭搜索。普通业务不因此获得互联网搜索能力。

## 验证

```bash
uv run pytest tests/test_llm_client.py tests/test_llm_fallback.py tests/test_llm_cli_runner.py tests/test_llm_timing.py tests/earnings_outlook tests/signal_center -q
```

历史迁移0052保留：旧usage标为api/success且duration_ms=0，未知模型和engine可空；不回写历史耗时。

Signal Center v2同样使用`web_search=True, prefer_search=True`；初筛/最终分别保存transport evidence，外部引用必须有检索执行证据。未确认搜索仍可依据正式快照判断，但不能宣称外部来源已被检索。见[信号中心](signal-center.md)。
