# -*- coding: utf-8 -*-
"""
===================================
Finance Analysis - 测试包
===================================

职责：
1. 提供单元测试包结构
2. 统一测试模块入口
3. 为需要数据库的测试设置默认 DATABASE_URL（PostgreSQL）
"""
import os

# CI / 本地 pytest 默认连接（可被环境变量覆盖）
_DEFAULT_TEST_PG_URL = (
    "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/finance_analysis_test"
)

if not (os.environ.get("DATABASE_URL") or "").strip():
    os.environ["DATABASE_URL"] = _DEFAULT_TEST_PG_URL
