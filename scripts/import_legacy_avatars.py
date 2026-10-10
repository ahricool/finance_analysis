"""Retry the legacy avatar import after restoring the original DATA_DIR volume.

Run: uv run python scripts/import_legacy_avatars.py
"""

import importlib.util
from pathlib import Path

from finance_analysis.config import load_env
from finance_analysis.database.session import DatabaseManager


def main():
    load_env()
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0071_user_avatar.py"
    spec = importlib.util.spec_from_file_location("avatar_revision", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        migration.import_legacy_avatars(session.connection())
        session.commit()


if __name__ == "__main__":
    main()
