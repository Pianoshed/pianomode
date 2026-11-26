"""saved practice results

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "practice_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("movement_slug", sa.String(80), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("key", sa.String(4), nullable=True),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("hands", sa.String(4), nullable=False),
        sa.Column("pass_index", sa.Integer(), nullable=False),
        sa.Column("tempo_bpm", sa.Float(), nullable=True),
        sa.Column("window_ms", sa.Float(), nullable=True),
        sa.Column("expected", sa.Integer(), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("accuracy", sa.Float(), nullable=False),
        sa.Column("on_time", sa.Integer(), nullable=False),
        sa.Column("early", sa.Integer(), nullable=False),
        sa.Column("late", sa.Integer(), nullable=False),
        sa.Column("missed", sa.Integer(), nullable=False),
        sa.Column("near_miss", sa.Integer(), nullable=False),
        sa.Column("extra", sa.Integer(), nullable=False),
        sa.Column("mean_error_ms", sa.Float(), nullable=True),
        sa.Column("tendency", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_practice_attempts_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_practice_attempts"),
    )
    for col in ("user_id", "session_id", "movement_slug", "created_at"):
        op.create_index(f"ix_practice_attempts_{col}", "practice_attempts", [col])


def downgrade() -> None:
    for col in ("created_at", "movement_slug", "session_id", "user_id"):
        op.drop_index(f"ix_practice_attempts_{col}", table_name="practice_attempts")
    op.drop_table("practice_attempts")
