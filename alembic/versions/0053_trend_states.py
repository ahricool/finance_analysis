"""Remove theoretical positions and rebuild trend states from stored indicators.

Snapshot scores and prices are preserved. Stale carried rows and rows without
required indicators are removed; they cannot describe that day's trend.
The removed execution context cannot be restored by downgrade.
"""

import json

from alembic import op
import sqlalchemy as sa

revision = "0053_trend_states"
down_revision = "0052_simplify_llm"
branch_labels = None
depends_on = None

SNAPSHOT_COLUMNS = (
    "action", "entry_price", "signal_date", "signal_price", "pending_action", "pending_since",
    "pending_regime", "pending_max_exposure", "last_add_price", "highest_close", "initial_stop",
    "trailing_stop", "next_add_price", "exit_level", "units", "opened_at",
    "suggested_initial_weight", "suggested_max_weight",
)
SUMMARY_COLUMNS = ("suggested_max_exposure", "entry_count", "add_count", "hold_count", "reduce_count", "exit_count")


def upgrade():
    connection = op.get_bind()
    dates = connection.execute(sa.text(
        "SELECT DISTINCT trade_date FROM trend_following_snapshot ORDER BY trade_date"
    )).scalars().all()
    previous = {}
    for day in dates:
        rows = connection.execute(sa.text(
            "SELECT id, market, code, reference_price, trend_score, rs_score, alpha_score, features, reasons "
            "FROM trend_following_snapshot WHERE trade_date = :day ORDER BY market, code"
        ), {"day": day}).mappings().all()
        for row in rows:
            features = row["features"] or {}
            reasons = row["reasons"] or []
            if isinstance(features, str):
                features = json.loads(features)
            if isinstance(reasons, str):
                reasons = json.loads(reasons)
            required = ("ma10", "ma20", "ma20_slope", "previous_low_10", "trend_candidate", "valid_setup")
            if any(features.get(key) is None for key in required) or any(
                "data unavailable" in reason or "execution data was unavailable" in reason for reason in reasons
            ):
                connection.execute(sa.text("DELETE FROM trend_following_snapshot WHERE id = :id"), {"id": row["id"]})
                continue
            prior = previous.get((row["market"], row["code"]))
            established = prior in {"CANDIDATE", "TRENDING", "WEAKENING"}
            close = row["reference_price"]
            broken = close < features["previous_low_10"] or (
                close < features["ma20"] and features["ma20_slope"] <= 0
            )
            weak = (not features["trend_candidate"] or row["trend_score"] < 60
                    or row["rs_score"] < 55 or close < features["ma10"])
            candidate = (features["trend_candidate"] and features["valid_setup"]
                         and row["trend_score"] >= 62 and row["rs_score"] >= 60 and row["alpha_score"] >= 67)
            if broken and (established or prior == "BROKEN"):
                state = "BROKEN"
            elif established and weak:
                state = "WEAKENING"
            elif established:
                state = "TRENDING"
            elif candidate:
                state = "CANDIDATE"
            else:
                state = "WATCHING" if features["trend_candidate"] else "IDLE"
            previous[row["market"], row["code"]] = state
            connection.execute(sa.text(
                "UPDATE trend_following_snapshot SET state = :state, reasons = :reasons WHERE id = :id"
            ).bindparams(sa.bindparam("reasons", type_=sa.JSON())), {
                "state": state, "reasons": ["trend state rebuilt from stored daily indicators"], "id": row["id"],
            })
    op.execute("""
        UPDATE trend_following_summary AS summary SET candidate_count = (
            SELECT count(*) FROM trend_following_snapshot AS snapshot
            WHERE snapshot.market = summary.market AND snapshot.trade_date = summary.trade_date
              AND snapshot.state = 'CANDIDATE'
        )
    """)
    op.drop_constraint("ck_trend_following_units", "trend_following_snapshot", type_="check")
    for column in SNAPSHOT_COLUMNS:
        op.drop_column("trend_following_snapshot", column)
    for column in SUMMARY_COLUMNS:
        op.drop_column("trend_following_summary", column)
    op.create_check_constraint(
        "ck_trend_following_state", "trend_following_snapshot",
        "state IN ('IDLE', 'WATCHING', 'CANDIDATE', 'TRENDING', 'WEAKENING', 'BROKEN')",
    )


def downgrade():
    raise RuntimeError("Trend execution context was removed; restore a pre-migration backup to downgrade")
