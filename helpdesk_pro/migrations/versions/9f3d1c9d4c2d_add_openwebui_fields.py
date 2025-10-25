"""add openwebui fields

Revision ID: 9f3d1c9d4c2d
Revises: b46609b443f8
Create Date: 2025-10-25 14:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9f3d1c9d4c2d'
down_revision = 'b46609b443f8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('assistant_config', sa.Column('openwebui_api_key', sa.String(length=255), nullable=True))
    op.add_column('assistant_config', sa.Column('openwebui_base_url', sa.String(length=512), nullable=True))
    op.add_column('assistant_config', sa.Column('openwebui_model', sa.String(length=80), nullable=True))


def downgrade():
    op.drop_column('assistant_config', 'openwebui_model')
    op.drop_column('assistant_config', 'openwebui_base_url')
    op.drop_column('assistant_config', 'openwebui_api_key')
