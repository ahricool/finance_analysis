"""Retain independently sampled USD-M market metrics after watchlist removal."""
from alembic import op
import sqlalchemy as sa

revision = "0103_futures_metric_sample"
down_revision = "0102_crypto_strategy"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "futures_metric_sample",
        sa.Column("symbol", sa.String(32), primary_key=True),
        sa.Column("period", sa.String(4), primary_key=True),
        sa.Column("timestamp", sa.BigInteger(), primary_key=True),
        *(sa.Column(name, sa.JSON()) for name in ("accounts", "top_accounts", "top_positions", "oi", "taker", "price")),
    )


def downgrade():
    op.drop_table("futures_metric_sample")
