"""Add vault profile reset state

Revision ID: 6a7b8c9d0e1f
Revises: 5f6e7d8c9b0a
Create Date: 2026-05-29 12:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "6a7b8c9d0e1f"
down_revision = "5f6e7d8c9b0a"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("vault_user_profile", "kdf_salt", nullable=True)
    op.alter_column("vault_user_profile", "verification_blob", nullable=True)
    op.add_column(
        "vault_user_profile",
        sa.Column("reset_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("vault_user_profile", sa.Column("reset_at", sa.DateTime(), nullable=True))
    op.add_column(
        "vault_user_profile",
        sa.Column("reset_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
    )
    op.alter_column("vault_user_profile", "reset_required", server_default=None)


def downgrade():
    op.drop_column("vault_user_profile", "reset_by_user_id")
    op.drop_column("vault_user_profile", "reset_at")
    op.drop_column("vault_user_profile", "reset_required")
    op.alter_column("vault_user_profile", "verification_blob", nullable=False)
    op.alter_column("vault_user_profile", "kdf_salt", nullable=False)
