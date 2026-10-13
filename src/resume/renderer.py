"""Render tailored markdown → .docx → .pdf via LibreOffice headless.

  1. python-docx writes a fresh, ATS-friendly .docx from the tailored markdown
     (headings, bullets, numbered lists, **bold** / *italic* runs, links).
  2. `libreoffice --headless --convert-to pdf` renders it, using a throwaway
     LibreOffice profile per call (a shared profile lets one stuck soffice
     process lock every later render) and a hard timeout.
  3. The PDF is verified (exists, non-empty, starts with %PDF) and the run's
     UUID is stamped into its metadata with pypdf, so response rates can be
     tracked per resume variant.

Each render lives in its own folder, data/tailored/<uuid>/, and the PDF is
named `<First>_<Last>_Resume.pdf` — that filename is what a recruiter sees,
so it must not leak internal variant names.

Source resumes are never touched.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docx import Document
from docx.shared import Pt

from src.config import DATA_DIR

log = logging.getLogger(__name__)

TAILORED_DIR = DATA_DIR / "tailored"
_TIMEOUT_S = 90


class RenderError(RuntimeError):
    pass


@dataclass
class RenderResult:
    uuid: str
    docx_path: Path
    pdf_path: Path
    pdf_ok: bool = True  # False when LibreOffice is unavailable (dry-run only)


def _safe(s: str, n: int) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:n] or "Candidate"


def render(
    tailored_md: str,
    *,
    variant: str,
    company: str,
    role: str,
    candidate_name: str = "",
    require_pdf: bool = False,
) -> RenderResult:
    """Render to data/tailored/<uuid>/. Blocking (LibreOffice) — call it via
    asyncio.to_thread from async code.

    require_pdf=True (real submissions) raises RenderError when no valid PDF
    could be produced; otherwise a missing LibreOffice yields pdf_ok=False.
    """
    rid = uuid.uuid4().hex[:12]
    out_dir = TAILORED_DIR / rid
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{_safe(candidate_name, 40)}_Resume" if candidate_name else "Resume"

    docx_path = out_dir / f"{stem}.docx"
    _md_to_docx(tailored_md, docx_path, uuid_tag=rid)
    (out_dir / "meta.txt").write_text(
        f"uuid={rid}\nvariant={variant}\ncompany={company}\nrole={role}\n", encoding="utf-8",
    )

    pdf_path = docx_path.with_suffix(".pdf")
    pdf_ok = _docx_to_pdf(docx_path, pdf_path)
    if pdf_ok:
        _stamp_pdf(pdf_path, rid)
    elif require_pdf:
        raise RenderError(
            "could not produce a PDF resume (is LibreOffice installed? "
            "`sudo apt install libreoffice --no-install-recommends`)",
        )
    log.info("rendered tailored resume: %s (pdf_ok=%s)", pdf_path, pdf_ok)
    return RenderResult(uuid=rid, docx_path=docx_path, pdf_path=pdf_path, pdf_ok=pdf_ok)


# --- markdown → docx ---------------------------------------------------------

_INLINE_RE = re.compile(r"(\*\*[^*]+\*\*|__[^_]+__|\*[^*\s][^*]*\*|_[^_\s][^_]*_|`[^`]+`|\[[^\]]+\]\([^)]+\))")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _add_runs(paragraph, text: str) -> None:
    """Add text to a paragraph, converting inline markdown to formatted runs."""
    for part in _INLINE_RE.split(text):
        if not part:
            continue
        if (part.startswith("**") and part.endswith("**")) or (part.startswith("__") and part.endswith("__")):
            paragraph.add_run(part[2:-2]).bold = True
        elif len(part) > 2 and part[0] in "*_" and part[-1] == part[0]:
            paragraph.add_run(part[1:-1]).italic = True
        elif part.startswith("`") and part.endswith("`"):
            paragraph.add_run(part[1:-1])
        elif (m := _LINK_RE.fullmatch(part)):
            label, url = m.group(1), m.group(2)
            bare = re.sub(r"^(https?://)?(www\.)?", "", url).rstrip("/")
            paragraph.add_run(label if bare in label or url in label else f"{label} ({url})")
        else:
            paragraph.add_run(part)


def _md_to_docx(md: str, out: Path, *, uuid_tag: str) -> None:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"  # ATS-friendly default
    style.font.size = Pt(11)

    for line in md.splitlines():
        s = line.rstrip()
        stripped = s.strip()
        if not stripped or re.fullmatch(r"[-*_]{3,}", stripped):
            continue  # blank lines / horizontal rules: spacing comes from styles
        if m := re.match(r"^(#{1,4})\s+(.*)$", stripped):
            level = len(m.group(1)) - 1
            heading = doc.add_heading("", level=level)
            _add_runs(heading, m.group(2).strip())
        elif m := re.match(r"^\s*[-*+]\s+(.*)$", s):
            _add_runs(doc.add_paragraph(style="List Bullet"), m.group(1).strip())
        elif m := re.match(r"^\s*\d+[.)]\s+(.*)$", s):
            _add_runs(doc.add_paragraph(style="List Number"), m.group(1).strip())
        elif stripped.startswith(">"):
            _add_runs(doc.add_paragraph(), stripped.lstrip("> ").strip())
        else:
            _add_runs(doc.add_paragraph(), stripped)

    doc.core_properties.identifier = uuid_tag
    doc.core_properties.comments = f"apply-agent uuid={uuid_tag}"
    doc.save(str(out))


# --- docx → pdf ----------------------------------------------------------------


def _docx_to_pdf(docx_path: Path, pdf_path: Path) -> bool:
    libreoffice = shutil.which("libreoffice") or shutil.which("soffice")
    if libreoffice is None:
        log.warning(
            "libreoffice not found — PDF rendering skipped. "
            "Install with: sudo apt install libreoffice --no-install-recommends",
        )
        return False

    with tempfile.TemporaryDirectory(prefix="apply_agent_lo_") as profile_dir:
        cmd = [
            libreoffice,
            f"-env:UserInstallation={Path(profile_dir).as_uri()}",
            "--headless", "--norestore",
            "--convert-to", "pdf",
            "--outdir", str(docx_path.parent),
            str(docx_path),
        ]
        popen_kw: dict = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
        if os.name == "posix":
            popen_kw["start_new_session"] = True  # so we can kill the whole group
        proc = subprocess.Popen(cmd, **popen_kw)
        try:
            _out, err = proc.communicate(timeout=_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            _kill(proc)
            log.error("libreoffice timed out after %ss", _TIMEOUT_S)
            return False
        if proc.returncode != 0:
            log.error("libreoffice convert failed: %s", err.decode("utf-8", "replace")[:500])
            return False

    try:
        ok = pdf_path.stat().st_size > 0 and pdf_path.read_bytes()[:5] == b"%PDF-"
    except OSError:
        ok = False
    if not ok:
        log.error("libreoffice exited 0 but produced no valid PDF at %s", pdf_path)
    return ok


def _kill(proc: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError):
        pass
    proc.wait(timeout=5)


def _stamp_pdf(pdf_path: Path, rid: str) -> None:
    """Write the run UUID into the PDF's Subject/Keywords metadata."""
    try:
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(str(pdf_path))
        writer = PdfWriter(clone_from=reader)
        meta: dict[str, Any] = dict(reader.metadata or {})
        meta.update({"/Subject": f"apply-agent uuid={rid}", "/Keywords": f"apply-agent,{rid}"})
        writer.add_metadata(meta)
        tmp = pdf_path.with_suffix(".tmp.pdf")
        with tmp.open("wb") as fh:
            writer.write(fh)
        os.replace(tmp, pdf_path)
    except Exception as e:  # metadata is nice-to-have; never fail a render over it
        log.warning("could not stamp PDF metadata: %s", e)
