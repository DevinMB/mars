"""an optional schema registry

Revision ID: a82f6c05d3e1
Revises: f0a71d2b8c94
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = 'a82f6c05d3e1'
down_revision = 'f0a71d2b8c94'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Where an Avro schema can be looked up, when there is somewhere to look.

    Optional by design: no row enabled means nothing about Avro appears, which is
    right for the installations that never touch it. The credential is a reference
    into the secret store rather than a second place credentials can live.
    """
    if "schema_registry" in set(inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "schema_registry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("auth_method", sa.String(length=16), nullable=False, server_default="none"),
        sa.Column("username", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("secret_name", sa.String(length=128), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    if "schema_registry" in set(inspect(op.get_bind()).get_table_names()):
        op.drop_table("schema_registry")
