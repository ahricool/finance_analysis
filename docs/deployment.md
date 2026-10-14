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

Ctrl-C/SIGTERM 会中断部署客户端，保留阶段记录。已发出的 Docker stop 请求仍可能由 daemon
继续执行；重新运行部署会再次等待当前容器退出，不直接强制替换它们。

**失败后的统一入口仍是 `bash deploy.sh`。** 每次都会拉取最新 main 并准备对应镜像，
然后停止 Beat、等待当前 worker（包括上次部分发布后已经启动的 worker）、迁移并更新应用。
不要求完成上次失败的版本，也不要求 HEAD 与上次相同。工作区仍需干净。

| 失败位置 | 处理方式 |
| --- | --- |
| 拉取、校验或其他暂停前检查 | 当前服务保持原状；排除原因后重新运行部署 |
| Beat/worker 停止阶段 | 重新运行部署，继续等待当前任务正常结束 |
| 迁移或应用替换 | 修复并发布新版本镜像后重新运行部署，向前修复，不自动回滚数据库 |
| 新 Beat 启动/心跳校验 | 脚本再次暂停 Beat；排除原因后重新运行部署 |

`--resume` 保留为无参数部署的兼容别名，**同样部署最新 main，不再锁定失败版本**。
`--recover` 不再启动原版本容器，而是提示使用正常部署入口。
worker 非零退出、OOM 或被强杀时，包括重试前已经停止的容器，都不会被当成正常排空；
需核查任务和容器日志，确认异常原因后处理。脚本不会自动重启旧 Beat。

阶段记录、锁、日志和本轮 digest override 位于 Git 内部的 `finance-deploy` 目录，
通常是 `.git/finance-deploy/`。`release.json` 是最近成功发布；`pending.json` 记录未完成发布，
仅供诊断，不阻止新发布。新一轮准备完成并开始暂停服务后更新 pending；准备失败时保留旧记录。
旧脚本留下的 pending 无需手动删除。digest 只保证本轮使用已经校验的镜像，不限制下一轮选版本。

兼容 Compose 参数透传，例如 `bash deploy.sh ps`；只读命令在部署持锁期间仍可用。
修改类透传命令使用最近尝试发布的镜像（存在 pending 时优先于成功记录），属于显式维护，
不执行任务等待流程。直接 Compose 停 worker 的后备宽限为普通 worker 1h、Qlib 4h，
期限结束后仍会强杀。日常发布和失败重试都使用无参数入口。

### 0072 趋势索引旧名导致迁移失败

历史迁移 `0031` 创建 `ix_trend_following_symbol_date`，`0039` 只将列改名为
`instrument_id`，未改索引名；旧 `0072` 因找不到 `ix_trend_following_instrument_date` 而失败。
修复后的 `0072` 兼容旧名、新名、两者并存及缺失的情况，统一重建带周期的索引。

包含迁移修复和新版部署脚本的代码合并、SHA 镜像发布完成后，在生产目录执行：

```bash
cd ~/svr/finance_analysis
git pull --ff-only origin main
bash deploy.sh
```

这里先手动 pull 是为了让本次启动直接加载新版部署脚本；旧版 Python 脚本已经加载到内存后，
不会因运行中的 git pull 自动切换实现。无需修改索引名、手动 stamp 或删除 pending。
`0072` 仍按原设计清空旧趋势快照和汇总，部署后需要重新计算。

## 调度暂停的边界

本次改动只保证部署操作等待正在执行的 Celery 任务正常完成。
Beat 的调度状态仍使用容器内默认文件，不挂载到宿主机持久化。
部署脚本不检查、不补发暂停期间漏掉的定时任务；不增加任务重放或业务补算逻辑。
每次正常发布都重建 Beat，从新容器的调度状态开始，避免同版本发布重新启动旧调度状态。

### 删除周期任务时的队列边界

移除任务定义和 Worker 注册后，新的 Beat 不再发布该任务，任务中心不再列出它，旧 job ID 的手动运行请求返回 404。
已保存的 TaskRecord、分析历史和通知仍可按原权限读取，不需要数据库迁移或删除历史数据。

上述优雅停止只等待正在执行的任务，不保证 Redis 中尚未消费的消息被排空。
若旧任务消息在升级后才被新 Worker 消费，Celery 会按未注册任务拒绝它，不会执行旧逻辑，也不会转给其他任务。
当前应用没有 unknown-task 状态回写钩子，因此对应的历史 pending TaskRecord 不会自动变成终态。
发布前应检查待移除任务的队列积压；需要保留执行结果时，先暂停 Beat，让旧 Worker 消费完相关消息后再升级。
不要为删除一个任务清空共享 analysis 队列；本次代码删除不自动清队列或更改历史记录。

## 首次使用新脚本

从旧脚本升级时，首次应先手动 `git pull --ff-only origin main`，
确认新脚本已在生产目录，再运行 `bash deploy.sh`。
宿主机需要能写入仓库的 Git 内部目录，用于锁和部署记录。
