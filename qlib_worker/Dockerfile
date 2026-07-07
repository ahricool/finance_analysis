FROM --platform=linux/amd64 python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=0 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 procps \
    && rm -rf /var/lib/apt/lists/*

COPY qlib_worker/pyproject.toml qlib_worker/uv.lock /workspace/qlib_worker/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project /workspace/qlib_worker --frozen --no-dev --no-install-project

COPY qlib_worker /workspace/qlib_worker
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project /workspace/qlib_worker --frozen --no-dev

ENV PATH="/workspace/qlib_worker/.venv/bin:${PATH}" \
    VIRTUAL_ENV=/workspace/qlib_worker/.venv

CMD ["celery", "-A", "qlib_worker.celery_app:celery_app", "worker", "-Q", "qlib", "--loglevel=INFO", "--concurrency=1", "--prefetch-multiplier=1", "--max-tasks-per-child=1"]
