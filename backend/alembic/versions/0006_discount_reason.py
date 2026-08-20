"""причина скидки

Revision ID: 0006_discount_reason
Revises: 0005_stock
Create Date: 2026-08-20 13:40:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_discount_reason"
down_revision: str | None = "0005_stock"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("checks", sa.Column("discount_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("checks", "discount_reason")
