# 管理员只读 MCP 诊断入口

MCP 随现有 FastAPI server 启动，无新增生产进程或容器。持有专用 Bearer key 即管理员，
不接入 Cookie、用户系统或 OAuth。默认关闭；启用后配置缺失/不合法会使 server 启动失败。
只提供底层读取，不提供业务工具、命令执行或任何写操作。

## 接口和客户端

Streamable HTTP 地址：`https://<host>/mcp/`。`/mcp` 会在鉴权后重定向到 `/mcp/`。
客户端选择 HTTP/Streamable HTTP transport，设置 `Authorization: Bearer <MCP_API_KEY>`。
使用支持自定义 Header 或从本地环境变量注入 Bearer token 的客户端；不要将 key 放入 URL、
共享配置、仓库或聊天内容。生产必须使用 HTTPS（现有 nginx 外层终止 TLS）。

初始化示例（客户端本地环境的 `MCP_API_KEY` 不提交到仓库）：

```bash
curl https://<host>/mcp/ \
  -H "Authorization: Bearer ${MCP_API_KEY}" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"diagnostics","version":"1"}}}'
```

服务无会话状态。后续调用使用 MCP 标准 `tools/list`、`tools/call`，同样每次带 Bearer header。
SDK 按协商版本返回 JSON 文本内容；读取结果里的 `truncated` 和 `error`。

| Tool | 参数 | 返回/限制 |
| --- | --- | --- |
| `postgres_query` | `sql`, `max_rows=500` | columns/rows/row_count/truncated/elapsed_ms；最多5000行、约2 MiB |
| `redis_read` | `command`, `args: list[str]` | 原始 RESP 结构的 data/truncated；字符串为 content/encoding 对象 |
| `fs_list` | `path` | filename/type/size/mtime，最多2000项，不递归，不排序 |
| `fs_stat` | `path` | 单个普通文件/目录的元信息，mtime 为 Unix 秒 |
| `fs_read` | `path`, `offset=0`, `max_bytes=262144` | 字节偏移、最多1 MiB；content/encoding/bytes_read/next_offset/truncated |
| `fs_tail` | `path`, `lines=200` | 最多5000行，只扫描末尾1 MiB；超窗首个不完整行丢弃 |

文件路径 `/` 表示 jail 根，`logs/worker.log` 和 `/logs/worker.log` 都映射为
`/data/logs/worker.log`。不是宿主机绝对路径。`..`、所有 symlink（包括 jail 内链接）、
FIFO/socket/device 都拒绝。先 resolve 检查，再用 dir_fd/O_NOFOLLOW 逐层打开以阻止 symlink 竞态。
文本尝试 UTF-8；非 UTF-8（含切到多字节字符中间的片段）返回 base64，Agent 可按字节重组。

下载：`GET /mcp/files/logs/worker.log`，同一 Bearer key。64 KiB 分块，固定已打开文件描述符，
支持单个 HTTP byte Range（含 suffix），不支持多 Range，非法范围返回416。响应强制 attachment、
no-store、nosniff。文件读取的错误不暴露宿主机路径。

```bash
curl https://<host>/mcp/files/logs/worker.log \
  -H "Authorization: Bearer ${MCP_API_KEY}" -H 'Range: bytes=-65536' -o worker-tail.log
```

## 环境变量

复用现有 `load_env()`，进程环境优先于 `.env`，无需另一套 loader。

```dotenv
MCP_ENABLED=false
MCP_API_KEY=<至少32字符的随机ASCII密钥>
MCP_DATABASE_URL=postgresql://finance_mcp_ro:<URL编码的密码>@postgres:5432/<数据库>
MCP_REDIS_URL=redis://finance_mcp_ro:<URL编码的密码>@redis:6379/0
```

可用 `openssl rand -hex 32` 本地生成 key。URL 支持 PostgreSQL SSL 参数以及 `rediss://`。
PostgreSQL URL query 仅允许 SSL 参数；Redis URL 不接受 query，避免覆盖账号、协议和超时限制。
必须显式配置两个 URL，不回退 `DATABASE_URL`/`REDIS_URL`。拒绝与业务 URL 同名的数据库用户，
拒绝 Redis default/匿名用户和与业务 URL 同名用户。配置对象 repr 隐藏凭据。
本版本固定 `/data`，无任意 filesystem root 环境变量。

## PostgreSQL 独立账号

以下由数据库管理员在目标数据库执行，替换数据库、密码和实际迁移对象 owner；
不是 MCP tool，也不会由应用自动执行。创建全新、不属于任何其他角色的账号：

