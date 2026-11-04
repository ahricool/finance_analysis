"""Allow ten-session Trend results while retaining historical sixty-session rows."""

from alembic import op
import sqlalchemy as sa

revision = "0090_trend_ten_day"
down_revision = "0089_retire_us_postmarket"
branch_labels = None
depends_on = None

CONSTRAINTS = (
    ("trend_following_snapshot", "ck_trend_following_snapshot_period", "trend_period", (20, 40, 60)),
    ("trend_following_summary", "ck_trend_following_summary_period", "trend_period", (20, 40, 60)),
    ("research_preview", "ck_research_preview_variant", "variant", (0, 20, 40, 60)),
)


def upgrade():
    for table, name, column, periods in CONSTRAINTS:
        allowed = ", ".join(str(value) for value in sorted((*periods, 10)))
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_="check")
            batch.create_check_constraint(name, f"{column} IN ({allowed})")


def downgrade():
    # Only newly introduced ten-session results are incompatible with the old schema.
    # Preview items are removed explicitly for SQLite as well as PostgreSQL cascades.
    op.execute(sa.text(
        "DELETE FROM research_preview_item WHERE variant = 10"
    ))
    for table, name, column, periods in CONSTRAINTS:
        op.execute(sa.text(f"DELETE FROM {table} WHERE {column} = 10"))
        allowed = ", ".join(str(value) for value in periods)
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_="check")
            batch.create_check_constraint(name, f"{column} IN ({allowed})")
