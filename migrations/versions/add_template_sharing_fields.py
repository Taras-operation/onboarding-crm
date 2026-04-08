"""add template sharing fields

Revision ID: add_template_sharing_fields
Revises: 295ce02943bf
Create Date: 2026-04-08
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_template_sharing_fields'
down_revision = 'ca45cb293b26'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('onboarding_template', sa.Column('is_global', sa.Boolean(), nullable=True))
    op.add_column('onboarding_template', sa.Column('shared_departments', sa.JSON(), nullable=True))
    op.add_column('onboarding_template', sa.Column('is_copy', sa.Boolean(), nullable=True))
    op.add_column('onboarding_template', sa.Column('source_template_id', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('onboarding_template', 'source_template_id')
    op.drop_column('onboarding_template', 'is_copy')
    op.drop_column('onboarding_template', 'shared_departments')
    op.drop_column('onboarding_template', 'is_global')