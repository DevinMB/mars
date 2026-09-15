"""authentication options for the AI provider

Revision ID: c91a5f38d7b2
Revises: b7d4e1a92c33
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = 'c91a5f38d7b2'
down_revision = 'b7d4e1a92c33'
branch_labels = None
depends_on = None

COLUMNS = {
    "auth_method": sa.Column("auth_method", sa.String(length=16), nullable=False,
                             server_default="none"),
    "auth_header": sa.Column("auth_header", sa.String(length=64), nullable=False,
                             server_default=""),
    "auth_username": sa.Column("auth_username", sa.String(length=128), nullable=False,
                               server_default=""),
    "extra_headers": sa.Column("extra_headers", sa.Text(), nullable=False,
                               server_default="{}"),
    "temperature": sa.Column("temperature", sa.String(length=16), nullable=False,
                             server_default="0"),
    "max_tokens": sa.Column("max_tokens", sa.Integer(), nullable=False,
                            server_default="1500"),
}


def _columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """Lets an operator describe how their endpoint expects to be authenticated.

    Providers disagree about this and a rule per provider would be wrong for the
    next one: Anthropic reads x-api-key, OpenAI-compatible servers read a bearer
    token, Azure reads api-key, and a gateway may sit behind basic auth or want
    an extra routing header. So the method, the header name and any extra headers
    are all configuration rather than code.
    """
    if "ai_provider" not in set(inspect(op.get_bind()).get_table_names()):
        return
    have = _columns("ai_provider")
    with op.batch_alter_table("ai_provider", schema=None) as batch_op:
        for name, column in COLUMNS.items():
            if name not in have:
                batch_op.add_column(column)


def downgrade() -> None:
    have = _columns("ai_provider")
    with op.batch_alter_table("ai_provider", schema=None) as batch_op:
        for name in COLUMNS:
            if name in have:
                batch_op.drop_column(name)
