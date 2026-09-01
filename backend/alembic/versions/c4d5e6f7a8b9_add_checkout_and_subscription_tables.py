"""add checkout and subscription tables

Revision ID: c4d5e6f7a8b9
Revises: b2b_receivables_chaser
Create Date: 2026-09-01
"""

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    # --- checkout_abandonments ---
    op.create_table(
        "checkout_abandonments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=False, index=True),
        sa.Column("recovery_case_id", sa.Uuid(), sa.ForeignKey("recovery_cases.id"), nullable=True, index=True),
        sa.Column("cart_ref", sa.String(255), nullable=False, index=True),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), server_default="INR"),
        sa.Column("item_count", sa.Integer(), server_default="1"),
        sa.Column("abandoned_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("abandonment_reason", sa.String(500), nullable=True),
        sa.Column("source", sa.String(50), server_default="checkout"),
        sa.Column("reengagement_count", sa.Integer(), server_default="0"),
        sa.Column("last_reengagement_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reengagement_channel", sa.String(50), nullable=True),
        sa.Column("status", sa.String(30), server_default="abandoned"),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- subscription_failures ---
    op.create_table(
        "subscription_failures",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=False, index=True),
        sa.Column("recovery_case_id", sa.Uuid(), sa.ForeignKey("recovery_cases.id"), nullable=True, index=True),
        sa.Column("subscription_id", sa.String(255), nullable=False, index=True),
        sa.Column("plan_id", sa.String(255), nullable=True),
        sa.Column("plan_name", sa.String(255), nullable=True),
        sa.Column("billing_cycle", sa.String(50), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), server_default="INR"),
        sa.Column("failure_code", sa.String(100), nullable=True),
        sa.Column("failure_reason", sa.String(500), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("renewal_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_billing_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("days_until_churn", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0"),
        sa.Column("max_retries", sa.Integer(), server_default="3"),
        sa.Column("last_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(30), server_default="failed"),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("subscription_failures")
    op.drop_table("checkout_abandonments")
