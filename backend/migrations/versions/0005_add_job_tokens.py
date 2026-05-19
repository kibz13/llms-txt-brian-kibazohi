"""add tokens_in and tokens_out to jobs

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("tokens_in", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("tokens_out", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "tokens_out")
    op.drop_column("jobs", "tokens_in")
