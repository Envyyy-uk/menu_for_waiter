"""склад

Revision ID: 0005_stock
Revises: 0004_station_shifts
Create Date: 2026-08-20 05:26:22.094729
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
revision: str = "0005_stock"
down_revision: str | None = '0004_station_shifts'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('stock_items',
    sa.Column('venue_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('unit', sa.String(length=4), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=12, scale=3), nullable=False),
    sa.Column('low_at', sa.Numeric(precision=12, scale=3), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['venue_id'], ['venues.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('venue_id', 'name', name='uq_stock_name')
    )
    op.create_index(op.f('ix_stock_items_venue_id'), 'stock_items', ['venue_id'], unique=False)
    op.create_table('recipes',
    sa.Column('venue_id', sa.UUID(), nullable=False),
    sa.Column('menu_item_id', sa.UUID(), nullable=False),
    sa.Column('stock_item_id', sa.UUID(), nullable=False),
    sa.Column('options', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('per_unit', sa.Numeric(precision=12, scale=3), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['menu_item_id'], ['menu_items.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['stock_item_id'], ['stock_items.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['venue_id'], ['venues.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_recipes_menu_item_id'), 'recipes', ['menu_item_id'], unique=False)
    op.create_index(op.f('ix_recipes_stock_item_id'), 'recipes', ['stock_item_id'], unique=False)
    op.create_index(op.f('ix_recipes_venue_id'), 'recipes', ['venue_id'], unique=False)
    op.create_table('stock_moves',
    sa.Column('venue_id', sa.UUID(), nullable=False),
    sa.Column('stock_item_id', sa.UUID(), nullable=False),
    sa.Column('delta', sa.Numeric(precision=12, scale=3), nullable=False),
    sa.Column('reason', sa.String(length=10), nullable=False),
    sa.Column('check_item_id', sa.UUID(), nullable=True),
    sa.Column('by_id', sa.UUID(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['check_item_id'], ['check_items.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['stock_item_id'], ['stock_items.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['venue_id'], ['venues.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_stock_moves_at'), 'stock_moves', ['at'], unique=False)
    op.create_index(op.f('ix_stock_moves_reason'), 'stock_moves', ['reason'], unique=False)
    op.create_index(op.f('ix_stock_moves_stock_item_id'), 'stock_moves', ['stock_item_id'], unique=False)
    op.create_index(op.f('ix_stock_moves_venue_id'), 'stock_moves', ['venue_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_stock_moves_venue_id'), table_name='stock_moves')
    op.drop_index(op.f('ix_stock_moves_stock_item_id'), table_name='stock_moves')
    op.drop_index(op.f('ix_stock_moves_reason'), table_name='stock_moves')
    op.drop_index(op.f('ix_stock_moves_at'), table_name='stock_moves')
    op.drop_table('stock_moves')
    op.drop_index(op.f('ix_recipes_venue_id'), table_name='recipes')
    op.drop_index(op.f('ix_recipes_stock_item_id'), table_name='recipes')
    op.drop_index(op.f('ix_recipes_menu_item_id'), table_name='recipes')
    op.drop_table('recipes')
    op.drop_index(op.f('ix_stock_items_venue_id'), table_name='stock_items')
    op.drop_table('stock_items')
