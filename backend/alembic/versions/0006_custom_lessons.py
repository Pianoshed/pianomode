"""lessons written in the admin screen

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_lessons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("lesson_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
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
            name="fk_custom_lessons_created_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_custom_lessons"),
    )
    op.create_index("ix_custom_lessons_lesson_id", "custom_lessons", ["lesson_id"], unique=True)
    op.create_index("ix_custom_lessons_status", "custom_lessons", ["status"])


def downgrade() -> None:
    op.drop_index("ix_custom_lessons_status", table_name="custom_lessons")
    op.drop_index("ix_custom_lessons_lesson_id", table_name="custom_lessons")
    op.drop_table("custom_lessons")
