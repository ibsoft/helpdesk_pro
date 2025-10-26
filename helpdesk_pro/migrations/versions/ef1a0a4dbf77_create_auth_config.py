"""create auth config

Revision ID: ef1a0a4dbf77
Revises: d4c6c1c3f5c4
Create Date: 2025-10-26 13:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ef1a0a4dbf77'
down_revision = 'd4c6c1c3f5c4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'auth_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('allow_self_registration', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('allow_password_reset', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('default_role', sa.String(length=20), nullable=False, server_default='user'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('auth_config')
