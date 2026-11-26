"""saved cards for opt-in automatic renewal; payments.save_card

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("save_card", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_table(
        "saved_cards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_code", sa.String(512), nullable=False),
        sa.Column("brand", sa.String(24), nullable=False),
        sa.Column("last4", sa.String(4), nullable=False),
        sa.Column("exp_month", sa.String(2), nullable=False),
        sa.Column("exp_year", sa.String(4), nullable=False),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("failures", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_saved_cards_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_saved_cards"),
        sa.UniqueConstraint("user_id", name="uq_saved_cards_user_id"),
    )


def downgrade() -> None:
    op.drop_table("saved_cards")
    op.drop_column("payments", "save_card")
