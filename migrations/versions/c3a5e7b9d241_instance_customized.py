"""add customized flag to onboarding_instance

Revision ID: c3a5e7b9d241
Revises: b2f4d6a8c013
Create Date: 2026-10-26

Idempotent add-column (the table has drifted via create_all on prod before).
"""
from alembic import op
import sqlalchemy as sa


revision = 'c3a5e7b9d241'
down_revision = 'b2f4d6a8c013'
branch_labels = None
depends_on = None


def _has_column(table, column):
    insp = sa.inspect(op.get_bind())
    return column in {c['name'] for c in insp.get_columns(table)}


def upgrade():
    if not _has_column('onboarding_instance', 'customized'):
        op.add_column('onboarding_instance',
                      sa.Column('customized', sa.Boolean(), nullable=False,
                                server_default='0'))


def downgrade():
    if _has_column('onboarding_instance', 'customized'):
        op.drop_column('onboarding_instance', 'customized')
