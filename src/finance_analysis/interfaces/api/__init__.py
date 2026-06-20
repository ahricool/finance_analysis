# -*- coding: utf-8 -*-
"""
API 模块初始化
===================================

职责：
1. 导出 API 模块的公共接口
2. 统一版本管理
"""

from finance_analysis.interfaces.api.app import _check_frontend_assets_consistency

__version__ = "1.0.0"

__all__ = ["__version__", "_check_frontend_assets_consistency"]
