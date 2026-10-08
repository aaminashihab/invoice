"""Milestone M4B Phase 1: Controlled Pilot Hardening schema migration.

Adds user_session, lpo, lpo_line tables.
Adds LPO binding, site receipt verification, and document quarantine fields.
Compatible with both PostgreSQL and SQLite.

Revision ID: 003_m4b_pilot_hardening
Revises: 002_m4a_pilot
Create Date: 2026-10-08 11:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = '003_m4b_pilot_hardening'
down_revision: Union[str, None] = '002_m4a_pilot'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == 'sqlite'
    insp = inspect(bind)
    existing_tables = set(insp.get_table_names())

    # 1. Create user_session table
    if 'user_session' not in existing_tables:
        op.create_table(
            'user_session',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('user_id', sa.String(length=36), sa.ForeignKey('user.id', name='fk_user_session_user_id'), nullable=False),
            sa.Column('session_token_hash', sa.String(length=64), unique=True, nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('is_revoked', sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column('revoked_at', sa.DateTime(), nullable=True),
            sa.Column('ip_address', sa.String(length=50), nullable=True),
            sa.Column('user_agent', sa.String(length=255), nullable=True),
            sa.Column(
                'created_at',
                sa.DateTime(),
                server_default=sa.text('(CURRENT_TIMESTAMP)'),
                nullable=False,
            ),
        )
        op.create_index('ix_user_session_user_id', 'user_session', ['user_id'], unique=False)
        op.create_index('ix_user_session_token_hash', 'user_session', ['session_token_hash'], unique=True)

    # 2. Create lpo table
    if 'lpo' not in existing_tables:
        op.create_table(
            'lpo',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('lpo_number', sa.String(length=100), unique=True, nullable=False),
            sa.Column('project_id', sa.String(length=36), sa.ForeignKey('project.id', name='fk_lpo_project_id'), nullable=False),
            sa.Column('supplier_id', sa.String(length=36), sa.ForeignKey('supplier.id', name='fk_lpo_supplier_id'), nullable=False),
            sa.Column('lpo_date', sa.String(length=30), nullable=False),
            sa.Column('currency', sa.String(length=10), server_default='AED', nullable=False),
            sa.Column('document_id', sa.String(length=36), sa.ForeignKey('document.id', name='fk_lpo_document_id'), nullable=True),
            sa.Column('total_amount_cap', sa.Text(), nullable=True),
            sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column('created_by', sa.String(length=36), sa.ForeignKey('user.id', name='fk_lpo_created_by'), nullable=True),
            sa.Column(
                'created_at',
                sa.DateTime(),
                server_default=sa.text('(CURRENT_TIMESTAMP)'),
                nullable=False,
            ),
        )
        op.create_index('ix_lpo_number', 'lpo', ['lpo_number'], unique=True)
        op.create_index('ix_lpo_project_id', 'lpo', ['project_id'], unique=False)
        op.create_index('ix_lpo_supplier_id', 'lpo', ['supplier_id'], unique=False)

    # 3. Create lpo_line table
    if 'lpo_line' not in existing_tables:
        op.create_table(
            'lpo_line',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('lpo_id', sa.String(length=36), sa.ForeignKey('lpo.id', name='fk_lpo_line_lpo_id'), nullable=False),
            sa.Column('line_no', sa.Integer(), nullable=False),
            sa.Column('material_id', sa.String(length=36), sa.ForeignKey('material.id', name='fk_lpo_line_material_id'), nullable=True),
            sa.Column('description', sa.String(length=255), nullable=False),
            sa.Column('ordered_qty', sa.Text(), nullable=False),
            sa.Column('unit', sa.String(length=20), nullable=False),
            sa.Column('agreed_unit_price', sa.Text(), nullable=False),
            sa.Column('line_amount_cap', sa.Text(), nullable=True),
        )
        op.create_index('ix_lpo_line_lpo_id', 'lpo_line', ['lpo_id'], unique=False)

    # Helper for adding columns
    def add_col_if_missing(table_name: str, col_name: str, sqlite_sql: str, sa_col: sa.Column):
        if is_sqlite:
            existing_cols = [c[1] for c in bind.execute(sa.text(f"PRAGMA table_info({table_name})")).fetchall()]
            if col_name not in existing_cols:
                op.execute(f"ALTER TABLE {table_name} ADD COLUMN {sqlite_sql}")
        else:
            op.add_column(table_name, sa_col)

    # 4. Verification case LPO binding
    add_col_if_missing(
        'verification_case',
        'lpo_id',
        'lpo_id VARCHAR(36) REFERENCES lpo(id)',
        sa.Column('lpo_id', sa.String(length=36), sa.ForeignKey('lpo.id', name='fk_verification_case_lpo_id'), nullable=True)
    )

    # 5. Document quarantine and scan fields
    add_col_if_missing(
        'document',
        'quarantine_status',
        "quarantine_status VARCHAR(30) NOT NULL DEFAULT 'CLEAN'",
        sa.Column('quarantine_status', sa.String(length=30), server_default='CLEAN', nullable=False)
    )
    add_col_if_missing(
        'document',
        'security_scan_result',
        'security_scan_result VARCHAR(100)',
        sa.Column('security_scan_result', sa.String(length=100), nullable=True)
    )
    add_col_if_missing(
        'document',
        'is_quarantined',
        'is_quarantined BOOLEAN NOT NULL DEFAULT 0',
        sa.Column('is_quarantined', sa.Boolean(), server_default=sa.false(), nullable=False)
    )

    # 6. Line item site receipt and engineer verification metadata
    add_col_if_missing(
        'line_item',
        'storekeeper_ticket_no',
        'storekeeper_ticket_no VARCHAR(100)',
        sa.Column('storekeeper_ticket_no', sa.String(length=100), nullable=True)
    )
    add_col_if_missing(
        'line_item',
        'gate_entry_at',
        'gate_entry_at DATETIME',
        sa.Column('gate_entry_at', sa.DateTime(), nullable=True)
    )
    add_col_if_missing(
        'line_item',
        'storekeeper_confirmed',
        'storekeeper_confirmed BOOLEAN NOT NULL DEFAULT 0',
        sa.Column('storekeeper_confirmed', sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    add_col_if_missing(
        'line_item',
        'storekeeper_user_id',
        'storekeeper_user_id VARCHAR(36) REFERENCES user(id)',
        sa.Column('storekeeper_user_id', sa.String(length=36), sa.ForeignKey('user.id', name='fk_line_item_storekeeper_user_id'), nullable=True)
    )
    add_col_if_missing(
        'line_item',
        'engineer_verified',
        'engineer_verified BOOLEAN NOT NULL DEFAULT 0',
        sa.Column('engineer_verified', sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    add_col_if_missing(
        'line_item',
        'engineer_user_id',
        'engineer_user_id VARCHAR(36) REFERENCES user(id)',
        sa.Column('engineer_user_id', sa.String(length=36), sa.ForeignKey('user.id', name='fk_line_item_engineer_user_id'), nullable=True)
    )
    add_col_if_missing(
        'line_item',
        'rejected_qty',
        'rejected_qty TEXT',
        sa.Column('rejected_qty', sa.Text(), nullable=True)
    )
    add_col_if_missing(
        'line_item',
        'rejection_reason_code',
        'rejection_reason_code VARCHAR(50)',
        sa.Column('rejection_reason_code', sa.String(length=50), nullable=True)
    )
    add_col_if_missing(
        'line_item',
        'has_rejection_evidence',
        'has_rejection_evidence BOOLEAN NOT NULL DEFAULT 0',
        sa.Column('has_rejection_evidence', sa.Boolean(), server_default=sa.false(), nullable=False)
    )

    # 7. Line link LPO line binding
    add_col_if_missing(
        'line_link',
        'lpo_line_id',
        'lpo_line_id VARCHAR(36) REFERENCES lpo_line(id)',
        sa.Column('lpo_line_id', sa.String(length=36), sa.ForeignKey('lpo_line.id', name='fk_line_link_lpo_line_id'), nullable=True)
    )


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == 'sqlite'

    if not is_sqlite:
        op.drop_column('line_link', 'lpo_line_id')
        op.drop_column('line_item', 'has_rejection_evidence')
        op.drop_column('line_item', 'rejection_reason_code')
        op.drop_column('line_item', 'rejected_qty')
        op.drop_column('line_item', 'engineer_user_id')
        op.drop_column('line_item', 'engineer_verified')
        op.drop_column('line_item', 'storekeeper_user_id')
        op.drop_column('line_item', 'storekeeper_confirmed')
        op.drop_column('line_item', 'gate_entry_at')
        op.drop_column('line_item', 'storekeeper_ticket_no')
        op.drop_column('document', 'is_quarantined')
        op.drop_column('document', 'security_scan_result')
        op.drop_column('document', 'quarantine_status')
        op.drop_column('verification_case', 'lpo_id')

    op.drop_index('ix_lpo_line_lpo_id', table_name='lpo_line')
    op.drop_table('lpo_line')

    op.drop_index('ix_lpo_supplier_id', table_name='lpo')
    op.drop_index('ix_lpo_project_id', table_name='lpo')
    op.drop_index('ix_lpo_number', table_name='lpo')
    op.drop_table('lpo')

    op.drop_index('ix_user_session_token_hash', table_name='user_session')
    op.drop_index('ix_user_session_user_id', table_name='user_session')
    op.drop_table('user_session')
