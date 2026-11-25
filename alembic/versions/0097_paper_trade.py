"""Persist Binance Demo strategies, intents, exchange records and equity history."""

from alembic import op
import sqlalchemy as sa

revision = "0097_paper_trade"
down_revision = "0096_contract_market"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "paper_strategy",
        sa.Column("symbol", sa.String(32), primary_key=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("cursor", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(128), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "paper_intent",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("strategy", sa.String(32)),
        sa.Column("bar_time", sa.BigInteger()),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("strategy", "bar_time", name="uq_paper_signal_bar"),
    )
    op.create_table(
        "paper_exchange_record",
        sa.Column("kind", sa.String(16), primary_key=True),
        sa.Column("symbol", sa.String(32), primary_key=True),
        sa.Column("exchange_id", sa.String(80), primary_key=True),
        sa.Column("timestamp", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_paper_exchange_record_timestamp", "paper_exchange_record", ["timestamp"])
    op.create_table(
        "paper_account_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )


def downgrade():
    for table in ("paper_account_snapshot", "paper_exchange_record", "paper_intent", "paper_strategy"):
        op.drop_table(table)
