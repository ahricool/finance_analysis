# Trend Following 缺失快照恢复

## 2026-09-07 / 09-08 故障原因

- CN：普通快照包含 `entry_price` 等字段，候选过期记录缺少这些字段。混合批量 INSERT
  报 `A value is required for bind parameter 'entry_price'`，整日事务回滚。
  09-08 的 catch-up 从 09-07 开始，因此再次失败，两个日期均未生成。
- US：09-07 非交易日；09-08 只有 475/503 只成分股有当日日线，94.43% 低于 95% 门槛。
- `TrendFollowingService.run()` 将业务失败转换为返回值；原 Task 未将该状态转换为异常，
  所以任务中心错误显示 completed。

## 修复行为

Repository 根据 `TrendFollowingSnapshot` ORM 列统一所有写入记录：缺失 nullable 列填 None，
`features` / `score_breakdown` 默认 `{}`，`reasons` 默认 `[]`，`units` 默认 0。
其他非空必填列缺失或为 None 时，在开启事务前抛出包含证券代码和列名的 ValueError。
`instrument_id` 由证券主数据解析，`generated_at` 由 Repository 生成。
`upsert_snapshots()` 和 `replace_day()` 共用该保护层，无 schema migration。

CN / US Trend Following Task 只接受 `status=completed`；failed / incomplete 抛出带市场、
日期、业务状态、warnings 和可用 coverage 的异常，复用原生命周期记录失败并发送失败通知。
全局 `track_task` 不变，95% coverage 门槛不变。

日线同步行为：

1. 按现有 scope 和历史窗口同步，保留 provider 的正常重试和前复权尺度变化检查。
2. yfinance / TickFlow 实际日线 batch 请求之间等待 10 秒；首批前、末批后不等待。
   TickFlow 的批次顺序执行；单批 SDK 参数保持不变。yfinance 同一失败批次的内部 retry
   不额外叠加 batch 间隔。同步任务、日期分组、补缺和 provider fallback 共用一次请求序列。
3. 写库后查询数据库目标交易日实际存在的证券 ID，记录 requested、success、missing、coverage
   及完整缺失代码。目标日期固定为本次运行时最近已完成的交易日。
4. 若缺失，等待一次 300 秒；等待后再次检查，剔除已被其他同步补齐的代码。
5. 仅剩余 missing symbols 进入补缺，每批最多 10 只；使用原历史窗口，以保留前复权尺度检查，
   普通补缺执行 upsert，不因小批次重试删除既有历史。确认尺度变化时仍走既有完整刷新逻辑。
6. 补缺批次之间仍等待 10 秒；五分钟等待后的首批不再额外等 10 秒。
7. 重新查库，记录 retry_requested、retry_success、remaining_missing 和 final_coverage。
   仍有缺失就结束并返回 partial；全体请求失败仍遵循原同步错误语义。没有无限循环。
   Trend Following 再按自己的 Universe 和 95% 门槛判断，低于门槛即 incomplete / Task failed。

同步 scope 比趋势 Universe 大，两个 coverage 分母不能混用。
CN 继续 TickFlow 优先，US 继续 yfinance 优先；未恢复 Longbridge 为普通日线主来源。
错误日志保留 request_failed、parse_failed、provider_error、empty_response、requested_date_missing
等原因；新输出的 provider 错误详情使用现有脱敏函数。

## 部署后恢复（下列生产写入命令未在修复过程中执行）

先部署包含本修复的后端镜像并重建普通 Celery Worker，确认其运行新代码。
命令适用于生产 Compose 容器 `finance-analysis-celery`，从 `~/svr/finance_analysis` 运维。

### A 股

提交截至 2026-09-08 的趋势任务：

```bash
docker exec -i finance-analysis-celery python - <<'PY'
from finance_analysis.tasks.celery.jobs.trend_following.tasks import run_trend_following_cn
job = run_trend_following_cn.apply_async(
    kwargs={"trade_date": "2026-09-08", "trigger_source": "manual"}, queue="analysis"
)
print(job.id)
PY
```

若最新快照仍是 09-04，现有 rebuild 会顺序计算 09-07 → 09-08。
如果部署时已存在更新日期，现有历史重算会继续重建后续状态链。
在任务中心确认任务 completed、业务结果 completed、相应快照日期实际存在。
不要直接 INSERT 快照，也不要绕过前一天状态单独拼装 09-08。

### 美股

先执行美股增量日线同步，等待其初次同步和可能的一次延迟补缺结束：

```bash
docker exec -i finance-analysis-celery python - <<'PY'
from finance_analysis.tasks.celery.jobs.market_data_sync.tasks import sync_us_market_data
job = sync_us_market_data.apply_async(
    kwargs={"sync_mode": "incremental", "trigger_source": "manual"}, queue="ingestion"
)
print(job.id)
PY
```

增量同步使用滚动历史窗口；若恢复时 09-08 已不在配置的刷新窗口内，应按现有完整同步流程
补齐历史再验证。延迟重试只保障本次同步的目标交易日，不自动对每个历史日期各等五分钟。

检查 **09-08 精确日期** 在趋势 Universe 的 coverage（只读）：

```bash
docker exec -i finance-analysis-celery python - <<'PY'
from datetime import date
from finance_analysis.database.repositories.stock import StockRepository
from finance_analysis.database.repositories.universe import UniverseResolver
members = UniverseResolver().resolve_universe("us_sp500")
ready = StockRepository().daily_ids_on_date([item.id for item in members], date(2026, 9, 8))
missing = [item.code for item in members if item.id not in ready]
print({"requested": len(members), "ready": len(ready),
       "coverage": len(ready) / len(members) if members else 0, "missing": missing})
PY
```

503 只的 Universe 至少需要 478 只有当日日线；benchmark 及历史长度检查也必须通过。
满足数据条件后提交趋势任务：

```bash
docker exec -i finance-analysis-celery python - <<'PY'
from finance_analysis.tasks.celery.jobs.trend_following.tasks import run_trend_following_us
job = run_trend_following_us.apply_async(
    kwargs={"trade_date": "2026-09-08", "trigger_source": "manual"}, queue="analysis"
)
print(job.id)
PY
```

09-07 非交易日，不生成 US 快照。若任务仍 failed，检查 warnings 和 remaining missing；
不要降低门槛。最终检查数据库 summary / snapshot 日期及任务结果，再验证页面显示。
