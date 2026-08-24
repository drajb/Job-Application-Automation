"""Sacred validator. Rejects tailored output that introduces unseen facts.

Per docs/SPEC.md Hard Rules: "DO NOT weaken the resume validator. Regenerate or
escalate." This module is INTENTIONALLY strict. If it rejects something it
shouldn't have, escalate to the human via Telegram — do NOT loosen the rules.

Approach:
  - Extract sets of "entity-shaped" tokens from source and tailored output.
  - Allowed sets: 4-digit years, ALLCAPS acronyms, capitalized proper-noun phrases,
    tech keywords (with a small allowlist for very common generic terms).
  - If tailored introduces a year, an acronym, or a capitalized phrase that
    doesn't appear (case-insensitively, substring-tolerant) in the source +
    profile, REJECT.

Limitations (called out so we don't kid ourselves):
  - This catches blatant fabrication. It does NOT catch subtle paraphrase that
    drifts in meaning. That's why Telegram approval also shows bullet diffs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Generic terms that may appear in a tailored draft without being in the source.
# Keep this list TINY. Adding to it weakens the validator.
_GENERIC_ALLOW = {
    "AI", "ML", "API", "APIs", "SDK", "SDKs", "LLM", "LLMs",
    "US", "USA", "EU", "UK", "CI", "CD", "QA",
    "Engineer", "Engineering", "Software", "Systems", "Data", "Tech", "Team", "Lead",
    "Senior", "Staff", "Principal", "Director", "Manager", "VP", "Head",
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
}


@dataclass
class ValidationResult:
    ok: bool
    new_entities: list[str] = field(default_factory=list)
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}\b")
_PROPER_PHRASE_RE = re.compile(r"\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+){0,4})\b")


def _entities(text: str) -> set[str]:
    s: set[str] = set()
    s.update(_YEAR_RE.findall(text))
    s.update(_ACRONYM_RE.findall(text))
    s.update(_PROPER_PHRASE_RE.findall(text))
    return s


def _normalize(s: set[str]) -> set[str]:
    return {x.strip().lower() for x in s if x.strip()}


def validate(tailored: str, source: str, *, extra_known: str = "") -> ValidationResult:
    """Return ValidationResult(ok=True) iff every entity in `tailored` traces to source/extra."""
    known = _normalize(_entities(source) | _entities(extra_known) | _GENERIC_ALLOW)
    tailored_ents = _entities(tailored)

    # Substring tolerance only uses known tokens >= 4 chars. Short generic
    # tokens ("ai", "ml", "us", "ci") would otherwise leak: e.g. "Mailchimp"
    # contains "ai", so a fabricated employer could slip through. Those short
    # tokens still pass via the exact-match check below; they just don't get to
    # vouch for arbitrary longer strings as substrings.
    substr_known = {k for k in known if len(k) >= 4}

    new: list[str] = []
    for ent in tailored_ents:
        el = ent.strip().lower()
        if el in known:
            continue
        # Substring tolerance: "Southwest" should match source "Southwest
        # Airlines", and tailored "Acme Corp" should match source "Acme".
        if any(el in k for k in substr_known) or any(k in el for k in substr_known):
            continue
        new.append(ent)

    if new:
        # De-duplicate, keep first-occurrence order.
        seen: set[str] = set()
        dedup = [x for x in new if not (x.lower() in seen or seen.add(x.lower()))]
        return ValidationResult(
            ok=False,
            new_entities=dedup,
            reason=(
                f"Tailored output introduces {len(dedup)} entity/entities not present in "
                f"the source resume: {dedup[:10]}{'...' if len(dedup) > 10 else ''}"
            ),
        )
    return ValidationResult(ok=True, reason="validator: all entities traced to source")


# --- diff helpers for the Telegram approval card ----------------------------


_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+)$")


def extract_bullets(md: str) -> list[str]:
    return [m.group(1).strip() for line in md.splitlines() if (m := _BULLET_RE.match(line))]


def bullet_diff(source_md: str, tailored_md: str, max_pairs: int = 6) -> list[tuple[str, str]]:
    """Pair source bullets to closest tailored bullet for the approval card.

    Naive longest-common-substring pairing — good enough for a Telegram preview.
    """
    src = extract_bullets(source_md)
    tgt = extract_bullets(tailored_md)
    pairs: list[tuple[str, str]] = []
    used: set[int] = set()
    for s in src:
        best_i = -1
        best = 0
        for i, t in enumerate(tgt):
            if i in used:
                continue
            overlap = _overlap(s.lower(), t.lower())
            if overlap > best:
                best = overlap
                best_i = i
        if best_i >= 0 and best >= 8:
            pairs.append((s, tgt[best_i]))
            used.add(best_i)
        if len(pairs) >= max_pairs:
            break
    return pairs


def _overlap(a: str, b: str) -> int:
    # Length of the longest common substring. Linear-ish heuristic.
    if not a or not b:
        return 0
    n, m = len(a), len(b)
    dp = [0] * (m + 1)
    best = 0
    for i in range(1, n + 1):
        prev = 0
        for j in range(1, m + 1):
            cur = dp[j]
            if a[i - 1] == b[j - 1]:
                dp[j] = prev + 1
                if dp[j] > best:
                    best = dp[j]
            else:
                dp[j] = 0
            prev = cur
    return best
