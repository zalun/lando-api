"""Diff ID added

Revision ID: 363fc0301235
Revises: 67151bb74080
Create Date: 2017-07-11 13:38:58.995392

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '363fc0301235'
down_revision = '67151bb74080'
branch_labels = ()
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column(
        'landings', sa.Column('diff_id', sa.Integer(), nullable=True)
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('landings', 'diff_id')
    # ### end Alembic commands ###
