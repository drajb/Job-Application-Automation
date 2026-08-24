"""qa_log: semantic-search store for learned Q&A pairs.

Per docs/SPEC.md §5.2:
  sim > 0.85  → reuse verbatim
  0.7 - 0.85  → LLM rephrases for context fit (calls Gemini)
  < 0.7       → pause and ask human via Telegram

Embedding: bge-small-en-v1.5 (local). Storage: SQLAlchemy + raw float32 blob.
"""

from __future__ import annotations

import logging
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


def store(
    question: str,
    answer: str,
    *,
    source: Source,
    category: str | None = None,
    company: str | None = None,
    confidence: float = 1.0,
) -> int:
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


def lookup(question: str) -> QAMatch:
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

    if best_score >= HIGH_THRESHOLD:
        # Bump use_count.
        with get_session() as s:
            r = s.get(QALog, best.id)
            if r:
                r.use_count = (r.use_count or 0) + 1
                s.commit()
        return QAMatch(
            decision="reuse", answer=best.answer_text, score=best_score,
            source=best.source, matched_id=best.id,
        )
    if best_score >= MID_THRESHOLD:
        return QAMatch(
            decision="rephrase", answer=best.answer_text, score=best_score,
            source=best.source, matched_id=best.id,
        )
    return QAMatch(decision="pause", answer=None, score=best_score, source=None, matched_id=None)


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
