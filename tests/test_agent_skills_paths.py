# -*- coding: utf-8 -*-
"""Tests for built-in agent strategy directory resolution."""

from __future__ import annotations

from finance_analysis.agent.skills import base as skills_base
from finance_analysis.agent.skills import defaults as skills_defaults
from finance_analysis.core.paths import PROJECT_ROOT, STRATEGIES_DIR


def test_strategies_dir_points_at_repo_root_strategies() -> None:
    assert STRATEGIES_DIR == PROJECT_ROOT / "strategies"
    assert STRATEGIES_DIR.is_dir()


def test_builtin_skill_dirs_use_strategies_dir() -> None:
    assert skills_base._BUILTIN_SKILLS_DIR == STRATEGIES_DIR
    assert skills_defaults._BUILTIN_SKILLS_DIR == STRATEGIES_DIR
