"""PDF text cache, shared by refresh (fills it) and the MCP server (reads it).

One JSON file per PDF under <course>/.text/, keyed by path, mtime and size, so a changed PDF is extracted again.
Refresh fills the cache in parallel processes, so the first search after a download is fast.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

CACHE_DIR = ".text"
PDF_AREAS = ("content", "assignments", "linked", "announcements")

log = logging.getLogger("dtu-learn")
logging.getLogger("pypdf").setLevel(logging.ERROR)


def cache_file(course: Path, rel: str) -> Path:
    return course / CACHE_DIR / (hashlib.sha1(rel.encode()).hexdigest()[:20] + ".json")


def cached(course: Path, pdf: Path) -> list[str] | None:
    rel, st = str(pdf.relative_to(course)), pdf.stat()
    try:
        hit = json.loads(cache_file(course, rel).read_text())
    except (OSError, ValueError):
        return None
    if hit.get("path") == rel and hit.get("mtime") == st.st_mtime_ns and hit.get("size") == st.st_size:
        return hit["pages"]
    return None


def pages(course: Path, pdf: Path) -> list[str]:
    """Page texts of one PDF, from the cache or extracted now (and cached)."""
    hit = cached(course, pdf)
    if hit is not None:
        return hit
    from pypdf import PdfReader

    rel, st = str(pdf.relative_to(course)), pdf.stat()
    log.info("extracting %s", rel)
    try:
        out = []
        for pg in PdfReader(str(pdf)).pages:
            try:
                out.append(pg.extract_text() or "")
            except Exception as e:  # noqa: BLE001 - one bad page must not kill the file
                out.append(f"[page could not be extracted: {type(e).__name__}]")
    except Exception as e:  # noqa: BLE001
        log.warning("pdf failed %s: %s", rel, e)
        out = [f"[PDF could not be read: {type(e).__name__}: {e}]"]
    target = cache_file(course, rel)
    target.parent.mkdir(exist_ok=True)
    tmp = target.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"path": rel, "mtime": st.st_mtime_ns, "size": st.st_size, "pages": out},
                              ensure_ascii=False))
    tmp.replace(target)  # atomic: a reader never sees half a file
    return out


def _job(args: tuple[str, str]) -> int:
    course, pdf = map(Path, args)
    return len(pages(course, pdf))


def missing(course: Path) -> list[Path]:
    pdfs = [f for area in PDF_AREAS if (course / area).is_dir()
            for f in (course / area).rglob("*") if f.is_file() and f.suffix.lower() == ".pdf"]
    return [p for p in pdfs if cached(course, p) is None]


def warm(courses: list[Path], workers: int | None = None) -> int:
    """Extract every PDF that is not cached yet, in parallel processes. Returns how many were extracted."""
    jobs = [(str(c), str(p)) for c in courses for p in missing(c)]
    if not jobs:
        return 0
    workers = min(len(jobs), workers or os.cpu_count() or 4)
    if workers == 1:
        for j in jobs:
            _job(j)
    else:
        with ProcessPoolExecutor(workers) as pool:
            list(pool.map(_job, jobs, chunksize=1))
    return len(jobs)
