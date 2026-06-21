"""Scan 1st-degree connections for people working at a target company.

Open the company's LinkedIn People page, scroll, collect names + roles. Returns
candidates ranked by signal (e.g. recruiter > engineer > unrelated).

We DO NOT send connection requests or DMs. We hand the list to the drafter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import quote_plus

from playwright.async_api import async_playwright

from src.linkedin.session import has_session, session_path

log = logging.getLogger(__name__)


@dataclass
class Candidate:
    name: str
    headline: str
    profile_url: str
    relevance_score: int


async def scan(company: str, *, max_results: int = 20) -> list[Candidate]:
    if not has_session():
        log.warning("no LinkedIn session at %s; user must log in first", session_path())
        return []

    url = f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(company)}&network=%5B%22F%22%5D"
    candidates: list[Candidate] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(storage_state=str(session_path()))
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            # Scroll to load more results.
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, 800)")
                await page.wait_for_timeout(800)

            cards = await page.query_selector_all("li.reusable-search__result-container")
            for card in cards[:max_results]:
                name_el = await card.query_selector(".entity-result__title-text a")
                headline_el = await card.query_selector(".entity-result__primary-subtitle")
                if not (name_el and headline_el):
                    continue
                name = ((await name_el.inner_text()) or "").strip().splitlines()[0]
                headline = ((await headline_el.inner_text()) or "").strip()
                href = (await name_el.get_attribute("href")) or ""
                candidates.append(Candidate(
                    name=name, headline=headline,
                    profile_url=href.split("?")[0],
                    relevance_score=_rank(headline, company),
                ))
        finally:
            await ctx.close()
            await browser.close()

    candidates.sort(key=lambda c: c.relevance_score, reverse=True)
    return candidates


def _rank(headline: str, company: str) -> int:
    h = headline.lower()
    score = 0
    if company.lower() in h:
        score += 5
    if any(k in h for k in ("recruiter", "talent", "people partner")):
        score += 10
    if any(k in h for k in ("engineering manager", "head of", "director")):
        score += 6
    if any(k in h for k in ("engineer", "scientist", "researcher")):
        score += 3
    return score
