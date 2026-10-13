"""discovered_jobs table; NOT NULL on columns the models always fill; email_uid index.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07

Migration 0001 created nine columns as nullable (with server defaults) that
the SQLAlchemy models declare NOT NULL. Existing NULLs are backfilled with
the same defaults, then the constraint is applied (SQLite batch mode
rebuilds the table, preserving rows).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# table → [(column, type, backfill SQL literal)]
_NOT_NULL: dict[str, list[tuple[str, sa.types.TypeEngine, str]]] = {
    "qa_log": [("confidence", sa.Float(), "1.0"), ("use_count", sa.Integer(), "0")],
    "portal_credentials": [("email_used", sa.String(255), "''"), ("verified", sa.Boolean(), "0")],
    "email_expectations": [("created_at", sa.DateTime(), "CURRENT_TIMESTAMP"),
                           ("fulfilled", sa.Boolean(), "0")],
    "training_runs": [("intervened", sa.Boolean(), "0"),
                      ("timestamp", sa.DateTime(), "CURRENT_TIMESTAMP")],
    "response_log": [("notified", sa.Boolean(), "0")],
}


def upgrade() -> None:
    op.create_table(
        "discovered_jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("url_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("ats", sa.String(32), nullable=False),
        sa.Column("company", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("location", sa.String(255)),
        sa.Column("remote", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("posted_at", sa.DateTime),
        sa.Column("first_seen", sa.DateTime, nullable=False,
                  server_default=sa.func.current_timestamp()),
        sa.Column("last_seen", sa.DateTime),
        sa.Column("fit_score", sa.Float),
        sa.Column("missing_keywords", sa.Text),
        sa.Column("status", sa.String(16), nullable=False, server_default="new"),
    )
    op.create_index("discovered_jobs_status", "discovered_jobs", ["status"])
    op.create_index("response_log_uid", "response_log", ["email_uid"])

    for table, cols in _NOT_NULL.items():
        for col, _typ, default in cols:
            op.execute(f"UPDATE {table} SET {col} = {default} WHERE {col} IS NULL")
        with op.batch_alter_table(table) as batch:
            for col, typ, _default in cols:
                batch.alter_column(col, existing_type=typ, nullable=False)


def downgrade() -> None:
    for table, cols in _NOT_NULL.items():
        with op.batch_alter_table(table) as batch:
            for col, typ, _default in cols:
                batch.alter_column(col, existing_type=typ, nullable=True)
    op.drop_index("response_log_uid", table_name="response_log")
    op.drop_index("discovered_jobs_status", table_name="discovered_jobs")
    op.drop_table("discovered_jobs")
