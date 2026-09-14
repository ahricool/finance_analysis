"""Seed US Macro and include it in the existing US daily synchronization scope."""

from alembic import op
import sqlalchemy as sa

revision = "0051_us_macro"
down_revision = "0050_market_structure_health"
branch_labels = None
depends_on = None


def upgrade():
    from finance_analysis.database.us_macro import seed_us_macro

    seed_us_macro(op.get_bind())


def downgrade():
    # Shared instruments and their authoritative daily history must survive.
    connection = op.get_bind()
    params = {"key": "us_macro"}
    connection.execute(
        sa.text(
            "DELETE FROM universe_include WHERE universe_id IN (SELECT id FROM universe WHERE key=:key) "
            "OR included_universe_id IN (SELECT id FROM universe WHERE key=:key)"
        ),
        params,
    )
    connection.execute(
        sa.text("DELETE FROM universe_member WHERE universe_id IN (SELECT id FROM universe WHERE key=:key)"), params
    )
    connection.execute(sa.text("DELETE FROM universe WHERE key=:key"), params)
