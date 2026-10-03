import os
from pathlib import Path

import pytest

from conftest import make_pdf, write_json
from dtulearn import mcp_server as m

SYS = "DTU_e26_02132 02132 Computer systems, Fall 2026"
NLP = "CO_01NLP_2026 NLP course 2026 Autumn"
SYS_OU, NLP_OU = 338557, 340001


@pytest.fixture
def out(tmp_path, monkeypatch):
    o = tmp_path / "out"
    s, n = o / SYS, o / NLP
    write_json(s / ".manifest.json", {"ou": SYS_OU})
    write_json(n / ".manifest.json", {"ou": NLP_OU})
    write_json(o / "not a course" / "readme.json", {})          # no manifest: ignored

    write_json(s / "announcements" / "news.json", [
        {"Id": 1, "Title": "Welcome", "StartDate": "2026-09-01T08:00:00.000Z",
         "Body": {"Html": "<p>Welcome to the course.</p>"}, "Attachments": [{"FileName": "plan.pdf"}]},
        {"Id": 2, "Title": "Lab moved", "StartDate": "2026-09-15T08:00:00.000Z",
         "Body": {"Html": "<p>The lab is in room 101.</p>"}},
        {"Id": 3, "Title": "Exam date", "StartDate": "2026-09-25T08:00:00.000Z",
         "Body": {"Html": "<p>The final exam is on 12 December. Bring an example sheet.</p>"}},
        {"Id": 4, "Title": "Hidden draft", "StartDate": "2026-09-30T08:00:00.000Z", "IsHidden": True,
         "Body": {"Html": "<p>secret</p>"}},
    ])
    write_json(n / "announcements" / "news.json", [
        {"Id": 9, "Title": "NLP kickoff", "StartDate": "2026-09-20T08:00:00.000Z",
         "Body": {"Html": "<p>Projects start now.</p>"}},
    ])
    write_json(s / "assignments" / "folders.json", [
        {"Id": 1, "Name": "Assignment 1", "DueDate": "2099-01-10T10:00:00.000Z",
         "CustomInstructions": {"Html": "<p>Implement the parser.</p>"}},
        {"Id": 2, "Name": "Lab 0", "DueDate": "2000-01-01T10:00:00.000Z"},
        {"Id": 3, "Name": "Hidden one", "DueDate": "2099-01-01T10:00:00.000Z", "IsHidden": True},
        {"Id": 4, "Name": "Undated report"},
    ])
    write_json(s / "assignments" / "Assignment 1" / "my_submissions.json", [
        {"Submissions": [{"SubmissionDate": "2026-09-20T10:00:00.000Z"},
                         {"SubmissionDate": "2026-09-21T10:00:00.000Z"}]}])
    write_json(n / "assignments" / "folders.json", [
        {"Id": 5, "Name": "Project: Proposal", "DueDate": "2098-12-01T10:00:00.000Z"}])
    # Folder name is sanitised on disk the same way the scraper does it.
    write_json(n / "assignments" / "Project_ Proposal" / "my_submissions.json", [
        {"Submissions": [{"SubmissionDate": "2026-10-01T09:00:00.000Z"}]}])

    files = {
        s / "content" / "Week 1" / "notes.md": "This example is good.\nSee the   final\n  exam rules.",
        s / "content" / "Week 1" / "rules.txt": "Examination rules apply.",
        s / "content" / "Week 1" / "code.py": "print('hello')",
        s / "content" / "toc.json": "{}",
        s / "announcements" / "announcements.md": "zebra generated copy",
        s / "assignments" / "Assignment 1" / "README.md": "zebra generated copy",
        n / "content" / "Lecture 1" / "intro.md": "For example, tokenization and embeddings.",
        s / "outside.txt": "not in a file area",
    }
    for p, t in files.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t)
    (s / "content" / "Week 1" / "blob.bin").write_bytes(b"\x00\x01\x02")
    (s / "content" / "Week 2").mkdir(parents=True)
    (s / "content" / "Week 2" / "slides.pdf").write_bytes(make_pdf(["Pipelining overview", "Hazards and the exam"]))
    monkeypatch.setattr(m, "OUT", o)
    return o


# ---------------------------------------------------------------- courses / resolve


