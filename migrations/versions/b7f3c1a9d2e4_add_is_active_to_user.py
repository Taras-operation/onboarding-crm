"""add is_active to user

Revision ID: b7f3c1a9d2e4
Revises: add_template_sharing_fields
Create Date: 2026-08-07

Adds User.is_active. Existing rows default to active (server_default true) so the
deploy does not lock anyone out; deactivation is then an explicit admin action.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b7f3c1a9d2e4'
down_revision = 'add_template_sharing_fields'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'user',
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
    )


def downgrade():
    op.drop_column('user', 'is_active')
