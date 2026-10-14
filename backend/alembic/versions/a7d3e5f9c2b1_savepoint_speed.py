"""savepoint size and duration, and options on bulk actions

Revision ID: a7d3e5f9c2b1
Revises: f6c1d8e2a7b4
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = 'a7d3e5f9c2b1'
down_revision = 'f6c1d8e2a7b4'
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """Measured savepoint speed, so waits and estimates scale with state size."""
    have = _columns("job_runs")
    with op.batch_alter_table("job_runs", schema=None) as batch_op:
        if "savepoint_bytes" not in have:
            batch_op.add_column(sa.Column("savepoint_bytes", sa.BigInteger(), nullable=True))
        if "savepoint_ms" not in have:
            batch_op.add_column(sa.Column("savepoint_ms", sa.Integer(), nullable=True))
    if "options" not in _columns("batch_operations"):
        with op.batch_alter_table("batch_operations", schema=None) as batch_op:
            batch_op.add_column(sa.Column("options", sa.Text(), nullable=False, server_default="{}"))


def downgrade() -> None:
    have = _columns("job_runs")
    with op.batch_alter_table("job_runs", schema=None) as batch_op:
        for name in ("savepoint_bytes", "savepoint_ms"):
            if name in have:
                batch_op.drop_column(name)
    if "options" in _columns("batch_operations"):
        with op.batch_alter_table("batch_operations", schema=None) as batch_op:
            batch_op.drop_column("options")
