# 任务业务结果

任务中心的 PostgreSQL `task.status` 是业务运行事实源。Celery 成功只表示函数正常返回。

批量分析、财报处理、日线同步及美股新闻/盘后报告通过 `track_task(outcome_getter=...)` 显式声明结果：

- `completed`：本适配层声明的工作成功；预期跳过、成功降级和财报 frozen/ineligible/deferred 不计失败。
- `failed`：批量分析/财报中全部项目失败，或原有异常路径失败。
- `partial`：批量项目部分失败、日线返回 partial，或报告产生后自选股校验/某个实际尝试的推送渠道失败。

`partial` 是终态，保留原始结果、完成时间与摘要错误。业务结果正常返回给 Celery，不触发异常通知或整批重试，避免重复业务写入和推送。其他任务未配置 outcome_getter 时沿用原语义；不根据任意字典中的 status/failed 字段猜测任务状态。

财报任务在明细截断前保存 `total_count`、`failed_count`、`status_counts`；长错误超过结果 JSON 的 12000 字符预算时仍保留这些结构化汇总，只缩减 `results` 并标记 `remaining_items`。排查不能从最多40条明细推断整个批次。Qlib daily 仅跟踪主应用父任务，隔离 Worker 子调用通过发布 header 跳过建档，父任务继续 processing 直至主应用回调完成；不改变 Qlib payload 协议。

自选股创建/更新在写入前用既有 canonical 工具验证代码与显式市场；如 `AAPL.US + CN` 会返回 422。历史无效行仍可在列表中查看，响应带 `validation_error`。批量读取隔离无效行并保留 `validation_failures`：每日/盘前分析把它计入总数与失败数，全部无效时直接失败且不调用分析流水线；盘前新闻/盘后报告保留明细并声明 partial。有效行照常处理，不修改或清理历史数据。

已有历史任务状态不修改，新闻标题继续使用 VARCHAR(300)，不新增数据库迁移。统一写入边界将标题截断至 300 个 Unicode 字符；无 URL 时先用完整原始标题生成去重键，避免相同前缀的不同新闻合并。正文与摘要不截断。全量自选股分析按市场预取行情及名称，仍保留一轮分析与汇总报告。
