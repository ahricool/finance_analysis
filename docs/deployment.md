# 生产环境优雅部署

生产目录为 `~/svr/finance_analysis`，入口仍是 `bash deploy.sh`。部署主流程由
`scripts/deploy.py` 实现，宿主机需要 Python 3.10+（只用标准库）、Git、Docker 和支持
`up --wait --wait-timeout` 的 Compose。主应用仍使用镜像中的 Python 3.13，Qlib 使用 Python 3.12。

## 发布流程

1. 获取宿主机文件锁；重复部署立即失败，不同时操作容器。
2. 检查干净工作区，切到 main 并 `git pull --ff-only`。
3. 要求已有 PostgreSQL/Redis 健康；按 `sha-<完整提交SHA>` 拉取六个应用服务镜像。
   校验每个镜像的 OCI revision，并将本轮镜像固定到 registry digest。
4. 停止 Beat，不新增调度状态持久化或漏跑补偿。
5. 同时通过 `docker stop --timeout -1` 停止普通 worker 和 Qlib worker。
   Celery SIGTERM 等待执行中的任务完成，Docker 不设置强杀期限。只在容器正常退出后推进，
   不用 `inspect active` 无回复或 PostgreSQL processing 数量推断排空。
6. 停止 API/streamer，在新后端镜像中完成现有数据库迁移和种子初始化，再更新应用服务。
7. 等待 API、Web、两个 worker 健康，检查目标镜像及 streamer 运行状态。
8. 最后重建 Beat（即使发布提交相同也使用新容器），要求它写入本次启动后的新心跳；再次检查应用状态。
9. 记录发布结果，释放部署锁。

所有应用 `up` 使用 `--no-deps --no-build --pull never`；不会更新 PostgreSQL/Redis，
也不会全栈 `down` 或删除 orphan。Redis 当前没有持久化，重建/重启会丢失待执行消息与结果，
必须单独安排基础设施维护。首次安装时先单独启动基础设施：

```bash
docker compose -f docker-compose.prod.yml up -d postgres redis
bash deploy.sh
```

GitHub Actions 依次发布后端、Web、Qlib 的 SHA 镜像；若尚未全部发布完成，部署会在暂停前失败，
旧服务继续运行。脚本不会回退到 latest，不会等停机后再下载或构建镜像。

普通 worker 可能在退出前向 Qlib 发布任务，Qlib 也可能把 callback 留在普通队列里；
未执行消息由新 worker 接手。因此更新必须保持任务 payload/callback 协议向后兼容。
API 在 drain 阶段仍可接收手动任务；这些消息也会排队。新 worker 启动后会开始消费，
所以替换失败时不能直接删除或回滚正在执行的新 worker。

## 长任务与中断恢复

```bash
bash deploy.sh --status
bash deploy.sh logs --tail 100 worker qlib-worker beat
```

默认等待超过 900 秒后每 900 秒提示一次，继续等待，不强杀任务。
`DEPLOY_DRAIN_WARN_SECONDS` 只改变提示间隔；`DEPLOY_READY_TIMEOUT`（默认 300 秒）控制
新服务的就绪等待。两者必须为正整数：

```bash
DEPLOY_DRAIN_WARN_SECONDS=1800 DEPLOY_READY_TIMEOUT=600 bash deploy.sh
```

Ctrl-C/SIGTERM 会中断部署客户端，保留部署记录。已发出的 Docker stop 请求仍可能由 daemon
继续执行；不要立即重启这些 worker，也不要对它们执行另一次强制替换。
新部署和透传的修改命令会被未完成记录拦截，`--status` 和日志/ps 等只读命令仍可使用。

| 失败位置 | 恢复方式 |
| --- | --- |
| 拉取、校验或其他暂停前检查 | 旧任务不受影响；排除原因后重新运行 `bash deploy.sh` |
| Beat/worker 停止阶段，尚未开始替换 | 等待已请求停止的原容器正常退出，运行 `bash deploy.sh --recover` 恢复原容器，或 `--resume` 继续原发布 |
| API 停止、迁移或应用替换已经开始 | 核查迁移/容器日志，排除原因后 `bash deploy.sh --resume`；禁止自动回滚数据库或启动旧 Beat |
| 新 Beat 启动/心跳校验失败 | 脚本再次暂停 Beat，保留现场；排除原因后 `--resume` |

`--resume` 要求工作区干净且 HEAD 与未完成发布的 SHA 相同，使用已记录的 digest，
再次优雅停止当前 worker（包括已经运行任务的新 worker）后继续发布。
一旦进入替换阶段，即使继续部署时再次在 drain 阶段失败，也不能使用 `--recover` 回滚旧版本。
worker 非零退出、OOM 或被强杀时，不会被当成正常排空；需要先核查任务和日志。

部署记录、锁、日志和 digest override 位于 Git 的内部
`finance-deploy` 目录，通常是 `.git/finance-deploy/`，不会进入提交，也不保存 Compose
配置或业务 payload/result。`release.json` 是最近成功发布；`pending.json` 是未完成发布。
不要通过删除 pending 文件跳过恢复检查。

兼容原来的 Compose 参数透传，例如 `bash deploy.sh ps`。成功发布之后修改类透传命令使用
该发布的 digest；日志/ps 等只读命令在部署持锁期间也可使用。
`restart/stop/down/up` 等透传命令属于显式维护操作，不执行完整优雅发布流程；
直接 Compose 停 worker 的后备宽限为普通 worker 1h、Qlib 4h，期限结束后仍会强杀。
日常发布使用无参数入口。

## 调度暂停的边界

本次改动只保证部署操作等待正在执行的 Celery 任务正常完成。
Beat 的调度状态仍使用容器内默认文件，不挂载到宿主机持久化。
部署脚本不检查、不补发暂停期间漏掉的定时任务；不增加任务重放或业务补算逻辑。
每次正常发布都重建 Beat，从新容器的调度状态开始，避免同版本发布重新启动旧调度状态。
`--recover` 恢复原容器时仍使用 Celery 默认到期判断，不增加额外补偿逻辑。

## 首次使用新脚本

旧 deploy.sh 在拉取代码后会继续执行旧的全栈更新逻辑。合并本次 PR 后首次安装应先手动
`git pull --ff-only origin main`，确认新脚本已在生产目录，再运行 `bash deploy.sh`。
宿主机需要能写入仓库的 Git 内部目录，用于锁和部署记录。
