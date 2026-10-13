"""qa_log: semantic-search store for learned Q&A pairs.

Per docs/SPEC.md §5.2:
  sim > 0.85  → reuse verbatim
  0.7 - 0.85  → LLM rephrases for context fit (calls Gemini)
  < 0.7       → pause and ask human via Telegram

Two safety rules on top of the thresholds:
  - SENSITIVE questions (visa / sponsorship / salary / legal / felony /
    clearance — docs/SPEC.md §8) are only reused when the stored question is
    the SAME question (normalised text match). Embeddings can't tell "Do you
    require sponsorship?" from "Can you work without sponsorship?", so a
    near-match on those never auto-answers.
  - Company-specific answers ("Why do you want to work at X?") are only
    reused verbatim for the same company; for another company they drop to
    the rephrase band.

Embedding: bge-small-en-v1.5 (local). Storage: SQLAlchemy + raw float32 blob.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

import numpy as np
from sqlalchemy import select

from src.db.models import QALog
from src.db.session import get_session
from src.resume.embeddings import embed
from src.util.time import utcnow

log = logging.getLogger(__name__)

HIGH_THRESHOLD = 0.85
MID_THRESHOLD = 0.70

Source = Literal["human", "llm_inferred"]


@dataclass
class QAMatch:
    decision: Literal["reuse", "rephrase", "pause"]
    answer: str | None
    score: float
    source: Source | None
    matched_id: int | None


def _vec(v: np.ndarray) -> bytes:
    return v.astype(np.float32).tobytes()


def _unvec(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def _norm_q(q: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", q.lower()).strip()


_COMPANY_SPECIFIC = re.compile(
    r"why (?:do you want to|are you interested in|would you like to) (?:work|join)|"
    r"why (?:this|our) (?:company|team|role)|interest(?:ed)? in (?:this|our)|about (?:us|our company)",
    re.I,
)


def is_company_specific(question: str, company: str | None = None) -> bool:
    if _COMPANY_SPECIFIC.search(question):
        return True
    return bool(company) and (company or "").lower() in question.lower()


def store(
    question: str,
    answer: str,
    *,
    source: Source,
    category: str | None = None,
    company: str | None = None,
    confidence: float = 1.0,
) -> int:
    if category is None:
        from src.ats.fields import classify
        category = classify(question)
    q_emb = embed(question)
    with get_session() as s:
        row = QALog(
            question_text=question,
            question_embed=_vec(q_emb),
            answer_text=answer,
            category=category,
            source=source,
            confidence=confidence,
            company=company,
            applied_at=utcnow(),
            use_count=0,
        )
        s.add(row)
        s.commit()
        return row.id


def lookup(question: str, *, company: str | None = None) -> QAMatch:
    from src.ats.fields import is_sensitive

    q_emb = embed(question)
    with get_session() as s:
        rows = list(s.scalars(select(QALog)))
    if not rows:
        return QAMatch(decision="pause", answer=None, score=0.0, source=None, matched_id=None)

    best_score = -1.0
    best = None
    for r in rows:
        v = _unvec(r.question_embed)
        if v.shape != q_emb.shape:
            continue
        score = float(np.dot(v, q_emb))  # bge embeddings are L2-normalized
        if score > best_score:
            best_score = score
            best = r

    if best is None:
        return QAMatch(decision="pause", answer=None, score=0.0, source=None, matched_id=None)

    sensitive = is_sensitive(question) or is_sensitive(best.question_text)
    if sensitive and _norm_q(best.question_text) != _norm_q(question):
        return QAMatch(decision="pause", answer=None, score=best_score,
                       source=None, matched_id=None)

    if (
        best_score >= HIGH_THRESHOLD
        and company
        and best.company
        and best.company.strip().lower() != company.strip().lower()
        and is_company_specific(question, company)
    ):
        best_score = min(best_score, HIGH_THRESHOLD - 1e-6)  # adapt, don't copy

    if best_score >= HIGH_THRESHOLD:
        # Bump use_count.
        with get_session() as s:
            hit = s.get(QALog, best.id)
            if hit:
                hit.use_count = (hit.use_count or 0) + 1
                s.commit()
        return QAMatch(
            decision="reuse", answer=best.answer_text, score=best_score,
            source=_source(best.source), matched_id=best.id,
        )
    if best_score >= MID_THRESHOLD:
        return QAMatch(
            decision="rephrase", answer=best.answer_text, score=best_score,
            source=_source(best.source), matched_id=best.id,
        )
    return QAMatch(decision="pause", answer=None, score=best_score, source=None, matched_id=None)


def _source(s: str | None) -> Source | None:
    return "human" if s == "human" else ("llm_inferred" if s == "llm_inferred" else None)


def rephrase_prompt(question: str, prior_answer: str, company: str, role: str) -> str:
    return f"""You have a prior answer to a similar question. Adapt it to fit the new
question, company, and role. Stay truthful — do not add facts that weren't in the
prior answer or the candidate's known profile.

# New question
{question}

# Prior answer (verbatim)
{prior_answer}

# Company / Role
{company} / {role}

# Output
The adapted answer text only. No preamble.
"""
