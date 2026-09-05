"""Merge published Signal removal and the Index ETF / CSI2000 migration.

Both 0041 revisions descend from the published 0040. This empty merge keeps
`alembic upgrade head` unambiguous without changing either revision's ancestry.
"""

revision = "0042_merge_reference_heads"
down_revision = ("0041_drop_signal", "0041_index_etf_csi2000")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
