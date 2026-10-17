"""initial schema: users and events

Revision ID: 0001
Revises:
Create Date: 2025-03-01 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Europe/Moscow"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform", "external_id", name="uq_users_platform_external_id"),
    )
    op.create_index("ix_users_external_id", "users", ["external_id"])

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(), nullable=True),
        sa.Column("remind_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("source", sa.String(length=16), nullable=True),
        sa.Column("reminder_sent_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_user_id", "events", ["user_id"])
    op.create_index("ix_events_status", "events", ["status"])
    op.create_index("ix_events_user_starts_at", "events", ["user_id", "starts_at"])
    op.create_index("ix_events_remind_at", "events", ["remind_at"])


def downgrade() -> None:
    op.drop_index("ix_events_remind_at", table_name="events")
    op.drop_index("ix_events_user_starts_at", table_name="events")
    op.drop_index("ix_events_status", table_name="events")
    op.drop_index("ix_events_user_id", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_users_external_id", table_name="users")
    op.drop_table("users")
