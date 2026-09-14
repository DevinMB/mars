"""execution targets

Revision ID: dd27ba6e0281
Revises: c80ea6d837dc
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = 'dd27ba6e0281'
down_revision = 'c80ea6d837dc'
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {i["name"] for i in inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    """Applied defensively, because the database may be half-built already.

    Earlier builds called Base.metadata.create_all on start. That creates missing
    *tables* but never missing *columns*, so a database touched by one of those
    already has `targets` while still lacking `jobs.target_name`. Creating the table
    blindly then fails with "table targets already exists" and the console
    restart-loops on every boot.

    Mixing create_all with migrations is what produced that state; the application
    no longer does it. These guards exist so installs that already met the old
    behaviour can still upgrade.
    """
    if "targets" not in _tables():
        op.create_table(
            "targets",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=64), nullable=False),
            sa.Column("description", sa.String(length=512), nullable=True),
            sa.Column("flink_rest_url", sa.String(length=512), nullable=False),
            sa.Column("gateway_url", sa.String(length=512), nullable=False),
            sa.Column("labels", sa.Text(), nullable=False),
            sa.Column("is_default", sa.Boolean(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    if "ix_targets_name" not in _indexes("targets"):
        op.create_index("ix_targets_name", "targets", ["name"], unique=True)

    if "target_name" not in _columns("jobs"):
        with op.batch_alter_table("jobs", schema=None) as batch_op:
            batch_op.add_column(sa.Column("target_name", sa.String(length=64), nullable=True))

    if "ix_jobs_target_name" not in _indexes("jobs"):
        op.create_index("ix_jobs_target_name", "jobs", ["target_name"], unique=False)


def downgrade() -> None:
    if "ix_jobs_target_name" in _indexes("jobs"):
        op.drop_index("ix_jobs_target_name", table_name="jobs")
    if "target_name" in _columns("jobs"):
        with op.batch_alter_table("jobs", schema=None) as batch_op:
            batch_op.drop_column("target_name")
    if "targets" in _tables():
        op.drop_table("targets")
