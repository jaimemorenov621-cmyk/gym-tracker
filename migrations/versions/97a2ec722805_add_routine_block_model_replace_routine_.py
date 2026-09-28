"""add routine_block model, replace routine.block string with block_id

Revision ID: 97a2ec722805
Revises: 02c102e829b3
Create Date: 2026-09-28 09:52:00.631926

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '97a2ec722805'
down_revision = '02c102e829b3'
branch_labels = None
depends_on = None

# Paleta para dar un color de partida distinto a cada bloque migrado desde el
# antiguo texto libre -- solo para que no salgan todos del mismo color hasta
# que el usuario los personalice a mano.
_DEFAULT_PALETTE = ['#7c4dff', '#22c98c', '#ff9800', '#e91e63', '#00acc1', '#8d6e63']

_meta = sa.MetaData()
routine_table = sa.Table(
    'routine',
    _meta,
    sa.Column('id', sa.Integer, primary_key=True),
    sa.Column('user_id', sa.Integer),
    sa.Column('block', sa.String),
    sa.Column('block_id', sa.Integer),
)
routine_block_table = sa.Table(
    'routine_block',
    _meta,
    sa.Column('id', sa.Integer, primary_key=True),
    sa.Column('name', sa.String),
    sa.Column('color', sa.String),
    sa.Column('is_default', sa.Boolean),
    sa.Column('order_index', sa.Integer),
    sa.Column('user_id', sa.Integer),
)


def upgrade():
    op.create_table('routine_block',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('color', sa.String(length=7), nullable=False),
    sa.Column('is_default', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('order_index', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('routine_block', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_routine_block_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('routine', schema=None) as batch_op:
        batch_op.add_column(sa.Column('block_id', sa.Integer(), nullable=True))

    # Migra los valores de texto libre existentes en routine.block a filas
    # reales de routine_block, y enlaza routine.block_id -- antes de borrar
    # la columna vieja, para no perder la clasificación que ya hubiera hecho
    # el usuario en producción.
    conn = op.get_bind()
    rows = conn.execute(
        sa.select(routine_table.c.id, routine_table.c.user_id, routine_table.c.block)
        .where(routine_table.c.block.isnot(None))
    ).fetchall()

    block_ids = {}
    next_order = {}
    for row in rows:
        key = (row.user_id, row.block)
        if key not in block_ids:
            idx = next_order.get(row.user_id, 0)
            color = _DEFAULT_PALETTE[idx % len(_DEFAULT_PALETTE)]
            result = conn.execute(
                routine_block_table.insert().values(
                    name=row.block, color=color, is_default=False, order_index=idx, user_id=row.user_id
                )
            )
            block_ids[key] = result.inserted_primary_key[0]
            next_order[row.user_id] = idx + 1
        conn.execute(
            routine_table.update()
            .where(routine_table.c.id == row.id)
            .values(block_id=block_ids[key])
        )

    with op.batch_alter_table('routine', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_routine_block_id'), ['block_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_routine_block_id', 'routine_block', ['block_id'], ['id'], ondelete='SET NULL'
        )
        batch_op.drop_column('block')


def downgrade():
    with op.batch_alter_table('routine', schema=None) as batch_op:
        batch_op.add_column(sa.Column('block', sa.VARCHAR(length=64), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(
        sa.select(routine_table.c.id, routine_block_table.c.name)
        .select_from(routine_table.join(routine_block_table, routine_table.c.block_id == routine_block_table.c.id))
    ).fetchall()
    for row in rows:
        conn.execute(
            routine_table.update().where(routine_table.c.id == row.id).values(block=row.name)
        )

    with op.batch_alter_table('routine', schema=None) as batch_op:
        batch_op.drop_constraint('fk_routine_block_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_routine_block_id'))
        batch_op.drop_column('block_id')

    with op.batch_alter_table('routine_block', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_routine_block_user_id'))

    op.drop_table('routine_block')
