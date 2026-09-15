"""Remove chat storage and record backend-neutral LLM attempt statistics.

Conversation contents and per-call stock association are permanently deleted.
Downgrade restores the old schema, not the deleted data.
"""

from alembic import op
import sqlalchemy as sa

revision = "0052_simplify_llm"
down_revision = "0051_us_macro"
branch_labels = None
depends_on = None


def upgrade():
    # Some empty databases were bootstrapped from metadata without chat history.
    op.execute("DROP TABLE IF EXISTS conversation_messages")
    op.drop_column("llm_usage", "stock_code")
    op.alter_column("llm_usage", "prompt_tokens", new_column_name="input_tokens")
    op.alter_column("llm_usage", "completion_tokens", new_column_name="output_tokens")
    op.alter_column("llm_usage", "model", existing_type=sa.String(128), nullable=True)
    op.add_column(
        "llm_usage",
        sa.Column("backend", sa.String(8), nullable=False, server_default="api"),
    )
    op.add_column("llm_usage", sa.Column("engine", sa.String(16), nullable=True))
    op.add_column(
        "llm_usage",
        sa.Column("status", sa.String(16), nullable=False, server_default="success"),
    )
    op.add_column(
        "llm_usage",
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("llm_usage", sa.Column("error", sa.String(500), nullable=True))
    for column in ("backend", "status", "duration_ms"):
        op.alter_column("llm_usage", column, server_default=None)


def downgrade():
    op.execute("UPDATE llm_usage SET model = 'unknown' WHERE model IS NULL")
    for column in ("backend", "engine", "status", "duration_ms", "error"):
        op.drop_column("llm_usage", column)
    op.alter_column("llm_usage", "model", existing_type=sa.String(128), nullable=False)
    op.alter_column("llm_usage", "input_tokens", new_column_name="prompt_tokens")
    op.alter_column("llm_usage", "output_tokens", new_column_name="completion_tokens")
    op.add_column("llm_usage", sa.Column("stock_code", sa.String(16), nullable=True))
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(100), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in ("uid", "session_id", "created_at"):
        op.create_index(f"ix_conversation_messages_{column}", "conversation_messages", [column])
