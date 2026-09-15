"""savepoints on job runs

Revision ID: d2b8c4f10e57
Revises: c91a5f38d7b2
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = 'd2b8c4f10e57'
down_revision = 'c91a5f38d7b2'
branch_labels = None
depends_on = None

COLUMNS = {
    "savepoint_path": sa.Column("savepoint_path", sa.String(length=1024), nullable=True),
    "restored_from": sa.Column("restored_from", sa.String(length=1024), nullable=True),
}


def _columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """Records where a run's state was saved, and where it resumed from.

    Without this a restart of a stateful job silently starts from empty state:
    a half-finished session window, a running count or a join buffer is gone,
    and nothing in the console said so.
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
