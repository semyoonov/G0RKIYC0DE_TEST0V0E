"""Replace one-time email codes with an email and password login.

Revision ID: 0005
Revises: 0004
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user_emails", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.alter_column(
        "user_emails",
        "verified_at",
        new_column_name="claimed_at",
        existing_type=sa.DateTime(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "user_emails",
        "claimed_at",
        new_column_name="verified_at",
        existing_type=sa.DateTime(),
        existing_nullable=False,
    )
    op.drop_column("user_emails", "password_hash")
