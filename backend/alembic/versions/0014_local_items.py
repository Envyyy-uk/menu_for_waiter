"""своя позиция в меню, которой нет на сайте

Revision ID: 0014_local_items
Revises: 0013_where_and_hours
Create Date: 2026-08-24 12:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_local_items"
down_revision: str | None = "0013_where_and_hours"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "menu_items",
        sa.Column("local", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("menu_items", "local")
