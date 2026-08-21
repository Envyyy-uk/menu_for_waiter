"""списание по выбранному объёму

Revision ID: 0009_recipe_by_volume
Revises: 0008_source_state
Create Date: 2026-08-21 05:40:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_recipe_by_volume"
down_revision: str | None = "0008_source_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "recipes",
        sa.Column("by_volume", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("recipes", "by_volume")
