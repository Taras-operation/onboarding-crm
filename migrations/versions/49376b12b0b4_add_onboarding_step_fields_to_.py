"""Add onboarding_step fields to OnboardingInstance

Revision ID: 49376b12b0b4
Revises: 1c3cca2707a2
Create Date: 2025-06-26 19:22:51.469227

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '49376b12b0b4'
down_revision = '1c3cca2707a2'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('onboarding_instance', sa.Column('onboarding_step', sa.Integer(), nullable=True))
    op.add_column('onboarding_instance', sa.Column('onboarding_step_total', sa.Integer(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('onboarding_instance', 'onboarding_step_total')
    op.drop_column('onboarding_instance', 'onboarding_step')
    # ### end Alembic commands ###
