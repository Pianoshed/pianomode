"""plan-ending reminder emails: opt-out flag and sent-notice log

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("reminder_emails", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "expiry_notices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            name="fk_expiry_notices_subscription_id_subscriptions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_expiry_notices"),
        sa.UniqueConstraint(
            "subscription_id", "period_end", "kind", name="uq_expiry_notices_once_per_period"
        ),
    )
    op.create_index("ix_expiry_notices_subscription_id", "expiry_notices", ["subscription_id"])


def downgrade() -> None:
    op.drop_index("ix_expiry_notices_subscription_id", table_name="expiry_notices")
    op.drop_table("expiry_notices")
    op.drop_column("users", "reminder_emails")
