"""Watchlist: which companies to scan and which roles you care about.

Lives at `watchlist.yaml` in the repo root (gitignored) or wherever
`WATCHLIST_PATH` points. Start from `watchlist.example.yaml`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import yaml

from src.config import REPO_ROOT
from src.discovery.boards import SUPPORTED_BOARDS, Posting
from src.util.time import utcnow


def default_path() -> Path:
    return Path(os.environ.get("WATCHLIST_PATH") or REPO_ROOT / "watchlist.yaml").expanduser()


@dataclass(frozen=True)
class Board:
    ats: str
    slug: str
    name: str | None = None


@dataclass
class Filters:
    title_include: list[str] = field(default_factory=list)  # any-of, substring, case-insensitive
    title_exclude: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)  # any-of substring; empty = anywhere
    remote_ok: bool = True  # remote roles pass the location filter
    max_age_days: int | None = 30
    min_fit: float = 0.0  # 0..1
    top_n: int = 10

    def accepts(self, p: Posting) -> bool:
        title = p.title.lower()
        if self.title_include and not any(k.lower() in title for k in self.title_include):
            return False
        if any(k.lower() in title for k in self.title_exclude):
            return False
        if self.locations:
            loc = p.location.lower()
            loc_ok = any(k.lower() in loc for k in self.locations)
            if not loc_ok and not (self.remote_ok and p.remote):
                return False
        too_old = (
            self.max_age_days is not None
            and p.posted_at is not None
            and p.posted_at < utcnow() - timedelta(days=self.max_age_days)
        )
        return not too_old


@dataclass
class Watchlist:
    boards: list[Board]
    filters: Filters


class WatchlistError(ValueError):
    pass


def _str_list(v, key: str) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise WatchlistError(f"filters.{key} must be a list of strings")
    return v


def parse(data: dict) -> Watchlist:
    if not isinstance(data, dict):
        raise WatchlistError("watchlist must be a YAML mapping")
    boards: list[Board] = []
    for i, c in enumerate(data.get("companies") or []):
        if not isinstance(c, dict) or not c.get("ats") or not c.get("slug"):
            raise WatchlistError(f"companies[{i}] needs both `ats` and `slug`")
        ats = str(c["ats"]).lower().strip()
        if ats not in SUPPORTED_BOARDS:
            raise WatchlistError(
                f"companies[{i}].ats={ats!r} unsupported (use one of {', '.join(SUPPORTED_BOARDS)})",
            )
        boards.append(Board(ats=ats, slug=str(c["slug"]).strip(), name=c.get("name")))
    f = data.get("filters") or {}
    if not isinstance(f, dict):
        raise WatchlistError("filters must be a mapping")
    max_age = f.get("max_age_days", 30)
    filters = Filters(
        title_include=_str_list(f.get("title_include"), "title_include"),
        title_exclude=_str_list(f.get("title_exclude"), "title_exclude"),
        locations=_str_list(f.get("locations"), "locations"),
        remote_ok=bool(f.get("remote_ok", True)),
        max_age_days=None if max_age in (None, 0) else int(max_age),
        min_fit=float(f.get("min_fit", 0.0)),
        top_n=int(f.get("top_n", 10)),
    )
    if not 0.0 <= filters.min_fit <= 1.0:
        raise WatchlistError("filters.min_fit must be between 0 and 1")
    return Watchlist(boards=boards, filters=filters)


def load(path: Path | None = None) -> Watchlist:
    path = path or default_path()
    if not path.exists():
        raise FileNotFoundError(
            f"no watchlist at {path}. Copy watchlist.example.yaml to watchlist.yaml and edit it.",
        )
    return parse(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
