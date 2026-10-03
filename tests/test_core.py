import json
from pathlib import Path

import httpx
import pytest

from conftest import write_json
from dtulearn import core


# ---------------------------------------------------------------- safe / headers


@pytest.mark.parametrize("raw, expected", [
    ("Lecture 1: Intro/Overview?", "Lecture 1_ Intro_Overview_"),
    ('a\\b*c"d<e>f|g', "a_b_c_d_e_f_g"),
    ("tab\there\x01", "tab_here_"),
    ("  .hidden name. ", "hidden name"),
    ("...", "untitled"),
    ("", "untitled"),
])
def test_safe(raw, expected):
    assert core.safe(raw) == expected


def test_safe_truncates_to_180():
    assert core.safe("x" * 400) == "x" * 180


@pytest.mark.parametrize("cd, expected", [
    ("attachment; filename*=UTF-8''na%C3%AFve%20slides.pdf", "naïve slides.pdf"),
    ('attachment; filename="Week 3 slides.pdf"', "Week 3 slides.pdf"),
    ("inline; filename=plain.pdf", "plain.pdf"),
    ('attachment; filename="fallback.pdf"; filename*=UTF-8\'\'real%20name.pdf', "real name.pdf"),
])
def test_filename_from_headers(cd, expected):
    assert core.filename_from_headers(httpx.Headers({"Content-Disposition": cd})) == expected


def test_filename_from_headers_missing():
    assert core.filename_from_headers(httpx.Headers({})) is None
    assert core.filename_from_headers(httpx.Headers({"Content-Disposition": "inline"})) is None


def test_filename_from_headers_lowercase_charset():
    h = httpx.Headers({"Content-Disposition": "attachment; filename*=utf-8''a%20b.pdf"})
    assert core.filename_from_headers(h) == "a b.pdf"


# ---------------------------------------------------------------- current_semester


def enr(ou_id, start, type_id=3):
    access = {"IsActive": True}
    if start is not ...:
        access["StartDate"] = start
    return {"OrgUnit": {"Id": ou_id, "Type": {"Id": type_id, "Code": "x"}, "Name": f"c{ou_id}"}, "Access": access}


def test_current_semester_window_and_filters():
    es = [
        enr(1, "2026-08-25T00:00:00.000Z"),          # newest course offering
        enr(2, "2026-04-27T00:00:00.000Z"),          # exactly 120 days before: kept
        enr(3, "2026-04-26T00:00:00.000Z"),          # 121 days: dropped
        enr(4, "2025-09-01T00:00:00.000Z"),          # last year
        enr(5, "2027-01-01T00:00:00.000Z", type_id=4),  # group/department: ignored, must not move "newest"
        enr(6, None),                                 # StartDate null
        enr(7, ...),                                  # StartDate missing
    ]
    assert [e["OrgUnit"]["Id"] for e in core.current_semester(es)] == [1, 2]


def test_current_semester_empty():
    assert core.current_semester([]) == []
    assert core.current_semester([enr(1, None), enr(2, "2026-01-01T00:00:00Z", type_id=2)]) == []


# ---------------------------------------------------------------- pdf_candidate / find_urls


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=abc",
    "https://youtu.be/abc",
    "https://dtu.zoom.us/rec/share/xyz",
    "https://ids.brightspace.com/files/report.pdf",
    "https://dtu.panopto.eu/Panopto/Pages/Viewer.aspx?id=1",
    "https://docs.google.com/forms/d/e/abc/viewform",
    "https://teams.microsoft.com/l/meetup-join/x",
    "https://learn.inside.dtu.dk/d2l/common/dialogs/quickLink/quickLink.d2l?ou=1&type=coursefile&fileId=a.pdf",
    "https://learn.inside.dtu.dk/content/enforced/1-x/page.html",
    "https://learn.inside.dtu.dk/d2l/le/content/1/viewContent/2/View",
])
def test_pdf_candidate_skipped(url):
    assert core.pdf_candidate(url) is None


