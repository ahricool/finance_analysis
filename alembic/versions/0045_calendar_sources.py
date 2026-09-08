"""Destructively rebuild the finance calendar schema; no legacy event data survives.

Back up before upgrading if old calendar history is needed. After deployment run
Market Calendar Sync to rebuild the upcoming 30-day earnings/macro calendar.
"""

import sqlalchemy as sa

from alembic import op

revision = "0045_calendar_sources"
down_revision = "0044_crypto_btc"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("DELETE FROM finance_events"))
    with op.batch_alter_table("finance_events") as batch:
        batch.alter_column("financial_market_time", new_column_name="market_session", existing_type=sa.String(64))
        batch.add_column(sa.Column("reporting_period", sa.String(64)))
        for name in ("eps_estimate", "reported_eps", "eps_surprise_pct"):
            batch.add_column(sa.Column(name, sa.Float()))
        batch.drop_index("ix_finance_events_star")
        for name in ("activity_type", "date_type", "star", "data_kv_json"):
            batch.drop_column(name)
        batch.create_check_constraint("ck_finance_events_type", "calendar_type IN ('earnings', 'macro')")
        batch.create_check_constraint(
            "ck_finance_events_scope",
            "(calendar_type = 'macro' AND market = 'US' AND symbol IS NULL) OR "
            "(calendar_type = 'earnings' AND market IN ('US', 'CN') AND symbol IS NOT NULL)",
        )


def downgrade():
    raise RuntimeError("Calendar data deletion is irreversible; restore a pre-migration backup to roll back.")
