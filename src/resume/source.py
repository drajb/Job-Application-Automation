"""Read source resume .md (preferred) / .docx as plain text. READ-ONLY."""

from __future__ import annotations

import logging
from pathlib import Path

from docx import Document

log = logging.getLogger(__name__)


def read_source(md_or_docx: Path) -> str:
    """Return the source resume as a single string. Prefers .md over .docx."""
    p = md_or_docx
    if p.suffix.lower() == ".md" and p.exists():
        return p.read_text(encoding="utf-8")
    docx = p if p.suffix.lower() == ".docx" else p.with_suffix(".docx")
    if not docx.exists():
        raise FileNotFoundError(p)
    doc = Document(str(docx))
    parts: list[str] = []
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text)
    return "\n".join(parts)