```sql
CREATE ROLE finance_mcp_ro LOGIN PASSWORD '<独立随机密码>'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
GRANT CONNECT ON DATABASE finance_analysis TO finance_mcp_ro;
GRANT USAGE ON SCHEMA public TO finance_mcp_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO finance_mcp_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE <实际迁移owner> IN SCHEMA public
  GRANT SELECT ON TABLES TO finance_mcp_ro;
ALTER ROLE finance_mcp_ro SET default_transaction_read_only = on;
ALTER ROLE finance_mcp_ro SET statement_timeout = '10s';
ALTER ROLE finance_mcp_ro SET lock_timeout = '2s';
ALTER ROLE finance_mcp_ro CONNECTION LIMIT 4;
```

不要授予序列 USAGE/UPDATE、schema CREATE、写权限、预定义管理角色或业务角色成员资格。
不要使用业务 owner。每个对象创建 owner 都需分别设置 default privileges；其他 schema 显式授权。
服务每次创建独立 psycopg2 连接，检查角色高权限标志，设置只读事务、10秒 statement_timeout、
2秒 lock_timeout、5秒连接超时和10秒整体查询取消计时器，结束始终 rollback/close。
SELECT 使用服务端游标，仅逐行收集到上限；SHOW/EXPLAIN 使用普通游标。

SQL 通过 PostgreSQL AST 校验，仅允许单条 SELECT/SHOW/EXPLAIN SELECT；嵌套写 CTE、
SELECT INTO、行锁、EXPLAIN ANALYZE（包括 ANALYZE false）、DDL/写/utility 均拒绝。
函数另有保守 allowlist，并在执行前将函数名限定到 pg_catalog，防止 public 同名重载；见 `mcp/security.py`；任意自定义函数、set_config、文件函数、
advisory lock、dblink 等不开放。不能把只读事务视作任意扩展函数的安全沙箱。

