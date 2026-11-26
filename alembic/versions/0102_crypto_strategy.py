"""Persist strategy selection periods and switch-time equity."""
from alembic import op
import sqlalchemy as sa

revision = "0102_crypto_strategy"
down_revision = "0101_contract_underlying"
branch_labels = None
depends_on = None


def upgrade():
    # Retire legacy auto-entry presets; keep their rows for existing exits.
    op.execute("UPDATE paper_strategy SET enabled = false, status = 'PAUSED' WHERE enabled")
    op.create_table("crypto_strategy_period",
                    sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("environment", sa.String(8), nullable=False),
                    sa.Column("strategy", sa.String(32), nullable=False),
                    sa.Column("actor_id", sa.Integer(), nullable=False),
                    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
                    sa.Column("ended_at", sa.DateTime(timezone=True)),
                    sa.Column("start_equity", sa.Numeric(), nullable=False),
                    sa.Column("end_equity", sa.Numeric()))
    op.create_index("uq_crypto_strategy_active", "crypto_strategy_period", ["environment"],
                    unique=True, postgresql_where=sa.text("ended_at IS NULL"), sqlite_where=sa.text("ended_at IS NULL"))


def downgrade():
    op.drop_table("crypto_strategy_period")
