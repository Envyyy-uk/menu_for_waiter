"""место стола на плане зала

Revision ID: 0003_table_plan
Revises: 0002_menu_sync
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_table_plan"
down_revision: str | None = "0002_menu_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tables", sa.Column("x", sa.Float(), nullable=True))
    op.add_column("tables", sa.Column("y", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("tables", "y")
    op.drop_column("tables", "x")
