"""add B2B receivables chaser tables

Creates receivable_invoices and receivable_escalation_events tables
for tracking overdue B2B invoices and automated escalation workflows.

Revision ID: b2b_receivables
Revises: 8c4e2f1a7b3d
Create Date: 2026-08-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2b_receivables'
down_revision: Union[str, None] = '8c4e2f1a7b3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'receivable_invoices',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('customer_id', sa.Uuid(), nullable=True),
        sa.Column('customer_name', sa.String(length=255), nullable=False),
        sa.Column('customer_email', sa.String(length=255), nullable=False),
        sa.Column('customer_company', sa.String(length=255), nullable=True),
        sa.Column('invoice_number', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('amount_paid', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=False),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('due_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('escalation_tier', sa.String(length=50), nullable=False),
        sa.Column('last_escalation_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_escalation_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('escalation_count', sa.Integer(), nullable=False),
        sa.Column('max_escalations', sa.Integer(), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_receivable_invoices_customer_id'),
        'receivable_invoices', ['customer_id'], unique=False,
    )
    op.create_index(
        op.f('ix_receivable_invoices_invoice_number'),
        'receivable_invoices', ['invoice_number'], unique=True,
    )
    op.create_index(
        op.f('ix_receivable_invoices_due_date'),
        'receivable_invoices', ['due_date'], unique=False,
    )
    op.create_index(
        op.f('ix_receivable_invoices_status'),
        'receivable_invoices', ['status'], unique=False,
    )
    op.create_index(
        op.f('ix_receivable_invoices_escalation_tier'),
        'receivable_invoices', ['escalation_tier'], unique=False,
    )
    op.create_index(
        op.f('ix_receivable_invoices_next_escalation_at'),
        'receivable_invoices', ['next_escalation_at'], unique=False,
    )

    op.create_table(
        'receivable_escalation_events',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('receivable_invoice_id', sa.Uuid(), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('old_tier', sa.String(length=50), nullable=True),
        sa.Column('new_tier', sa.String(length=50), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['receivable_invoice_id'], ['receivable_invoices.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_receivable_escalation_events_receivable_invoice_id'),
        'receivable_escalation_events', ['receivable_invoice_id'], unique=False,
    )
    op.create_index(
        op.f('ix_receivable_escalation_events_event_type'),
        'receivable_escalation_events', ['event_type'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_receivable_escalation_events_event_type'), table_name='receivable_escalation_events')
    op.drop_index(op.f('ix_receivable_escalation_events_receivable_invoice_id'), table_name='receivable_escalation_events')
    op.drop_table('receivable_escalation_events')

    op.drop_index(op.f('ix_receivable_invoices_next_escalation_at'), table_name='receivable_invoices')
    op.drop_index(op.f('ix_receivable_invoices_escalation_tier'), table_name='receivable_invoices')
    op.drop_index(op.f('ix_receivable_invoices_status'), table_name='receivable_invoices')
    op.drop_index(op.f('ix_receivable_invoices_due_date'), table_name='receivable_invoices')
    op.drop_index(op.f('ix_receivable_invoices_invoice_number'), table_name='receivable_invoices')
    op.drop_index(op.f('ix_receivable_invoices_customer_id'), table_name='receivable_invoices')
    op.drop_table('receivable_invoices')
