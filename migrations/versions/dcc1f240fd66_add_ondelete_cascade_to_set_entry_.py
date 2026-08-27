"""add ondelete cascade to set_entry workout_id fk

Revision ID: dcc1f240fd66
Revises: e9729bd7ddd2
Create Date: 2026-08-26 19:17:29.472304

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'dcc1f240fd66'
down_revision = 'e9729bd7ddd2'
branch_labels = None
depends_on = None


# En SQLite las FK no tienen nombre real (confirmado con
# sa.inspect().get_foreign_keys()) -- batch_alter_table necesita un nombre
# sintético via naming_convention para poder referenciarla ahí. En Postgres
# sí hay un nombre real y persistente en pg_constraint, así que ahí se
# detecta dinámicamente en tiempo de migración en vez de hardcodearlo.
NAMING_CONVENTION = {'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s'}
FK_NAME_SQLITE = 'fk_set_entry_workout_id_workout'


def _fk_name(bind):
    insp = sa.inspect(bind)
    fk = next(
        fk for fk in insp.get_foreign_keys('set_entry')
        if fk['constrained_columns'] == ['workout_id']
    )
    return fk['name']


def upgrade():
    bind = op.get_bind()
    is_pg = bind.dialect.name == 'postgresql'
    if is_pg:
        name, kwargs = _fk_name(bind), {}
    else:
        name, kwargs = FK_NAME_SQLITE, {'naming_convention': NAMING_CONVENTION}
    with op.batch_alter_table('set_entry', schema=None, **kwargs) as batch_op:
        batch_op.drop_constraint(name, type_='foreignkey')
        batch_op.create_foreign_key(name, 'workout', ['workout_id'], ['id'], ondelete='CASCADE')


def downgrade():
    bind = op.get_bind()
    is_pg = bind.dialect.name == 'postgresql'
    if is_pg:
        # Tras upgrade() la constraint sigue llamándose igual (create_foreign_key reusó el mismo `name`).
        name, kwargs = _fk_name(bind), {}
    else:
        name, kwargs = FK_NAME_SQLITE, {'naming_convention': NAMING_CONVENTION}
    with op.batch_alter_table('set_entry', schema=None, **kwargs) as batch_op:
        batch_op.drop_constraint(name, type_='foreignkey')
        batch_op.create_foreign_key(name, 'workout', ['workout_id'], ['id'])
