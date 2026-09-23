"""Include every US postmarket benchmark/sector ETF in explicit daily ingestion."""

from alembic import op
import sqlalchemy as sa

revision = "0068_us_postmarket_sync"
down_revision = "0067_signal_center"
branch_labels = None
depends_on = None


def upgrade():
    from finance_analysis.database.us_postmarket import seed_us_postmarket_symbols

    seed_us_postmarket_symbols(op.get_bind())


def downgrade():
    # Preserve instruments, their history and pre-existing direct memberships.
    op.execute(sa.text("""
        DELETE FROM universe_member
        WHERE source = 'US_POSTMARKET_REVIEW'
          AND universe_id = (SELECT id FROM universe WHERE key = 'us_daily_sync')
    """))
