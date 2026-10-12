"""tags on jobs

Revision ID: b2e9c4d1f8a3
Revises: a7d3e5f9c2b1
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = 'b2e9c4d1f8a3'
down_revision = 'a7d3e5f9c2b1'
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """Labels for grouping jobs; every existing job starts with none."""
    if "tags" not in _columns("jobs"):
        with op.batch_alter_table("jobs", schema=None) as batch_op:
            batch_op.add_column(sa.Column("tags", sa.Text(), nullable=False, server_default="[]"))


def downgrade() -> None:
    if "tags" in _columns("jobs"):
        with op.batch_alter_table("jobs", schema=None) as batch_op:
            batch_op.drop_column("tags")
