# LLM fallback 验证记录（2026-09-23）

## 行为

统一 LLMClient 显式支持 `agy,codex,api` 顺序，首次调用后可重试错误最多重试三次，退避2/4/8秒。
总预算、后续渠道预留及单次上限共同限制实际尝试次数。配置与恢复步骤见 [llm.md](llm.md)。

不修改 Signal Center 候选、prompt、历史 snapshot 或已经完成的筛选桶，不新增 schema。
筛选桶和最终决策记录实际成功渠道；全部失败保持 failed，不能变成 NO_TRADE。

## 一轮 code review

检查了错误分类、跨渠道时间预算、共享锁、SSH/子进程清理、审计归属、业务任务时限与配置兼容性。
发现并修复：

1. DB 初始化/连接错误可能被当作网络错误，导致绕过 CLI 锁切到 API。现在锁基础设施失败直接终止，
   已增加连接失败不调用任何模型的回归测试。
2. validator 的 TypeError 可能是程序错误，不应反复调用模型。只把 ValueError 类业务校验失败纳入重试，
   程序错误直接终止。
3. macOS 刚退出的进程组可能短暂返回 EPERM；清理时先回收并重新检查，不把该状态立即认定为清理失败。
   signal handler 使用独立异常，避免 selectors 吞掉 InterruptedError 而延迟清理。

同时核对了 Trade Engine 的540秒 soft limit，保持原有每用户180秒上限，配置更短时从短。

## 真实 Docker → Host 联调

仅在现有 server 容器的独立 Python 测试进程加载新 LLM 模块，业务源码、生产配置和运行服务未替换。
复用现有生产 SSH 登录态、API 配置和 PostgreSQL advisory lock。仅发送最小 JSON 验证请求，
未生成或覆盖正式 Signal；LLM 用量保留 `llm_fallback_verification` 记录。

| 验证 | 结果 |
| --- | --- |
| 真实 AGY 额度耗尽 → 真实 Codex | AGY 6.630秒识别 quota_exhausted，Codex 9.183秒成功，总约15.8秒 |
| 两个 CLI 路径故意设为不存在 → 真实 API | 依次记录 executable_missing，API 首次输出校验失败、退避2秒后成功，总约8.8秒 |
| 调用后 DB 锁 | CLI advisory lock 数量为0 |
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
