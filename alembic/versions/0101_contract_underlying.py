"""Persist the underlying asset identity for contract detail navigation."""
from alembic import op
import sqlalchemy as sa

revision = "0101_contract_underlying"
down_revision = "0100_minute_forecast_optin"
branch_labels = None
depends_on = None


def backfill(connection):
    # Frozen legacy classification: only known US equity/ETF categories use the US detail API.
    table = sa.table("futures_contract", sa.column("symbol", sa.String),
                     sa.column("category", sa.String), sa.column("underlying_symbol", sa.String))
    base = sa.func.substr(table.c.symbol, 1, sa.func.length(table.c.symbol) - 4)
    suffix = sa.case(
        (table.c.category.in_(("COIN", "加密货币")), ".CRYPTO"),
        (sa.and_(table.c.category.in_(("美股", "ETF", "EQUITY")),
                 base.not_in(("SKHYNIX", "SPCX", "ANT", "SKHY", "SNXX", "XAU", "XAG", "CL"))), ".US"),
        else_=".OTHER",
    )
    connection.execute(table.update().where(table.c.symbol.like("%USDT"), sa.func.length(table.c.symbol) > 4,
                                            table.c.underlying_symbol.is_(None))
                       .values(underlying_symbol=sa.cast(base, sa.String) + suffix))


def upgrade():
    op.add_column("futures_contract", sa.Column("underlying_symbol", sa.String(64), nullable=True))
    backfill(op.get_bind())


def downgrade():
    op.drop_column("futures_contract", "underlying_symbol")
