"""Cluster recent HITL interventions, propose qa_log seeds + profile additions.

Runs every 10 applications per docs/SPEC.md §8. Output goes to
docs/training_proposals_<date>.md as a human-readable diff.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from src.config import REPO_ROOT
from src.db.models import TrainingRun
from src.db.session import get_session
from src.util.time import utcnow


def collect_recent(days: int = 14) -> list[TrainingRun]:
    cutoff = utcnow() - timedelta(days=days)
    with get_session() as s:
        return list(s.scalars(
            select(TrainingRun).where(
                TrainingRun.intervened.is_(True),
                TrainingRun.timestamp >= cutoff,
            ),
        ))


def group_by_question(rows: list[TrainingRun]) -> dict[str, list[TrainingRun]]:
    out: defaultdict[str, list[TrainingRun]] = defaultdict(list)
    for r in rows:
        key = (r.question or "").strip()
        if not key:
            continue
        out[key].append(r)
    return dict(out)


def write_report(groups: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    today = utcnow().date()
    path = out_dir / f"training_proposals_{today:%Y-%m-%d}.md"
    lines = [f"# Training proposals — {today:%Y-%m-%d}\n"]
    lines.append(f"Found {sum(len(v) for v in groups.values())} interventions across "
                 f"{len(groups)} unique questions.\n")
    for q, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"## {q}")
        lines.append(f"  - count: {len(items)}")
        answers = [i.human_action for i in items if i.human_action]
        if answers:
            lines.append(f"  - example answer: {answers[0][:200]}")
        lines.append(
            "  - **proposal**: add to qa_log as `source=human` with category inferred from text.\n",
        )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    rows = collect_recent()
    groups = group_by_question(rows)
    if not groups:
        print("no recent HITL interventions found")
        return 0
    path = write_report(groups, REPO_ROOT / "docs")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
