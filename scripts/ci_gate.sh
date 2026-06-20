#!/usr/bin/env bash
# Backend CI gate: syntax, flake8, deterministic checks, offline pytest.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/finance_analysis_test}"

run_syntax() {
  python -m compileall -q src main.py alembic tests
}

run_flake8() {
  flake8 src tests alembic main.py \
    --select=E9,F63,F7,F82 \
    --format='%(path)s:%(row)d: %(code)s %(text)s'
}

run_deterministic() {
  python -m pytest tests/test_config_manager.py -q
}

run_offline_tests() {
  python -m pytest tests/ -q -m "not network" \
    --ignore=tests/longbridge_live_smoke.py
}

case "${1:-all}" in
  syntax) run_syntax ;;
  flake8) run_flake8 ;;
  deterministic) run_deterministic ;;
  offline-tests) run_offline_tests ;;
  all)
    run_syntax
    run_flake8
    run_deterministic
    run_offline_tests
    ;;
  *)
    echo "Usage: $0 {syntax|flake8|deterministic|offline-tests|all}" >&2
    exit 1
    ;;
esac
