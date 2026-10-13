"""Replace legacy trend results with independently keyed 20/40/60-session runs."""

from alembic import op
import sqlalchemy as sa

revision = "0072_trend_periods"
down_revision = "0071_user_avatar"
branch_labels = None
depends_on = None

TABLES = {
    "trend_following_snapshot": (
        "uix_trend_following_market_date_code", ["market", "trade_date", "code"],
        {
            "ix_trend_following_market_date_alpha": ["market", "trade_date", "alpha_score"],
            "ix_trend_following_instrument_date": ["instrument_id", "trade_date"],
            "ix_trend_following_market_date_state": ["market", "trade_date", "state"],
        },
    ),
    "trend_following_summary": (
        "uix_trend_following_summary_market_date", ["market", "trade_date"],
        {"ix_trend_following_summary_market_date": ["market", "trade_date"]},
    ),
}


def upgrade():
    # The owner will regenerate results; old 15-session scores cannot become 20-session scores.
    for table, (unique, columns, indexes) in TABLES.items():
        op.execute(sa.text(f"DELETE FROM {table}"))
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("trend_period", sa.Integer(), nullable=False, server_default="20"))
            batch.drop_constraint(unique, type_="unique")
            batch.create_unique_constraint(unique, [columns[0], "trend_period", *columns[1:]])
            batch.create_check_constraint(f"ck_{table}_period", "trend_period IN (20, 40, 60)")
            for name, fields in indexes.items():
                batch.drop_index(name)
                batch.create_index(name, [fields[0], "trend_period", *fields[1:]])


def downgrade():
    # Neither periodized results nor the removed legacy results can be translated back.
    for table, (unique, columns, indexes) in TABLES.items():
        op.execute(sa.text(f"DELETE FROM {table}"))
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(unique, type_="unique")
            batch.create_unique_constraint(unique, columns)
            batch.drop_constraint(f"ck_{table}_period", type_="check")
            for name, fields in indexes.items():
                batch.drop_index(name)
                batch.create_index(name, fields)
            batch.drop_column("trend_period")
