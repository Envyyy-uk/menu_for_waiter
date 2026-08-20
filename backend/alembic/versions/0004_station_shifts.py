"""PIN планшета станции и смены

Revision ID: 0004_station_shifts
Revises: 0003_table_plan
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_station_shifts"
down_revision: str | None = "0003_table_plan"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "station_pins",
        sa.Column("venue_id", sa.Uuid(), nullable=False),
        sa.Column("station", sa.String(length=10), nullable=False),
        sa.Column("pin_hash", sa.String(length=255), nullable=False),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("station"),
    )
    op.create_index("ix_station_pins_venue_id", "station_pins", ["venue_id"])

    op.create_table(
        "shifts",
        sa.Column("venue_id", sa.Uuid(), nullable=False),
        sa.Column("station", sa.String(length=10), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tickets_done", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_shifts_venue_id", "shifts", ["venue_id"])
    op.create_index("ix_shifts_station", "shifts", ["station"])
    op.create_index("ix_shifts_closed_at", "shifts", ["closed_at"])


def downgrade() -> None:
    op.drop_table("shifts")
    op.drop_table("station_pins")
