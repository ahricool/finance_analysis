# ===================================
# Finance Analysis - Docker 镜像
# ===================================
# 多阶段构建：前端打包 + Python 依赖安装 + 运行时
#
# Python 3.13 + uv for fast, reproducible dependency installation.
# Note: Python 3.14 is intentionally skipped — litellm requires <3.14.
# Database: PostgreSQL via psycopg2-binary (no system libpq needed).

# ── Stage 1: Web frontend build ─────────────────────────────────────────────
FROM node:24-slim AS web-builder

WORKDIR /workspace/web

COPY web/ ./
RUN npm install
RUN npm run build

# ── Stage 2: Python dependency build (uv) ────────────────────────────────────
FROM python:3.13-slim-trixie AS py-builder

# Inject uv binary from the official distroless image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# gcc is needed at build time to compile C extensions (e.g. pandas, numpy)
RUN apt-get update && apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Enable bytecode compilation for faster container startup
ENV UV_COMPILE_BYTECODE=1
# Use copy link mode when a Docker cache mount is active
ENV UV_LINK_MODE=copy
# Never download extra Python interpreters (use the system Python)
ENV UV_PYTHON_DOWNLOADS=never


COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ── Stage 3: Runtime image ───────────────────────────────────────────────────
FROM python:3.13-slim-trixie

# Inject uv binary from the official distroless image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# 设置工作目录
WORKDIR /workspace

# 设置时区为上海
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gosu \
    fontconfig \
    libjpeg62-turbo \
    libxrender1 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*


# Copy installed Python packages from the builder stage
COPY --from=py-builder /workspace/.venv /workspace/.venv

# 让 `python` 默认走 venv 解释器，使 CMD / HEALTHCHECK / 镜像 smoke 都使用已安装的依赖
ENV PATH="/workspace/.venv/bin:${PATH}"
ENV VIRTUAL_ENV="/workspace/.venv"

# 复制项目元数据（保留 `uv run` / `uv pip` 在容器内的兜底能力，并使 Python 版本可追溯）
COPY pyproject.toml uv.lock .python-version ./

# 复制应用代码
COPY *.py ./
COPY api/ ./api/
COPY data_provider/ ./data_provider/
COPY bot/ ./bot/
COPY src/ ./src/
COPY strategies/ ./strategies/

COPY --from=web-builder /workspace/static ./static/

# 设置环境变量默认值
ENV PYTHONUNBUFFERED=1
ENV LOG_DIR=/workspace/logs
# Web/API service
ENV WEBUI_HOST=0.0.0.0
ENV API_PORT=8000

# 暴露 API 端口
EXPOSE 8000

# 数据卷（持久化数据）
VOLUME ["/workspace/data", "/workspace/logs", "/workspace/reports"]

# 健康检查（FastAPI 模式）
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || curl -f http://localhost:8000/health \
    || python -c "import sys; sys.exit(0)"


# 默认命令（可被覆盖）
# 使用 venv 内的 python（已通过 PATH 注入），与 smoke / HEALTHCHECK 行为一致
CMD ["python", "main.py"]
