"""Virtual position transitions on BTC state and snapshots; no execution table."""

import sqlalchemy as sa

from alembic import op

revision = "0060_crypto_positions"
down_revision = "0059_drop_crypto_kline"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "crypto_strategy_state", sa.Column("position_pct", sa.Numeric(18, 12), nullable=False, server_default="0")
    )
    op.add_column("crypto_strategy_state", sa.Column("average_entry_price", sa.Numeric(30, 12)))
    op.execute(
        "UPDATE crypto_strategy_state SET position_pct = CASE WHEN position_state = 'LONG' THEN 1 ELSE 0 END, "
        "average_entry_price = CASE WHEN position_state = 'LONG' THEN entry_price ELSE NULL END"
    )
    for name in ("position_before", "position_after", "position_delta"):
        op.add_column("crypto_strategy_snapshot", sa.Column(name, sa.Numeric(18, 12)))
    op.add_column("crypto_strategy_snapshot", sa.Column("average_entry_price", sa.Numeric(30, 12)))
    # Do not invent historical transitions or entry cost, even on old BUY/EXIT rows.
    op.execute(
        "UPDATE crypto_strategy_snapshot SET position_after = CASE WHEN position_state = 'LONG' THEN 1 ELSE 0 END"
    )
    with op.batch_alter_table("crypto_strategy_state") as batch:
        batch.create_check_constraint("ck_crypto_state_pct", "position_pct >= 0 AND position_pct <= 1")
    with op.batch_alter_table("crypto_strategy_snapshot") as batch:
        batch.create_check_constraint("ck_crypto_snapshot_before", "position_before >= 0 AND position_before <= 1")
        batch.create_check_constraint("ck_crypto_snapshot_after", "position_after >= 0 AND position_after <= 1")
        batch.create_check_constraint("ck_crypto_snapshot_delta", "position_delta = position_after - position_before")


def downgrade():
    with op.batch_alter_table("crypto_strategy_snapshot") as batch:
        for name in ("before", "after", "delta"):
            batch.drop_constraint("ck_crypto_snapshot_" + name, type_="check")
        for name in ("position_before", "position_after", "position_delta", "average_entry_price"):
            batch.drop_column(name)
    with op.batch_alter_table("crypto_strategy_state") as batch:
        batch.drop_constraint("ck_crypto_state_pct", type_="check")
        batch.drop_column("position_pct")
        batch.drop_column("average_entry_price")
