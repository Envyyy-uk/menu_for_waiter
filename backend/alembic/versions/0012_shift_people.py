"""кто был на смене станции

Revision ID: 0012_shift_people
Revises: 0011_shift_by_whom
Create Date: 2026-08-22 09:10:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_shift_people"
down_revision: str | None = "0011_shift_by_whom"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shift_people",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("shift_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name_snapshot", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["shift_id"], ["shifts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_shift_people_shift_id", "shift_people", ["shift_id"])
    # Один человек в смене один раз: вошёл, ушёл, вернулся — это та же строка,
    # а не вторая запись «Игорь» в списке.
    op.create_unique_constraint(
        "uq_shift_people_shift_user", "shift_people", ["shift_id", "user_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_shift_people_shift_user", "shift_people", type_="unique")
    op.drop_index("ix_shift_people_shift_id", table_name="shift_people")
    op.drop_table("shift_people")
