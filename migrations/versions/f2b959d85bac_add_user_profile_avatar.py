"""add user profile avatar

Revision ID: f2b959d85bac
Revises:
Create Date: 2026-11-17 14:24:51.304904

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f2b959d85bac'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("user") and "avatar" not in {
        column["name"] for column in inspector.get_columns("user")
    }:
        with op.batch_alter_table("user", schema=None) as batch_op:
            batch_op.add_column(sa.Column("avatar", sa.String(length=100), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("user") and "avatar" in {
        column["name"] for column in inspector.get_columns("user")
    }:
        with op.batch_alter_table("user", schema=None) as batch_op:
            batch_op.drop_column("avatar")
