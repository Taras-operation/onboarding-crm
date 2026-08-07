"""add login_attempt table

Revision ID: c8d4e2f10a9b
Revises: b7f3c1a9d2e4
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa


revision = 'c8d4e2f10a9b'
down_revision = 'b7f3c1a9d2e4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'login_attempt',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('username', sa.String(length=150), nullable=True),
        sa.Column('ip', sa.String(length=64), nullable=True),
        sa.Column('user_agent', sa.String(length=400), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_login_attempt_user_id', 'login_attempt', ['user_id'])
    op.create_index('ix_login_attempt_created_at', 'login_attempt', ['created_at'])


def downgrade():
    op.drop_index('ix_login_attempt_created_at', table_name='login_attempt')
    op.drop_index('ix_login_attempt_user_id', table_name='login_attempt')
    op.drop_table('login_attempt')
