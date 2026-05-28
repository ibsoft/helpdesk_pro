"""Convert VaultWarden JSON columns to JSONB for PostgreSQL"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "2c5b6a7f9d3e"
down_revision = "1a3b0f2a5c3d"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "vault_item",
        "tags",
        type_=postgresql.JSONB(),
        postgresql_using="tags::jsonb",
    )
    op.alter_column(
        "vault_item",
        "encrypted_blob",
        type_=postgresql.JSONB(),
        postgresql_using="encrypted_blob::jsonb",
    )
    op.alter_column(
        "vault_item",
        "metadata_blob",
        type_=postgresql.JSONB(),
        postgresql_using="metadata_blob::jsonb",
    )
    op.alter_column(
        "vault_item",
        "password_history",
        type_=postgresql.JSONB(),
        postgresql_using="password_history::jsonb",
    )


def downgrade():
    op.alter_column(
        "vault_item",
        "tags",
        type_=sa.JSON(),
        postgresql_using="tags::json",
    )
    op.alter_column(
        "vault_item",
        "encrypted_blob",
        type_=sa.JSON(),
        postgresql_using="encrypted_blob::json",
    )
    op.alter_column(
        "vault_item",
        "metadata_blob",
        type_=sa.JSON(),
        postgresql_using="metadata_blob::json",
    )
    op.alter_column(
        "vault_item",
        "password_history",
        type_=sa.JSON(),
        postgresql_using="password_history::json",
    )
