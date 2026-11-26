"""graded exercise attempts

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exercise_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("exercise_id", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("difficulty", sa.String(12), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_exercise_attempts_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_exercise_attempts"),
    )
    op.create_index("ix_exercise_attempts_user_id", "exercise_attempts", ["user_id"])
    op.create_index("ix_exercise_attempts_kind", "exercise_attempts", ["kind"])
    op.create_index("ix_exercise_attempts_created_at", "exercise_attempts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_exercise_attempts_created_at", table_name="exercise_attempts")
    op.drop_index("ix_exercise_attempts_kind", table_name="exercise_attempts")
    op.drop_index("ix_exercise_attempts_user_id", table_name="exercise_attempts")
    op.drop_table("exercise_attempts")
