"""add monitoring tables and columns

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add HTTP header columns to pages for watchlist change detection
    op.add_column("pages", sa.Column("etag",          sa.Text(), nullable=True))
    op.add_column("pages", sa.Column("last_modified", sa.Text(), nullable=True))

    # New domains table for monitoring
    op.create_table(
        "domains",
        sa.Column("id",                postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("base_url",          sa.Text(), nullable=False, unique=True),
        sa.Column("domain",            sa.Text(), nullable=False),
        sa.Column("monitoring_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_checked_at",   sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_job_id",       postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("sitemap_hash",      sa.Text(), nullable=True),
        sa.Column("created_at",        sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at",        sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index("ix_domains_domain", "domains", ["domain"])


def downgrade() -> None:
    op.drop_table("domains")
    op.drop_column("pages", "last_modified")
    op.drop_column("pages", "etag")
