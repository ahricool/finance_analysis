# -*- coding: utf-8 -*-
"""Tests for database session configuration."""

from unittest.mock import Mock, patch

from src.storage import DatabaseManager


def test_database_sessions_do_not_expire_on_commit():
    DatabaseManager.reset_instance()
    config = Mock()
    config.get_db_url.return_value = "postgresql+psycopg2://user:pass@localhost:5432/test"
    config.db_pool_size = 1
    config.db_max_overflow = 0
    config.db_pool_recycle = 300

    try:
        with (
            patch("src.db.session.get_config", return_value=config),
            patch("src.db.session.create_engine", return_value=object()),
            patch("src.db.session.event.listen"),
            patch("src.db.session.bootstrap_database"),
        ):
            db = DatabaseManager()

        assert db._SessionLocal.kw["expire_on_commit"] is False
    finally:
        DatabaseManager.reset_instance()
