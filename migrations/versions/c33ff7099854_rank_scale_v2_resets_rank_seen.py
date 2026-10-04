"""rank scale v2 resets rank_seen

Revision ID: c33ff7099854
Revises: 5832103828ac
Create Date: 2026-10-04 17:41:24.349328

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c33ff7099854'
down_revision = '5832103828ac'
branch_labels = None
depends_on = None


def upgrade():
    # Escala de rangos v2 (Titán = Élite): con la misma fuerza casi todos
    # quedan más arriba. Se olvida el rango "visto" para que Inicio lo
    # presente de nuevo ("Tu rango de fuerza") en vez de celebrar una
    # subida que no ha ocurrido.
    op.execute('UPDATE "user" SET rank_seen = NULL')


def downgrade():
    pass  # no hay vuelta atrás útil: el rango visto se recalcula solo
