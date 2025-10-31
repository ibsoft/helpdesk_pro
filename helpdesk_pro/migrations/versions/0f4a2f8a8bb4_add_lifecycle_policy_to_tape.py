"""Add lifecycle policy to tape

Revision ID: 0f4a2f8a8bb4
Revises: c8b6500b8c13
Create Date: 2025-10-31 10:52:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0f4a2f8a8bb4'
down_revision = 'e28d07d1e9bf'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'backup_tape_cartridge',
        sa.Column('lifecycle_policy', sa.String(length=32), nullable=True),
    )


def downgrade():
    op.drop_column('backup_tape_cartridge', 'lifecycle_policy')
