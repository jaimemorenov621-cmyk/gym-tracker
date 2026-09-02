"""routine exercise rir rpe as free text range

Revision ID: 5758485c5fb3
Revises: 915e748fd6da
Create Date: 2026-09-02 14:04:33.302475

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5758485c5fb3'
down_revision = '915e748fd6da'
branch_labels = None
depends_on = None


# Alembic no genera un USING para este ALTER COLUMN. En SQLite no hace
# falta (batch_alter_table recrea la tabla y el tipo TEXT acepta el valor
# entero sin más); en Postgres, ALTER COLUMN ... TYPE varchar desde
# integer falla sin un cast explícito -- postgresql_using se ignora en
# SQLite y solo se aplica cuando el dialecto es realmente postgresql.
def upgrade():
    with op.batch_alter_table('routine_exercise', schema=None) as batch_op:
        batch_op.alter_column(
            'rir',
            existing_type=sa.INTEGER(),
            type_=sa.String(length=16),
            existing_nullable=True,
            postgresql_using='rir::varchar(16)',
        )
        batch_op.alter_column(
            'rpe',
            existing_type=sa.INTEGER(),
            type_=sa.String(length=16),
            existing_nullable=True,
            postgresql_using='rpe::varchar(16)',
        )


def downgrade():
    # No seguro en general: si ya existe algún valor tipo "2-3" guardado,
    # este cast a integer falla en Postgres y se comporta de forma rara
    # en SQLite. Limitación conocida y aceptada, no resuelta aquí.
    with op.batch_alter_table('routine_exercise', schema=None) as batch_op:
        batch_op.alter_column(
            'rpe',
            existing_type=sa.String(length=16),
            type_=sa.INTEGER(),
            existing_nullable=True,
            postgresql_using='rpe::integer',
        )
        batch_op.alter_column(
            'rir',
            existing_type=sa.String(length=16),
            type_=sa.INTEGER(),
            existing_nullable=True,
            postgresql_using='rir::integer',
        )
