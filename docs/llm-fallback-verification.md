# LLM fallback 验证记录（2026-09-23）

## 行为

统一 LLMClient 显式支持 `agy,codex,api` 顺序，首次调用后可重试错误最多重试三次，退避2/4/8秒。
总预算、后续渠道预留及单次上限共同限制实际尝试次数。配置与恢复步骤见 [llm.md](llm.md)。

不修改 Signal Center 候选、prompt、历史 snapshot 或已经完成的筛选桶，不新增 schema。
筛选桶和最终决策记录实际成功渠道；全部失败保持 failed，不能变成 NO_TRADE。

## 一轮 code review

检查了错误分类、跨渠道时间预算、SSH/子进程清理、审计归属、业务任务时限与配置兼容性。
发现并修复：

1. validator 的 TypeError 可能是程序错误，不应反复调用模型。只把 ValueError 类业务校验失败纳入重试，
   程序错误直接终止。
2. macOS 刚退出的进程组可能短暂返回 EPERM；清理时先回收并重新检查，不把该状态立即认定为清理失败。
   signal handler 使用独立异常，避免 selectors 吞掉 InterruptedError 而延迟清理。

后续统一预算改动已移除 Trade Engine 的540秒 soft limit 与每用户180秒覆盖；当前行为见 `docs/llm.md`。

## 真实 Docker → Host 联调

仅在现有 server 容器的独立 Python 测试进程加载新 LLM 模块，业务源码、生产配置和运行服务未替换。
复用现有生产 SSH 登录态与 API 配置。仅发送最小 JSON 验证请求，
未生成或覆盖正式 Signal；LLM 用量保留 `llm_fallback_verification` 记录。

| 验证 | 结果 |
| --- | --- |
| 真实 AGY 额度耗尽 → 真实 Codex | AGY 6.630秒识别 quota_exhausted，Codex 9.183秒成功，总约15.8秒 |
| 两个 CLI 路径故意设为不存在 → 真实 API | 依次记录 executable_missing，API 首次输出校验失败、退避2秒后成功，总约8.8秒 |
| 主机路径 | 原固定 /usr/local/bin/codex 不存在；联调使用已安装 Codex 包中的原生 binary 绝对路径 |
| 实际模型 | API 返回配置模型；Codex 默认模型未报告，保持未知而不猜测 |

CLI 进程监督另有离线真实子进程测试：正常退出、额度错误提前结束、超时 TERM/KILL、HUP、
衍生进程组清理，以及其他无关进程不受影响。未进行新的 CLI 登录或改动个人登录态。

## 后端门禁

使用独立 PostgreSQL 16 Docker 测试库，未将 pytest 指向生产库。

- syntax、flake8、deterministic 均通过。
- 完整离线测试：**2418 passed、27 skipped、2 deselected、5 failed**，另92个 subtests 通过。
- 以下5个失败已在未修改的主分支 `36211bb0` 独立复现，不属于本次引入：
  - `test_llm_usage.py::test_removed_api_and_request_surface`：旧字段断言漏掉既有 web_search。
  - `test_unified_instrument_universe.py::test_removed_domains_are_absent_from_current_schema_and_api`：旧已删除领域断言与当前 metadata 不符。
  - `trade_engine/test_market.py::test_us_yfinance_fallback_has_snapshot_time`。
  - `trade_engine/test_market.py::test_longbridge_pull_preserves_timestamp_or_uses_fetch_time`。
  - `trade_engine/test_market.py::test_fuyao_snapshot_preserves_timestamp_or_uses_fetch_time`。

这5个失败保留在门禁结果中，未跳过或修改断言以制造全绿。相关 LLM、Signal Center、重试及 resolver 用例通过。

## CLI 并发与任务互斥

AGY / Codex CLI attempts may execute concurrently.
Each attempt is independently bounded by LLM_ATTEMPT_TIMEOUT and the shared request deadline.
链模式共用一次请求的总 deadline；兼容单渠道模式使用请求剩余预算。
每次 attempt 独立记录预算与传输 diagnostics，未配置渠道的 skipped 记录不携带上次传输数据。
失败也记录已采集的 `ssh_ms`、`cli_execution_ms`、`stdout_received`、`stdout_bytes` 或 `api_ms`；
stdout 指标仅表示协议输出，不表示成功，不记录原始 stdout、stderr 或 provider 错误信息。
HTTP 402 保持 insufficient_credits，不重试当前渠道，可以继续 fallback。

Trade Engine 定时入口单独使用 TRADE_ENGINE_CN / TRADE_ENGINE_US 非阻塞任务锁：
同市场上一轮未结束则 TaskSkipped，两个市场可独立执行。uid + market 锁继续保护用户决策。
不恢复业务 timeout override 或旧 Celery 时限。

### 本次离线验证

- LLM/CLI runner、任务锁/生命周期/调度、盘前收盘复核及 Trade Engine resolver/用户锁/service：200 passed。
- syntax、flake8、deterministic 通过；完整离线 suite：2500 passed、35 skipped、2 deselected、39 failed、4 errors，92 subtests passed。
- 将全部43个失败/错误用例在修改前 PR #371 提交 `0b6ea236` 复跑，失败集合完全一致。
  当前环境包括本地测试 PostgreSQL 账号认证失败，以及已有 schema/API 与行情时间戳断言问题。
- 本轮只执行离线测试，未调用真实 LLM 或修改生产数据。