def test_course_code_and_name(out):
    cs = {c.dir: c for c in m.courses()}
    assert set(cs) == {SYS, NLP}
    assert (cs[SYS].code, cs[SYS].number, cs[SYS].name, cs[SYS].ou) == ("02132", "02132", "Computer systems, Fall 2026", SYS_OU)
    assert (cs[NLP].code, cs[NLP].number, cs[NLP].name, cs[NLP].ou) == ("NLP", None, "NLP course 2026 Autumn", NLP_OU)


@pytest.mark.parametrize("q, expected", [
    (SYS_OU, SYS), (str(NLP_OU), NLP), ("02132", SYS), (" 02132 ", SYS), ("nlp", NLP), ("Computer SYSTEMS", SYS),
])
def test_resolve_one(out, q, expected):
    assert [c.dir for c in m.resolve(q)] == [expected]


def test_resolve_all_ambiguous_unknown(out):
    assert {c.dir for c in m.resolve(None)} == {SYS, NLP}
    assert {c.dir for c in m.resolve("  ")} == {SYS, NLP}
    with pytest.raises(ValueError, match="matches several courses"):
        m.resolve("2026")
    with pytest.raises(ValueError, match=r"No course matches 'xyz'\. Available: .*02132.*NLP"):
        m.resolve("xyz")


def test_resolve_without_data(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "OUT", tmp_path / "nothing")
    with pytest.raises(ValueError, match="No downloaded courses yet"):
        m.resolve(None)
    assert m.list_courses() == m.NEED_DATA


def test_list_courses(out):
    text = m.list_courses()
    assert text.startswith(f"2 courses (data in {out}):")
    assert f"- 02132  Computer systems, Fall 2026  [id {SYS_OU}]  files: 7, announcements: 4, assignments: 4" in text
    assert f"- NLP  NLP course 2026 Autumn  [id {NLP_OU}]  files: 1, announcements: 1, assignments: 1" in text
    assert text.index("02132") < text.index("- NLP")


# ---------------------------------------------------------------- deadlines / announcements


def test_get_deadlines_upcoming(out):
    lines = m.get_deadlines().splitlines()
    assert lines[0] == "Times are Europe/Copenhagen."
    assert lines[1:] == [
        "- Mon 2098-12-01 11:00 | NLP | Project: Proposal | submitted Thu 2026-10-01 11:00",
        "- Sat 2099-01-10 11:00 | 02132 | Assignment 1 | submitted Mon 2026-09-21 12:00",
        "- no due date | 02132 | Undated report | not submitted",
    ]


def test_get_deadlines_include_past_and_course(out):
    lines = m.get_deadlines("02132", include_past=True).splitlines()[1:]
    assert lines[0] == "- Sat 2000-01-01 11:00 (passed) | 02132 | Lab 0 | not submitted"
    assert [l.split(" | ")[2] for l in lines] == ["Lab 0", "Assignment 1", "Undated report"]
    assert "Hidden one" not in "\n".join(lines)


def test_get_deadlines_none(out):
    (out / NLP / "assignments" / "folders.json").write_text("[]")
    assert m.get_deadlines("nlp") == "No upcoming deadlines. (include_past=true shows passed ones)"


def test_get_announcements_limit(out):
    text = m.get_announcements(limit=2)
    blocks = text.split("\n\n---\n\n")
    assert len(blocks) == 2
    assert blocks[0].startswith("## Exam date\n02132 Computer systems, Fall 2026 | Fri 2026-09-25 10:00")
    assert blocks[1].startswith("## NLP kickoff\nNLP NLP course 2026 Autumn | Sun 2026-09-20 10:00")
    assert text.endswith("(2 older not shown; raise limit)")
    assert "Hidden draft" not in m.get_announcements(limit=50)


def test_get_announcements_since_and_course(out):
    text = m.get_announcements(since="2026-09-16")
    assert "Exam date" in text and "NLP kickoff" in text
    assert "Lab moved" not in text and "Welcome" not in text
    one = m.get_announcements("02132", since="2026-09-01T00:00:00Z")
    assert "NLP kickoff" not in one and "Welcome" in one
    assert "Attachments: announcements/1/plan.pdf" in one
    assert m.get_announcements("nlp", since="2026-12-24") == "No announcements since 2026-12-24."
    with pytest.raises(ValueError, match="ISO date"):
        m.get_announcements(since="last week")


# ---------------------------------------------------------------- files


