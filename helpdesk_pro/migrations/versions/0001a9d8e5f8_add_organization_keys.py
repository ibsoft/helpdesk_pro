"""Add organization key storage and sharing tables"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001a9d8e5f8"
down_revision = "8f7d9a2a5c4b"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "vault_organization",
        sa.Column("key_ciphertext", sa.Text(), nullable=True),
    )
    op.add_column(
        "vault_organization",
        sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "vault_organization",
        sa.Column("key_created_at", sa.DateTime(), nullable=True),
    )
    op.alter_column("vault_organization", "key_version", server_default=None)

    op.create_table(
        "vault_organization_key_share",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("vault_organization.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("key_blob", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("user.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )
    op.alter_column("vault_organization_key_share", "version", server_default=None)


def downgrade():
    op.drop_table("vault_organization_key_share")
    op.drop_column("vault_organization", "key_ciphertext")
    op.drop_column("vault_organization", "key_version")
    op.drop_column("vault_organization", "key_created_at")
