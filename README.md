# Finance Analysis 🐣📈

欢迎来到 **Finance Analysis**！这是一只会帮你盯盘、读新闻、做策略分析的小小金融助手 (｡･ω･｡)ﾉ♡  
项目把 **多市场行情数据 + AI 智能分析 + 策略 Agent + Web 可视化 + 通知推送** 串在一起，适合用来做日常股票观察、策略复盘和投研小助手搭建～✨

> ⚠️ 友情提醒：本项目输出仅用于学习、研究与辅助决策，不构成任何投资建议。市场有风险，冲鸭之前请先系好安全带 🛟

## 它可以做什么？🪄

- 🧠 **AI 股票分析**：支持 A 股 / 港股 / 美股等标的，结合行情、新闻、技术面与策略给出结构化分析。
- 🧩 **策略 Agent**：内置多头趋势、均线金叉、放量突破、缩量回踩、缠论、波浪理论、情绪周期等策略技能。
- 🌐 **WebUI + API**：FastAPI 后端统一提供接口，前端使用 Vue/Vite 构建，浏览器里点点点也能用～
- 🗄️ **PostgreSQL 持久化**：分析历史、持仓列表、系统配置等数据可落库保存。
- 🔔 **多渠道通知**：支持 Telegram、邮件、自定义 Webhook、ntfy、AstrBot 等推送方式。
- 🧪 **回测与校准**：可对历史分析结果做回测，帮助观察策略表现。
- 🐳 **Docker 友好部署**：开发环境和生产环境分别提供 Compose 文件，启动姿势很清晰 (ง •̀_•́)ง

## 项目结构速览 🗺️

```text
.
├── api/                    # FastAPI 应用、路由、中间件
├── src/                    # 核心分析、服务、仓储、配置、调度等后端逻辑
├── data_provider/          # AkShare / efinance / Tushare / yfinance 等数据源适配
├── bot/                    # 机器人命令与消息分发
├── strategies/             # 内置 Agent 策略 YAML
├── web/                    # Vue + Vite 前端工程
├── alembic/                # 数据库迁移脚本
├── docs/                   # 更多专题文档
├── Dockerfile              # 前后端一体化镜像构建
├── docker-compose.dev.yml  # 本地开发用 Compose
└── docker-compose.prod.yml # 生产部署用 Compose
```

## 准备工作 🍱

### 基础依赖

| 场景 | 需要准备 |
| --- | --- |
| Docker 快速启动 | Docker、Docker Compose |
| 本地后端开发 | Python 3.13、uv、PostgreSQL |
| 本地前端开发 | Node.js 24+、pnpm 11+ |

### 配置 `.env`

先复制一份配置模板：

```bash
cp .env.example .env
```

最少需要关注这些配置：

```dotenv
# 数据库
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=finance_analysis
DATABASE_URL=postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:5432/${POSTGRES_DB}
REDIS_URL=redis://localhost:6379/0

# AI / 搜索 / 数据源：任选你实际使用的服务填写
GEMINI_API_KEY=
OPENAI_API_KEY=
TUSHARE_TOKEN=
TAVILY_API_KEYS=
SERPAPI_API_KEYS=
```

> 小贴士：Docker Compose 会自动把 `DATABASE_URL` 和 `REDIS_URL` 改成容器内服务地址；如果你本机裸跑 Python，则保持 `localhost` 即可。

## 本地环境怎么搭建？🧑‍💻🌱

本地开发有两种姿势：**Docker 一键跑起来** 或 **前后端分开调试**。

### 方式 A：Docker Compose 开发环境（推荐新手）🐳

开发 Compose 会：

- 启动 PostgreSQL；
- 构建/启动后端服务；
- 把 `api/`、`src/`、`data_provider/`、`bot/`、`strategies/` 等目录挂载进容器，方便改代码；
- 将 `data/` 挂载到宿主机保存（日志、报告、上传文件等均位于 `data/` 下）。

```bash
cp .env.example .env
# 按需编辑 .env，比如 API Key、数据库密码等

docker compose -f docker-compose.dev.yml up --build
```

启动后访问：

- 🌐 WebUI：`http://localhost:8001`
- 📚 API 文档：`http://localhost:8001/docs`
- ❤️ 健康检查：`http://localhost:8001/api/health`

后台运行可以这样：

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

查看日志：

```bash
docker compose -f docker-compose.dev.yml logs -f server
```

停止服务：

```bash
docker compose -f docker-compose.dev.yml down
```

