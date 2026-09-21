# Trend Following 趋势状态与快照恢复

## 趋势状态（0053 起）

趋势跟踪只描述股票趋势，不维护实际或理论持仓。正式收盘和盘中预演使用同一分类函数，
预演仍只写 Redis。市场 Regime 保留为环境指标，不参与个股状态或仓位限制。

按以下优先顺序判断：

1. 前次状态为 CANDIDATE / TRENDING / WEAKENING（已确认趋势），或已为 BROKEN，
   且收盘价低于前 10 日最低价，或低于 MA20 且 MA20 斜率不大于 0：BROKEN（趋势破坏）。
2. 已确认趋势中，TrendCandidate 不成立、Trend Score < 60、RS Score < 55、收盘价低于 MA10
   任一成立：WEAKENING（趋势弱化）。恢复健康后回到 TRENDING。
3. 已确认趋势且无上述破坏/弱化条件：TRENDING（趋势明确且健康）。
4. 其他状态满足既有候选条件：CANDIDATE。条件为 TrendCandidate、Trend >= 62、RS >= 60、
   ValidSetup、Alpha >= 67；下一有效快照健康时转为 TRENDING，不要求再次出现突破形态。
5. 仅 TrendCandidate 成立：WATCHING（趋势形成）；否则 IDLE（无明显趋势）。

TrendCandidate 继续使用 Close>MA10、MA10>MA20、10 日收益>0、15 日加权斜率>0 四项至少三项通过。
BROKEN 恢复时重新经过候选/观察判断。前次快照只提供趋势状态，不携带交易价格或持仓信息。
无当日日线或历史不足的股票不生成当日快照，历史格留空；下一有效日期参考此前最近的正式状态。
Fragility、trend_lifecycle 和持续天数继续作为独立解释指标，不额外增加分类分支。

### 存储与接口清理

迁移 `0053_trend_states` 删除 Snapshot 的 `action`、`units`、`entry_price`、`last_add_price`、
`opened_at`、`highest_close`、`initial_stop`、`trailing_stop`、`next_add_price`、`exit_level`、
`signal_date`、`signal_price`、全部 `pending_*` 字段及 `suggested_initial_weight` / `suggested_max_weight`。
Summary 删除 `suggested_max_exposure` 和 entry/add/hold/reduce/exit 计数，保留候选状态计数。

已存历史按当时保存的价格、评分与指标顺序重建六态和候选计数，移除沿用旧行情或缺少必要指标的行。
迁移不读取外部行情、不生成模拟成交。删除的数据不可由 downgrade 还原。
部署需更新 API、普通 Worker、Web，并执行 `uv run alembic upgrade head`；不要让旧 Worker 在迁移后继续写入。
正式排名缓存版本为 v6，Preview key 为 `trend_following:preview:v2:{market}`，旧缓存不再读取。

删除 `/trend-following/portfolio`、ranking 的 portfolio、所有 action 和 pending 字段。
changes 仅比较状态/排名/评分，以 `new_broken` 替代旧动作分类。前端删除理论组合、敞口进度、
交易日期/价格/止损/加减仓展示；排名、详情、历史、热力图、Dashboard 统一使用六态。
没有新增 Portfolio/Holding 抽象。

## 快照写入与失败恢复

Repository 根据 `TrendFollowingSnapshot` ORM 列统一所有写入记录：缺失 nullable 列填 None，
`features` / `score_breakdown` 默认 `{}`，`reasons` 默认 `[]`。
其他非空必填列缺失或为 None 时，在开启事务前抛出包含证券代码和列名的 ValueError。
`instrument_id` 由证券主数据解析，`generated_at` 由 Repository 生成。
`upsert_snapshots()` 和 `replace_day()` 共用该保护层。

CN / US Trend Following Task 只接受 `status=completed`；failed / incomplete 抛出带市场、
日期、业务状态、warnings 和可用 coverage 的异常，复用原生命周期记录失败并发送失败通知。
全局 `track_task` 不变。当前 CN / US 正式计算及盘中预演的最低数据覆盖率为 90%；
历史覆盖率检查也复用该配置，benchmark 及其他计算条件仍须满足。

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
   Trend Following 再按自己的 Universe 和 90% 门槛判断，低于门槛即 incomplete / Task failed。

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

503 只的 Universe 至少需要 453 只有当日日线；benchmark 及历史长度检查也必须通过。
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
按当前 90% 门槛核对覆盖率及其他数据条件。最终检查数据库 summary / snapshot 日期及任务结果，再验证页面显示。

## Alpha 评分

Alpha V2 的公式、参数、快照兼容与新旧对照见 [trend-alpha-v2.md](trend-alpha-v2.md)。
状态机和 Candidate 的 ValidSetup 条件保持本页语义。

### 排名指标读模型

`/trend-following/ranking` 一次批量投影返回 Alpha V2 排名标量 `features`，
从 `score_breakdown` JSON 路径提取质量分与贡献标量，不返回整份嵌套 `score_breakdown`，
不逐行请求详情，不改变策略计算。缺失历史指标返回 null。`breakout_score` 仍是 Setup Score
的兼容别名，主表只展示 Setup，不重复 Breakout Score 列。收益百分位等已退出计分的 V1 字段
不再进入排名投影。

主表按 Core、Alpha、Trend、RS、Setup、Path、Signals / Explain、Risk / Health 分组
展示 Official 与 Preview 共用的最新指标。Alpha/Trend/RS/Setup/Path 只放实际参与 V2
计分的分量；`priorCompression`、`compressionBreakout`、`trendResume`、
`signedEfficiencyRatio10D` 等解释字段归入 Signals / Explain。完整股票池先经 State
筛选、搜索和排序，再截取虚拟滚动行；缺失值始终置后。
表格可横向滚动，股票名称固定在左侧。
