"""Add vault user profile verifier

Revision ID: 5f6e7d8c9b0a
Revises: b7e4c2d9a6f1
Create Date: 2026-05-29 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "5f6e7d8c9b0a"
down_revision = "b7e4c2d9a6f1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vault_user_profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "kdf_algorithm",
            sa.String(length=40),
            nullable=False,
            server_default="argon2id-or-pbkdf2",
        ),
        sa.Column("kdf_salt", sa.String(length=255), nullable=False),
        sa.Column("verification_blob", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_vault_user_profile_user_id", "vault_user_profile", ["user_id"])
    op.alter_column("vault_user_profile", "kdf_algorithm", server_default=None)
    op.alter_column("vault_user_profile", "version", server_default=None)


def downgrade():
    op.drop_index("ix_vault_user_profile_user_id", table_name="vault_user_profile")
    op.drop_table("vault_user_profile")
