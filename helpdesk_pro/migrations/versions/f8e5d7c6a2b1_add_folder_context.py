"""Add organization/collection context to vault folders

Revision ID: f8e5d7c6a2b1
Revises: 8f7d9a2a5c4b
Create Date: 2025-11-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f8e5d7c6a2b1"
down_revision = "8f7d9a2a5c4b"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "vault_folder",
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("vault_organization.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "vault_folder",
        sa.Column(
            "collection_id",
            sa.Integer(),
            sa.ForeignKey("vault_collection.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("vault_folder", "collection_id")
    op.drop_column("vault_folder", "organization_id")
