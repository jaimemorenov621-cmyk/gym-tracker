"""add routines

Revision ID: 3a0c8a9893e3
Revises: 7701a8b5b550
Create Date: 2026-07-25 18:02:57.266231

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "3a0c8a9893e3"
down_revision = "7701a8b5b550"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "routine",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_routine_user_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("routine", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_routine_user_id"), ["user_id"], unique=False)

    op.create_table(
        "routine_exercise",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("exercise", sa.String(length=64), nullable=False),
        sa.Column("target_sets", sa.Integer(), nullable=False),
        sa.Column("target_reps", sa.String(length=16), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("routine_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["routine_id"], ["routine.id"], name="fk_routine_exercise_routine_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("routine_exercise", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_routine_exercise_routine_id"), ["routine_id"], unique=False)

    with op.batch_alter_table("workout", schema=None) as batch_op:
        batch_op.add_column(sa.Column("routine_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_workout_routine_id"), ["routine_id"], unique=False
        )
        batch_op.create_foreign_key(
            "fk_workout_routine_id", "routine", ["routine_id"], ["id"]
        )


def downgrade():
    with op.batch_alter_table("workout", schema=None) as batch_op:
        batch_op.drop_constraint("fk_workout_routine_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_workout_routine_id"))
        batch_op.drop_column("routine_id")

    with op.batch_alter_table("routine_exercise", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_routine_exercise_routine_id"))
    op.drop_table("routine_exercise")

    with op.batch_alter_table("routine", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_routine_user_id"))
    op.drop_table("routine")