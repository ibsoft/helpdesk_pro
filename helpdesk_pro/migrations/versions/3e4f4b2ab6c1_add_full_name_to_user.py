"""add full_name to user

Revision ID: 3e4f4b2ab6c1
Revises: 0f4a2f8a8bb4
Create Date: 2025-10-31 20:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3e4f4b2ab6c1'
down_revision = '0f4a2f8a8bb4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('full_name', sa.String(length=150), nullable=True))


def downgrade():
    op.drop_column('user', 'full_name')
