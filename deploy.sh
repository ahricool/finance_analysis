#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "❌ 工作区存在未提交改动，请先提交或暂存后再部署。"
  exit 1
fi

echo "==> 切换到 main 分支"
git checkout main

echo "==> 拉取 main 最新代码"
git pull --ff-only origin main

echo "==> 使用生产配置启动容器"
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d --remove-orphans

echo "✅ 生产环境部署完成"
