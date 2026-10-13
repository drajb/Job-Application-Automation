"""Scan the watchlist, filter, score fit, dedupe, persist.

Discovery only SUGGESTS. Nothing here applies anywhere: you still pick each
role (Telegram 🚀 Apply button or `/apply <url>`), and every application still
passes pre-flight, the validator and your approval.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy import select

from src.config import RESUME_SOURCE_DIR
from src.db.models import Application, DiscoveredJob
from src.db.session import get_session
from src.discovery.boards import Posting, fetch_board
from src.discovery.fit import FitReport, score_fit
from src.discovery.watchlist import Watchlist
from src.util.time import utcnow

log = logging.getLogger(__name__)

_CONCURRENCY = 6


@dataclass
class ScoredPosting:
    posting: Posting
    fit: FitReport
    job_id: int | None = None  # discovered_jobs.id once persisted
    seen_before: bool = False


def url_hash(url: str) -> str:
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()


def load_resume_corpus(root: Path = RESUME_SOURCE_DIR) -> str:
    """Union of every resume variant's text — the facts you can claim."""
    if not root.exists():
        return ""
    from src.resume.selector import is_example

    parts = [
        p.read_text(encoding="utf-8", errors="replace")
        for p in sorted(root.rglob("*.md"))
        if not any(part.startswith(".") for part in p.relative_to(root).parts)
        and not is_example(p)
    ]
    return "\n\n".join(parts)


async def fetch_all(wl: Watchlist, *, client: httpx.AsyncClient | None = None) -> list[Posting]:
    sem = asyncio.Semaphore(_CONCURRENCY)
    own = client is None
    client = client or httpx.AsyncClient(follow_redirects=True)

    async def one(b):
        async with sem:
            return await fetch_board(client, b.ats, b.slug, b.name)

    try:
        results = await asyncio.gather(*(one(b) for b in wl.boards))
    finally:
        if own:
            await client.aclose()
    postings = [p for chunk in results for p in chunk]
    # Same role can be cross-listed; keep first by URL.
    seen: set[str] = set()
    unique = []
    for p in postings:
        if p.url not in seen:
            seen.add(p.url)
            unique.append(p)
    return unique


def _embedder():
    try:
        from src.resume.embeddings import embed
        return embed
    except Exception as e:  # torch / sentence-transformers missing
        log.info("discovery: embeddings unavailable (%s) — keyword scoring only", e)
        return None


def rank(
    postings: list[Posting],
    wl: Watchlist,
    resume_text: str,
    *,
    use_embeddings: bool = True,
) -> list[ScoredPosting]:
    accepted = [p for p in postings if wl.filters.accepts(p)]
    embed_fn = _embedder() if (use_embeddings and accepted and resume_text) else None
    resume_emb = None
    if embed_fn is not None:
        try:
            resume_emb = embed_fn(resume_text)
        except Exception as e:
            log.info("discovery: embedding failed (%s) — keyword scoring only", e)
            embed_fn = None
    scored = []
    for p in accepted:
        jd = f"{p.title}\n{p.description}"
        fit = score_fit(jd, resume_text, embed_fn=embed_fn, resume_embedding=resume_emb)
        if fit.score >= wl.filters.min_fit:
            scored.append(ScoredPosting(posting=p, fit=fit))
    scored.sort(key=lambda s: s.fit.score, reverse=True)
    return scored


def persist(scored: list[ScoredPosting]) -> list[ScoredPosting]:
    """Upsert into discovered_jobs; mark which ones we'd already surfaced or applied to."""
    with get_session() as s:
        applied_hashes = set(s.scalars(select(Application.url_hash)))
        for sp in scored:
            h = url_hash(sp.posting.url)
            row = s.scalar(select(DiscoveredJob).where(DiscoveredJob.url_hash == h))
            if row is None:
                row = DiscoveredJob(
                    url_hash=h,
                    url=sp.posting.url,
                    ats=sp.posting.ats,
                    company=sp.posting.company[:255],
                    title=sp.posting.title[:255],
                    location=(sp.posting.location or "")[:255],
                    remote=sp.posting.remote,
                    posted_at=sp.posting.posted_at,
                    first_seen=utcnow(),
                    status="new",
                )
                s.add(row)
            else:
                sp.seen_before = row.status != "new"
            if h in applied_hashes and row.status != "applied":
                row.status = "applied"
                sp.seen_before = True
            row.fit_score = sp.fit.score
            row.missing_keywords = json.dumps(sp.fit.missing[:25])
            row.last_seen = utcnow()
            s.flush()
            sp.job_id = row.id
        s.commit()
    return scored


async def scan(
    wl: Watchlist,
    *,
    resume_root: Path = RESUME_SOURCE_DIR,
    use_embeddings: bool = True,
    include_seen: bool = False,
    save: bool = True,
) -> list[ScoredPosting]:
    """Full pipeline. Returns the top-N postings (new ones only, unless include_seen)."""
    postings = await fetch_all(wl)
    log.info("discovery: %d open roles across %d boards", len(postings), len(wl.boards))
    resume_text = load_resume_corpus(resume_root)
    if not resume_text:
        log.warning("discovery: no resumes under %s — fit scores will be 0", resume_root)
    scored = await asyncio.to_thread(rank, postings, wl, resume_text, use_embeddings=use_embeddings)
    if save:
        scored = persist(scored)
    if not include_seen:
        scored = [s for s in scored if not s.seen_before]
    return scored[: wl.filters.top_n]


def set_status(job_id: int, status: str) -> DiscoveredJob | None:
    """new | notified | applied | dismissed."""
    with get_session() as s:
        row = s.get(DiscoveredJob, job_id)
        if row is None:
            return None
        row.status = status
        s.commit()
        return row
