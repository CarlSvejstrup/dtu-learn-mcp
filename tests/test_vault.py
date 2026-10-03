import re
from datetime import date
from pathlib import Path

import pytest

from conftest import write_json
from dtulearn import vault

TODAY = date.today().isoformat()


def test_course_folder():
    assert vault.course_folder(Path("/v/studies/02132/material/learn")) == Path("/v/studies/02132")
    assert vault.course_folder(Path("/v/studies/02132/learn")) is None
    assert vault.course_folder(Path("/v/studies/02132/material/other")) is None


# ---------------------------------------------------------------- announcements

NEWS = [
    {"Id": 1, "Title": " Welcome ", "StartDate": "2026-09-01T08:00:00.000Z",
     "Body": {"Html": "<p>Hello <b>class</b>, see <a href=\"https://x.org\">this</a>.</p>"},
     "Attachments": [{"FileName": "plan.pdf"}]},
    {"Id": 2, "Title": "Exam info", "StartDate": "2026-12-01T10:30:00.000Z",
     "Body": {"Html": "", "Text": "Plain fallback text"}, "Attachments": []},
    {"Id": 3, "Title": "Undated note", "StartDate": None, "Body": {"Html": "<p>x</p>"}},
]


@pytest.fixture
def vault_course(tmp_path):
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    course = root / "studies" / "02132"
    course.mkdir(parents=True)
    src = tmp_path / "out" / "02132 Computer systems"
    return src, course


def test_write_announcements_markdown_newest_first_cph_time(vault_course):
    src, course = vault_course
    write_json(src / "announcements" / "news.json", NEWS)
    assert vault.write_announcements(src, course, "02132 Computer systems") == 3
    text = (course / "announcements.md").read_text()
    assert text.startswith(f"---\ntype: reference\nsource: DTU Learn\nupdated: {TODAY}\n---\n")
    assert "# 02132 Computer systems: DTU Learn announcements" in text
    # Copenhagen time: CET (+1) in December, CEST (+2) in September.
    i_exam = text.index("## 2026-12-01 11:30 · Exam info")
    i_welcome = text.index("## 2026-09-01 10:00 · Welcome\n")
    i_undated = text.index("## undated · Undated note")
    assert i_exam < i_welcome < i_undated
    assert "Hello **class**" in text and "see [this](https://x.org)." in text
    assert "<p>" not in text
    assert "Plain fallback text" in text
    # Attachment wikilink relative to the vault root.
    assert "- Attachment: [[studies/02132/material/learn/announcements/1/plan.pdf|plan.pdf]]" in text


def test_write_announcements_without_vault_root(tmp_path):
    src, course = tmp_path / "src", tmp_path / "course"
    course.mkdir()
    write_json(src / "announcements" / "news.json", NEWS[:1])
    assert vault.write_announcements(src, course, "C") == 1
    assert "[[material/learn/announcements/1/plan.pdf|plan.pdf]]" in (course / "announcements.md").read_text()


def test_write_announcements_unchanged_leaves_file_untouched(vault_course):
    src, course = vault_course
    write_json(src / "announcements" / "news.json", NEWS)
    vault.write_announcements(src, course, "C")
    target = course / "announcements.md"
    old = target.read_text().replace(f"updated: {TODAY}", "updated: 2020-01-01")
    target.write_text(old)
    assert vault.write_announcements(src, course, "C") == 0
    assert target.read_text() == old  # only `updated:` would differ, so nothing is written


def test_write_announcements_rewrites_on_change(vault_course):
    src, course = vault_course
    write_json(src / "announcements" / "news.json", NEWS[:1])
    vault.write_announcements(src, course, "C")
    write_json(src / "announcements" / "news.json", NEWS)
    assert vault.write_announcements(src, course, "C") == 3
    assert "Exam info" in (course / "announcements.md").read_text()


def test_write_announcements_empty_or_missing(vault_course):
    src, course = vault_course
    assert vault.write_announcements(src, course, "C") == 0
    write_json(src / "announcements" / "news.json", [])
    assert vault.write_announcements(src, course, "C") == 0
    assert not (course / "announcements.md").exists()


# ---------------------------------------------------------------- backlog

BACKLOG = """---
type: backlog
updated: 2020-01-01
---

# 02132 backlog

## Next

- [ ] **Read chapter 3** *(execute · 2026-09-01)*
- [ ] **Project 2 report** *(execute · 2026-09-02)* due 2099-04-01, started by hand.

## Waiting

- [ ] Reply from TA
"""
OU = 338557


def folder(fid, name, due):
    f = {"Id": fid, "Name": name}
    if due is not None:
        f["DueDate"] = due
    return f


@pytest.fixture
def backlog_course(tmp_path):
    src, course = tmp_path / "src", tmp_path / "course"
    course.mkdir()
    (course / "backlog.md").write_text(BACKLOG)
    return src, course


def mark(fid):
    return f"<!-- learn:dropbox:{OU}:{fid} -->"