@pytest.mark.parametrize("url, expected", [
    ("https://learn.inside.dtu.dk/content/enforced/338557-x/Week1/Slides.PDF",
     "https://learn.inside.dtu.dk/content/enforced/338557-x/Week1/Slides.PDF"),
    ("https://arxiv.org/abs/1706.03762", "https://arxiv.org/pdf/1706.03762"),
    ("https://arxiv.org/abs/1706.03762v7", "https://arxiv.org/pdf/1706.03762"),
    ("https://arxiv.org/pdf/1706.03762v2.pdf", "https://arxiv.org/pdf/1706.03762"),
    ("https://arxiv.org/abs/cs/0112017", "https://arxiv.org/pdf/cs/0112017"),
    ("https://example.com/papers/attention.pdf", "https://example.com/papers/attention.pdf"),
    ("https://example.com/download?id=7", "https://example.com/download?id=7"),
])
def test_pdf_candidate_kept(url, expected):
    assert core.pdf_candidate(url) == expected


def test_find_urls_joins_relative_href():
    html = '<p><a href="/content/enforced/1-x/a.pdf">a</a> <a href=\'/d2l/le/x\'>b</a></p>'
    assert core.find_urls(html) == {
        "https://learn.inside.dtu.dk/content/enforced/1-x/a.pdf",
        "https://learn.inside.dtu.dk/d2l/le/x",
    }


def test_find_urls_strips_trailing_punctuation_and_backslash():
    text = ("See https://example.com/a.pdf. Also https://example.com/b.pdf, and https://example.com/c.pdf; "
            "or https://example.com/d.pdf: done. JSON: <a href=\\\"https://example.com/e.pdf\\\">")
    assert core.find_urls(text) == {f"https://example.com/{c}.pdf" for c in "abcde"}


def test_find_urls_unescapes_amp():
    assert core.find_urls('<a href="https://x.org/get?a=1&amp;b=2">x</a>') == {"https://x.org/get?a=1&b=2"}


def test_find_urls_relative_href_inside_json():
    text = json.dumps({"Body": {"Html": '<a href="/content/enforced/1-x/a.pdf">a</a>'}})
    assert "https://learn.inside.dtu.dk/content/enforced/1-x/a.pdf" in core.find_urls(text)


# ---------------------------------------------------------------- write_changes / queue_new_lectures


def test_write_changes_nothing_new(tmp_path):
    core.write_changes(tmp_path, {"Course A": [], "Course B": []})
    changes = (tmp_path / "CHANGES.md").read_text()
    assert changes.startswith("# DTU Learn: new since last run\n\n## ")
    assert "Nothing new." in changes
    assert "###" not in changes


def test_write_changes_lists_items_and_changelog_newest_first(tmp_path):
    core.write_changes(tmp_path, {"Course A": ["File: content/old.pdf"]})
    core.write_changes(tmp_path, {"Course A": [], "Course B": ["Announcement: Exam room (2026-12-01)"]})
    changes = (tmp_path / "CHANGES.md").read_text()
    assert "### Course B\n- Announcement: Exam room (2026-12-01)\n" in changes
    assert "Course A" not in changes and "Nothing new." not in changes
    log = (tmp_path / "changelog.md").read_text()
    assert log.count("# DTU Learn changelog") == 1
    assert log.startswith("# DTU Learn changelog\n\n## ")
    assert log.index("Exam room") < log.index("content/old.pdf")


def test_queue_new_lectures(tmp_path):
    report = {"02132 Computer systems": [
        "File: content/Week 1/Lecture 1 slides.pdf",
        "File: content/Week 1/Lecture 1 handout.pptx",
        "File: content/Week 1/Exercises week 1.pdf",
        "File: content/Week 1/Solution week 1.pdf",
        "File: content/Week 2/Lecture 2.pdf",
        "File: content/Misc/notes.pdf",              # no lecture hint
        "File: content/Week 1/recording.mp4",        # not slides
        "File: assignments/Week 1 lecture/x.pdf",    # not under content/
        "Announcement: Lecture 1 slides are up (2026-09-01)",
    ]}
    roots = {"02132 Computer systems": tmp_path / "out" / "02132"}
    touched = core.queue_new_lectures(tmp_path, report, roots)
    assert [(e["lecture"], e["files"]) for e in touched] == [
        ("content/Week 1", ["content/Week 1/Lecture 1 slides.pdf", "content/Week 1/Lecture 1 handout.pptx"]),
        ("content/Week 2", ["content/Week 2/Lecture 2.pdf"]),
    ]
    queue = json.loads((tmp_path / "new_lectures.json").read_text())
    assert all(q["status"] == "pending" and q["out_dir"] == str(roots["02132 Computer systems"]) for q in queue)
    # Same report again: nothing new, no duplicates.
    assert core.queue_new_lectures(tmp_path, report, roots) == []
    assert json.loads((tmp_path / "new_lectures.json").read_text()) == queue


