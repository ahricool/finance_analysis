# 任务业务结果

任务中心的 PostgreSQL `task.status` 是业务运行事实源。Celery 成功只表示函数正常返回。

批量分析、财报处理、日线同步及美股新闻/盘后报告通过 `track_task(outcome_getter=...)` 显式声明结果：

- `completed`：本适配层声明的工作成功；预期跳过、成功降级和财报 frozen/ineligible/deferred 不计失败。
- `failed`：批量分析/财报中全部项目失败，或原有异常路径失败。
- `partial`：批量项目部分失败、日线返回 partial，或报告产生后某个实际尝试的推送渠道失败。

`partial` 是终态，保留原始结果、完成时间与摘要错误。业务结果正常返回给 Celery，不触发异常通知或整批重试，避免重复业务写入和推送。其他任务未配置 outcome_getter 时沿用原语义；不根据任意字典中的 status/failed 字段猜测任务状态。

财报任务在明细截断前保存 `total_count`、`failed_count`、`status_counts`；排查不能从最多40条明细推断整个批次。Qlib daily 仅跟踪主应用父任务，隔离 Worker 子调用通过发布 header 跳过建档，父任务继续 processing 直至主应用回调完成；不改变 Qlib payload 协议。

已有历史任务状态不在本次迁移中修改。新增 `0070_news_title_text` 仅把原始新闻标题由 VARCHAR(300) 改为 TEXT；已有数据保留，含超长标题时回退会失败，避免丢失原文。
