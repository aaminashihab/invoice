"""Milestone M4A: Controlled Internal Pilot Foundation schema migration.

Adds project_user relationship table and authentication fields to user table.
Compatible with both PostgreSQL and SQLite.

Revision ID: 002_m4a_pilot
Revises: 001_initial_m2
Create Date: 2026-10-07 16:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '002_m4a_pilot'
down_revision: Union[str, None] = '001_initial_m2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update user table with authentication credentials and created_at
    op.add_column('user', sa.Column('hashed_password', sa.String(length=255), nullable=True))
    op.add_column('user', sa.Column('created_at', sa.DateTime(), nullable=True))
    op.execute('UPDATE "user" SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL')

    # 2. Create project_user relationship table
    op.create_table(
        'project_user',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('project_id', sa.String(length=36), sa.ForeignKey('project.id'), nullable=False),
        sa.Column('user_id', sa.String(length=36), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('assigned_by', sa.String(length=36), sa.ForeignKey('user.id'), nullable=True),
        sa.Column(
            'assigned_at',
            sa.DateTime(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.UniqueConstraint('project_id', 'user_id', name='uq_project_user'),
    )
    op.create_index('ix_project_user_project_id', 'project_user', ['project_id'], unique=False)
    op.create_index('ix_project_user_user_id', 'project_user', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_project_user_user_id', table_name='project_user')
    op.drop_index('ix_project_user_project_id', table_name='project_user')
    op.drop_table('project_user')
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('created_at')
        batch_op.drop_column('hashed_password')
