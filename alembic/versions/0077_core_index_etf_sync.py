"""Include core index ETFs in daily ingestion without expanding strategy pools."""

from alembic import op
import sqlalchemy as sa

revision = "0077_core_index_etf_sync"
down_revision = "0076_stock_strategies"
branch_labels = None
depends_on = None


def upgrade():
    from finance_analysis.database.core_index_etf import seed_core_index_etfs

    seed_core_index_etfs(op.get_bind())


def downgrade():
    # Only remove memberships introduced here; retain identities and price history.
    op.execute(sa.text("""
        DELETE FROM universe_member
        WHERE source = 'CORE_INDEX_ETF'
          AND universe_id IN (SELECT id FROM universe WHERE key IN ('cn_daily_sync', 'us_daily_sync'))
    """))
