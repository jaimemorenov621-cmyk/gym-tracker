"""backfill effort_scale none to rir

Revision ID: b2e517b98bdf
Revises: 5758485c5fb3
Create Date: 2026-09-16 14:22:20.622587

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2e517b98bdf'
down_revision = '5758485c5fb3'
branch_labels = None
depends_on = None


# Ya no se puede dejar una serie sin RIR/RPE (settings.html quitó la opción
# "No anotar"), así que cualquier usuario que se hubiera quedado en
# effort_scale="none" pasa a "rir" -- mismo default que usa el modelo para
# usuarios nuevos (app/models.py).
def upgrade():
    user = sa.table("user", sa.column("effort_scale", sa.String))
    op.execute(
        user.update().where(user.c.effort_scale == "none").values(effort_scale="rir")
    )


def downgrade():
    # No reversible de forma fiable: una vez migrados, ya no se puede saber
    # qué filas eran "none" en origen frente a las que ya eran "rir".
    pass