> `docker-compose.yml` 默认 include 的就是开发配置，所以你也可以直接 `docker compose up --build`，懒人友好～(=^･ω･^=)

### 方式 B：本机后端 + 本机前端（适合深度开发）🛠️

1. 启动 PostgreSQL（可以只用 Compose 起数据库）：

```bash
docker compose -f docker-compose.dev.yml up -d postgres
```

2. 安装 Python 依赖：

```bash
uv sync
```

3. 准备环境变量：

```bash
cp .env.example .env
# 确认 DATABASE_URL 指向 localhost:5432
```

4. 启动后端 API：

```bash
uv run python main.py --host 127.0.0.1 --port 8000
```

5. 另开一个终端启动前端开发服务器：

```bash
cd web
corepack enable
pnpm install --frozen-lockfile
pnpm run dev
```

本机开发常用地址：

- 后端 API：`http://127.0.0.1:8000`
- API 文档：`http://127.0.0.1:8000/docs`
- Vite 前端：`http://127.0.0.1:5173`

## 生产环境怎么部署？🚀🏡

生产环境建议使用 `docker-compose.prod.yml`，它会使用发布镜像 `ghcr.io/ahricool/finance_analysis:latest`，并减少开发目录挂载，只保留必要的数据和策略目录。

### 1. 准备服务器目录

```bash
mkdir -p finance_analysis/{data,strategies}
cd finance_analysis
```

把项目里的这些文件放到服务器目录：

```text
.env
良心建议再放：docker-compose.prod.yml、strategies/
```

也可以直接在服务器上克隆仓库，然后进入仓库根目录部署。

### 2. 配置生产 `.env`

```bash
cp .env.example .env
```

生产环境重点检查：

```dotenv
# 强烈建议改掉默认密码！(｀・ω・´)
POSTGRES_USER=finance_user
POSTGRES_PASSWORD=请换成超长随机密码
POSTGRES_DB=finance_analysis

# 按需填写你的 AI、搜索、行情、通知配置
OPENAI_API_KEY=
GEMINI_API_KEY=
TUSHARE_TOKEN=
TAVILY_API_KEYS=
TELEGRAM_BOT_TOKEN=
EMAIL_SENDER=
EMAIL_PASSWORD=
```

> 安全小蛋糕 🍰：生产环境请不要把 `.env` 提交到 Git；如果暴露公网，建议再加 Nginx/HTTPS/防火墙/访问控制。

### 3. 拉起服务

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

### 4. 检查服务状态

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f server
curl http://127.0.0.1:8000/api/health
```

访问：

- 🌍 WebUI：`http://你的服务器IP:8000`
- 📖 API 文档：`http://你的服务器IP:8000/docs`

### 5. 更新版本

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

如果你本地要自己构建生产镜像：

```bash
docker build -t finance-analysis:local .
```

然后把 `docker-compose.prod.yml` 里的 `server.image` 改成你的镜像名即可。

## 常用运维小抄 📒✨

```bash
# 看容器状态
docker compose -f docker-compose.prod.yml ps

# 看后端日志
docker compose -f docker-compose.prod.yml logs -f server

# 看数据库日志
docker compose -f docker-compose.prod.yml logs -f postgres

# 重启服务
docker compose -f docker-compose.prod.yml restart server

# 停止但保留数据卷
docker compose -f docker-compose.prod.yml down

# 连进应用容器
docker compose -f docker-compose.prod.yml exec server bash
```

数据默认保存在：

- `data/`：所有运行时文件（`data/logs/`、`data/reports/`、`data/uploads/` 等）；
- Docker volume `finance-analysis-postgres-data`：PostgreSQL 数据。

## 开发检查 🧪

后端常用：

```bash
uv run pytest
```

前端常用：

```bash
cd web
pnpm run lint
pnpm run build
pnpm run test
```

Docker 构建冒烟：

```bash
docker build -t finance-analysis:test .
docker run --rm finance-analysis:test python -c "print('Docker OK 🐳')"
```

## 进一步探索 🐾

- 想调整策略？去 `strategies/` 看看那些可爱的 YAML 策略卡片～
- 想接入更多模型？看 `.env.example` 里的 LLM 渠道配置，基本照着填就能跑。
- 想做 Web 二开？前端在 `web/`，后端 API 在 `api/`，核心服务在 `src/`。
- 想部署得更稳？建议配合 Nginx、HTTPS、日志轮转、数据库备份和监控告警。

祝你分析顺利，K 线温柔，日志永远绿色 ✅ ٩(ˊᗜˋ*)و
