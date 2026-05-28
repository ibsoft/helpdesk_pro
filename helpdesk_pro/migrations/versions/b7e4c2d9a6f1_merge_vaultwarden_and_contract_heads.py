"""merge vaultwarden and contract heads

Revision ID: b7e4c2d9a6f1
Revises: 2c5b6a7f9d3e, f8e5d7c6a2b1, 9a1f2b3c4d5e
Create Date: 2026-05-28 14:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b7e4c2d9a6f1"
down_revision = ("2c5b6a7f9d3e", "f8e5d7c6a2b1", "9a1f2b3c4d5e")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
