"""version history for catalog entries

Revision ID: e5c93a71f402
Revises: d2b8c4f10e57
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = 'e5c93a71f402'
down_revision = 'd2b8c4f10e57'
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """Gives sources and sinks the history jobs already had.

    The asymmetry was backwards: one catalog entry feeds many jobs, so editing a
    source changes behaviour for everything referencing it, and that was the edit
    with no record of what it used to be.

    Existing entries are seeded at version 1 with their current definition, so the
    history starts from something real rather than from the next edit.
    """
    if "catalog_versions" not in _tables():
        op.create_table(
            "catalog_versions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("entry_id", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("sql_text", sa.Text(), nullable=False),
            sa.Column("description", sa.String(length=512), nullable=True),
            sa.Column("options_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("note", sa.String(length=512), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", sa.String(length=64), nullable=True),
            sa.ForeignKeyConstraint(["entry_id"], ["catalog_entries.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("entry_id", "version", name="uq_catalog_entry_version"),
        )
        op.create_index("ix_catalog_versions_entry_id", "catalog_versions", ["entry_id"])

    if "version" not in _columns("catalog_entries"):
        with op.batch_alter_table("catalog_entries", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("version", sa.Integer(), nullable=False, server_default="1")
            )

    bind = op.get_bind()
    bind.execute(sa.text(
        """
        INSERT INTO catalog_versions
            (entry_id, version, sql_text, description, options_json, note,
             created_at, created_by)
        SELECT e.id, 1, e.sql_text, e.description, e.options_json,
               'Definition as it stood when history began.',
               e.created_at, e.created_by
        FROM catalog_entries e
        WHERE NOT EXISTS (
            SELECT 1 FROM catalog_versions v WHERE v.entry_id = e.id
        )
        """
    ))


def downgrade() -> None:
    if "version" in _columns("catalog_entries"):
        with op.batch_alter_table("catalog_entries", schema=None) as batch_op:
            batch_op.drop_column("version")
    if "catalog_versions" in _tables():
        op.drop_table("catalog_versions")
