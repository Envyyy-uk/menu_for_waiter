"""откуда вошли и правка часов в табеле

Revision ID: 0013_where_and_hours
Revises: 0012_shift_people
Create Date: 2026-08-24 10:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_where_and_hours"
down_revision: str | None = "0012_shift_people"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("app", sa.String(length=10), nullable=False, server_default="hall"),
    )
    # Кто и когда поправил часы руками. Табель — это зарплата, и правка в нём
    # не должна выглядеть так же, как отработанное время.
    op.add_column("work_shifts", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("work_shifts", sa.Column("edited_by_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_work_shifts_edited_by", "work_shifts", "users", ["edited_by_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_work_shifts_edited_by", "work_shifts", type_="foreignkey")
    op.drop_column("work_shifts", "edited_by_id")
    op.drop_column("work_shifts", "edited_at")
    op.drop_column("sessions", "app")
