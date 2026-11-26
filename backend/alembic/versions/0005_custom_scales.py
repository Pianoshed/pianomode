"""administrator-defined scales

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_scales",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scale_id", sa.String(40), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("history", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_custom_scales_created_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_custom_scales"),
    )
    op.create_index("ix_custom_scales_scale_id", "custom_scales", ["scale_id"], unique=True)
    op.create_index("ix_custom_scales_status", "custom_scales", ["status"])


def downgrade() -> None:
    op.drop_index("ix_custom_scales_status", table_name="custom_scales")
    op.drop_index("ix_custom_scales_scale_id", table_name="custom_scales")
    op.drop_table("custom_scales")
