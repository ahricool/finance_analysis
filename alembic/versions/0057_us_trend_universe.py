"""Expand daily coverage while keeping Trend and Market Structure scopes independent."""

from alembic import op
import sqlalchemy as sa

revision = "0057_us_trend_universe"
down_revision = "0056_market_sentiment"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    for key, name, market, kind in (
        ("us_sp400", "S&P MidCap 400", "US", "INDEX"),
        ("us_market_structure", "美股市场结构", "US", "STRATEGY"),
        ("cn_market_structure", "A股市场结构", "CN", "STRATEGY"),
    ):
        connection.execute(sa.text("""
            INSERT INTO universe (key, name, market, universe_type, enabled, config, created_at, updated_at)
            VALUES (:key, :name, :market, :kind, true, '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (key) DO NOTHING
        """), {"key": key, "name": name, "market": market, "kind": kind})
    for parent, child in (
        ("us_trend", "us_sp400"),
        ("us_trend", "us_nasdaq100"),
        ("us_daily_sync", "us_sp500"),
        ("us_daily_sync", "us_sp400"),
        ("us_daily_sync", "us_nasdaq100"),
        ("cn_daily_sync", "cn_csi2000"),
        ("us_market_structure", "us_sp500"),
        ("cn_market_structure", "cn_csi300"),
        ("cn_market_structure", "cn_csi500"),
        ("cn_market_structure", "cn_csi1000"),
    ):
        connection.execute(sa.text("""
            INSERT INTO universe_include (universe_id, included_universe_id, created_at)
            SELECT p.id, c.id, CURRENT_TIMESTAMP FROM universe p, universe c
            WHERE p.key = :parent AND c.key = :child
            ON CONFLICT (universe_id, included_universe_id) DO NOTHING
        """), {"parent": parent, "child": child})
    connection.execute(sa.text("""
        DELETE FROM universe_include
        WHERE universe_id = (SELECT id FROM universe WHERE key = 'us_daily_sync')
          AND included_universe_id = (SELECT id FROM universe WHERE key = 'us_trend')
    """))


def downgrade():
    # Keep collected memberships and snapshots; restoring a smaller universe does
    # not safely restore the strategy's historical ranking/coverage semantics.
    raise NotImplementedError("US Trend universe expansion requires a forward migration")
