"""when retention removed a run's savepoint

Revision ID: e4b7c2a9f150
Revises: d8a2f4c6b913
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = 'e4b7c2a9f150'
down_revision = 'd8a2f4c6b913'
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """Old savepoints are now removed; the run keeps its path and says when."""
    if "savepoint_removed_at" not in _columns("job_runs"):
        with op.batch_alter_table("job_runs", schema=None) as batch_op:
            batch_op.add_column(sa.Column("savepoint_removed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    if "savepoint_removed_at" in _columns("job_runs"):
        with op.batch_alter_table("job_runs", schema=None) as batch_op:
            batch_op.drop_column("savepoint_removed_at")