# ---------------------------------------------------------------- sync_course


@pytest.fixture
def sync_tree(tmp_path):
    src = tmp_path / "out" / "02132 Computer systems"
    for rel, body in {
        "content/Week 1/Lecture 1.pdf": b"%PDF lecture one",
        "content/Week 1/Exercises.pdf": b"%PDF exercises one",
        "content/toc.json": b"{}",
        "announcements/news.json": b"[]",
        "assignments/A1/my_submissions.json": b"[]",
        ".manifest.json": b'{"ou": 1}',
        ".text/abc.json": b"{}",
        "content/.DS_Store": b"x",
        "linked/.hidden/x.pdf": b"%PDF hidden",
    }.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    course = tmp_path / "vault" / "02132"
    dest = course / "material" / "learn"
    mine = dest.parent / "lectures" / "my renamed exercises.pdf"   # same bytes, other name, beside dest
    mine.parent.mkdir(parents=True)
    mine.write_bytes(b"%PDF exercises one")
    return src, dest, mine


def test_sync_course_dry_run_copies_nothing(sync_tree):
    src, dest, mine = sync_tree
    copied, dupes = core.sync_course(src, dest, dry_run=True)
    assert copied == [str(Path("content/Week 1/Lecture 1.pdf"))]
    assert dupes == [f"{Path('content/Week 1/Exercises.pdf')} (already at {Path('lectures/my renamed exercises.pdf')})"]
    assert not dest.exists()


def test_sync_course_copies_skips_and_never_deletes(sync_tree):
    src, dest, mine = sync_tree
    dest.mkdir(parents=True)
    (dest / "my own note.md").write_text("keep me")
    copied, dupes = core.sync_course(src, dest, dry_run=False)
    assert copied == [str(Path("content/Week 1/Lecture 1.pdf"))]
    assert len(dupes) == 1
    files = sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())
    assert files == sorted([str(Path("content/Week 1/Lecture 1.pdf")), "my own note.md"])
    assert (dest / "my own note.md").read_text() == "keep me"
    assert mine.read_bytes() == b"%PDF exercises one"

    # Second run: identical content, nothing to do.
    assert core.sync_course(src, dest, dry_run=False) == ([], dupes)

    # Changed upstream file is copied again (overwrites only inside dest); removed upstream file stays.
    (src / "content/Week 1/Lecture 1.pdf").write_bytes(b"%PDF lecture one v2")
    (src / "content/Week 1/Exercises.pdf").unlink()
    copied, dupes = core.sync_course(src, dest, dry_run=False)
    assert copied == [str(Path("content/Week 1/Lecture 1.pdf"))] and dupes == []
    assert (dest / "content/Week 1/Lecture 1.pdf").read_bytes() == b"%PDF lecture one v2"
    assert (dest / "my own note.md").exists() and mine.exists()


# ---------------------------------------------------------------- scrape_args


def test_scrape_args_defaults(dl):
    a = core.scrape_args()
    assert vars(a) == dict(course=None, current=True, all=False, include_inactive=False, out=str(dl.paths.OUT),
                           force=False, no_linked=False, no_recordings=False, sync=False, dry_run=False,
                           config=str(dl.paths.SYNC_CONFIG), no_vault=False)
    assert str(dl.home) in a.out


def test_scrape_args_sync_follows_config_and_overrides(dl):
    write_json(dl.paths.SYNC_CONFIG, {"1": "/tmp/x"})
    a = core.scrape_args(course=[1], current=False, force=True)
    assert a.sync is True and a.course == [1] and a.current is False and a.force is True
