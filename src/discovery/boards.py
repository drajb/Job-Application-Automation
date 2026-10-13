"""Public job-board fetchers for the ATSes we support.

Every supported ATS exposes an unauthenticated JSON feed of a company's open
roles. Reading those feeds is exactly what the company's own careers page
does, so this is polite, cheap and needs no API key:

  greenhouse       https://boards-api.greenhouse.io/v1/boards/<slug>/jobs?content=true
  lever            https://api.lever.co/v0/postings/<slug>?mode=json
  ashby            https://api.ashbyhq.com/posting-api/job-board/<slug>
  smartrecruiters  https://api.smartrecruiters.com/v1/companies/<slug>/postings

`<slug>` is the company's board token — the path segment in its careers URL,
e.g. `boards.greenhouse.io/<slug>` or `jobs.lever.co/<slug>`.

Fetchers never raise for a single bad board: they log and return []. One
misspelled slug in your watchlist must not kill the whole scan.
"""

from __future__ import annotations

import html
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from selectolax.lexbor import LexborHTMLParser as HTMLParser

log = logging.getLogger(__name__)

SUPPORTED_BOARDS = ("greenhouse", "lever", "ashby", "smartrecruiters")

_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_HEADERS = {"User-Agent": "apply-agent job-discovery (+https://github.com/drajb/Job-Application-Automation)"}


@dataclass(frozen=True)
class Posting:
    """One open role, normalised across ATSes."""

    ats: str
    company: str
    title: str
    location: str
    url: str
    description: str = ""
    posted_at: datetime | None = None  # naive UTC
    remote: bool = False


def html_to_text(raw: str) -> str:
    """Strip tags from a (possibly HTML-escaped) HTML fragment."""
    if not raw:
        return ""
    unescaped = html.unescape(raw)
    if "<" not in unescaped:
        return unescaped.strip()
    tree = HTMLParser(unescaped)
    text = tree.body.text(separator="\n") if tree.body else tree.text(separator="\n")
    lines = (ln.strip() for ln in text.splitlines())
    return "\n".join(ln for ln in lines if ln)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def _from_epoch_ms(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC).replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError):
        return None


def _looks_remote(*parts: str) -> bool:
    return any("remote" in (p or "").lower() for p in parts)


# --- per-ATS parsers (pure functions: JSON in, Postings out — easy to test) ---


def parse_greenhouse(data: dict, slug: str, company: str | None = None) -> list[Posting]:
    out: list[Posting] = []
    for j in data.get("jobs") or []:
        loc = (j.get("location") or {}).get("name") or ""
        out.append(Posting(
            ats="greenhouse",
            company=company or j.get("company_name") or slug.replace("-", " ").title(),
            title=(j.get("title") or "").strip(),
            location=loc,
            url=j.get("absolute_url") or "",
            description=html_to_text(j.get("content") or ""),
            posted_at=_parse_iso(j.get("first_published") or j.get("updated_at")),
            remote=_looks_remote(loc),
        ))
    return out


def parse_lever(data: list, slug: str, company: str | None = None) -> list[Posting]:
    out: list[Posting] = []
    for j in data or []:
        cats = j.get("categories") or {}
        loc = cats.get("location") or ", ".join(cats.get("allLocations") or [])
        workplace = j.get("workplaceType") or ""
        out.append(Posting(
            ats="lever",
            company=company or slug.replace("-", " ").title(),
            title=(j.get("text") or "").strip(),
            location=loc,
            url=j.get("hostedUrl") or j.get("applyUrl") or "",
            description=j.get("descriptionPlain") or html_to_text(j.get("description") or ""),
            posted_at=_from_epoch_ms(j.get("createdAt")),
            remote=workplace == "remote" or _looks_remote(loc),
        ))
    return out


def parse_ashby(data: dict, slug: str, company: str | None = None) -> list[Posting]:
    out: list[Posting] = []
    for j in data.get("jobs") or []:
        if j.get("isListed") is False:
            continue
        loc = j.get("location") or ""
        out.append(Posting(
            ats="ashby",
            company=company or slug.replace("-", " ").title(),
            title=(j.get("title") or "").strip(),
            location=loc,
            url=j.get("jobUrl") or j.get("applyUrl") or "",
            description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml") or ""),
            posted_at=_parse_iso(j.get("publishedAt")),
            remote=bool(j.get("isRemote")) or _looks_remote(loc),
        ))
    return out


def parse_smartrecruiters(data: dict, slug: str, company: str | None = None) -> list[Posting]:
    out: list[Posting] = []
    for j in data.get("content") or []:
        loc_obj = j.get("location") or {}
        loc = ", ".join(x for x in (loc_obj.get("city"), loc_obj.get("region"), loc_obj.get("country")) if x)
        posting_id = j.get("id") or ""
        out.append(Posting(
            ats="smartrecruiters",
            company=company or (j.get("company") or {}).get("name") or slug,
            title=(j.get("name") or "").strip(),
            location=loc,
            url=f"https://jobs.smartrecruiters.com/{slug}/{posting_id}" if posting_id else "",
            # The list endpoint has no description; title-only fit scoring applies.
            description="",
            posted_at=_parse_iso(j.get("releasedDate")),
            remote=bool(loc_obj.get("remote")) or _looks_remote(loc),
        ))
    return out


_ENDPOINTS: dict[str, tuple[str, Callable[..., list[Posting]]]] = {
    "greenhouse": ("https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true", parse_greenhouse),
    "lever": ("https://api.lever.co/v0/postings/{slug}?mode=json", parse_lever),
    "ashby": ("https://api.ashbyhq.com/posting-api/job-board/{slug}", parse_ashby),
    "smartrecruiters": ("https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100", parse_smartrecruiters),
}


async def fetch_board(
    client: httpx.AsyncClient, ats: str, slug: str, company: str | None = None,
) -> list[Posting]:
    """Fetch and normalise one company's open roles. Returns [] on any error."""
    ats = ats.lower().strip()
    if ats not in _ENDPOINTS:
        log.warning("discovery: unsupported ats %r for %s (supported: %s)",
                    ats, slug, ", ".join(SUPPORTED_BOARDS))
        return []
    url_tpl, parser = _ENDPOINTS[ats]
    url = url_tpl.format(slug=slug)
    try:
        r = await client.get(url, timeout=_TIMEOUT, headers=_HEADERS)
        if r.status_code == 404:
            log.warning("discovery: %s board %r not found — check the slug", ats, slug)
            return []
        r.raise_for_status()
        postings = parser(r.json(), slug, company)
    except (httpx.HTTPError, ValueError) as e:
        log.warning("discovery: %s/%s fetch failed: %s", ats, slug, e)
        return []
    return [p for p in postings if p.title and p.url]
