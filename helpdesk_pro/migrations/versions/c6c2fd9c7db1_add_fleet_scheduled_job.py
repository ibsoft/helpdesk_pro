"""add fleet scheduled job table

Revision ID: c6c2fd9c7db1
Revises: merge_fleet_links
Create Date: 2025-11-17 11:55:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c6c2fd9c7db1"
down_revision = "merge_fleet_links"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "fleet_scheduled_job",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False, server_default="command"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="scheduled"),
        sa.Column("run_at", sa.DateTime(), nullable=False),
        sa.Column("recurrence", sa.String(length=32), nullable=False, server_default="once"),
        sa.Column(
            "target_hosts",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "payload",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"]),
    )


def downgrade():
    op.drop_table("fleet_scheduled_job")
