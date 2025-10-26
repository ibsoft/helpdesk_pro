"""add assistant sessions, messages, and documents

Revision ID: d4c6c1c3f5c4
Revises: 9f3d1c9d4c2d
Create Date: 2025-10-26 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4c6c1c3f5c4'
down_revision = '9f3d1c9d4c2d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'assistant_session',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=True),
        sa.Column('is_archived', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_assistant_session_user_id', 'assistant_session', ['user_id'])

    op.create_table(
        'assistant_message',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('token_usage', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['session_id'], ['assistant_session.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_assistant_message_session_id', 'assistant_message', ['session_id'])
    op.create_index('ix_assistant_message_created_at', 'assistant_message', ['created_at'])

    op.create_table(
        'assistant_document',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('stored_filename', sa.String(length=255), nullable=False),
        sa.Column('mimetype', sa.String(length=120), nullable=True),
        sa.Column('file_size', sa.BigInteger(), nullable=True),
        sa.Column('extracted_text', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='ready'),
        sa.Column('failure_reason', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['session_id'], ['assistant_session.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_assistant_document_session_id', 'assistant_document', ['session_id'])
    op.create_index('ix_assistant_document_user_id', 'assistant_document', ['user_id'])


def downgrade():
    op.drop_index('ix_assistant_document_user_id', table_name='assistant_document')
    op.drop_index('ix_assistant_document_session_id', table_name='assistant_document')
    op.drop_table('assistant_document')
    op.drop_index('ix_assistant_message_created_at', table_name='assistant_message')
    op.drop_index('ix_assistant_message_session_id', table_name='assistant_message')
    op.drop_table('assistant_message')
    op.drop_index('ix_assistant_session_user_id', table_name='assistant_session')
    op.drop_table('assistant_session')
