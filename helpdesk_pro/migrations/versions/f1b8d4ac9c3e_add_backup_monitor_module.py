"""add backup monitor module tables

Revision ID: f1b8d4ac9c3e
Revises: ef1a0a4dbf77
Create Date: 2025-10-30 10:15:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f1b8d4ac9c3e'
down_revision = '42459622cc71'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'backup_tape_cartridge',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('barcode', sa.String(length=64), nullable=False),
        sa.Column('lto_generation', sa.String(length=16), nullable=False),
        sa.Column('nominal_capacity_tb', sa.Numeric(10, 2), nullable=True),
        sa.Column('usable_capacity_tb', sa.Numeric(10, 2), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='empty'),
        sa.Column('usage_tags', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('last_inventory_at', sa.DateTime(), nullable=True),
        sa.Column('current_location_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('barcode', name='uq_backup_tape_barcode'),
    )
    op.create_index(
        'ix_backup_tape_cartridge_status',
        'backup_tape_cartridge',
        ['status'],
        unique=False,
    )

    op.create_table(
        'backup_job',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('job_date', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('retention_days', sa.Integer(), nullable=False, server_default=sa.text('30')),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('total_files', sa.Integer(), nullable=True),
        sa.Column('total_size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('verify_result', sa.String(length=32), nullable=True),
        sa.Column('source_system', sa.String(length=120), nullable=True),
        sa.Column('responsible_user_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['responsible_user_id'], ['user.id'], name='fk_backup_job_responsible_user', ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_backup_job_job_date', 'backup_job', ['job_date'], unique=False)
    op.create_index('ix_backup_job_expires_at', 'backup_job', ['expires_at'], unique=False)

    op.create_table(
        'backup_audit_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_type', sa.String(length=32), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('field_name', sa.String(length=64), nullable=True),
        sa.Column('old_value', sa.Text(), nullable=True),
        sa.Column('new_value', sa.Text(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('changed_by_user_id', sa.Integer(), nullable=True),
        sa.Column('changed_by_username', sa.String(length=120), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['changed_by_user_id'], ['user.id'], name='fk_backup_audit_user', ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_backup_audit_log_entity',
        'backup_audit_log',
        ['entity_type', 'entity_id'],
        unique=False,
    )
    op.create_index(
        'ix_backup_audit_log_created_at',
        'backup_audit_log',
        ['created_at'],
        unique=False,
    )

    op.create_table(
        'backup_tape_location',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tape_id', sa.Integer(), nullable=False),
        sa.Column('location_type', sa.String(length=20), nullable=False),
        sa.Column('site_name', sa.String(length=120), nullable=True),
        sa.Column('shelf_code', sa.String(length=80), nullable=True),
        sa.Column('locker_code', sa.String(length=80), nullable=True),
        sa.Column('provider_name', sa.String(length=120), nullable=True),
        sa.Column('provider_contact', sa.String(length=120), nullable=True),
        sa.Column('custody_holder', sa.String(length=120), nullable=True),
        sa.Column('custody_reference', sa.String(length=120), nullable=True),
        sa.Column('check_in_at', sa.DateTime(), nullable=True),
        sa.Column('check_out_at', sa.DateTime(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_current', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['user.id'], name='fk_backup_location_user', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tape_id'], ['backup_tape_cartridge.id'], name='fk_backup_location_tape', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_backup_tape_location_tape_id', 'backup_tape_location', ['tape_id'], unique=False)
    op.create_index('ix_backup_tape_location_is_current', 'backup_tape_location', ['is_current'], unique=False)

    op.create_table(
        'backup_job_tape',
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('tape_id', sa.Integer(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['job_id'], ['backup_job.id'], name='fk_backup_job_tape_job', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tape_id'], ['backup_tape_cartridge.id'], name='fk_backup_job_tape_tape', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('job_id', 'tape_id'),
        sa.UniqueConstraint('job_id', 'tape_id', name='uq_backup_job_tape_membership'),
    )
    op.create_index('ix_backup_job_tape_sequence', 'backup_job_tape', ['sequence'], unique=False)

    op.create_table(
        'backup_tape_custody',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tape_id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=32), nullable=False, server_default='transfer'),
        sa.Column('event_time', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('handed_over_by', sa.String(length=120), nullable=True),
        sa.Column('handed_over_signature', sa.String(length=120), nullable=True),
        sa.Column('received_by', sa.String(length=120), nullable=True),
        sa.Column('received_signature', sa.String(length=120), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['user.id'], name='fk_backup_custody_user', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tape_id'], ['backup_tape_cartridge.id'], name='fk_backup_custody_tape', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_backup_tape_custody_event_time', 'backup_tape_custody', ['event_time'], unique=False)

    op.create_foreign_key(
        'fk_backup_tape_current_location',
        'backup_tape_cartridge',
        'backup_tape_location',
        ['current_location_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade():
    op.drop_constraint('fk_backup_tape_current_location', 'backup_tape_cartridge', type_='foreignkey')

    op.drop_index('ix_backup_tape_custody_event_time', table_name='backup_tape_custody')
    op.drop_table('backup_tape_custody')

    op.drop_index('ix_backup_job_tape_sequence', table_name='backup_job_tape')
    op.drop_table('backup_job_tape')

    op.drop_index('ix_backup_tape_location_is_current', table_name='backup_tape_location')
    op.drop_index('ix_backup_tape_location_tape_id', table_name='backup_tape_location')
    op.drop_table('backup_tape_location')

    op.drop_index('ix_backup_audit_log_created_at', table_name='backup_audit_log')
    op.drop_index('ix_backup_audit_log_entity', table_name='backup_audit_log')
    op.drop_table('backup_audit_log')

    op.drop_index('ix_backup_job_expires_at', table_name='backup_job')
    op.drop_index('ix_backup_job_job_date', table_name='backup_job')
    op.drop_table('backup_job')

    op.drop_index('ix_backup_tape_cartridge_status', table_name='backup_tape_cartridge')
    op.drop_table('backup_tape_cartridge')
