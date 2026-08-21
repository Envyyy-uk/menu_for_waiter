"""состав позиции из каталога

Revision ID: 0010_menu_ingredients
Revises: 0009_recipe_by_volume
Create Date: 2026-08-21 07:10:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_menu_ingredients"
down_revision: str | None = "0009_recipe_by_volume"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "menu_items",
        sa.Column(
            "ingredients",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("menu_items", "ingredients")
