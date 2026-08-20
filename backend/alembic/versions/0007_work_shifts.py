"""личные смены — табель

Revision ID: 0007_work_shifts
Revises: 0006_discount_reason
Create Date: 2026-08-20 15:10:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_work_shifts"
down_revision: str | None = "0006_discount_reason"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "work_shifts",
        sa.Column("venue_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name_snapshot", sa.String(length=120), nullable=False),
        sa.Column("role_snapshot", sa.String(length=20), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_work_shifts_venue_id"), "work_shifts", ["venue_id"])
    op.create_index(op.f("ix_work_shifts_user_id"), "work_shifts", ["user_id"])
    op.create_index(op.f("ix_work_shifts_opened_at"), "work_shifts", ["opened_at"])
    op.create_index(op.f("ix_work_shifts_closed_at"), "work_shifts", ["closed_at"])


def downgrade() -> None:
    op.drop_table("work_shifts")
