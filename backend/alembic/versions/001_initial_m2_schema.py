"""Initial M2 schema with all 16 Revision 3 tables

Revision ID: 001_initial_m2
Revises: 
Create Date: 2026-10-06 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '001_initial_m2'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. user
    op.create_table(
        'user',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=120), unique=True, nullable=False),
        sa.Column('role', sa.String(length=30), nullable=False),
        sa.Column('can_review', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('active', sa.Boolean(), server_default=sa.true(), nullable=False),
    )

    # 2. project
    op.create_table(
        'project',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('code', sa.String(length=50), unique=True, nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('client', sa.String(length=200), nullable=False),
        sa.Column('site_location', sa.String(length=200), nullable=False),
        sa.Column('active', sa.Boolean(), server_default=sa.true(), nullable=False),
    )

    # 3. supplier
    op.create_table(
        'supplier',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('trn', sa.String(length=20), nullable=False),
        sa.Column('aliases', sa.JSON(), nullable=False),
        sa.Column('active', sa.Boolean(), server_default=sa.true(), nullable=False),
    )

    # 4. material
    op.create_table(
        'material',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('code', sa.String(length=50), unique=True, nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('default_unit', sa.String(length=20), nullable=False),
        sa.Column('aliases', sa.JSON(), nullable=False),
        sa.Column('spec_attributes', sa.JSON(), nullable=False),
    )

    # 5. unit
    op.create_table(
        'unit',
        sa.Column('code', sa.String(length=20), primary_key=True),
        sa.Column('dimension', sa.String(length=30), nullable=False),
        sa.Column('aliases', sa.JSON(), nullable=False),
    )

    # 6. unit_conversion
    op.create_table(
        'unit_conversion',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('from_unit', sa.String(length=20), sa.ForeignKey('unit.code'), nullable=False),
        sa.Column('to_unit', sa.String(length=20), sa.ForeignKey('unit.code'), nullable=False),
        sa.Column('factor', sa.Text(), nullable=False),
        sa.Column('scope', sa.String(length=20), nullable=False),
        sa.Column('material_id', sa.String(length=36), sa.ForeignKey('material.id'), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='PROPOSED', nullable=False),
        sa.Column('confirmed_by', sa.String(length=36), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.Column('source_note', sa.Text(), nullable=True),
    )

    # 7. verification_case
    op.create_table(
        'verification_case',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('case_ref', sa.String(length=50), unique=True, nullable=False),
        sa.Column('project_id', sa.String(length=36), sa.ForeignKey('project.id'), nullable=False),
        sa.Column('supplier_id', sa.String(length=36), sa.ForeignKey('supplier.id'), nullable=False),
        sa.Column('invoice_number_hint', sa.String(length=100), nullable=True),
        sa.Column('currency', sa.String(length=10), server_default='AED', nullable=False),
        sa.Column('lpo_required', sa.Boolean(), nullable=False),
        sa.Column('lpo_reason_code', sa.String(length=50), nullable=True),
        sa.Column('lpo_reason_text', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=50), server_default='DRAFT', nullable=False),
        sa.Column('assignee_reviewer_id', sa.String(length=36), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('created_by', sa.String(length=36), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('locked_at', sa.DateTime(), nullable=True),
    )

    # 8. document
    op.create_table(
        'document',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('case_id', sa.String(length=36), sa.ForeignKey('verification_case.id'), nullable=False),
        sa.Column('doc_type', sa.String(length=20), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('storage_key', sa.String(length=255), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('page_count', sa.Integer(), server_default='1', nullable=False),
        sa.Column('uploaded_by', sa.String(length=36), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(), nullable=False),
        sa.Column('extraction_status', sa.String(length=30), server_default='PENDING', nullable=False),
        sa.Column('extraction_error', sa.Text(), nullable=True),
        sa.Column('extractor_name', sa.String(length=50), nullable=True),
        sa.Column('data_review_status', sa.String(length=30), server_default='UNREVIEWED', nullable=False),
        sa.Column('reference_no_normalized', sa.String(length=100), nullable=True),
        sa.Column('superseded_by_id', sa.String(length=36), sa.ForeignKey('document.id'), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default=sa.false(), nullable=False),
    )

    # 9. line_item
    op.create_table(
        'line_item',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('document_id', sa.String(length=36), sa.ForeignKey('document.id'), nullable=False),
        sa.Column('line_no', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=20), server_default='MATERIAL', nullable=False),
        sa.Column('material_id', sa.String(length=36), sa.ForeignKey('material.id'), nullable=True),
        sa.Column('deleted_reason', sa.Text(), nullable=True),
    )

    # 10. extracted_field
    op.create_table(
        'extracted_field',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('document_id', sa.String(length=36), sa.ForeignKey('document.id'), nullable=False),
        sa.Column('line_item_id', sa.String(length=36), sa.ForeignKey('line_item.id'), nullable=True),
        sa.Column('field_key', sa.String(length=100), nullable=False),
        sa.Column('raw_value', sa.Text(), nullable=True),
        sa.Column('normalized_value', sa.Text(), nullable=True),
        sa.Column('value_type', sa.String(length=30), nullable=False),
        sa.Column('confidence', sa.String(length=10), nullable=True),
        sa.Column('status', sa.String(length=30), server_default='EXTRACTED', nullable=False),
        sa.Column('source_page', sa.Integer(), nullable=True),
        sa.Column('source_bbox', sa.JSON(), nullable=True),
        sa.Column('source_text', sa.Text(), nullable=True),
        sa.Column('method', sa.String(length=30), server_default='MOCK', nullable=False),
        sa.Column('updated_by', sa.String(length=36), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )

    # 11. field_revision
    op.create_table(
        'field_revision',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('field_id', sa.String(length=36), sa.ForeignKey('extracted_field.id'), nullable=False),
        sa.Column('old_value', sa.Text(), nullable=True),
        sa.Column('new_value', sa.Text(), nullable=True),
        sa.Column('old_status', sa.String(length=30), nullable=True),
        sa.Column('new_status', sa.String(length=30), nullable=True),
        sa.Column('reason_code', sa.String(length=50), nullable=True),
        sa.Column('reason_text', sa.Text(), nullable=True),
        sa.Column('actor_id', sa.String(length=36), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('at', sa.DateTime(), nullable=False),
    )

    # 12. line_link
    op.create_table(
        'line_link',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('case_id', sa.String(length=36), sa.ForeignKey('verification_case.id'), nullable=False),
        sa.Column('invoice_line_id', sa.String(length=36), sa.ForeignKey('line_item.id'), nullable=False),
        sa.Column('dn_line_id', sa.String(length=36), sa.ForeignKey('line_item.id'), nullable=False),
        sa.Column('link_method', sa.String(length=30), server_default='MANUAL', nullable=False),
        sa.Column('status', sa.String(length=30), server_default='CONFIRMED', nullable=False),
        sa.Column('confirmed_by', sa.String(length=36), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('case_id', 'dn_line_id', name='uq_case_dn_line_link'),
    )

    # 13. verification_run
    op.create_table(
        'verification_run',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('case_id', sa.String(length=36), sa.ForeignKey('verification_case.id'), nullable=False),
        sa.Column('run_no', sa.Integer(), nullable=False),
        sa.Column('ruleset_version', sa.String(length=50), nullable=False),
        sa.Column('active_checks', sa.JSON(), nullable=False),
        sa.Column('input_snapshot', sa.JSON(), nullable=False),
        sa.Column('input_hash', sa.String(length=64), nullable=False),
        sa.Column('summary', sa.String(length=100), nullable=False),
        sa.Column('summary_labels', sa.JSON(), nullable=False),
        sa.Column('started_by', sa.String(length=36), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('duration_ms', sa.Integer(), server_default='0', nullable=False),
    )

    # 14. finding
    op.create_table(
        'finding',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('run_id', sa.String(length=36), sa.ForeignKey('verification_run.id'), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('rule_code', sa.String(length=50), nullable=False),
        sa.Column('outcome', sa.String(length=30), nullable=False),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('subject_type', sa.String(length=50), nullable=False),
        sa.Column('subject_id', sa.String(length=100), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('expected', sa.Text(), nullable=True),
        sa.Column('actual', sa.Text(), nullable=True),
        sa.Column('difference', sa.Text(), nullable=True),
        sa.Column('difference_pct', sa.Text(), nullable=True),
        sa.Column('unit', sa.String(length=20), nullable=True),
        sa.Column('conversion_used', sa.Text(), nullable=True),
        sa.Column('sources', sa.JSON(), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('rule_status', sa.String(length=20), server_default='CONFIRMED', nullable=False),
        sa.Column('numeric_policy', sa.String(length=30), nullable=True),
    )

    # 15. review
    op.create_table(
        'review',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('case_id', sa.String(length=36), sa.ForeignKey('verification_case.id'), nullable=False),
        sa.Column('run_id', sa.String(length=36), sa.ForeignKey('verification_run.id'), nullable=False),
        sa.Column('reviewer_id', sa.String(length=36), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('outcome', sa.String(length=50), nullable=False),
        sa.Column('comment', sa.Text(), nullable=False),
        sa.Column('declaration_accepted', sa.Boolean(), nullable=False),
        sa.Column('sod_warning', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('qualifiers', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('run_id', name='uq_review_run_id'),
    )

    # 16. finding_disposition
    op.create_table(
        'finding_disposition',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('review_id', sa.String(length=36), sa.ForeignKey('review.id'), nullable=False),
        sa.Column('finding_id', sa.String(length=36), sa.ForeignKey('finding.id'), nullable=False),
        sa.Column('disposition', sa.String(length=50), nullable=False),
        sa.Column('comment', sa.Text(), nullable=False),
        sa.Column('manual_check_items', sa.JSON(), nullable=False),
    )

    # 17. audit_event
    op.create_table(
        'audit_event',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('at', sa.DateTime(), nullable=False),
        sa.Column('actor_id', sa.String(length=36), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('entity_type', sa.String(length=50), nullable=False),
        sa.Column('entity_id', sa.String(length=100), nullable=False),
        sa.Column('case_id', sa.String(length=36), sa.ForeignKey('verification_case.id'), nullable=True),
        sa.Column('before_state', sa.JSON(), nullable=True),
        sa.Column('after_state', sa.JSON(), nullable=True),
        sa.Column('request_id', sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('audit_event')
    op.drop_table('finding_disposition')
    op.drop_table('review')
    op.drop_table('finding')
    op.drop_table('verification_run')
    op.drop_table('line_link')
    op.drop_table('field_revision')
    op.drop_table('extracted_field')
    op.drop_table('line_item')
    op.drop_table('document')
    op.drop_table('verification_case')
    op.drop_table('unit_conversion')
    op.drop_table('unit')
    op.drop_table('material')
    op.drop_table('supplier')
    op.drop_table('project')
    op.drop_table('user')
