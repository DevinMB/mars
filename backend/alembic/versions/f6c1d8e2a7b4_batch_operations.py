"""bulk job actions, run by the console rather than a browser

Revision ID: f6c1d8e2a7b4
Revises: e4b7c2a9f150
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = 'f6c1d8e2a7b4'
down_revision = 'e4b7c2a9f150'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "batch_operations" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "batch_operations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("cluster", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("items", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_batch_operations_status", "batch_operations", ["status"])


def downgrade() -> None:
    if "batch_operations" in inspect(op.get_bind()).get_table_names():
        op.drop_index("ix_batch_operations_status", table_name="batch_operations")
        op.drop_table("batch_operations")
