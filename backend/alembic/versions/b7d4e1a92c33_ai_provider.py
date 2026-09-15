"""the model MARS talks to

Revision ID: b7d4e1a92c33
Revises: a3f1c72b9e04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = 'b7d4e1a92c33'
down_revision = 'a3f1c72b9e04'
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    """One row describing the model every AI feature uses.

    The API key is deliberately absent: secret_name points into the existing
    encrypted secret store, so a model credential is handled the same way as a
    database password rather than through a second mechanism that would have to
    be secured, redacted and audited separately.
    """
    if "ai_provider" not in _tables():
        op.create_table(
            "ai_provider",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("base_url", sa.String(length=512), nullable=False),
            sa.Column("model", sa.String(length=128), nullable=False),
            sa.Column("secret_name", sa.String(length=128), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("timeout_seconds", sa.Integer(), nullable=False),
            sa.Column("updated_by", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    if "ai_provider" in _tables():
        op.drop_table("ai_provider")