def test_update_backlog_adds_future_deadlines_under_next(backlog_course):
    src, course = backlog_course
    write_json(src / "assignments" / "folders.json", [
        folder(10, "Assignment 1: Parsing", "2099-03-10T21:59:00.000Z"),   # future: added
        folder(11, "Lab 0", "2000-01-01T00:00:00.000Z"),                  # past: skipped
        folder(12, "Project 2 - Report", "2099-04-01T10:00:00.000Z"),      # prefix + same date in backlog
        folder(13, "Read chapter 3", "2099-05-01T10:00:00.000Z"),          # full name already there
        folder(14, "No due date", None),
        folder(15, "Project 2 - Slides", "2099-06-01T10:00:00.000Z"),      # prefix there, other date: added
    ])
    changes = vault.update_backlog(src, course, OU)
    assert changes == ["Deadline added: Assignment 1: Parsing (2099-03-10 22:59)",
                       "Deadline added: Project 2 - Slides (2099-06-01 12:00)"]
    text = (course / "backlog.md").read_text()
    assert f"updated: {TODAY}" in text and "updated: 2020-01-01" not in text
    line = (f"- [ ] **Assignment 1: Parsing** *(execute · {TODAY})* DTU Learn deadline **2099-03-10 22:59**. "
            f"{mark(10)}")
    assert line in text
    nxt, waiting = text.split("## Next", 1)[1].split("## Waiting")
    assert mark(10) in nxt and mark(15) in nxt
    assert nxt.index("Project 2 report") < nxt.index(mark(10))   # appended after existing items
    for fid in (11, 12, 13, 14):
        assert mark(fid) not in text
    assert "Reply from TA" in waiting


def test_update_backlog_idempotent_and_moved_deadline(backlog_course):
    src, course = backlog_course
    folders = [folder(10, "Assignment 1: Parsing", "2099-03-10T21:59:00.000Z")]
    write_json(src / "assignments" / "folders.json", folders)
    vault.update_backlog(src, course, OU)
    before = (course / "backlog.md").read_text()
    assert vault.update_backlog(src, course, OU) == []
    assert (course / "backlog.md").read_text() == before

    # The deadline moves: the tagged line is updated in place, not duplicated.
    (course / "backlog.md").write_text(before.replace(f"updated: {TODAY}", "updated: 2020-01-01"))
    folders[0]["DueDate"] = "2099-03-17T21:59:00.000Z"
    write_json(src / "assignments" / "folders.json", folders)
    assert vault.update_backlog(src, course, OU) == ["Deadline moved: Assignment 1: Parsing -> 2099-03-17 22:59"]
    text = (course / "backlog.md").read_text()
    assert text.count(mark(10)) == 1
    assert "deadline **2099-03-17 22:59**" in text and "2099-03-10" not in text
    assert f"updated: {TODAY}" in text


def test_update_backlog_empty_next_section(tmp_path):
    src, course = tmp_path / "src", tmp_path / "course"
    course.mkdir()
    (course / "backlog.md").write_text("---\nupdated: 2020-01-01\n---\n\n## Next\n\n## Done\n\n- [x] old\n")
    write_json(src / "assignments" / "folders.json", [folder(1, "Hand-in", "2099-01-05T12:00:00Z")])
    assert len(vault.update_backlog(src, course, OU)) == 1
    text = (course / "backlog.md").read_text()
    assert re.search(r"## Next\n\n- \[ \] \*\*Hand-in\*\*.*\n\n## Done", text)


def test_update_backlog_needs_files(tmp_path):
    src, course = tmp_path / "src", tmp_path / "course"
    course.mkdir()
    write_json(src / "assignments" / "folders.json", [folder(1, "X", "2099-01-01T00:00:00Z")])
    assert vault.update_backlog(src, course, OU) == []      # no backlog.md
    assert not (course / "backlog.md").exists()


# ---------------------------------------------------------------- videos


def test_write_videos(tmp_path):
    src = tmp_path / "src"
    write_json(src / "content" / "toc.json", {"Modules": [{"Description": {"Html":
        '<a href="https://www.youtube.com/watch?v=abc&amp;t=10">yt</a> https://video.dtu.dk/media/Lecture+1/0_x1'}}]})
    write_json(src / "announcements" / "news.json", [{"Body": {"Html":
        "Recording (https://youtu.be/xyz). Same as https://video.dtu.dk/media/Lecture+1/0_x1, "
        "and https://dtu.zoom.us/rec/share/abc;"}}])
    write_json(src / "assignments" / "folders.json", [{"Name": "no video here https://example.com/a.pdf"}])
    assert vault.write_videos(src) == 4
    text = (src / "videos.md").read_text()
    assert text.startswith("# Video links\n")
    lines = [l for l in text.splitlines() if l.startswith("- ")]
    assert lines == sorted(lines)
    assert "- https://www.youtube.com/watch?v=abc&t=10 (content)" in lines
    assert "- https://youtu.be/xyz (announcements)" in lines
    assert "- https://dtu.zoom.us/rec/share/abc (announcements)" in lines
    assert "- https://video.dtu.dk/media/Lecture+1/0_x1 (content)" in lines   # first source wins
    assert "example.com" not in text


def test_write_videos_none_removes_old_file(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "videos.md").write_text("stale")
    write_json(src / "content" / "toc.json", {"Modules": []})
    assert vault.write_videos(src) == 0
    assert not (src / "videos.md").exists()
