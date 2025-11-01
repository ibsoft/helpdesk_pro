"""Add manager notification prefs

Revision ID: 11074d820bc0
Revises: 6c55f27a68e9
Create Date: 2025-11-01 09:32:17.123116

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '11074d820bc0'
down_revision = '6c55f27a68e9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('notify_team_ticket_email', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('notify_team_ticket_teams', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('teams_webhook_url', sa.String(length=512), nullable=True))

    op.execute(
        """
        UPDATE "user"
        SET notify_team_ticket_email = FALSE,
            notify_team_ticket_teams = FALSE
        WHERE notify_team_ticket_email IS NULL
           OR notify_team_ticket_teams IS NULL
        """
    )

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column('notify_team_ticket_email', existing_type=sa.Boolean(), nullable=False)
        batch_op.alter_column('notify_team_ticket_teams', existing_type=sa.Boolean(), nullable=False)


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('teams_webhook_url')
        batch_op.drop_column('notify_team_ticket_teams')
        batch_op.drop_column('notify_team_ticket_email')
