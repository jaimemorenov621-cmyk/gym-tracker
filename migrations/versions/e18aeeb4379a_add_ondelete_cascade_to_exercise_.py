"""add ondelete cascade to exercise_favorite fk

Revision ID: e18aeeb4379a
Revises: 70f45d78aeef
Create Date: 2026-08-21 21:18:36.704690

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e18aeeb4379a'
down_revision = '70f45d78aeef'
branch_labels = None
depends_on = None


FK_NAME_PG = 'exercise_favorite_exercise_id_fkey'  # verificado a mano contra pg_constraint en producción
FK_NAME_SQLITE = 'fk_exercise_favorite_exercise_id_exercise'  # nombre sintético, ver naming_convention abajo
NAMING_CONVENTION = {'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s'}


def upgrade():
    # batch_alter_table recrea la tabla entera en SQLite (no soporta ALTER
    # de constraints), pero en Postgres altera in-place -- ahí hace falta
    # el nombre REAL de la constraint. El autogenerado por Alembic venía
    # como None, que directamente no es un nombre válido para
    # drop_constraint() en ningún dialecto con esta versión de Alembic; en
    # SQLite la propia constraint no tiene nombre en absoluto (confirmado
    # con sa.inspect().get_foreign_keys()), así que se le da un nombre
    # sintético vía naming_convention para poder referenciarla.
    bind = op.get_bind()
    is_pg = bind.dialect.name == 'postgresql'
    name = FK_NAME_PG if is_pg else FK_NAME_SQLITE
    kwargs = {} if is_pg else {'naming_convention': NAMING_CONVENTION}
    with op.batch_alter_table('exercise_favorite', schema=None, **kwargs) as batch_op:
        batch_op.drop_constraint(name, type_='foreignkey')
        batch_op.create_foreign_key(
            name, 'exercise', ['exercise_id'], ['id'], ondelete='CASCADE'
        )


def downgrade():
    bind = op.get_bind()
    is_pg = bind.dialect.name == 'postgresql'
    name = FK_NAME_PG if is_pg else FK_NAME_SQLITE
    kwargs = {} if is_pg else {'naming_convention': NAMING_CONVENTION}
    with op.batch_alter_table('exercise_favorite', schema=None, **kwargs) as batch_op:
        batch_op.drop_constraint(name, type_='foreignkey')
        batch_op.create_foreign_key(name, 'exercise', ['exercise_id'], ['id'])
