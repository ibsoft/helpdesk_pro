"""add user avatar fields

Revision ID: 6c55f27a68e9
Revises: 3e4f4b2ab6c1
Create Date: 2025-10-31 20:06:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6c55f27a68e9'
down_revision = '3e4f4b2ab6c1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('avatar_filename', sa.String(length=255), nullable=True))
    op.add_column('user', sa.Column('use_gravatar', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.alter_column('user', 'use_gravatar', server_default=None)


def downgrade():
    op.drop_column('user', 'use_gravatar')
    op.drop_column('user', 'avatar_filename')
