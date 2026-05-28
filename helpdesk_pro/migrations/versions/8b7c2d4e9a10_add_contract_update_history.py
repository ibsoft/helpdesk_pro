"""add contract update history

Revision ID: 8b7c2d4e9a10
Revises: 1c35ffc409e8
Create Date: 2026-05-28 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "8b7c2d4e9a10"
down_revision = "1c35ffc409e8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "contract_update_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contract_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("previous_start_date", sa.Date(), nullable=True),
        sa.Column("previous_end_date", sa.Date(), nullable=True),
        sa.Column("new_start_date", sa.Date(), nullable=True),
        sa.Column("new_end_date", sa.Date(), nullable=True),
        sa.Column("previous_renewal_date", sa.Date(), nullable=True),
        sa.Column("new_renewal_date", sa.Date(), nullable=True),
        sa.Column("previous_status", sa.String(length=120), nullable=True),
        sa.Column("new_status", sa.String(length=120), nullable=True),
        sa.Column("previous_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("new_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("previous_currency", sa.String(length=8), nullable=True),
        sa.Column("new_currency", sa.String(length=8), nullable=True),
        sa.Column("changed_by_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["changed_by_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["contract_id"], ["contract.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_contract_update_history_contract_id",
        "contract_update_history",
        ["contract_id"],
    )


def downgrade():
    op.drop_index("ix_contract_update_history_contract_id", table_name="contract_update_history")
    op.drop_table("contract_update_history")
