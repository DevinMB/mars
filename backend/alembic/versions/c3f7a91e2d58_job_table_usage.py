"""remembering which tables Flink's plan says a job reads and writes

Revision ID: c3f7a91e2d58
Revises: b5e2d9c71a40
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = 'c3f7a91e2d58'
down_revision = 'b5e2d9c71a40'
branch_labels = None
depends_on = None

COLUMNS = {
    "tables_read": sa.Column("tables_read", sa.Text(), nullable=True),
    "tables_written": sa.Column("tables_written", sa.Text(), nullable=True),
    "tables_from": sa.Column("tables_from", sa.String(length=8), nullable=True),
    "tables_key": sa.Column("tables_key", sa.String(length=64), nullable=True),
}


def _columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """Lets the catalog show which jobs read and write each table.

    A catalog entry's source/sink role is replaced by how jobs actually use it,
    taken from Flink's plan when a job is validated. Until then, or after its SQL
    changes, it is read from the SQL, so nothing needs backfilling.
    """
    have = _columns("jobs")
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        for name, column in COLUMNS.items():
            if name not in have:
                batch_op.add_column(column)


def downgrade() -> None:
    have = _columns("jobs")
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        for name in COLUMNS:
            if name in have:
                batch_op.drop_column(name)
