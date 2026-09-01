"""add ENGAGED and PAYMENT_PLAN to RecoveryStatus enum

Customer replies / active negotiations now promote a case to ENGAGED, and an
accepted installment plan to PAYMENT_PLAN, instead of exhausting the outreach
attempt counter.

Revision ID: 8c4e2f1a7b3d
Revises: a1d30b9b9e91
Create Date: 2026-08-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '8c4e2f1a7b3d'
down_revision: Union[str, None] = 'a1d30b9b9e91'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL uses a native enum type that must be extended with ALTER TYPE.
    # SQLite materializes the enum as VARCHAR, so there is nothing to alter.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(
                "ALTER TYPE recoverystatus ADD VALUE IF NOT EXISTS 'ENGAGED'"
            )
            op.execute(
                "ALTER TYPE recoverystatus ADD VALUE IF NOT EXISTS 'PAYMENT_PLAN'"
            )


def downgrade() -> None:
    # PostgreSQL cannot remove a value from an enum type without recreating it.
    # This is intentionally a no-op: re-using the two statuses is non-destructive.
    pass