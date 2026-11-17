"""Dedicated underlying paper trades and durable signal events."""

from alembic import op
import sqlalchemy as sa

revision = "0093_intraday_simulation"
down_revision = "0092_retire_prediction_catalog"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "intraday_simulation_state",
        sa.Column("symbol", sa.String(32), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "intraday_simulation_trade",
        sa.Column("id", sa.String(256), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("process_id", sa.String(192), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("symbol", "process_id"),
    )
    op.create_table(
        "intraday_simulation_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    for table, fields in [
        ("intraday_simulation_trade", ["symbol", "trading_date"]),
        ("intraday_simulation_event", ["symbol", "occurred_at"]),
    ]:
        for field in fields:
            op.create_index(f"ix_{table}_{field}", table, [field])

    op.create_index(
        "uq_intraday_simulation_open",
        "intraday_simulation_trade",
        ["symbol"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )


def downgrade():
    for name in ("intraday_simulation_event", "intraday_simulation_trade", "intraday_simulation_state"):
        op.drop_table(name)
