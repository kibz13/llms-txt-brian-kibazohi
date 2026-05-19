"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id",                  postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("url",                 sa.Text(),    nullable=False),
        sa.Column("status",              sa.Text(),    nullable=False, server_default="queued"),
        sa.Column("result",              sa.Text(),    nullable=True),
        sa.Column("error",               sa.Text(),    nullable=True),
        sa.Column("site_type",           sa.Text(),    nullable=True),
        sa.Column("page_count",          sa.Integer(), nullable=True),
        sa.Column("generation_time_ms",  sa.Integer(), nullable=True),
        sa.Column("created_at",          sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at",          sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index("ix_jobs_status",     "jobs", ["status"])
    op.create_index("ix_jobs_created_at", "jobs", ["created_at"])

    op.create_table(
        "pages",
        sa.Column("id",                    postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("url",                   sa.Text(), nullable=False, unique=True),
        sa.Column("domain",                sa.Text(), nullable=False, server_default=""),
        sa.Column("title",                 sa.Text(), nullable=True),
        sa.Column("description",           sa.Text(), nullable=True),
        sa.Column("content_hash",          sa.Text(), nullable=True),
        sa.Column("page_type",             sa.Text(), nullable=True),
        sa.Column("page_type_confidence",  sa.Float(), nullable=True),
        sa.Column("created_at",            sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at",            sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index("ix_pages_domain", "pages", ["domain"])

    op.create_table(
        "job_pages",
        sa.Column("job_id",  postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("jobs.id"), primary_key=True),
        sa.Column("page_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("pages.id"), primary_key=True),
        sa.Column("rank",    sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("job_pages")
    op.drop_table("pages")
    op.drop_table("jobs")
