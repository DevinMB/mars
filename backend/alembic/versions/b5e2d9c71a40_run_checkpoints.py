"""recording each run's latest checkpoint

Revision ID: b5e2d9c71a40
Revises: a82f6c05d3e1
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = 'b5e2d9c71a40'
down_revision = 'a82f6c05d3e1'
branch_labels = None
depends_on = None

COLUMNS = {
    "checkpoint_path": sa.Column("checkpoint_path", sa.String(length=1024), nullable=True),
    "checkpoint_at": sa.Column("checkpoint_at", sa.DateTime(timezone=True), nullable=True),
}


def _columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """Lets a supervised job resume from its last checkpoint after a crash.

    Without HA a JobManager restart erases Flink's record of every job, including
    where its checkpoints were written. Recording the path while the job runs is
    the only way to know it afterwards.
    """
    have = _columns("job_runs")
    with op.batch_alter_table("job_runs", schema=None) as batch_op:
        for name, column in COLUMNS.items():
            if name not in have:
                batch_op.add_column(column)


def downgrade() -> None:
    have = _columns("job_runs")
    with op.batch_alter_table("job_runs", schema=None) as batch_op:
        for name in COLUMNS:
            if name in have:
                batch_op.drop_column(name)
