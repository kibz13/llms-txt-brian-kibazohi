"""add score column to job_pages

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-18
"""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_pages", sa.Column("score", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("job_pages", "score")
