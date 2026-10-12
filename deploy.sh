#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

# Host Python only uses the standard library; no uv/project dependencies needed.
exec python3 scripts/deploy.py "$@"
