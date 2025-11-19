"""merge heads for fleet download links

Revision ID: merge_fleet_links
Revises: 7c7f2cf3d2b1, 3c9bcb5a6b6f
Create Date: 2025-11-14 15:47:00
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'merge_fleet_links'
down_revision = ('7c7f2cf3d2b1', '3c9bcb5a6b6f')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
