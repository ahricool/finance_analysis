# 消息中心与通知

`notification` 是系统消息的唯一持久化事实源。业务产生消息后，`NotificationService.send()` 先写入 PostgreSQL，再调用原有 Noise Control，并向 Telegram / ntfy best-effort 推送。没有渠道、路由未命中、降噪抑制或外部推送失败，都不会删除已保存的消息。入库失败记录异常，不阻断核心分析或任务。

## 数据与用户范围

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| id | INTEGER | 主键 |
| uid | INTEGER NULL，外键 users.id | 非空为用户消息；空为全局消息 |
| title | VARCHAR(300) | 标题，默认从内容首个非空行提取 |
| content | TEXT | 完整 Markdown |
| route_type | VARCHAR(32) | report / alert / system_error |
| severity | VARCHAR(16) | 复用现有严重级别及默认推断 |
| created_at | TIMESTAMPTZ | aware UTC 创建时间 |

索引：created_at、(uid, created_at)、(route_type, created_at)、(severity, created_at)。不保存任何渠道、投递状态、失败原因或重试信息，不创建 Delivery 表。

API 从认证会话取得 uid；列表和详情均只允许 `uid = 当前用户 OR uid IS NULL`。管理员也遵循此范围。客户端不能指定其他用户范围；无权限详情返回 404。已有 Profile Telegram / ntfy 配置保持兼容。

## API 与页面

- `GET /api/v1/notifications`：page（默认 1）、page_size（默认 20，最大 100）、keyword（标题及正文）、route_type、severity、start_time、end_time。时间接受 ISO 8601；默认按 created_at DESC、id DESC 排序。返回 items / total / page / page_size，列表只返回最多 240 字符的 content_preview。
- `GET /api/v1/notifications/{id}`：完整 Markdown 正文，无投递状态。
- 头像菜单“消息中心”进入 `/notifications`，不加入顶部导航。筛选时间输入按本机时区转换为 UTC，消息时间沿用应用展示时区；详情复用现有安全 Markdown renderer。

不包含已读、红点、删除、收藏、实时订阅或统计功能。

## 业务边界

A股/美股盘中提醒、A股收盘前复核、美股盘前分析及新闻报告、美股盘后复盘、市场复盘、单股/汇总分析、Agent 提醒和任务错误统一使用 NotificationService。已知用户归属向下传 uid；无法确定时保持 NULL。一次业务消息只调用一次 send，渠道循环不写库。原先绕过 NotificationService 的分析汇总推送已统一入口。

报告不再自动写本地文件或 timeline_entries。Timeline 保留真实财经事件和逐条新闻结构化判断；旧 timeline_entries 表暂时保留，无报告读写入口。分析历史、新闻原文/结构化研究结果和任务执行统计仍属于各自业务领域，不作为消息中心的数据来源。

Calendar 仍保存 earnings / macro 真实事件。日历现有“日期、准确时间、session 实质变化”规则生成提醒后只调用 NotificationService，不再在 FinanceEvent 上记录通知标记或 fingerprint；推送去重键只传给原有 Noise Control。

## 升级

Alembic `0049_notification_center` 接在 `0048_trend_duration_days` 后：创建消息表及索引，执行 `DELETE FROM timeline_entries`，删除 finance_events 的 notified_at / notification_fingerprint 两列。保留全部现存财经事件，不搬运任何旧报告或旧推送状态。清理不可逆，downgrade 明确拒绝。

上线需一起更新应用和 Worker，避免旧进程继续写 Timeline 或访问已删除列。生产库升级会清空旧 Timeline 报告；迁移测试在独立测试库验证。

通用 `notification/noise_control.py` 保持原实现；dedup、cooldown、quiet hours、severity 和 in-flight reservation 没有迁移到 Redis/PostgreSQL，也没有重设计。
