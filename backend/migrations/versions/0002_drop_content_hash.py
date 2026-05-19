"""drop content_hash from pages

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-17
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("pages", "content_hash")


def downgrade() -> None:
    import sqlalchemy as sa
    op.add_column("pages", sa.Column("content_hash", sa.Text(), nullable=True))
