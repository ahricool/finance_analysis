"""Drop the retired signal evaluation table.

Revision ID: 0041_drop_signal
Revises: 0040_daily_sync_universes
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0041_drop_signal"
down_revision = "0040_daily_sync_universes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # DROP TABLE also removes the table's indexes and local constraints.
    if "signal" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("signal")


def downgrade() -> None:
    # Restore the previous schema only; deleted evaluation data cannot be recovered.
    op.create_table(
        "signal",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("name", sa.String(80), nullable=True),
        sa.Column("signal_type", sa.String(80), nullable=True),
        sa.Column("signal_version", sa.String(32), server_default="v1", nullable=False),
        sa.Column("direction", sa.String(16), server_default="neutral", nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("signal_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluation", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("market IN ('CN', 'US', 'HK')", name="ck_signal_market"),
        sa.CheckConstraint("direction IN ('bullish', 'bearish', 'sideways', 'neutral')", name="ck_signal_direction"),
    )
    op.create_index("ix_signal_signal_at", "signal", ["signal_at"])
    op.create_index("ix_signal_market_signal_at_id", "signal", ["market", "signal_at", "id"])
    op.create_index("ix_signal_direction_signal_at", "signal", ["direction", "signal_at"])
    op.create_index("ix_signal_type_signal_at", "signal", ["signal_type", "signal_at"])
