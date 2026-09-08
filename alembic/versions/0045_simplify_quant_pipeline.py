"""Remove unused Quant event, sector, feature, and holdings designs.

Revision ID: 0045_simplify_quant
Revises: 0044_crypto_btc
"""

from alembic import op


revision = "0045_simplify_quant"
down_revision = "0044_crypto_btc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("event_feature_daily")
    op.drop_table("market_event")
    op.drop_table("daily_feature_snapshot")
    op.drop_table("model_prediction")
    op.drop_table("sector_regime_snapshot")

    op.drop_column("market_regime_snapshot", "sector_permissions")

    for column in (
        "sector_score",
        "event_score",
        "raw_final_score",
        "gated_final_score",
        "sector_rank",
        "target_position",
        "vetoed",
        "veto_reason",
    ):
        op.drop_column("model_signal", column)

    op.drop_constraint(
        "ck_portfolio_item_action",
        "portfolio_recommendation_item",
        type_="check",
    )
    for column in (
        "sector_key",
        "previous_rank",
        "action",
        "current_weight",
        "weight_change",
    ):
        op.drop_column("portfolio_recommendation_item", column)


def downgrade() -> None:
    raise NotImplementedError("Destructive Quant simplification is intentionally irreversible")
