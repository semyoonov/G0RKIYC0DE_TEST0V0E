"""Add rrule column to events table.

Revision ID: 0004
Revises: 0003
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("events", sa.Column("rrule", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "rrule")
