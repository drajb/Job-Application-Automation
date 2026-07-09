"""Two-stage resume selection.

Stage 1: route to the best-matching variant folder by JD role-type keywords
         and folder-name overlap (see `_route_family`).
Stage 2: cosine-rank the `.md` files within that folder against the JD
         embedding, when an embedding function is available.

Auto-discovers variants from `RESUME_SOURCE_DIR` (default `./resumes/`),
so adding or renaming a variant subdirectory needs no code changes.

Reads only. Source files are never modified.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.config import RESUME_SOURCE_DIR

log = logging.getLogger(__name__)

# Subdirectories inside the resume source dir that are NOT role variants.
# Add to this set in your fork if you keep, e.g., a `templates/` or `notes/`
# directory under `resumes/`.
_EXCLUDE = {"historical", "legacy", ".build"}

# Role-type lexicon. Each tuple is (role_type_slug, JD keywords implying it).
#
# The router uses these to detect role-type signals in a JD ("manager",
# "staff", "lead", "pm", "researcher"). It then maps each signal to whichever
# of your `resumes/<variant>/` folders best aligns (substring match on the
# folder name). So if your folder is `engineering-manager/`, `manager/`, or
# `ai-manager/`, all three count as the "manager" target for a JD that
# mentions "Director" or "Head of …".
#
# Add your own role types here if your variants don't fit. The keys are
# matched as substrings against variant folder names, so use lowercase.
_ROLE_TYPES: list[tuple[str, list[str]]] = [
    ("manager", ["manager", "director", "head of", "vp ", "chief", "people leader"]),
    ("lead",    ["lead", "engineering lead", "tech lead", "player-coach"]),
    ("staff",   ["staff", "principal", "senior staff", "distinguished", "senior engineer"]),
    ("pm",      ["product manager", "pm ", "program manager", "platform pm"]),
    ("researcher", ["research", "scientist", "applied scientist", "research engineer"]),
]

# Weight applied to a role-type signal vs a raw folder-name token match.
# 3 is enough to make role intent dominate over a single shared token.
_ROLE_WEIGHT = 3


@dataclass(frozen=True)
class ResumeChoice:
    variant: str
    md_path: Path
    docx_path: Path
    score: float


def list_variants(root: Path = RESUME_SOURCE_DIR) -> list[str]:
    if not root.exists():
        return []
    return sorted(
        d.name
        for d in root.iterdir()
        if d.is_dir() and d.name not in _EXCLUDE and not d.name.startswith(".")
    )


def _list_md_files(variant_dir: Path) -> list[Path]:
    return sorted(variant_dir.glob("*.md"))


def _route_family(jd_text: str, available: list[str]) -> str:
    """Pick the resume variant folder whose name best matches the JD.

    Two-stage scoring:

    1. Role-type signal: walk `_ROLE_TYPES`, sum length-weighted keyword hits
       in the JD per role type.
    2. Variant alignment: for each available folder name, add:
         - direct token overlap with the JD (folder words >= 3 chars present
           in the JD text, weighted by their length), plus
         - any role-type signal whose slug is a substring of the folder name,
           weighted by `_ROLE_WEIGHT` to keep role intent dominant.

    The highest-scoring folder wins. Falls back to `master` (or the first
    variant alphabetically) when nothing scores.

    Length-weighted: longer matches are more specific. "product manager" (15
    chars) beats "manager" (7) when both fire, so "AI Platform Product
    Manager" routes to a `pm` folder over a `manager` one.
    """
    jd_lower = jd_text.lower()

    # Stage 1: which role types does this JD signal?
    role_scores: dict[str, int] = {}
    for role, keywords in _ROLE_TYPES:
        role_scores[role] = sum(len(k) for k in keywords if k in jd_lower)

    # Stage 2: score each available variant folder.
    scores: dict[str, int] = {v: 0 for v in available}
    for variant in available:
        v_lower = variant.lower()
        # Direct token overlap: split the folder name on -/_/space, check
        # each non-trivial token against the JD.
        for token in re.split(r"[-_\s]+", v_lower):
            if len(token) >= 3 and token in jd_lower:
                scores[variant] += len(token)
        # Role-type alignment: any role whose slug is a substring of the
        # folder name inherits that role's keyword-match score (boosted).
        for role, score in role_scores.items():
            if role in v_lower:
                scores[variant] += score * _ROLE_WEIGHT

    best = max(scores, key=lambda v: scores[v])
    if scores[best] == 0:
        return "master" if "master" in available else available[0]
    return best


def select(
    jd_text: str,
    *,
    jd_embedding: np.ndarray | None = None,
    embed_fn=None,  # callable(text) -> np.ndarray; injected from src.resume.embeddings
    root: Path = RESUME_SOURCE_DIR,
) -> ResumeChoice:
    """Pick the best resume.md for a JD. Stage-1 family routing, Stage-2 cosine."""
    available = list_variants(root)
    if not available:
        raise FileNotFoundError(f"no resume variants found under {root}")

    family = _route_family(jd_text, available)
    variant_dir = root / family
    candidates = _list_md_files(variant_dir)
    if not candidates:
        raise FileNotFoundError(f"no .md files in {variant_dir}")

    if jd_embedding is None or embed_fn is None or len(candidates) == 1:
        # No embeddings available; pick the longer one (full > 1pager) by default.
        # Falls back to the first by name if all are similar size.
        chosen = max(candidates, key=lambda p: p.stat().st_size)
        score = 0.0
    else:
        sims: list[tuple[float, Path]] = []
        for md in candidates:
            emb = embed_fn(md.read_text(encoding="utf-8"))
            sims.append((_cos(jd_embedding, emb), md))
        sims.sort(reverse=True)
        score, chosen = sims[0]

    docx = chosen.with_suffix(".docx")
    log.info("resume selected: variant=%s file=%s score=%.3f", family, chosen.name, score)
    return ResumeChoice(variant=family, md_path=chosen, docx_path=docx, score=score)


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def parse_jd_company_role(jd_text: str) -> tuple[str, str]:
    """Best-effort heuristic to extract company + role from a JD.

    Many JDs start with "<Role> at <Company>" or have an H1 with the role.
    This is a simple regex heuristic; ATS adapters override it with
    site-specific parsing when available.
    """
    lines = [ln.strip() for ln in jd_text.splitlines() if ln.strip()]
    role = lines[0] if lines else "Unknown Role"
    role = re.sub(r"^#+\s*", "", role)
    company = "Unknown Company"
    m = re.search(r"\bat\s+([A-Z][A-Za-z0-9 &.,'\-]+)", role)
    if m:
        company = m.group(1).strip(" .")
        role = role[: m.start()].strip()
    return company, role
