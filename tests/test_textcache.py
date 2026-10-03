"""PDF text cache: refresh fills it, the MCP server reads it."""

import os

from conftest import make_pdf


def _course(tmp_path, n=2):
    course = tmp_path / "out" / "DTU_e26_02132 02132 Computer systems, Fall 2026"
    for i in range(n):
        p = course / "content" / f"Lecture {i}" / f"slides-{i}.pdf"
        p.parent.mkdir(parents=True)
        p.write_bytes(make_pdf([f"Lecture {i} page one", f"pipeline hazards {i}"]))
    return course


def test_warm_extracts_once_then_uses_cache(dl, tmp_path):
    from dtulearn import textcache

    course = _course(tmp_path)
    assert len(textcache.missing(course)) == 2
    assert textcache.warm([course], workers=1) == 2
    assert textcache.missing(course) == []
    assert textcache.warm([course], workers=1) == 0
    pdf = next(course.rglob("slides-0.pdf"))
    assert "pipeline hazards 0" in textcache.cached(course, pdf)[1]


def test_changed_pdf_is_extracted_again(dl, tmp_path):
    from dtulearn import textcache

    course = _course(tmp_path, n=1)
    pdf = next(course.rglob("*.pdf"))
    textcache.warm([course], workers=1)
    pdf.write_bytes(make_pdf(["new text after the teacher updated the slides"]))
    os.utime(pdf, ns=(1, 1))
    assert textcache.cached(course, pdf) is None
    assert textcache.warm([course], workers=1) == 1
    assert "teacher updated" in textcache.cached(course, pdf)[0]


def test_mcp_reads_what_refresh_cached(dl, tmp_path):
    from dtulearn import textcache

    course = _course(tmp_path, n=1)
    pdf = next(course.rglob("*.pdf"))
    textcache.warm([course], workers=1)
    assert textcache.pages(course, pdf) == textcache.cached(course, pdf)