def test_list_files(out):
    text = m.list_files("02132")
    for rel in ["content/Week 1/notes.md", "content/Week 1/rules.txt", "content/Week 2/slides.pdf",
                "announcements/announcements.md", "assignments/Assignment 1/README.md"]:
        assert f"- {rel}  (" in text
    for skipped in ["toc.json", "news.json", "folders.json", "my_submissions.json", "outside.txt", ".manifest"]:
        assert skipped not in text
    filtered = m.list_files("02132", query="WEEK 1/N")
    assert [l.split("  (")[0] for l in filtered.splitlines()[1:]] == ["- content/Week 1/notes.md"]
    assert m.list_files("nlp", query="nope") == "No files in NLP NLP course 2026 Autumn matching 'nope'."


def test_read_file_text(out):
    assert m.read_file("02132", "content/Week 1/notes.md").startswith("content/Week 1/notes.md\n\nThis example")
    assert m.read_file("02132", "content/Week 1/notes.md", max_chars=10).startswith("content/We\n\n[truncated at 10")
    assert "cannot be read as text" in m.read_file("02132", "content/Week 1/blob.bin")


def test_read_file_pdf_pages_and_cache(out):
    text = m.read_file("02132", "content/Week 2/slides.pdf")
    assert text.startswith("content/Week 2/slides.pdf (2 pages, showing 1-2)")
    assert "[page 1]\nPipelining overview" in text and "[page 2]\nHazards and the exam" in text
    p2 = m.read_file("02132", "content/Week 2/slides.pdf", page_start=2)
    assert "[page 1]" not in p2 and "Hazards" in p2
    assert "past the end" in m.read_file("02132", "content/Week 2/slides.pdf", page_start=5)
    cache = list((out / SYS / ".text").glob("*.json"))
    assert len(cache) == 1
    with pytest.raises(ValueError, match="text cache"):
        m.read_file("02132", f".text/{cache[0].name}")


@pytest.mark.parametrize("rel", ["../" + NLP + "/content/Lecture 1/intro.md", "/etc/passwd", "content/../../x"])
def test_read_file_path_traversal_refused(out, rel):
    with pytest.raises(ValueError, match="escapes the course folder"):
        m.read_file("02132", rel)


def test_read_file_symlink_escape_refused(out, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("nope")
    os.symlink(secret, out / SYS / "content" / "link.txt")
    with pytest.raises(ValueError, match="escapes"):
        m.read_file("02132", "content/link.txt")


def test_read_file_missing(out):
    with pytest.raises(ValueError, match="No such file"):
        m.read_file("02132", "content/nope.md")


# ---------------------------------------------------------------- search


def test_search_whole_word(out):
    text = m.search("exam", course="02132")
    assert "announcement: Exam date" in text
    assert "content/Week 2/slides.pdf (page 2)" in text
    assert "notes.md" in text   # "final\n  exam" matches as a word
    assert "rules.txt" not in text   # "Examination" is not the word "exam"


def test_search_exam_does_not_hit_example(out):
    # The NLP course only has "example": no whole-word hit, so the partial-word fallback answers.
    text = m.search("exam", course="nlp")
    assert text.startswith("No whole-word matches for 'exam'; these contain it inside other words:\n- NLP | ")
    assert "intro.md" in text
    assert m.search("exam", course="02132").startswith("3 matches for 'exam':")


def test_search_prefix(out):
    text = m.search("exam*", course="02132")
    assert "rules.txt" in text and "announcement: Exam date" in text


def test_search_multiword_any_whitespace(out):
    assert "notes.md" in m.search("final exam", course="02132")      # text has "final\n  exam"
    assert "announcement: Exam date" in m.search("FINAL\texam", course="02132")


def test_search_multiword_query_with_extra_spaces(out):
    assert "announcement: Exam date" in m.search("final  exam", course="02132")


def test_search_partial_word_fallback(out):
    text = m.search("xamina", course="02132")
    assert text.startswith("No whole-word matches for 'xamina'; these contain it inside other words:\n- ")
    assert "rules.txt" in text


def test_search_assignment_instructions_and_skips_generated(out):
    assert "assignment instructions: Assignment 1" in m.search("parser")
    assert m.search("zebra") == "No matches for 'zebra'."


def test_search_all_courses_and_limit(out):
    assert "NLP | content/Lecture 1/intro.md" in m.search("embeddings")
    limited = m.search("the", limit=1)
    assert limited.startswith("1 matches for 'the':") and limited.endswith("(stopped at limit=1)")


def test_search_empty_query(out):
    with pytest.raises(ValueError, match="empty"):
        m.search(" * ")
