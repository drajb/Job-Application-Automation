"""Scrape company about/values/news for essay context.

Intentionally minimal: fetch the homepage + /about + try /news,
parse with selectolax, return a compact text summary. A future change can
add Glassdoor and press-release crawling.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 apply-agent (https://github.com/drajb/Job-Application-Automation)"
)
TIMEOUT = 15.0


@dataclass
class CompanyFacts:
    homepage_url: str
    about_text: str
    raw_excerpts: list[str]

    def as_prompt_block(self) -> str:
        head = f"Homepage: {self.homepage_url}\n\nAbout:\n{self.about_text[:1200]}"
        if self.raw_excerpts:
            head += "\n\nOther:\n" + "\n---\n".join(self.raw_excerpts[:3])
        return head[:3000]


async def fetch(company_homepage: str) -> CompanyFacts:
    base = _normalize_url(company_homepage)
    headers = {"User-Agent": UA}
    async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers, follow_redirects=True) as client:
        home_text = await _safe_get_text(client, base)
        about_text = ""
        for path in ("/about", "/about-us", "/company", "/mission"):
            t = await _safe_get_text(client, urljoin(base, path))
            if len(t) > 300:
                about_text = t
                break
        news = []
        for path in ("/blog", "/news", "/press"):
            t = await _safe_get_text(client, urljoin(base, path))
            if len(t) > 300:
                news.append(t[:1500])
                if len(news) >= 2:
                    break

    return CompanyFacts(
        homepage_url=base,
        about_text=about_text or home_text[:1500],
        raw_excerpts=news,
    )


async def _safe_get_text(client: httpx.AsyncClient, url: str) -> str:
    try:
        r = await client.get(url)
        if r.status_code >= 400:
            return ""
        return _html_to_text(r.text)
    except Exception as e:
        log.debug("fetch failed %s: %s", url, e)
        return ""


def _html_to_text(html: str) -> str:
    try:
        tree = HTMLParser(html)
        for sel in ("script", "style", "noscript", "header", "nav", "footer"):
            for node in tree.css(sel):
                node.decompose()
        text = tree.body.text(separator=" ", strip=True) if tree.body else ""
        return " ".join(text.split())
    except Exception as e:
        log.debug("html parse failed: %s", e)
        return ""


def _normalize_url(u: str) -> str:
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    p = urlparse(u)
    return f"{p.scheme}://{p.netloc}"
