"""кто открыл и закрыл смену станции

Revision ID: 0011_shift_by_whom
Revises: 0010_menu_ingredients
Create Date: 2026-08-21 08:20:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_shift_by_whom"
down_revision: str | None = "0010_menu_ingredients"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("shifts", sa.Column("opened_by_id", sa.Uuid(), nullable=True))
    op.add_column("shifts", sa.Column("closed_by_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_shifts_opened_by", "shifts", "users", ["opened_by_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_shifts_closed_by", "shifts", "users", ["closed_by_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("fk_shifts_closed_by", "shifts", type_="foreignkey")
    op.drop_constraint("fk_shifts_opened_by", "shifts", type_="foreignkey")
    op.drop_column("shifts", "closed_by_id")
    op.drop_column("shifts", "opened_by_id")
