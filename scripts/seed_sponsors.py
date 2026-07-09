"""Seed sponsors_h1b from data/sponsors_h1b.csv.

The CSV is sourced from myvisajobs.com or USCIS H-1B Employer Data Hub.
Headers: company,sponsored_count,last_seen_year
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from sqlalchemy import select

from src.config import REPO_ROOT
from src.db.models import SponsorH1B
from src.db.session import get_session


def seed(csv_path: Path) -> int:
    if not csv_path.exists():
        print(f"ERROR: {csv_path} missing", file=sys.stderr)
        return 1
    inserted = updated = 0
    with csv_path.open(encoding="utf-8") as fh, get_session() as s:
        reader = csv.DictReader(fh)
        for row in reader:
            name = (row.get("company") or "").strip()
            if not name:
                continue
            count = int(row.get("sponsored_count") or 0)
            year = int(row.get("last_seen_year") or 0) or None
            existing = s.scalar(select(SponsorH1B).where(SponsorH1B.company == name))
            if existing is None:
                s.add(SponsorH1B(company=name, sponsored_count=count, last_seen_year=year))
                inserted += 1
            else:
                existing.sponsored_count = count
                existing.last_seen_year = year
                updated += 1
        s.commit()
    print(f"sponsors_h1b: inserted={inserted} updated={updated}")
    return 0


if __name__ == "__main__":
    sys.exit(seed(REPO_ROOT / "data" / "sponsors_h1b.csv"))
