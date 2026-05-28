"""add contract documents

Revision ID: 9a1f2b3c4d5e
Revises: 8b7c2d4e9a10
Create Date: 2026-05-28 12:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "9a1f2b3c4d5e"
down_revision = "8b7c2d4e9a10"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "contract_document",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contract_id", sa.Integer(), nullable=False),
        sa.Column("history_id", sa.Integer(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("stored_filename", sa.String(length=255), nullable=False),
        sa.Column("display_filename", sa.String(length=255), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("uploaded_by_id", sa.Integer(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["contract_id"], ["contract.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["history_id"], ["contract_update_history.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stored_filename"),
    )
    op.create_index("ix_contract_document_contract_id", "contract_document", ["contract_id"])
    op.create_index("ix_contract_document_history_id", "contract_document", ["history_id"])


def downgrade():
    op.drop_index("ix_contract_document_history_id", table_name="contract_document")
    op.drop_index("ix_contract_document_contract_id", table_name="contract_document")
    op.drop_table("contract_document")
