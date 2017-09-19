"""save_patches_and_timestamp

Revision ID: b164a1024568
Revises: 363fc0301235
Create Date: 2017-09-13 11:52:53.665046

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

from landoapi.phabricator import revision_id_to_int

# revision identifiers, used by Alembic.
revision = 'b164a1024568'
down_revision = '363fc0301235'
branch_labels = ()
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        'patches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('landing_id', sa.Integer(), nullable=True),
        sa.Column('revision_id', sa.Integer(), nullable=True),
        sa.Column('diff_id', sa.Integer(), nullable=True),
        sa.Column('s3_url', sa.String(length=128), nullable=True),
        sa.Column('created', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ['landing_id'],
            ['landings.id'],
        ), sa.PrimaryKeyConstraint('id')
    )

    # Change type of the column revision_id from String to Integer.
    # There is no full support of ALTER TABLE in SQLite
    # landoapi.phabricator.revision_id_to_int will be used on each value.
    conn = op.get_bind()
    conn.execute(text('ALTER TABLE landings RENAME TO tmp_landings'))
    op.create_table(
        'landings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.Integer(), nullable=True),
        sa.Column('revision_id', sa.Integer(), nullable=True),
        sa.Column('diff_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(30), nullable=True),
        sa.Column('error', sa.String(length=128), nullable=True),
        sa.Column('result', sa.String(length=128), nullable=True),
        sa.Column('created', sa.DateTime(), nullable=True),
        sa.Column('updated', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'), sa.UniqueConstraint('request_id')
    )
    result = conn.execute(
        text('SELECT id, request_id, revision_id, status FROM tmp_landings')
    )
    for row in result:
        landing_id, request_id, revision_id, status = row
        conn.execute(
            text(
                'INSERT INTO landings (id, request_id, revision_id, status)'
                'VALUES ({id}, {request_id}, {revision_id}, "{status}")'.format(
                    id=landing_id,
                    request_id=request_id,
                    revision_id=revision_id_to_int(revision_id),
                    status=status
                )
            )
        )

    op.drop_table('tmp_landings')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('patches')

    # converting back to String (from 3 to 'D3')
    conn = op.get_bind()
    conn.execute(text('ALTER TABLE landings RENAME TO tmp_landings'))
    op.create_table(
        'landings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.Integer(), nullable=True),
        sa.Column('revision_id', sa.String(30), nullable=True),
        sa.Column('diff_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(30), nullable=True),
        sa.PrimaryKeyConstraint('id'), sa.UniqueConstraint('request_id')
    )
    result = conn.execute(
        text('SELECT id, request_id, revision_id, status FROM tmp_landings')
    )
    for row in result:
        landing_id, request_id, revision_id, status = row
        conn.execute(
            text(
                'INSERT INTO landings (id, request_id, revision_id, status)'
                'VALUES ({id}, {request_id}, "{revision_id}", "{status}")'.
                format(
                    id=landing_id,
                    request_id=request_id,
                    revision_id='D{}'.format(revision_id),
                    status=status
                )
            )
        )

    op.drop_table('tmp_landings')
    # ### end Alembic commands ###
