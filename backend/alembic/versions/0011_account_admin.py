"""account deletion marker, two-factor sign-in, email-change tokens, upgrades/refunds, audit log

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("totp_secret", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("totp_enabled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("totp_last_step", sa.Integer(), nullable=True))
    op.add_column(
        "users",
        sa.Column("recovery_codes", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column("one_time_tokens", sa.Column("payload", sa.String(320), nullable=True))
    op.add_column(
        "payments",
        sa.Column("kind", sa.String(12), nullable=False, server_default="purchase"),
    )
    op.add_column("payments", sa.Column("from_plan_code", sa.String(32), nullable=True))
    op.add_column("payments", sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "admin_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_email", sa.String(320), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("target_user_id", sa.Uuid(), nullable=True),
        sa.Column("target_label", sa.String(320), nullable=False),
        sa.Column("detail", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_admin_actions_actor_id_users", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            name="fk_admin_actions_target_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_actions"),
    )
    op.create_index("ix_admin_actions_created", "admin_actions", ["created_at"])
    op.create_index("ix_admin_actions_target_user_id", "admin_actions", ["target_user_id"])


def downgrade() -> None:
    op.drop_index("ix_admin_actions_target_user_id", table_name="admin_actions")
    op.drop_index("ix_admin_actions_created", table_name="admin_actions")
    op.drop_table("admin_actions")
    op.drop_column("payments", "refunded_at")
    op.drop_column("payments", "from_plan_code")
    op.drop_column("payments", "kind")
    op.drop_column("one_time_tokens", "payload")
    op.drop_column("users", "recovery_codes")
    op.drop_column("users", "totp_last_step")
    op.drop_column("users", "totp_enabled_at")
    op.drop_column("users", "totp_secret")
    op.drop_column("users", "deleted_at")
