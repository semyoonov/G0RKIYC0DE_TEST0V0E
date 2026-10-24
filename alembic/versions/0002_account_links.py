"""account links and one-time link codes

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-24 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "account_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform", "external_id", name="uq_account_links_identity"),
    )
    op.create_index("ix_account_links_user_id", "account_links", ["user_id"])
    op.create_index("ix_account_links_external_id", "account_links", ["external_id"])

    op.create_table(
        "link_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_link_codes_code", "link_codes", ["code"], unique=True)
    op.create_index("ix_link_codes_user_id", "link_codes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_link_codes_user_id", table_name="link_codes")
    op.drop_index("ix_link_codes_code", table_name="link_codes")
    op.drop_table("link_codes")
    op.drop_index("ix_account_links_external_id", table_name="account_links")
    op.drop_index("ix_account_links_user_id", table_name="account_links")
    op.drop_table("account_links")
