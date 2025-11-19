"""add doc_key to fleet_message

Revision ID: 3c9bcb5a6b6f
Revises: bacba217dc0f
Create Date: 2025-11-13 17:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "3c9bcb5a6b6f"
down_revision = "bacba217dc0f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("fleet_message", sa.Column("doc_key", sa.String(length=128), nullable=True))
    op.create_unique_constraint("uq_fleet_message_doc_key", "fleet_message", ["doc_key"])
    op.create_index("ix_fleet_message_doc_key", "fleet_message", ["doc_key"], unique=False)


def downgrade():
    op.drop_index("ix_fleet_message_doc_key", table_name="fleet_message")
    op.drop_constraint("uq_fleet_message_doc_key", "fleet_message", type_="unique")
    op.drop_column("fleet_message", "doc_key")
