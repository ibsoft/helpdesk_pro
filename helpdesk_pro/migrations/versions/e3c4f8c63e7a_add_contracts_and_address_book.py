"""add contracts and address book tables

Revision ID: e3c4f8c63e7a
Revises: ef1a0a4dbf77
Create Date: 2025-03-10 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e3c4f8c63e7a'
down_revision = 'ef1a0a4dbf77'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'contract',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('contract_type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=120), nullable=True),
        sa.Column('vendor', sa.String(length=150), nullable=True),
        sa.Column('contract_number', sa.String(length=120), nullable=True),
        sa.Column('po_number', sa.String(length=120), nullable=True),
        sa.Column('value', sa.Numeric(12, 2), nullable=True),
        sa.Column('currency', sa.String(length=8), nullable=True),
        sa.Column('auto_renew', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('notice_period_days', sa.Integer(), nullable=True),
        sa.Column('coverage_scope', sa.String(length=255), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('renewal_date', sa.Date(), nullable=True),
        sa.Column('owner_id', sa.Integer(), nullable=True),
        sa.Column('support_email', sa.String(length=150), nullable=True),
        sa.Column('support_phone', sa.String(length=80), nullable=True),
        sa.Column('support_url', sa.String(length=255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['owner_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('contract_number')
    )

    op.create_table(
        'address_book_entry',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('category', sa.String(length=120), nullable=True),
        sa.Column('company', sa.String(length=150), nullable=True),
        sa.Column('job_title', sa.String(length=150), nullable=True),
        sa.Column('department', sa.String(length=150), nullable=True),
        sa.Column('email', sa.String(length=150), nullable=True),
        sa.Column('phone', sa.String(length=80), nullable=True),
        sa.Column('mobile', sa.String(length=80), nullable=True),
        sa.Column('website', sa.String(length=255), nullable=True),
        sa.Column('address_line', sa.String(length=255), nullable=True),
        sa.Column('city', sa.String(length=120), nullable=True),
        sa.Column('state', sa.String(length=120), nullable=True),
        sa.Column('postal_code', sa.String(length=40), nullable=True),
        sa.Column('country', sa.String(length=120), nullable=True),
        sa.Column('tags', sa.String(length=255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('contract')
    op.drop_table('address_book_entry')
