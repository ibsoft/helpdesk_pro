"""Add fleet agent download link table

Revision ID: 7c7f2cf3d2b1
Revises: bacba217dc0f
Create Date: 2025-11-14 15:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7c7f2cf3d2b1"
down_revision = "bacba217dc0f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "fleet_agent_download_link",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token", sa.String(length=96), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["user.id"],
            name="fk_fleet_agent_link_user",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_fleet_agent_download_link_token",
        "fleet_agent_download_link",
        ["token"],
        unique=True,
    )


def downgrade():
    op.drop_index("ix_fleet_agent_download_link_token", table_name="fleet_agent_download_link")
    op.drop_table("fleet_agent_download_link")
