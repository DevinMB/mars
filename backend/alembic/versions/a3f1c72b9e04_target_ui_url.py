"""browser-reachable cluster address

Revision ID: a3f1c72b9e04
Revises: dd27ba6e0281
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = 'a3f1c72b9e04'
down_revision = 'dd27ba6e0281'
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """Adds where a *browser* can reach each cluster's own web UI.

    MARS reaches Flink over the container network, at "http://jobmanager:8081".
    Linking a user to that address produces an unreachable page, because the name
    only resolves inside Docker. The two addresses are genuinely different things
    and conflating them was the bug.

    Nullable, and left null by default: for the stock compose file the console can
    derive a correct link from its own address, and asking every deployer to
    configure something that can be inferred is the opposite of the point.
    """
    if "ui_url" not in _columns("targets"):
        with op.batch_alter_table("targets", schema=None) as batch_op:
            batch_op.add_column(sa.Column("ui_url", sa.String(length=512), nullable=True))


def downgrade() -> None:
    if "ui_url" in _columns("targets"):
        with op.batch_alter_table("targets", schema=None) as batch_op:
            batch_op.drop_column("ui_url")
