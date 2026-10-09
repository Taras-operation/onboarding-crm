"""template change log table

Revision ID: e7a9c1b35d20
Revises: f4b1c2d3e5a6
Create Date: 2026-10-09

Idempotent: creates `template_change_log` only if it isn't already there, so it is
safe on a DB that drifted via create_all as well as on a strict-migration DB.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = 'e7a9c1b35d20'
down_revision = 'f4b1c2d3e5a6'
branch_labels = None
depends_on = None


def _has_table(name):
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade():
    if _has_table('template_change_log'):
        return

    json_type = JSONB() if op.get_bind().dialect.name == 'postgresql' else sa.JSON()

    op.create_table(
        'template_change_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True),
        sa.Column('username', sa.String(length=150), nullable=True),
        sa.Column('user_role', sa.String(length=50), nullable=True),
        sa.Column('template_id', sa.Integer(), nullable=True),
        sa.Column('template_name', sa.String(length=255), nullable=True),
        sa.Column('action', sa.String(length=32), nullable=True),
        sa.Column('kind', sa.String(length=32), nullable=True),
        sa.Column('details', json_type, nullable=True),
        sa.Column('summary', sa.String(length=500), nullable=True),
    )
    op.create_index('ix_template_change_log_created_at',
                    'template_change_log', ['created_at'])
    op.create_index('ix_template_change_log_template_id',
                    'template_change_log', ['template_id'])


def downgrade():
    if _has_table('template_change_log'):
        op.drop_index('ix_template_change_log_template_id', table_name='template_change_log')
        op.drop_index('ix_template_change_log_created_at', table_name='template_change_log')
        op.drop_table('template_change_log')
