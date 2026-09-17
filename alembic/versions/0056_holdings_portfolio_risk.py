"""Google Sheet holdings source and portfolio risk state."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB  # pragma: allowlist secret

revision = "0056_holdings_portfolio_risk"
down_revision = "0055_industry_history"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "holding_source",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.Integer(), nullable=False),
        sa.Column("spreadsheet_id", sa.String(length=128), nullable=True),
        sa.Column("accounts_range", sa.String(length=64), nullable=False, server_default="Accounts"),
        sa.Column("positions_range", sa.String(length=64), nullable=False, server_default="Positions"),
        sa.Column("schema_version", sa.String(length=32), nullable=False, server_default="v1"),
        sa.Column("encrypted_credentials", sa.LargeBinary(), nullable=True),
        sa.Column("auth_status", sa.String(length=32), nullable=False, server_default="NOT_CONFIGURED"),
        sa.Column("sync_status", sa.String(length=32), nullable=False, server_default="IDLE"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("published_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("risk_policy", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("policy_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("uid", name="uix_holding_source_uid"),
        sa.CheckConstraint(
            "auth_status IN ('NOT_CONFIGURED','DISCONNECTED','PENDING','CONNECTED',"
            "'CONNECTED_NO_OFFLINE','NEEDS_REAUTH')",
            name="ck_holding_source_auth_status",
        ),
        sa.CheckConstraint(
            "sync_status IN ('IDLE','SYNCING','OK','REJECTED','UNAVAILABLE')",
            name="ck_holding_source_sync_status",
        ),
    )
    op.create_index("ix_holding_source_uid", "holding_source", ["uid"], unique=True)

    op.create_table(
        "position_risk_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("holding_source.id"), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("position_id", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("canonical_symbol", sa.String(length=32), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("rule_version", sa.String(length=32), nullable=False, server_default="v1"),
        sa.Column("last_bar_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_quote_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("weak_streak", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recovery_streak", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("episode_id", sa.String(length=64), nullable=True),
        sa.Column("plan_status", sa.String(length=32), nullable=False, server_default="NONE"),
        sa.Column("plan_action", sa.String(length=16), nullable=False, server_default="HOLD"),
        sa.Column("plan_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_plan", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("legs_state", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "account_id", "position_id", name="uix_position_risk_state_identity"),
    )
    op.create_index("ix_position_risk_state_uid", "position_risk_state", ["uid"])
    op.create_index("ix_position_risk_state_source_id", "position_risk_state", ["source_id"])

    op.create_table(
        "risk_event",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("holding_source.id"), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("position_id", sa.String(length=64), nullable=False),
        sa.Column("leg_id", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("rule_version", sa.String(length=32), nullable=False),
        sa.Column("input_version", sa.String(length=64), nullable=True),
        sa.Column("episode_id", sa.String(length=64), nullable=True),
        sa.Column("plan_revision", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("trigger_quantity", sa.Numeric(28, 8), nullable=True),
        sa.Column("target_quantity", sa.Numeric(28, 8), nullable=True),
        sa.Column("evidence", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("data_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dedupe_key", sa.String(length=190), nullable=False),
        sa.Column("notification_id", sa.Integer(), nullable=True),
        sa.Column("push_status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("uid", "dedupe_key", name="uix_risk_event_uid_dedupe"),
        sa.CheckConstraint(
            "push_status IN ('PENDING','SKIPPED','SENT','FAILED')",
            name="ck_risk_event_push_status",
        ),
    )
    op.create_index("ix_risk_event_uid", "risk_event", ["uid"])
    op.create_index("ix_risk_event_source_id", "risk_event", ["source_id"])
    op.create_index("ix_risk_event_event_type", "risk_event", ["event_type"])


def downgrade():
    op.drop_table("risk_event")
    op.drop_table("position_risk_state")
    op.drop_table("holding_source")
