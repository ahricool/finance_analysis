"""Isolate research strategies by durable versioned key and symbol."""

import sqlalchemy as sa

from alembic import op

revision = "0061_crypto_strategy_keys"
down_revision = "0060_crypto_positions"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("crypto_strategy_state", "crypto_strategy_snapshot"):
        op.add_column(table, sa.Column("strategy_key", sa.String(64), nullable=False, server_default="btc_breakout_v1"))
    pk = sa.inspect(op.get_bind()).get_pk_constraint("crypto_strategy_state")["name"] or "pk_crypto_strategy_state"
    with op.batch_alter_table("crypto_strategy_state", naming_convention={"pk": "pk_%(table_name)s"}) as batch:
        batch.alter_column("strategy_key", server_default=None)
        batch.drop_constraint(pk, type_="primary")
        batch.create_primary_key("pk_crypto_strategy_state", ["strategy_key", "symbol"])
    with op.batch_alter_table("crypto_strategy_snapshot") as batch:
        batch.alter_column("strategy_key", server_default=None)
        batch.drop_constraint("uq_crypto_snapshot_symbol_evaluated", type_="unique")
        batch.create_unique_constraint(
            "uq_crypto_snapshot_strategy_symbol_evaluated", ["strategy_key", "symbol", "evaluated_at"]
        )


def downgrade():
    for table in ("crypto_strategy_state", "crypto_strategy_snapshot"):
        if (
            op.get_bind()
            .execute(sa.text(f"SELECT 1 FROM {table} WHERE strategy_key != 'btc_breakout_v1' LIMIT 1"))
            .first()
        ):
            raise ValueError("Cannot downgrade while other strategy data exists")
    with op.batch_alter_table("crypto_strategy_snapshot") as batch:
        batch.drop_constraint("uq_crypto_snapshot_strategy_symbol_evaluated", type_="unique")
        batch.create_unique_constraint("uq_crypto_snapshot_symbol_evaluated", ["symbol", "evaluated_at"])
        batch.drop_column("strategy_key")
    with op.batch_alter_table("crypto_strategy_state") as batch:
        batch.drop_constraint("pk_crypto_strategy_state", type_="primary")
        batch.create_primary_key("pk_crypto_strategy_state", ["symbol"])
        batch.drop_column("strategy_key")
