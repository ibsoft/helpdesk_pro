"""add assistant config table

Revision ID: 4b2f1d8aac9f
Revises: 21a47a08beec
Create Date: 2024-05-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4b2f1d8aac9f"
down_revision = "21a47a08beec"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "assistant_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.sql.expression.false()),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="webhook"),
        sa.Column("position", sa.String(length=16), nullable=False, server_default="right"),
        sa.Column("button_label", sa.String(length=120), nullable=False, server_default="Ask AI"),
        sa.Column("window_title", sa.String(length=120), nullable=False, server_default="AI Assistant"),
        sa.Column("welcome_message", sa.Text(), nullable=True),
        sa.Column("openai_api_key", sa.String(length=255), nullable=True),
        sa.Column("openai_model", sa.String(length=80), nullable=True),
        sa.Column("webhook_url", sa.String(length=512), nullable=True),
        sa.Column("webhook_method", sa.String(length=10), nullable=True),
        sa.Column("webhook_headers", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )


def downgrade():
    op.drop_table("assistant_config")
