"""aisaac training_delivery (stub: the tables are owned by aisaac's gym module)

Revision ID: b8d4f02e6c31
Revises: a7c3e91d5b20

aisaac's gym module shares this Postgres database and applied this revision there
(it adds training delivery tables and one nullable column). This hub does not use
them. The stub exists only so `alembic upgrade head` here recognizes the database's
stamped revision instead of aborting the Fly release_command with a missing-revision
error. Keep the id identical to aisaac's
backend/app/modules/gym/alembic/versions/b8d4f02e6c31_training_delivery.py.
"""

# revision identifiers, used by Alembic.
revision = 'b8d4f02e6c31'
down_revision = 'a7c3e91d5b20'
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass