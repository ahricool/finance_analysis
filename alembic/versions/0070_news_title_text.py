"""Preserve original news headlines longer than the old 300-character limit."""

from alembic import op
import sqlalchemy as sa

revision = "0070_news_title_text"
down_revision = "0069_earnings_outlook"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("news_intel", "title", existing_type=sa.String(300), type_=sa.Text(),
                    existing_nullable=False)


def downgrade():
    # Fail instead of silently truncating original news facts on rollback.
    op.alter_column("news_intel", "title", existing_type=sa.Text(), type_=sa.String(300),
                    existing_nullable=False)