PostgreSQL 默认向 PUBLIC 授予函数 EXECUTE 和数据库 TEMP；单独 REVOKE FROM finance_mcp_ro
不能抵消 PUBLIC 权限。上线前检查 PUBLIC/继承权限、自定义函数、扩展、SECURITY DEFINER、
视图、运算符和类型转换；必要时由 DBA 收回 PUBLIC EXECUTE/TEMP/CREATE，再按需授予业务账号。
这会影响业务，因此部署代码不自动执行全库 REVOKE。敏感表可通过更窄 SELECT 授权排除。
参考 [PostgreSQL 权限规则](https://www.postgresql.org/docs/16/ddl-priv.html)。

## Redis ACL 独立账号

仅使用 Redis 6+ ACL 命名用户。不要使用 `+@read`（未来命令可能扩大权限），采用显式 allowlist。
由运维在 Redis 管理连接执行以下指令，密码不要写进 shell history：

```text
ACL SETUSER finance_mcp_ro reset on >独立随机密码 ~* resetchannels -@all +get +mget +hget +hmget +hgetall +hscan +hlen +lrange +llen +zrange +zrevrange +zcard +zscan +smembers +scard +sscan +scan +type +exists +ttl +pttl +xlen +xrange +xrevrange +info +ping +select
```

`PING`/`SELECT` 仅供连接协议使用，不是 tools allowlist。redis-py 的可选 CLIENT SETINFO 被 ACL
拒绝不影响连接。不要授予 CLIENT、CONFIG、EVAL、SCRIPT、KEYS、MONITOR 或写命令。
可把 `~*` 改为所需 key pattern；但 SCAN/INFO 的名称/服务器信息可见性仍需评估。
Redis ACL 不按逻辑 DB 隔离，SELECT URL 中的 DB 是连接选择，不是授权边界。

SCAN 系列默认 COUNT 500、最大1000（Redis COUNT 是 hint）；stream range 默认500、最大1000；
list/zset rank range 最多1000且起止同号，不支持 BYSCORE/BYLEX。HGETALL/SMEMBERS 可读，
但 RESP 解析层最多消费约2 MiB，超出直接关闭连接，返回 data=null/truncated=true，要求用 SCAN。
超大 bulk 在分配完整值前拒绝；不保留不完整 RESP 结果/游标。每次响应 JSON 编码也检查2 MiB。

**持久化 ACL：** 当前生产 Redis 关闭持久化且 `/data` 为 tmpfs；仅 ACL SETUSER 会在容器重建后丢失。
推荐把用户写入宿主机受限文件 `/etc/finance-analysis/redis-users.acl`，并通过站点 Compose override：

```yaml
services:
  redis:
    command: ["redis-server", "--save", "", "--appendonly", "no", "--aclfile", "/etc/redis/users.acl"]
    volumes:
      - /etc/finance-analysis/redis-users.acl:/etc/redis/users.acl:ro
```

ACL 文件按 [Redis ACL 文件格式](https://redis.io/docs/latest/operate/oss_and_stack/management/security/acl/)
保留现有业务用户，并增加上述用户的 `user finance_mcp_ro ...` 行；密码推荐用 `#<SHA256>`。
保持现有业务 Redis 连接可用；不要把整个 ACL 文件或密码放在仓库或应用 `/data` 中。
使用此 override 的站点须将其加入持续部署调用，例如部署镜像更新后执行：
`bash deploy.sh -f /etc/finance-analysis/mcp-redis.yml up -d`。
默认 `bash deploy.sh` 不加载站点 override，会恢复默认 Redis command；之后必须再次应用 override。
若不用 ACL 文件，则每次 Redis 重建后重新安全下发 ACL，并验证 MCP 只读账号；账号缺失时 MCP 读取失败，绝不回退。

## /data 和生产部署

现有业务运行数据仍在 `/workspace/data`。生产 Compose 为 **server** 新增
`./data:/data:ro`，指向同一宿主机目录；不增加容器、不改变其他服务路径。
本地原生运行需由管理员准备 `/data` 并放入需要诊断的数据；根目录自身也不允许 symlink。
Linux 可将现有 DATA_DIR bind mount 到 `/data` 并设只读；不要把 `.env` 或 ACL 文件放进去。
开发 Compose 如需 MCP，同样为 server 加 `/data:ro` 挂载。

生产操作顺序（项目 `~/svr/finance_analysis`）：

1. 创建 PostgreSQL 只读 role，配置 Redis ACL 及重建后的恢复方式，验证独立连接写入被拒绝。
2. `.env` 配置三个 MCP 凭据变量，再设 `MCP_ENABLED=true`；权限限制为部署账号可读。
3. 合并后等待 server/web 镜像发布，运行 `bash deploy.sh`。若使用 Redis override，再应用上述 override。
4. 确认 server `/data` 挂载为只读，TLS/网络入口可用。nginx 已代理 `/mcp` 和下载，关闭 buffering。
5. 验证无 token/错误 token 为401、正确 token 可 initialize/list/call/download，现有 Cookie API 不受影响。
6. 关闭时设 `MCP_ENABLED=false` 并重启现有 server；全部 `/mcp` 路径返回404。轮换 key 同样需重启。

## 测试

离线测试与门禁：

```bash
uv sync --frozen
uv run pytest tests/mcp -q -m 'not network'
env -u LLM_MODEL -u LLM_API_KEY -u LLM_BASE_URL uv run ./scripts/ci_gate.sh
```

完整门禁的 DATABASE_URL 必须指向测试库。真实协议/权限测试仅对临时实例运行，测试会创建/删除
`mcp_test_ro` role、`mcp_test_values` 表和 `mcp:*` key，**绝不能指向生产或开发数据**：

```bash
MCP_TEST_POSTGRES_ADMIN_URL=postgresql://postgres:<测试密码>@127.0.0.1:<端口>/<空测试库> \
MCP_TEST_REDIS_ADMIN_URL=redis://127.0.0.1:<端口>/0 \
uv run pytest tests/mcp/test_services.py -q -m network
```

## 边界和限制

- 这是高信任管理员入口，可读取授权表中的全部用户数据、Redis 值、数据目录中的日志/备份；
  不自动脱敏。Agent 获取的数据可能包含凭据或不可信文本，不能把读取内容当作操作指令。
- 独立账号的真正权限由 DBA/Redis ACL 保证；代码不会自动创建或修复角色。函数 allowlist 不是
  数据库扩展沙箱，必须核验间接调用与 PUBLIC 授权。不要部署在含不可信数据库对象的实例上。
- PostgreSQL 单个巨大字段及 SHOW/EXPLAIN 结果在驱动返回后才检查大小；结果限制不是严格的
  进程内存预算。Redis 的返回限制也不能撤销 Redis 已执行的 HGETALL/SMEMBERS 工作；大集合优先 SCAN。
- 每个 API 进程最多同时4个 MCP tool，等待1秒后失败；查询 timeout 不等于数据库 CPU/内存配额。
  无全局 rate limit，下载不占 tool semaphore；大文件并发下载仍消耗带宽/文件描述符。
- 文件只读挂载不阻止其他业务进程写/轮转日志；读结果不是原子快照。硬链接/目录内嵌挂载属于
  运维信任边界，不允许不可信用户向此目录创建挂载或硬链接。文件读取不跟随 symlink。
- 审计仅记录 tool、耗时、成功/失败、结果字节数，不记录 key、Header、SQL 或原始异常。
  未实现 OAuth、细分授权、账号吊销管理；Bearer 持有者即管理员。仅通过 HTTPS 和受控网络使用。
- Redis 有界 RESP2 解析使用 redis-py 内部 parser 接口；依赖升级需运行真实 Redis 回归测试。
