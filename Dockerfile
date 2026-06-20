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

# Corepack reads `packageManager` from package.json on first `pnpm` invocation.
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable

WORKDIR /workspace/web

# Dependency layer: caches when only source (not lockfile) changes.
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN --mount=type=cache,id=pnpm-store-web,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

COPY web/ ./
RUN pnpm run build

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
    uv sync --frozen --no-dev --no-install-project

COPY src/ ./src/
COPY main.py ./

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
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY main.py ./
COPY src/ ./src/
COPY strategies/ ./strategies/
COPY templates/ ./templates/

COPY --from=web-builder /workspace/static ./static/

# 设置环境变量默认值
ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=/workspace/data

# 数据卷（持久化数据）
VOLUME ["/workspace/data"]

# 健康检查（FastAPI 模式）
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD sh -c 'curl -f "$HEALTHCHECK_URL" || curl -f "$HEALTHCHECK_FALLBACK_URL"'


# 默认命令（可被覆盖）
# 使用 venv 内的 python（已通过 PATH 注入），与 smoke / HEALTHCHECK 行为一致
CMD ["python", "main.py"]
