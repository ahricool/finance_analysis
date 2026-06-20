# -*- coding: utf-8 -*-
"""Tests for database session configuration."""

from unittest.mock import Mock, patch

from finance_analysis.database import DatabaseManager


def test_database_sessions_do_not_expire_on_commit():
    DatabaseManager.reset_instance()
    config = Mock()
    config.get_db_url.return_value = "postgresql+psycopg2://user:pass@localhost:5432/test"
    config.db_pool_size = 1
    config.db_max_overflow = 0
    config.db_pool_recycle = 300

    try:
        with (
            patch("finance_analysis.database.config.get_database_config", return_value=config),
            patch("finance_analysis.database.session.create_engine", return_value=object()),
            patch("finance_analysis.database.session.event.listen"),
            patch("finance_analysis.database.session.bootstrap_database"),
        ):
            db = DatabaseManager()

        assert db._SessionLocal.kw["expire_on_commit"] is False
    finally:
        DatabaseManager.reset_instance()
