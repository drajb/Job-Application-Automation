"""Resume ↔ JD fit scoring and keyword-gap analysis. Local, deterministic, $0.

Two signals:

  1. Keyword coverage — which skills/tools the JD asks for that your resume
     already mentions, and which it doesn't (the "gap"). Keywords come from a
     built-in skills lexicon plus acronyms / product-shaped tokens found in
     the JD. This is roughly what an ATS keyword screen does.
  2. Semantic similarity (optional) — cosine of local bge-small embeddings.

The gap list is advice for YOU, not for the tailor: if a missing keyword is
something you genuinely have, add it to your source resume. The tailor will
never add it on its own — the validator would reject it, by design.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from src.util.skills import ALL_SKILLS, term_regex

log = logging.getLogger(__name__)

# Skills lexicon shared with the validator: src/util/skills.py.
SKILLS: frozenset[str] = ALL_SKILLS

# Capitalised words that are just English, not skills.
_NOT_KEYWORDS = {
    "the", "and", "you", "your", "our", "we", "this", "that", "with", "for", "who", "what",
    "about", "role", "team", "teams", "experience", "requirements", "responsibilities",
    "qualifications", "benefits", "preferred", "required", "minimum", "bonus", "equal",
    "opportunity", "employer", "salary", "location", "remote", "hybrid", "onsite", "full",
    "time", "apply", "join", "us", "usa", "inc", "llc", "ltd", "company", "please", "note",
    "eeo", "eoe", "ada", "pto", "401k", "nice", "plus", "strong", "excellent", "ability",
    "work", "working", "senior", "staff", "principal", "lead", "manager", "director",
    "engineer", "engineering", "software", "new", "york", "san", "francisco", "united",
    "states", "america", "canada", "europe", "london", "years", "year", "how",
}

_ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9+#/]{1,9}\b")
# Product-shaped tokens: CamelCase (PyTorch, BigQuery) or dotted (Node.js).
_PRODUCT_RE = re.compile(r"\b(?:[A-Z][a-z]+[A-Z][A-Za-z]*|[A-Za-z]+\.(?:js|io|ai|net))\b")


@dataclass
class FitReport:
    score: float  # 0..1
    keyword_coverage: float | None  # 0..1, None when the JD has no keywords
    semantic: float | None  # 0..1 cosine, None when embeddings unavailable
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def percent(self) -> int:
        return round(self.score * 100)


def _contains(text_lower: str, term: str) -> bool:
    return term_regex(term).search(text_lower) is not None


def extract_keywords(jd_text: str) -> list[str]:
    """Skills/tools a JD asks for, in first-seen order, lower-cased."""
    lower = jd_text.lower()
    found: dict[str, int] = {}
    for skill in SKILLS:
        m = re.search(rf"(?<![a-z0-9]){re.escape(skill)}(?![a-z0-9])", lower)
        if m:
            found[skill] = m.start()
    for rx in (_ACRONYM_RE, _PRODUCT_RE):
        for m in rx.finditer(jd_text):
            tok = m.group(0).strip("/").lower()
            if len(tok) < 2 or tok in _NOT_KEYWORDS or tok.isdigit():
                continue
            found.setdefault(tok, m.start())
    # "llm" and "llms" are the same ask.
    if "llm" in found and "llms" in found:
        found.pop("llms")
    return [k for k, _ in sorted(found.items(), key=lambda kv: kv[1])]


def keyword_gap(jd_text: str, resume_text: str) -> tuple[list[str], list[str]]:
    """Return (matched, missing) JD keywords against the resume."""
    resume_lower = resume_text.lower()
    matched: list[str] = []
    missing: list[str] = []
    for kw in extract_keywords(jd_text):
        (matched if _contains(resume_lower, kw) else missing).append(kw)
    return matched, missing


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def score_fit(
    jd_text: str,
    resume_text: str,
    *,
    embed_fn: Callable[[str], np.ndarray] | None = None,
    resume_embedding: np.ndarray | None = None,
) -> FitReport:
    """Score how well `resume_text` covers `jd_text`.

    Weighting: 65% keyword coverage + 35% semantic similarity when embeddings
    are available, otherwise keyword coverage alone. bge-small cosines for
    related professional text sit roughly in 0.5 to 0.9, so the semantic term is
    rescaled from [0.5, 0.9] to [0, 1] before weighting.
    """
    matched, missing = keyword_gap(jd_text, resume_text)
    total = len(matched) + len(missing)
    coverage = (len(matched) / total) if total else None

    semantic: float | None = None
    if embed_fn is not None and jd_text.strip():
        try:
            r_emb = resume_embedding if resume_embedding is not None else embed_fn(resume_text)
            semantic = _cos(embed_fn(jd_text), r_emb)
        except Exception as e:  # embeddings are best-effort
            log.debug("fit: embeddings unavailable: %s", e)

    sem_scaled = None if semantic is None else min(1.0, max(0.0, (semantic - 0.5) / 0.4))
    if coverage is not None and sem_scaled is not None:
        score = 0.65 * coverage + 0.35 * sem_scaled
    elif coverage is not None:
        score = coverage
    elif sem_scaled is not None:
        score = sem_scaled
    else:
        score = 0.0
    return FitReport(
        score=score, keyword_coverage=coverage, semantic=semantic,
        matched=matched, missing=missing,
    )
