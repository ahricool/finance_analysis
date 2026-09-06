"""Replace task Calendar with the investment timeline and structured news judgments.

Historical Calendar rows are deliberately discarded. News query/symbol associations
are retained in usage rows before removing contextual columns from news facts.
"""

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    inspect,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0043_investment_timeline"
down_revision = "0042_merge_reference_heads"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    metadata = MetaData()
    Table("news_intel", metadata, Column("id", Integer, primary_key=True))
    table = Table(
        "timeline_entries",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("uid", Integer, nullable=False, index=True),
        Column("entry_type", String(32), nullable=False, index=True),
        Column("market", String(16), nullable=True, index=True),
        Column("event_time", DateTime(timezone=True), nullable=False, index=True),
        Column("title", String(300), nullable=False),
        Column("summary", String(500), nullable=False),
        Column("content", Text, nullable=False),
        Column("importance", String(16), nullable=False, server_default="normal", index=True),
        Column("actionability", String(24), nullable=False, server_default="none", index=True),
        Column("symbol", String(32)),
        Column(
            "related_symbols", JSON().with_variant(JSONB(), "postgresql"), nullable=False, server_default=text("'[]'")
        ),
        Column("source_task", String(128)),
        Column("source_run_id", String(64), index=True),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")),
        CheckConstraint(
            "entry_type IN ('a_share_pre_close','us_premarket','us_postmarket','manual_note')", name="ck_timeline_type"
        ),
        CheckConstraint("importance IN ('low','normal','high','critical')", name="ck_timeline_importance"),
        CheckConstraint("actionability IN ('none','watch','consider','action_required')", name="ck_timeline_action"),
    )
    table.create(bind, checkfirst=True)
    table = Table(
        "news_analysis",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("news_intel_id", Integer, ForeignKey("news_intel.id", ondelete="CASCADE"), nullable=False, index=True),
        Column("analysis_type", String(32), nullable=False),
        Column("importance_score", Integer, nullable=False),
        Column("importance_reason", Text),
        Column("event_type", String(64)),
        Column("time_sensitivity", String(32)),
        Column("importance_confidence", Float),
        Column("impact", String(32)),
        Column("impact_score", Integer),
        Column("impact_reason", Text),
        Column("impact_confidence", Float),
        Column(
            "related_symbols", JSON().with_variant(JSONB(), "postgresql"), nullable=False, server_default=text("'[]'")
        ),
        Column("watch_points", JSON().with_variant(JSONB(), "postgresql"), nullable=False, server_default=text("'[]'")),
        Column("risk_notes", JSON().with_variant(JSONB(), "postgresql"), nullable=False, server_default=text("'[]'")),
        Column("importance", String(16), nullable=False),
        Column("actionability", String(24), nullable=False),
        Column("model", String(128)),
        Column("prompt_version", String(64), nullable=False),
        Column("analyzed_at", DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")),
        UniqueConstraint("news_intel_id", "analysis_type", name="uq_news_analysis_type"),
        CheckConstraint("importance_score BETWEEN 0 AND 10", name="ck_news_importance_score"),
        CheckConstraint("importance IN ('low','normal','high','critical')", name="ck_news_importance"),
        CheckConstraint("actionability IN ('none','watch','consider','action_required')", name="ck_news_action"),
    )
    table.create(bind, checkfirst=True)
    table = Table(
        "news_intel_usage",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("news_intel_id", Integer, ForeignKey("news_intel.id", ondelete="CASCADE"), nullable=False, index=True),
        Column("usage_type", String(32), nullable=False, index=True),
        Column("query_id", String(64), nullable=False, server_default="", index=True),
        Column("symbol", String(32), nullable=False, index=True),
        Column("uid", Integer, index=True),
        Column("observed_at", DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")),
        UniqueConstraint("news_intel_id", "usage_type", "query_id", "symbol", name="uq_news_usage"),
    )
    table.create(bind, checkfirst=True)
    columns = {column["name"] for column in inspect(bind).get_columns("news_intel")}
    if "dimension" in columns:
        op.execute(text("""
            INSERT INTO news_intel_usage (news_intel_id, usage_type, query_id, symbol, uid, observed_at)
            SELECT id, COALESCE(dimension, 'news'), COALESCE(query_id, ''), code, uid,
                   COALESCE(fetched_at, CURRENT_TIMESTAMP)
            FROM news_intel
            ON CONFLICT (news_intel_id, usage_type, query_id, symbol) DO NOTHING
        """))
    for name in (
        "uid",
        "query_id",
        "code",
        "name",
        "dimension",
        "query",
        "query_source",
        "requester_platform",
        "requester_user_id",
        "requester_user_name",
        "requester_chat_id",
        "requester_message_id",
        "requester_query",
    ):
        if name in columns:
            op.drop_column("news_intel", name)
    if "calendar" in inspect(bind).get_table_names():
        op.drop_table("calendar")


def downgrade():
    raise RuntimeError("Investment Timeline migration is destructive; restore a pre-migration backup to roll back.")
