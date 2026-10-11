"""producers and consumers outside Flink, declared for the pipeline view

Revision ID: d8a2f4c6b913
Revises: c3f7a91e2d58
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = 'd8a2f4c6b913'
down_revision = 'c3f7a91e2d58'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """What writes or reads a topic from outside Flink, which no SQL can show."""
    if "external_endpoints" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "external_endpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("resource_key", sa.String(length=512), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("note", sa.String(length=512), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_external_endpoints_resource_key", "external_endpoints", ["resource_key"])


def downgrade() -> None:
    if "external_endpoints" in inspect(op.get_bind()).get_table_names():
        op.drop_index("ix_external_endpoints_resource_key", table_name="external_endpoints")
        op.drop_table("external_endpoints")
