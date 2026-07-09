"""SQLAlchemy models. Mirrors docs/SPEC.md §5 schemas (5.2-5.8) + resume_embeddings.

sqlite-vec is loaded as an extension in session.py before queries that need
vector ops. Embeddings are stored as BLOB (raw float32 bytes); the application
layer reshapes via numpy.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BLOB,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from src.util.time import utcnow


class Base(DeclarativeBase):
    pass


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    role_title: Mapped[str] = mapped_column(String(255), nullable=False)
    ats: Mapped[str | None] = mapped_column(String(64))
    tier_used: Mapped[str | None] = mapped_column(String(16))  # tier1|tier2|tier3
    resume_pdf: Mapped[str | None] = mapped_column(Text)
    resume_uuid: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str | None] = mapped_column(
        String(32),
        default="queued",
    )  # queued|tailored|submitted|rejected|response|interview|offer
    applied_at: Mapped[datetime | None] = mapped_column(DateTime)
    response_at: Mapped[datetime | None] = mapped_column(DateTime)
    screenshot_path: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    expectations: Mapped[list[EmailExpectation]] = relationship(back_populates="application")
    responses: Mapped[list[ResponseLog]] = relationship(back_populates="application")
    training: Mapped[list[TrainingRun]] = relationship(back_populates="application")


Index("apps_company_role", Application.company, Application.role_title)


class QALog(Base):
    __tablename__ = "qa_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_embed: Mapped[bytes] = mapped_column(BLOB, nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(32))  # visa|demo|comp|logistics|essay|other
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # human|llm_inferred
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    company: Mapped[str | None] = mapped_column(String(255))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime)
    use_count: Mapped[int] = mapped_column(Integer, default=0)


Index("qa_log_category", QALog.category)


class PortalCredential(Base):
    __tablename__ = "portal_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portal_domain: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    portal_url: Mapped[str | None] = mapped_column(Text)
    username: Mapped[str | None] = mapped_column(String(255))
    password_enc: Mapped[bytes] = mapped_column(BLOB, nullable=False)
    email_used: Mapped[str] = mapped_column(String(255), default="")
    signup_date: Mapped[datetime | None] = mapped_column(DateTime)
    last_used: Mapped[datetime | None] = mapped_column(DateTime)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)


class EmailExpectation(Base):
    __tablename__ = "email_expectations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id"))
    expected_sender_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    expected_subject_regex: Mapped[str | None] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)  # verify_email|password_reset|2fa
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    fulfilled: Mapped[bool] = mapped_column(Boolean, default=False)
    fulfilled_data: Mapped[str | None] = mapped_column(Text)

    application: Mapped[Application | None] = relationship(back_populates="expectations")


class TrainingRun(Base):
    __tablename__ = "training_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id"))
    step_number: Mapped[int | None] = mapped_column(Integer)
    question: Mapped[str | None] = mapped_column(Text)
    agent_action: Mapped[str | None] = mapped_column(Text)
    human_action: Mapped[str | None] = mapped_column(Text)
    intervened: Mapped[bool] = mapped_column(Boolean, default=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    application: Mapped[Application | None] = relationship(back_populates="training")


class SponsorH1B(Base):
    __tablename__ = "sponsors_h1b"

    company: Mapped[str] = mapped_column(String(255), primary_key=True)
    sponsored_count: Mapped[int | None] = mapped_column(Integer)
    last_seen_year: Mapped[int | None] = mapped_column(Integer)


class ResponseLog(Base):
    __tablename__ = "response_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id"))
    email_uid: Mapped[str | None] = mapped_column(String(255))
    from_addr: Mapped[str | None] = mapped_column(String(255))
    subject: Mapped[str | None] = mapped_column(Text)
    body_excerpt: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(32))
    classified_at: Mapped[datetime | None] = mapped_column(DateTime)
    notified: Mapped[bool] = mapped_column(Boolean, default=False)

    application: Mapped[Application | None] = relationship(back_populates="responses")


class ResumeEmbedding(Base):
    """Cached embeddings for source resume variants. Built once at startup.

    Not in docs/SPEC.md §5 — added so the two-stage selector (family → cosine
    inside variant) doesn't re-embed on every JD.
    """

    __tablename__ = "resume_embeddings"
    __table_args__ = (UniqueConstraint("variant", "filename"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    variant: Mapped[str] = mapped_column(String(64), nullable=False)  # master|staff-ai-engineer|...
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_mtime: Mapped[float] = mapped_column(Float, nullable=False)
    embedding: Mapped[bytes] = mapped_column(BLOB, nullable=False)
    text_excerpt: Mapped[str | None] = mapped_column(Text)
