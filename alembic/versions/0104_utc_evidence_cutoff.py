"""Normalize structured macro observation cutoffs without recomputing evidence."""

from alembic import op

revision = "0104_utc_evidence_cutoff"
down_revision = "0103_futures_metric_sample"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return  # Historical SQLite fixtures do not store production JSONB evidence.
    # Only these two source fields encode the market-local cutoff. The signal
    # center's frozen model inputs, prompts and citations are audit originals.
    for table, column in (("confluence_run", "source_availability"), ("confluence_snapshot", "signals")):
        path = "'{macro,evidence,cutoff}'"
        stamp = f"({column} #>> {path})"
        op.execute(f"""
            UPDATE {table}
            SET {column} = jsonb_set({column}, {path}, to_jsonb(
                to_char(({stamp})::timestamptz AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
            ), false)
            WHERE {stamp} ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}([.][0-9]+)?[+-][0-9]{{2}}:[0-9]{{2}}$'
        """)


def downgrade():
    # Both application versions accept an ISO timestamp with an explicit offset.
    pass
