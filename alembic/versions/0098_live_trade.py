"""Separate read-only Binance Live account history and persisted control."""

from alembic import op
import sqlalchemy as sa

revision = "0098_live_trade"
down_revision = "0097_paper_trade"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "live_trade_control",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_alias", sa.String(128)),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "live_trade_control_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("previous", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "live_exchange_record",
        sa.Column("kind", sa.String(16), primary_key=True),
        sa.Column("symbol", sa.String(32), primary_key=True),
        sa.Column("exchange_id", sa.String(80), primary_key=True),
        sa.Column("timestamp", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_live_exchange_record_timestamp", "live_exchange_record", ["timestamp"])
    op.create_table(
        "live_account_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )


def downgrade():
    for table in ("live_account_snapshot", "live_exchange_record", "live_trade_control_event", "live_trade_control"):
        op.drop_table(table)
