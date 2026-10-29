"""when a stop with a savepoint was asked for, so reconcile and the supervisor wait

Revision ID: c3f8a1d6e2b7
Revises: b2e9c4d1f8a3
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = 'c3f8a1d6e2b7'
down_revision = 'b2e9c4d1f8a3'
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """Marks a run whose stop-with-savepoint is in flight."""
    if "stop_requested_at" not in _columns("job_runs"):
        with op.batch_alter_table("job_runs", schema=None) as batch_op:
            batch_op.add_column(sa.Column("stop_requested_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    if "stop_requested_at" in _columns("job_runs"):
        with op.batch_alter_table("job_runs", schema=None) as batch_op:
            batch_op.drop_column("stop_requested_at")
