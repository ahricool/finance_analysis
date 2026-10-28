"""Move disposable research previews into latest-only PostgreSQL tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0078_research_preview"
down_revision = "0077_core_index_etf_sync"
branch_labels = None
depends_on = None


def upgrade():
    json_type = sa.JSON().with_variant(JSONB(), "postgresql")
    op.create_table(
        "research_preview",
        sa.Column("namespace", sa.String(32), primary_key=True),
        sa.Column("market", sa.String(8), primary_key=True),
        sa.Column("variant", sa.Integer(), primary_key=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("header", json_type, nullable=False),
        sa.Column("shared", json_type, nullable=False),
        sa.CheckConstraint("market IN ('CN', 'US')", name="ck_research_preview_market"),
        sa.CheckConstraint("variant IN (0, 20, 40, 60)", name="ck_research_preview_variant"),
    )
    op.create_table(
        "research_preview_item",
        sa.Column("namespace", sa.String(32), primary_key=True),
        sa.Column("market", sa.String(8), primary_key=True),
        sa.Column("variant", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(64), primary_key=True),
        sa.Column("item_key", sa.String(64), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instrument.id", ondelete="SET NULL")),
        sa.Column("has_name", sa.Boolean(), nullable=False),
        sa.Column("summary", json_type, nullable=False),
        sa.Column("detail", json_type, nullable=False),
        sa.ForeignKeyConstraint(
            ["namespace", "market", "variant"],
            ["research_preview.namespace", "research_preview.market", "research_preview.variant"],
            ondelete="CASCADE", name="fk_research_preview_item_batch",
        ),
    )


def downgrade():
    op.drop_table("research_preview_item")
    op.drop_table("research_preview")
