"""acknowledging a failed run

Revision ID: f0a71d2b8c94
Revises: e5c93a71f402
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = 'f0a71d2b8c94'
down_revision = 'e5c93a71f402'
branch_labels = None
depends_on = None

COLUMNS = {
    "acknowledged_at": sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    "acknowledged_by": sa.Column("acknowledged_by", sa.String(length=64), nullable=True),
}


def _columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """Lets a failure be marked as dealt with.

    Stored rather than hidden in a browser: an acknowledgement that lives in local
    storage means two people looking at the same console see different things, and
    the one who did not click it never learns the failure was handled.
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
