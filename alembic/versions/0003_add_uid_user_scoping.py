"""Add uid columns for per-user data isolation.

Revision ID: 0003_add_uid_user_scoping
Revises: 0002_users_extra_jsonb
Create Date: 2026-06-16
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_add_uid_user_scoping"
down_revision: Union[str, Sequence[str], None] = "0002_users_extra_jsonb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # analysis_history
    op.execute(
        """
        ALTER TABLE analysis_history
        ADD COLUMN IF NOT EXISTS uid INTEGER;
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_analysis_history_uid ON analysis_history (uid)")
    op.execute(
        """
        UPDATE analysis_history ah
        SET uid = u.id
        FROM users u
        WHERE ah.uid IS NULL
          AND u.email = 'whoreahri@gmail.com';
        """
    )
    op.execute(
        """
        UPDATE analysis_history
        SET uid = (SELECT MIN(id) FROM users)
        WHERE uid IS NULL
          AND EXISTS (SELECT 1 FROM users);
        """
    )

    # backtest_summaries
    op.execute(
        """
        ALTER TABLE backtest_summaries
        ADD COLUMN IF NOT EXISTS uid INTEGER;
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_backtest_summaries_uid ON backtest_summaries (uid)")
    op.execute(
        """
        UPDATE backtest_summaries
        SET uid = (SELECT MIN(id) FROM users)
        WHERE uid IS NULL
          AND EXISTS (SELECT 1 FROM users);
        """
    )
    op.execute(
        """
        ALTER TABLE backtest_summaries
        DROP CONSTRAINT IF EXISTS uix_backtest_summary_scope_code_window_version;
        """
    )
    op.execute(
        """
        ALTER TABLE backtest_summaries
        ADD CONSTRAINT uix_backtest_summary_uid_scope_code_window_version
        UNIQUE (uid, scope, code, eval_window_days, engine_version);
        """
    )

    # news_intel
    op.execute(
        """
        ALTER TABLE news_intel
        ADD COLUMN IF NOT EXISTS uid INTEGER;
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_news_intel_uid ON news_intel (uid)")
    op.execute(
        """
        UPDATE news_intel ni
        SET uid = ah.uid
        FROM analysis_history ah
        WHERE ni.uid IS NULL
          AND ni.query_id IS NOT NULL
          AND ni.query_id = ah.query_id
          AND ah.uid IS NOT NULL;
        """
    )
    op.execute(
        """
        UPDATE news_intel
        SET uid = (SELECT MIN(id) FROM users)
        WHERE uid IS NULL
          AND EXISTS (SELECT 1 FROM users);
        """
    )

    # fundamental_snapshot
    op.execute(
        """
        ALTER TABLE fundamental_snapshot
        ADD COLUMN IF NOT EXISTS uid INTEGER;
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_fundamental_snapshot_uid ON fundamental_snapshot (uid)")
    op.execute(
        """
        UPDATE fundamental_snapshot fs
        SET uid = ah.uid
        FROM analysis_history ah
        WHERE fs.uid IS NULL
          AND fs.query_id = ah.query_id
          AND ah.uid IS NOT NULL;
        """
    )
    op.execute(
        """
        UPDATE fundamental_snapshot
        SET uid = (SELECT MIN(id) FROM users)
        WHERE uid IS NULL
          AND EXISTS (SELECT 1 FROM users);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE backtest_summaries
        DROP CONSTRAINT IF EXISTS uix_backtest_summary_uid_scope_code_window_version;
        """
    )
    op.execute(
        """
        ALTER TABLE backtest_summaries
        ADD CONSTRAINT uix_backtest_summary_scope_code_window_version
        UNIQUE (scope, code, eval_window_days, engine_version);
        """
    )
    op.execute("ALTER TABLE fundamental_snapshot DROP COLUMN IF EXISTS uid")
    op.execute("ALTER TABLE news_intel DROP COLUMN IF EXISTS uid")
    op.execute("ALTER TABLE backtest_summaries DROP COLUMN IF EXISTS uid")
    op.execute("ALTER TABLE analysis_history DROP COLUMN IF EXISTS uid")
