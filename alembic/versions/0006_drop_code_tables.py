"""Drop the tables of the removed one-time-code logins.

Revision ID: 0006
Revises: 0005
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_link_codes_user_id", table_name="link_codes")
    op.drop_index("ix_link_codes_code", table_name="link_codes")
    op.drop_table("link_codes")
    op.drop_index("ix_email_challenges_email_normalized", table_name="email_challenges")
    op.drop_table("email_challenges")


def downgrade() -> None:
    op.create_table(
        "link_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_link_codes_user_id", "link_codes", ["user_id"])
    op.create_index("ix_link_codes_code", "link_codes", ["code"], unique=True)
    op.create_table(
        "email_challenges",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email_normalized", sa.String(length=254), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("identity_platform", sa.String(length=16), nullable=True),
        sa.Column("identity_external_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_challenges_email_normalized", "email_challenges", ["email_normalized"])
