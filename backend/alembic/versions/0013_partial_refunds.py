"""partial refunds: payments.refunded_kobo, payments.refunded_days

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("refunded_kobo", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "payments",
        sa.Column("refunded_days", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    # Payments already marked refunded were refunded in full.
    op.execute("UPDATE payments SET refunded_kobo = amount_kobo WHERE status = 'refunded'")


def downgrade() -> None:
    op.drop_column("payments", "refunded_days")
    op.drop_column("payments", "refunded_kobo")
