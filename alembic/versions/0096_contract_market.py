"""Replace BTC strategy research with editable USD-M perpetual contracts."""
from datetime import datetime, timedelta, timezone

from alembic import op
import sqlalchemy as sa

revision = "0096_contract_market"
down_revision = "0095_daily_forecast_accuracy"
branch_labels = None
depends_on = None

DEFAULTS = (
    ("BTCUSDT", "加密货币"), ("SOXLUSDT", "ETF"), ("ETHUSDT", "加密货币"),
    ("XAUUSDT", "黄金"), ("NVDAUSDT", "美股"), ("SOXSUSDT", "ETF"),
    ("SKHYNIXUSDT", "韩股"), ("SNDKUSDT", "美股"), ("SPCXUSDT", "美股市场"),
    ("SOLUSDT", "加密货币"), ("XAGUSDT", "白银"), ("ZECUSDT", "加密货币"),
    ("MUUSDT", "美股"), ("ANTUSDT", "美股市场"), ("KORUUSDT", "ETF"),
    ("QQQUSDT", "ETF"), ("SKHYUSDT", "美股市场"), ("CLUSDT", "WTI原油"),
    ("SNXXUSDT", "美股市场"),
)


def seed_rows():
    now = datetime.now(timezone.utc)
    return [{"symbol": symbol, "category": category, "created_at": now + timedelta(microseconds=index)}
            for index, (symbol, category) in enumerate(DEFAULTS)]


def seed(connection):
    table = sa.table("futures_contract", sa.column("symbol"), sa.column("category"), sa.column("created_at", sa.DateTime(timezone=True)))
    connection.execute(table.insert(), seed_rows())


def upgrade():
    op.drop_table("crypto_strategy_snapshot")
    op.drop_table("crypto_strategy_state")
    op.execute("DELETE FROM task WHERE task_type = 'scheduled_crypto_btc_strategy' "
               "OR scheduler_job_id = 'crypto_btc_strategy'")
    op.create_table(
        "futures_contract", sa.Column("symbol", sa.String(32), primary_key=True),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "futures_daily_bar",
        sa.Column("symbol", sa.String(32), sa.ForeignKey("futures_contract.symbol", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("timestamp", sa.BigInteger(), primary_key=True),
        *(sa.Column(field, sa.Float(), nullable=False)
          for field in ("open", "high", "low", "close", "volume", "turnover")),
    )
    if op.get_context().as_sql:
        table = sa.table("futures_contract", sa.column("symbol", sa.String), sa.column("category", sa.String),
                         sa.column("created_at", sa.DateTime(timezone=True)))
        op.bulk_insert(table, seed_rows())
    else:
        seed(op.get_bind())


def downgrade():
    raise RuntimeError("Retired BTC strategy history cannot be restored; restore a pre-migration backup.")
