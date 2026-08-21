"""состояние позиции с сайта

Revision ID: 0008_source_state
Revises: 0007_work_shifts
Create Date: 2026-08-21 04:10:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_source_state"
down_revision: str | None = "0007_work_shifts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "menu_items",
        sa.Column("source_state", sa.String(length=10), server_default="on", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("menu_items", "source_state")
