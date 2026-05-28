"""Add VaultWarden zero-knowledge tables

Revision ID: 8f7d9a2a5c4b
Revises: 8f2f6f18a4b2
Create Date: 2025-11-21 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8f7d9a2a5c4b'
down_revision = '8f2f6f18a4b2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'vault_folder',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('name', sa.String(length=180), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        'vault_organization',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=180), nullable=False),
        sa.Column('slug', sa.String(length=180), nullable=False, unique=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        'vault_organization_membership',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('vault_organization.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('role', sa.String(length=40), nullable=False, server_default='member'),
        sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        'vault_collection',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('vault_organization.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        'vault_item',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('vault_organization.id'), nullable=True),
        sa.Column('collection_id', sa.Integer(), sa.ForeignKey('vault_collection.id'), nullable=True),
        sa.Column('folder_id', sa.Integer(), sa.ForeignKey('vault_folder.id'), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('item_type', sa.String(length=50), nullable=False),
        sa.Column('favorite', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('trashed', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('tags', sa.JSON(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('encrypted_blob', sa.JSON(), nullable=False),
        sa.Column('metadata_blob', sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('password_history', sa.JSON(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('last_accessed', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_vault_item_owner', 'vault_item', ['owner_id'])
    op.create_index('ix_vault_item_trashed', 'vault_item', ['trashed'])

    op.create_table(
        'vault_item_share',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('item_id', sa.Integer(), sa.ForeignKey('vault_item.id', ondelete='CASCADE'), nullable=False),
        sa.Column('shared_with_user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('shared_with_collection_id', sa.Integer(), sa.ForeignKey('vault_collection.id'), nullable=True),
        sa.Column('access_level', sa.String(length=32), nullable=False, server_default='read'),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_vault_item_share_item_id', 'vault_item_share', ['item_id'])

    op.create_table(
        'vault_attachment',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('item_id', sa.Integer(), sa.ForeignKey('vault_item.id', ondelete='CASCADE'), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('mime_type', sa.String(length=120), nullable=True),
        sa.Column('size', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('storage_path', sa.String(length=512), nullable=True),
        sa.Column('encrypted_blob', sa.JSON(), nullable=False),
        sa.Column('uploaded_by_user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_vault_attachment_item_id', 'vault_attachment', ['item_id'])

    op.create_table(
        'vault_audit_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('vault_organization.id'), nullable=True),
        sa.Column('item_id', sa.Integer(), sa.ForeignKey('vault_item.id'), nullable=True),
        sa.Column('action', sa.String(length=80), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_vault_audit_log_user_id', 'vault_audit_log', ['user_id'])


def downgrade():
    op.drop_index('ix_vault_audit_log_user_id', table_name='vault_audit_log')
    op.drop_table('vault_audit_log')
    op.drop_index('ix_vault_attachment_item_id', table_name='vault_attachment')
    op.drop_table('vault_attachment')
    op.drop_index('ix_vault_item_share_item_id', table_name='vault_item_share')
    op.drop_table('vault_item_share')
    op.drop_index('ix_vault_item_trashed', table_name='vault_item')
    op.drop_index('ix_vault_item_owner', table_name='vault_item')
    op.drop_table('vault_item')
    op.drop_table('vault_collection')
    op.drop_table('vault_organization_membership')
    op.drop_table('vault_organization')
    op.drop_table('vault_folder')
