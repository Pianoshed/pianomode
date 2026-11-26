"""My Library: saved MIDI projects, audio analyses and progressions

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "library_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("data", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("file_name", sa.String(200), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("last_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_library_items_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_library_items"),
    )
    op.create_index("ix_library_items_user_id", "library_items", ["user_id"])
    op.create_index("ix_library_items_user_kind", "library_items", ["user_id", "kind"])
    op.create_index("ix_library_items_user_opened", "library_items", ["user_id", "last_opened_at"])


def downgrade() -> None:
    op.drop_index("ix_library_items_user_opened", table_name="library_items")
    op.drop_index("ix_library_items_user_kind", table_name="library_items")
    op.drop_index("ix_library_items_user_id", table_name="library_items")
    op.drop_table("library_items")
