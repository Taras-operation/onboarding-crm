"""add reviewed_blocks to onboarding_instance

Revision ID: b2f4d6a8c013
Revises: e7a9c1b35d20
Create Date: 2026-10-26

Idempotent: adds the column only if it isn't already present (the onboarding_instance
table has drifted via create_all on prod before), so it's safe either way.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b2f4d6a8c013'
down_revision = 'e7a9c1b35d20'
branch_labels = None
depends_on = None


def _has_column(table, column):
    insp = sa.inspect(op.get_bind())
    return column in {c['name'] for c in insp.get_columns(table)}


def upgrade():
    if not _has_column('onboarding_instance', 'reviewed_blocks'):
        op.add_column('onboarding_instance',
                      sa.Column('reviewed_blocks', sa.Integer(), nullable=False,
                                server_default='0'))


def downgrade():
    if _has_column('onboarding_instance', 'reviewed_blocks'):
        op.drop_column('onboarding_instance', 'reviewed_blocks')
