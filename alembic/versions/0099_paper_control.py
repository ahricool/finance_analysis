"""Move Demo opening control from environment into a persistent admin switch."""

from alembic import op
import sqlalchemy as sa

revision = "0099_paper_control"
down_revision = "0098_live_trade"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "paper_trade_control",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_alias", sa.String(128)),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("paper_trade_control")
