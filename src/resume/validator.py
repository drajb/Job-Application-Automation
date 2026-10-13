"""Sacred validator. Rejects tailored output that introduces unseen facts.

Per docs/SPEC.md Hard Rules: "DO NOT weaken the resume validator. Regenerate or
escalate." This module is INTENTIONALLY strict. If it rejects something it
shouldn't have, escalate to the human via Telegram — do NOT loosen the rules.

Every check below compares the tailored draft against the SOURCE resume plus
the profile facts (`extra_known`). Anything the draft asserts that the source
doesn't contain is a fabrication:

  1. Years                 — every 19xx/20xx must appear in the source.
  2. Capitalised tokens    — every proper noun / acronym / title word, checked
                             ONE TOKEN AT A TIME, as a whole word. (Checking
                             whole phrases with substring tolerance let
                             "Databricks" ride in on "data" and "Microsoft
                             Teams" on "team".) Light plural tolerance only.
  3. Numbers / metrics     — "$4M", "73%", "40 engineers": every numeric value
                             (and spelled-out number words) must appear in the
                             source.
  4. Lower-case tools      — "pytorch", "kubernetes", "c++", "grpc": any term
                             from the shared tech lexicon must be in the source.
  5. URLs and emails       — must appear verbatim in the source/profile.
  6. Completeness          — empty or truncated output (< 50% of the source
                             length, or dropping most of the source's dates) is
                             rejected, so a cut-off LLM response can't ship.

Deliberate leniency (all of it listed here, nowhere else):
  - A small allowlist of generic words / section headings (_GENERIC_ALLOW).
  - A sentence-initial word that is clearly a verb (past tense "-ed", "-ing",
    or a common irregular past tense like "Led", "Built") — the tailor may
    swap action verbs. Every OTHER token in that sentence is still checked.

Limitations (called out so we don't kid ourselves):
  - Set-based: moving a real tool from one employer to another isn't caught.
  - Subtle paraphrase that drifts in meaning isn't caught. That's why the
    Telegram approval card shows bullet-level diffs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from src.util.skills import TECH_SKILLS, contains_term, find_terms

log = logging.getLogger(__name__)

# Generic words that may appear capitalised in a tailored draft without being
# in the source. Keep this list SMALL — every entry is a word the validator
# will never question. NO job-title words (Senior, Staff, Principal, Lead,
# Director, Manager, Head, VP): adding those would allow title inflation.
_GENERIC_ALLOW = {
    "ai", "ml", "api", "apis", "sdk", "sdks", "llm", "llms", "ci", "cd", "qa",
    "us", "usa", "eu", "uk", "i",
    "engineer", "engineers", "engineering", "software", "systems", "data", "tech",
    "team", "teams",
    # corporate suffixes ("Acme" → "Acme Corp" is not a new employer)
    "inc", "corp", "corporation", "co", "llc", "ltd", "plc", "gmbh",
    # months / days
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "monday", "tuesday", "wednesday", "thursday", "friday", "present", "current",
    # function words that get capitalised at sentence / heading starts
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for", "with", "by",
    "from", "as", "via", "over", "across", "into", "through", "using", "while", "within",
    "this", "that", "these", "those", "each", "all", "both", "most", "my", "our", "key",
    # common resume section headings
    "summary", "profile", "objective", "experience", "professional", "work", "employment",
    "history", "education", "skills", "technical", "core", "competencies", "projects",
    "selected", "certifications", "certificates", "awards", "honors", "publications",
    "languages", "tools", "frameworks", "highlights", "achievements", "contact",
    "additional", "relevant", "volunteer", "interests", "community", "other",
    "about", "me", "overview", "qualifications", "expertise", "areas",
}

# Irregular past-tense action verbs (regular ones are covered by the -ed rule).
# Only honoured for the FIRST word of a sentence / bullet.
_IRREGULAR_VERBS = {
    "led", "built", "ran", "drove", "grew", "won", "cut", "set", "made", "took", "wrote",
    "began", "brought", "sold", "taught", "rebuilt", "spun", "held", "kept", "met",
    "sought", "oversaw", "upheld", "undertook", "became", "gave", "found", "put", "split",
    "spent", "sent", "stood", "rewrote", "broke", "chose", "drew", "fed", "fought",
    "hit", "laid", "left", "lent", "lost", "paid", "read", "rode", "rose", "saw", "shut",
    "spoke", "struck", "swept", "threw", "wound", "own", "owns",
}

_NUMBER_WORDS = {
    "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
    "thirteen": "13", "fourteen": "14", "fifteen": "15", "sixteen": "16",
    "seventeen": "17", "eighteen": "18", "nineteen": "19", "twenty": "20",
    "thirty": "30", "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
    "eighty": "80", "ninety": "90", "hundred": "100", "thousand": "1000",
    "million": "1000000", "billion": "1000000000", "dozen": "12",
    "double": "2", "triple": "3", "twice": "2", "thrice": "3", "tripled": "3",
    "doubled": "2", "halved": "50",
}


@dataclass
class ValidationResult:
    ok: bool
    new_entities: list[str] = field(default_factory=list)
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


_YEAR_RE = re.compile(r"(?<![\d.])(?:19|20)\d{2}(?!\d)")
_CAP_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-Za-z0-9]*")
_WORD_RE = re.compile(r"[a-z0-9]+")
# A number: 1,200 / 3.5 / 40 / 4M / 10x / 100ms — but not glued to a word on the
# left (v2, S3, EC2), not followed by a non-unit word (2FA, 3rd), and not a
# dotted version (1.2.3). Ordered-list markers ("1. ") are stripped first.
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9.])(\d+(?:,\d{3})*(?:\.\d+)?)([A-Za-z]*)(\.\d)?")
_UNITS = {
    "", "k", "m", "b", "bn", "mm", "x", "s", "h", "hr", "hrs", "ms", "kb", "mb", "gb", "tb",
    "pb", "yr", "yrs", "mo", "mos", "w", "d", "pct",
}
_LIST_MARKER_RE = re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)
_URL_RE = re.compile(
    r"https?://[^\s)>\]]+|www\.[^\s)>\]]+|"
    r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b|"
    r"\b[\w-]+\.(?:com|org|net|io|dev|me|co|ai|app)(?:/[^\s)>\]]*)?",
    re.IGNORECASE,
)
# Sentence / clause boundaries: punctuation, or a spaced em dash / en dash / pipe.
_SENTENCE_SPLIT_RE = re.compile("(?<=[.!?;:])\\s+|\\s+[—–|]\\s+")  # noqa: RUF001
# Markdown / quote characters that can precede the first word of a sentence.
_LEADING_MARKUP_RE = re.compile(
    "[\\s>#*_\\-+|`\\[(\"'“‘]*(?:\\d+[.)]\\s+)?[\\s*_`\\[(\"'“‘]*",  # noqa: RUF001
)


def _years(text: str) -> set[str]:
    return set(_YEAR_RE.findall(text))


def _words(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _numbers(text: str) -> set[str]:
    text = _LIST_MARKER_RE.sub(" ", text)
    out = set()
    for m in _NUMBER_RE.finditer(text):
        if m.group(3) or m.group(2).lower() not in _UNITS:
            continue  # version string, or part of an identifier like 2FA
        raw = m.group(1).replace(",", "")
        if "." in raw:
            raw = raw.rstrip("0").rstrip(".")
        unit = m.group(2).lower()
        mag = {"k": "k", "m": "m", "mm": "m", "b": "b", "bn": "b"}.get(unit, "")
        out.add(raw + mag)
    return out


def _sentence_initial_offsets(line: str) -> set[int]:
    """Char offsets of the first token of every sentence / bullet / heading in a line."""
    starts: set[int] = set()
    pos = 0
    for chunk in _SENTENCE_SPLIT_RE.split(line):
        idx = line.find(chunk, pos)
        if idx < 0:
            continue
        pos = idx + len(chunk)
        m = _LEADING_MARKUP_RE.match(chunk)
        starts.add(idx + (m.end() if m else 0))
    return starts


def _known_word(tok: str, known: set[str]) -> bool:
    t = tok.lower()
    if t in known:
        return True
    # light plural / possessive tolerance — whole-word only
    if t.endswith("ies") and t[:-3] + "y" in known:
        return True
    if t.endswith("es") and t[:-2] in known:
        return True
    if t.endswith("s") and t[:-1] in known:
        return True
    return t + "s" in known


def _is_verbish(tok: str) -> bool:
    t = tok.lower()
    return t.endswith(("ed", "ing")) or t in _IRREGULAR_VERBS


def _url_known(url: str, known_lower: str) -> bool:
    u = url.lower().rstrip(".,;:")
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u).rstrip("/")
    return u in known_lower


def check_completeness(tailored: str, source: str) -> str | None:
    """Return a reason string if `tailored` looks empty or truncated, else None."""
    t = tailored.strip()
    if not t:
        return "tailored output is empty"
    s_len = len(source.strip())
    if s_len >= 400 and len(t) < 0.5 * s_len:
        return f"tailored output looks truncated ({len(t)} chars vs {s_len} in the source)"
    src_years = _years(source)
    if len(src_years) >= 3:
        kept = len(src_years & _years(tailored))
        if kept < 0.8 * len(src_years):
            return (
                f"tailored output dropped dates — kept {kept}/{len(src_years)} of the "
                f"source's years (roles may be missing or the output was cut off)"
            )
    return None


def validate(
    tailored: str,
    source: str,
    *,
    extra_known: str = "",
    check_complete: bool = True,
) -> ValidationResult:
    """Return ValidationResult(ok=True) iff every fact in `tailored` traces to source/extra."""
    if check_complete:
        why = check_completeness(tailored, source)
        if why:
            return ValidationResult(ok=False, new_entities=[], reason=why)

    known_text = f"{source}\n{extra_known}"
    known_lower = known_text.lower()
    known_words = _words(known_text) | _GENERIC_ALLOW
    known_years = _years(known_text)
    known_numbers = _numbers(known_text)
    for w, digit in _NUMBER_WORDS.items():
        if w in known_words:
            known_numbers.add(digit)

    new: list[str] = []

    # 1. years
    new.extend(sorted(_years(tailored) - known_years))

    # 2. capitalised tokens, one at a time
    for line in tailored.splitlines():
        initial = _sentence_initial_offsets(line)
        for m in _CAP_TOKEN_RE.finditer(line):
            tok = m.group(0)
            if _known_word(tok, known_words):
                continue
            if m.start() in initial and _is_verbish(tok):
                continue
            new.append(tok)

    # 3. numbers / metrics (years are handled above)
    for num in sorted(_numbers(tailored) - known_numbers):
        if not _YEAR_RE.fullmatch(num):
            new.append(num)
    for w in sorted(_words(tailored) & _NUMBER_WORDS.keys()):
        if w not in known_words and _NUMBER_WORDS[w] not in known_numbers:
            new.append(w)

    # 4. lower-case tools from the tech lexicon
    for term in sorted(find_terms(tailored, TECH_SKILLS)):
        if not contains_term(known_text, term):
            new.append(term)

    # 5. URLs / emails
    for m in _URL_RE.finditer(tailored):
        if not _url_known(m.group(0), known_lower):
            new.append(m.group(0))

    if new:
        # De-duplicate, keep first-occurrence order.
        seen: set[str] = set()
        dedup = []
        for x in new:
            if x.lower() not in seen:
                seen.add(x.lower())
                dedup.append(x)
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
