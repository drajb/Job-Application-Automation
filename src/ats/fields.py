"""Application-form question classifier + profile-derived answers.

One place that decides, for a form label like "Will you now or in the future
require sponsorship?":

  - what kind of question it is (category),
  - whether the profile answers it deterministically (and with which polarity),
  - whether it is SENSITIVE (docs/SPEC.md §8: visa | salary | legal | felony |
    clearance) — sensitive questions the profile can't answer exactly are
    never auto-filled from a fuzzy memory match; a human answers them.

Every Tier-1 adapter routes custom questions through `answer_for()`.
"""

from __future__ import annotations

import re

from src.ats.base import ApplicationPlan

SENSITIVE = frozenset({"authorization", "sponsorship", "salary", "felony", "clearance", "legal"})

# Order matters: first match wins. Sponsorship before authorization, because
# "authorized to work without sponsorship" is a sponsorship-polarity question
# answered via authorization (see answer_for).
_CATEGORIES: list[tuple[str, re.Pattern[str]]] = [
    ("sponsorship", re.compile(r"sponsor|visa\b|h-?1b|immigration", re.I)),
    ("authorization", re.compile(
        r"authori[sz]ed to work|eligible to work|legally (?:able|permitted|allowed)|"
        r"right to work|work authori[sz]ation|employment eligibility", re.I)),
    ("salary", re.compile(r"salary|compensation|pay (?:range|expectation)|desired pay|"
                          r"expected (?:pay|base)|rate expectation", re.I)),
    ("felony", re.compile(r"felony|convicted|criminal|background check", re.I)),
    ("clearance", re.compile(r"clearance", re.I)),
    ("legal", re.compile(r"non-?compete|non-?solicit|lawsuit|litigation|"
                         r"restrictive covenant", re.I)),
    ("eeo", re.compile(r"gender|race|ethnic|veteran|disabilit|hispanic|latin[oax]|"
                       r"pronoun|sexual orientation|transgender", re.I)),
    ("linkedin", re.compile(r"linked\s*in", re.I)),
    ("github", re.compile(r"github", re.I)),
    ("portfolio", re.compile(r"portfolio|personal (?:site|website)|website|blog", re.I)),
    ("source", re.compile(r"how did you (?:hear|find|learn)|referral source|"
                          r"where did you (?:hear|find)", re.I)),
    ("first_name", re.compile(r"^\s*(?:legal\s+)?first name|given name", re.I)),
    ("last_name", re.compile(r"^\s*(?:legal\s+)?last name|surname|family name", re.I)),
    ("email", re.compile(r"\be-?mail\b", re.I)),
    ("phone", re.compile(r"phone|mobile|cell", re.I)),
    ("relocate", re.compile(r"relocat", re.I)),
    ("start", re.compile(r"start date|notice period|when can you start|earliest", re.I)),
]

_NEGATED_SPONSOR = re.compile(r"without (?:the need for |requiring |needing )?(?:visa )?sponsor", re.I)


def classify(label: str) -> str:
    for cat, rx in _CATEGORIES:
        if rx.search(label):
            return cat
    return "other"


def is_sensitive(label: str) -> bool:
    return classify(label) in SENSITIVE


def _yes_no(flag: bool | None) -> str | None:
    if flag is None:
        return None
    return "Yes" if flag else "No"


def answer_for(plan: ApplicationPlan, label: str) -> str | None:
    """Deterministic answer from the profile-derived plan, or None.

    Yes/No questions get "Yes"/"No" with the polarity the QUESTION asks for —
    "Do you require sponsorship?" and "Can you work without sponsorship?"
    get opposite answers from the same profile flag.
    """
    a = plan.answers
    cat = classify(label)

    if cat == "sponsorship":
        needs = _flag(a.get("requires_sponsorship"))
        if needs is None:
            return None
        if _NEGATED_SPONSOR.search(label):
            # "Are you authorized to work in the US without sponsorship?"
            auth = _flag(a.get("authorized_us"))
            return _yes_no(bool(auth) and not needs) if auth is not None else None
        return _yes_no(needs)
    if cat == "authorization":
        return _yes_no(_flag(a.get("authorized_us")))
    if cat == "salary":
        return a.get("salary_expectation") or None
    if cat in ("linkedin", "github", "portfolio", "first_name", "last_name", "email", "phone"):
        return a.get(cat) or None
    if cat == "source":
        return a.get("how_did_you_hear") or None
    # felony / clearance / legal / eeo / relocate / start / other: no
    # deterministic answer — a human (or an exact learned answer) decides.
    return None


def _flag(v: str | None) -> bool | None:
    if v is None or v == "":
        return None
    return str(v).strip().lower() in ("yes", "true", "1", "y")


def pick_option(options: list[str], answer: str) -> str | None:
    """Choose the <select>/radio option that best matches `answer`.

    Exact (case-insensitive) match first, then Yes/No by leading word, then a
    unique option that starts with / contains the answer.
    """
    norm = [(o, o.strip().lower()) for o in options if o and o.strip()]
    ans = answer.strip().lower()
    for o, lo in norm:
        if lo == ans:
            return o
    if ans in ("yes", "no"):
        hits = [o for o, lo in norm if re.match(rf"{ans}\b", lo)]
        if len(hits) == 1:
            return hits[0]
    starts = [o for o, lo in norm if lo.startswith(ans) or ans.startswith(lo)]
    if len(starts) == 1:
        return starts[0]
    contains = [o for o, lo in norm if ans in lo]
    if len(contains) == 1:
        return contains[0]
    return None
