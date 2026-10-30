"""Quant paired releases and immutable daily executions. No legacy data is deleted."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0081_quant_lifecycle"
down_revision = "0080_signal_center_v2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "quant_model_release",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("cross_section_id", sa.BigInteger(), sa.ForeignKey("model_run.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("time_series_id", sa.BigInteger(), sa.ForeignKey("model_run.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uix_quant_active_release", "quant_model_release", ["market"], unique=True,
                    postgresql_where=sa.text("active = true"))
    op.create_table(
        "quant_execution",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("universe_id", sa.Integer(), sa.ForeignKey("universe.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("release_id", sa.BigInteger(), sa.ForeignKey("quant_model_release.id", ondelete="RESTRICT")),
        sa.Column("task_id", sa.String(64)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("input_uri", sa.Text()),
        sa.Column("summary", JSONB(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('preparing','predicting','complete','failed')", name="ck_quant_execution_status"),
    )
    op.create_index("uix_quant_execution_active", "quant_execution", ["market", "trade_date"], unique=True,
                    postgresql_where=sa.text("status IN ('preparing','predicting')"))
    op.create_index("ix_quant_execution_latest", "quant_execution", ["market", "trade_date", "created_at"])
    op.execute("""
        INSERT INTO quant_model_release (market, cross_section_id, time_series_id, active, reason, created_at)
        SELECT cs.market, cs.id, ts.id, true, 'Migrated existing production pair', CURRENT_TIMESTAMP
        FROM model_run cs JOIN model_run ts ON cs.market = ts.market AND cs.universe_id = ts.universe_id
        WHERE cs.status = 'production' AND cs.model_key = 'cross_section_lgbm'
          AND ts.status = 'production' AND ts.model_key = 'time_series_lgbm'
        ON CONFLICT DO NOTHING
    """)


def downgrade():
    op.drop_table("quant_execution")
    op.drop_table("quant_model_release")
