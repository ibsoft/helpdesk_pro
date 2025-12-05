"""Add VaultWarden collection access controls"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "1a3b0f2a5c3d"
down_revision = "0001a9d8e5f8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vault_collection_access",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "collection_id",
            sa.Integer(),
            sa.ForeignKey("vault_collection.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("access_level", sa.String(length=32), nullable=False, server_default=sa.text("'read'")),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("collection_id", "user_id", name="uq_collection_user_access"),
    )
    op.create_index("ix_vault_collection_access_user", "vault_collection_access", ["user_id"])
    op.create_index("ix_vault_collection_access_collection", "vault_collection_access", ["collection_id"])


def downgrade():
    op.drop_index("ix_vault_collection_access_collection", table_name="vault_collection_access")
    op.drop_index("ix_vault_collection_access_user", table_name="vault_collection_access")
    op.drop_table("vault_collection_access")
