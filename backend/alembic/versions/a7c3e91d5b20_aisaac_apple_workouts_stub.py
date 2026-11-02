"""aisaac apple_workouts (stub: the table is owned by aisaac's gym module)

Revision ID: a7c3e91d5b20
Revises: 1ef14c36cb4b
Create Date: 2026-10-30 12:00:00.000000

aisaac's gym module shares this Postgres database and applied this revision there
(it creates apple_workouts). This hub does not use that table. The stub exists only so
`alembic upgrade head` here recognizes the database's stamped revision instead of
aborting the Fly release_command with "Can't locate revision". Keep the id identical
to aisaac's backend/app/modules/gym/alembic/versions/a7c3e91d5b20_add_apple_workouts.py.
"""

# revision identifiers, used by Alembic.
revision = 'a7c3e91d5b20'
down_revision = '1ef14c36cb4b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
