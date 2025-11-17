"""add source job to remote command

Revision ID: a8f1e2d3f4b5
Revises: 9e48e1cd10c0
Create Date: 2025-11-17 14:45:00
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a8f1e2d3f4b5'
down_revision = '9e48e1cd10c0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('fleet_remote_command', sa.Column('source_job_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_fleet_remote_command_job',
        'fleet_remote_command',
        'fleet_scheduled_job',
        ['source_job_id'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade():
    op.drop_constraint('fk_fleet_remote_command_job', 'fleet_remote_command', type_='foreignkey')
    op.drop_column('fleet_remote_command', 'source_job_id')
