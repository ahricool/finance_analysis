#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

COMPOSE=(docker compose -f docker-compose.prod.yml)

case "${1:-}" in
  down)
    shift
    "${COMPOSE[@]}" down "$@"
    ;;
  up)
    shift
    "${COMPOSE[@]}" up "$@"
    ;;
  "")
    if [[ -n "$(git status --porcelain)" ]]; then
      echo "❌ 工作区存在未提交改动，请先提交或暂存后再部署。"
      exit 1
    fi

    echo "==> 切换到 main 分支"
    git checkout main

    echo "==> 拉取 main 最新代码"
    git pull --ff-only origin main

    echo "==> 使用生产配置启动容器"
    "${COMPOSE[@]}" pull
    "${COMPOSE[@]}" up -d --remove-orphans

    echo "✅ 生产环境部署完成"
    ;;
  *)
    echo "用法: $0 [up|down] [docker compose 参数...]"
    echo "  $0          拉取 main 并部署生产环境（现有逻辑）"
    echo "  $0 up       执行 docker compose up，可追加参数，例如: $0 up -d"
    echo "  $0 down     执行 docker compose down，可追加参数，例如: $0 down --volumes"
    exit 1
    ;;
esac
