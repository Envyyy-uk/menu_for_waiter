"""начальная схема: чеки, подачи, марки, меню, персонал

Revision ID: 0001_initial
Revises: 
Create Date: 2026-08-20 00:25:49.575091
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('venues',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('timezone', sa.String(length=64), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('categories', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('check_seq', sa.Integer(), server_default='0', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key')
    )
    op.create_table('devices',
    sa.Column('venue_id', sa.UUID(), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=False),
    sa.Column('device_token', sa.String(length=64), nullable=False),
    sa.Column('user_agent', sa.Text(), nullable=True),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['venue_id'], ['venues.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('device_token')
    )
    op.create_index(op.f('ix_devices_venue_id'), 'devices', ['venue_id'], unique=False)
    op.create_table('menu_items',
    sa.Column('venue_id', sa.UUID(), nullable=False),
    sa.Column('key', sa.String(length=80), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('price_pence', sa.Integer(), nullable=False),
    sa.Column('station', sa.String(length=10), nullable=False),
    sa.Column('category', sa.String(length=80), nullable=True),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('state', sa.String(length=10), nullable=False),
    sa.Column('options', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('search_terms', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('warning', sa.Text(), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['venue_id'], ['venues.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('venue_id', 'key', name='uq_menu_item_key')
    )
    op.create_index(op.f('ix_menu_items_venue_id'), 'menu_items', ['venue_id'], unique=False)
    op.create_table('tables',
    sa.Column('venue_id', sa.UUID(), nullable=False),
    sa.Column('label', sa.String(length=40), nullable=False),
    sa.Column('zone', sa.String(length=40), server_default='Зал', nullable=False),
    sa.Column('seats', sa.Integer(), server_default='4', nullable=False),
    sa.Column('position', sa.Integer(), server_default='0', nullable=False),
    sa.Column('token', sa.String(length=64), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['venue_id'], ['venues.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token'),
    sa.UniqueConstraint('venue_id', 'label', name='uq_table_label')
    )
    op.create_index(op.f('ix_tables_venue_id'), 'tables', ['venue_id'], unique=False)
    op.create_table('users',
    sa.Column('venue_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('pin_hash', sa.String(length=255), nullable=True),
    sa.Column('pin_failed_attempts', sa.Integer(), nullable=False),
    sa.Column('pin_locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('colour', sa.String(length=7), server_default='#a25a2a', nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['venue_id'], ['venues.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_venue_id'), 'users', ['venue_id'], unique=False)
    op.create_table('audit_log',
    sa.Column('venue_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('action', sa.String(length=60), nullable=False),
    sa.Column('entity', sa.String(length=120), nullable=False),
    sa.Column('before', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('after', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['venue_id'], ['venues.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_log_action'), 'audit_log', ['action'], unique=False)
    op.create_index(op.f('ix_audit_log_at'), 'audit_log', ['at'], unique=False)
    op.create_index(op.f('ix_audit_log_venue_id'), 'audit_log', ['venue_id'], unique=False)
    op.create_table('checks',
    sa.Column('venue_id', sa.UUID(), nullable=False),
    sa.Column('table_id', sa.UUID(), nullable=False),
    sa.Column('waiter_id', sa.UUID(), nullable=True),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('guests', sa.Integer(), server_default='1', nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('discount_pence', sa.Integer(), server_default='0', nullable=False),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closed_by_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['closed_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['table_id'], ['tables.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['venue_id'], ['venues.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['waiter_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_checks_number'), 'checks', ['number'], unique=False)
    op.create_index(op.f('ix_checks_status'), 'checks', ['status'], unique=False)
    op.create_index(op.f('ix_checks_table_id'), 'checks', ['table_id'], unique=False)
    op.create_index(op.f('ix_checks_venue_id'), 'checks', ['venue_id'], unique=False)
    op.create_index(op.f('ix_checks_waiter_id'), 'checks', ['waiter_id'], unique=False)
    op.create_table('push_subscriptions',
    sa.Column('venue_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('endpoint', sa.Text(), nullable=False),
    sa.Column('p256dh', sa.String(length=255), nullable=False),
    sa.Column('auth', sa.String(length=255), nullable=False),
    sa.Column('failed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['venue_id'], ['venues.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('endpoint')
    )
    op.create_index(op.f('ix_push_subscriptions_user_id'), 'push_subscriptions', ['user_id'], unique=False)
    op.create_index(op.f('ix_push_subscriptions_venue_id'), 'push_subscriptions', ['venue_id'], unique=False)
    op.create_table('sessions',
    sa.Column('venue_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('device_id', sa.UUID(), nullable=True),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['venue_id'], ['venues.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_sessions_user_id'), 'sessions', ['user_id'], unique=False)
    op.create_index(op.f('ix_sessions_venue_id'), 'sessions', ['venue_id'], unique=False)
    op.create_table('orders',
    sa.Column('check_id', sa.UUID(), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('sent_by_id', sa.UUID(), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['check_id'], ['checks.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['sent_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('check_id', 'number', name='uq_order_number')
    )
    op.create_index(op.f('ix_orders_check_id'), 'orders', ['check_id'], unique=False)
    op.create_table('payments',
    sa.Column('check_id', sa.UUID(), nullable=False),
    sa.Column('method', sa.String(length=10), nullable=False),
    sa.Column('amount_pence', sa.Integer(), nullable=False),
    sa.Column('tendered_pence', sa.Integer(), nullable=True),
    sa.Column('by_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['check_id'], ['checks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_payments_check_id'), 'payments', ['check_id'], unique=False)
    op.create_table('tickets',
    sa.Column('order_id', sa.UUID(), nullable=False),
    sa.Column('station', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('accepted_by_id', sa.UUID(), nullable=True),
    sa.Column('ready_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ready_by_id', sa.UUID(), nullable=True),
    sa.Column('served_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('acked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['accepted_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['ready_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('order_id', 'station', name='uq_ticket_station')
    )
    op.create_index(op.f('ix_tickets_order_id'), 'tickets', ['order_id'], unique=False)
    op.create_index(op.f('ix_tickets_station'), 'tickets', ['station'], unique=False)
    op.create_index(op.f('ix_tickets_status'), 'tickets', ['status'], unique=False)
    op.create_table('check_items',
    sa.Column('check_id', sa.UUID(), nullable=False),
    sa.Column('ticket_id', sa.UUID(), nullable=True),
    sa.Column('menu_item_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('qty', sa.Integer(), nullable=False),
    sa.Column('unit_price_pence', sa.Integer(), nullable=False),
    sa.Column('name_snapshot', sa.String(length=200), nullable=False),
    sa.Column('station_snapshot', sa.String(length=10), nullable=False),
    sa.Column('options_snapshot', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('options_keys', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('added_by_id', sa.UUID(), nullable=True),
    sa.Column('cancelled_by_id', sa.UUID(), nullable=True),
    sa.Column('cancel_reason', sa.Text(), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['added_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['cancelled_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['check_id'], ['checks.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['menu_item_id'], ['menu_items.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_check_items_check_id'), 'check_items', ['check_id'], unique=False)
    op.create_index(op.f('ix_check_items_status'), 'check_items', ['status'], unique=False)
    op.create_index(op.f('ix_check_items_ticket_id'), 'check_items', ['ticket_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_check_items_ticket_id'), table_name='check_items')
    op.drop_index(op.f('ix_check_items_status'), table_name='check_items')
    op.drop_index(op.f('ix_check_items_check_id'), table_name='check_items')
    op.drop_table('check_items')
    op.drop_index(op.f('ix_tickets_status'), table_name='tickets')
    op.drop_index(op.f('ix_tickets_station'), table_name='tickets')
    op.drop_index(op.f('ix_tickets_order_id'), table_name='tickets')
    op.drop_table('tickets')
    op.drop_index(op.f('ix_payments_check_id'), table_name='payments')
    op.drop_table('payments')
    op.drop_index(op.f('ix_orders_check_id'), table_name='orders')
    op.drop_table('orders')
    op.drop_index(op.f('ix_sessions_venue_id'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_user_id'), table_name='sessions')
    op.drop_table('sessions')
    op.drop_index(op.f('ix_push_subscriptions_venue_id'), table_name='push_subscriptions')
    op.drop_index(op.f('ix_push_subscriptions_user_id'), table_name='push_subscriptions')
    op.drop_table('push_subscriptions')
    op.drop_index(op.f('ix_checks_waiter_id'), table_name='checks')
    op.drop_index(op.f('ix_checks_venue_id'), table_name='checks')
    op.drop_index(op.f('ix_checks_table_id'), table_name='checks')
    op.drop_index(op.f('ix_checks_status'), table_name='checks')
    op.drop_index(op.f('ix_checks_number'), table_name='checks')
    op.drop_table('checks')
    op.drop_index(op.f('ix_audit_log_venue_id'), table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_at'), table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_action'), table_name='audit_log')
    op.drop_table('audit_log')
    op.drop_index(op.f('ix_users_venue_id'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_tables_venue_id'), table_name='tables')
    op.drop_table('tables')
    op.drop_index(op.f('ix_menu_items_venue_id'), table_name='menu_items')
    op.drop_table('menu_items')
    op.drop_index(op.f('ix_devices_venue_id'), table_name='devices')
    op.drop_table('devices')
    op.drop_table('venues')
