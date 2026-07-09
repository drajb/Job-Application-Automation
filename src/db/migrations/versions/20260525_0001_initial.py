"""Initial schema: all core tables + resume_embeddings.

Revision ID: 0001
Revises:
Create Date: 2026-05-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("url_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("company", sa.String(255), nullable=False),
        sa.Column("role_title", sa.String(255), nullable=False),
        sa.Column("ats", sa.String(64)),
        sa.Column("tier_used", sa.String(16)),
        sa.Column("resume_pdf", sa.Text),
        sa.Column("resume_uuid", sa.String(36)),
        sa.Column("status", sa.String(32), server_default="queued"),
        sa.Column("applied_at", sa.DateTime),
        sa.Column("response_at", sa.DateTime),
        sa.Column("screenshot_path", sa.Text),
        sa.Column("notes", sa.Text),
    )
    op.create_index("apps_company_role", "applications", ["company", "role_title"])

    op.create_table(
        "qa_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("question_text", sa.Text, nullable=False),
        sa.Column("question_embed", sa.BLOB, nullable=False),
        sa.Column("answer_text", sa.Text, nullable=False),
        sa.Column("category", sa.String(32)),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float, server_default="1.0"),
        sa.Column("company", sa.String(255)),
        sa.Column("applied_at", sa.DateTime),
        sa.Column("use_count", sa.Integer, server_default="0"),
    )
    op.create_index("qa_log_category", "qa_log", ["category"])

    op.create_table(
        "portal_credentials",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("portal_domain", sa.String(255), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255)),
        sa.Column("portal_url", sa.Text),
        sa.Column("username", sa.String(255)),
        sa.Column("password_enc", sa.BLOB, nullable=False),
        sa.Column("email_used", sa.String(255), server_default=""),
        sa.Column("signup_date", sa.DateTime),
        sa.Column("last_used", sa.DateTime),
        sa.Column("verified", sa.Boolean, server_default=sa.text("0")),
        sa.Column("notes", sa.Text),
    )

    op.create_table(
        "email_expectations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("application_id", sa.Integer, sa.ForeignKey("applications.id")),
        sa.Column("expected_sender_domain", sa.String(255), nullable=False),
        sa.Column("expected_subject_regex", sa.Text),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.current_timestamp()),
        sa.Column("expires_at", sa.DateTime),
        sa.Column("fulfilled", sa.Boolean, server_default=sa.text("0")),
        sa.Column("fulfilled_data", sa.Text),
    )

    op.create_table(
        "training_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("application_id", sa.Integer, sa.ForeignKey("applications.id")),
        sa.Column("step_number", sa.Integer),
        sa.Column("question", sa.Text),
        sa.Column("agent_action", sa.Text),
        sa.Column("human_action", sa.Text),
        sa.Column("intervened", sa.Boolean, server_default=sa.text("0")),
        sa.Column("timestamp", sa.DateTime, server_default=sa.func.current_timestamp()),
    )

    op.create_table(
        "sponsors_h1b",
        sa.Column("company", sa.String(255), primary_key=True),
        sa.Column("sponsored_count", sa.Integer),
        sa.Column("last_seen_year", sa.Integer),
    )

    op.create_table(
        "response_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("application_id", sa.Integer, sa.ForeignKey("applications.id")),
        sa.Column("email_uid", sa.String(255)),
        sa.Column("from_addr", sa.String(255)),
        sa.Column("subject", sa.Text),
        sa.Column("body_excerpt", sa.Text),
        sa.Column("category", sa.String(32)),
        sa.Column("classified_at", sa.DateTime),
        sa.Column("notified", sa.Boolean, server_default=sa.text("0")),
    )

    op.create_table(
        "resume_embeddings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("variant", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_mtime", sa.Float, nullable=False),
        sa.Column("embedding", sa.BLOB, nullable=False),
        sa.Column("text_excerpt", sa.Text),
        sa.UniqueConstraint("variant", "filename", name="uq_resume_variant_filename"),
    )


def downgrade() -> None:
    op.drop_table("resume_embeddings")
    op.drop_table("response_log")
    op.drop_table("sponsors_h1b")
    op.drop_table("training_runs")
    op.drop_table("email_expectations")
    op.drop_table("portal_credentials")
    op.drop_index("qa_log_category", table_name="qa_log")
    op.drop_table("qa_log")
    op.drop_index("apps_company_role", table_name="applications")
    op.drop_table("applications")
