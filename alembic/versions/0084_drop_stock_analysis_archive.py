"""Delete the retired stock reports and fundamental snapshots, including data."""

from alembic import op

revision = "0084_drop_stock_analysis_archive"
down_revision = "0083_retire_stock_analysis"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DROP TABLE IF EXISTS fundamental_snapshot")
    op.execute("DROP TABLE IF EXISTS analysis_history")


def downgrade():
    raise RuntimeError("Stock analysis archive deletion is irreversible; deleted data cannot be restored")
