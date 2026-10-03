import json

import pytest

from conftest import write_json
from dtulearn import mcp_server as m
from dtulearn import recordings as rec

SRT = """1
00:00:01,631 --> 00:00:04,841
[Auto-generated transcript. Edits may have been applied for clarity.]
Welcome to the deep learning course.

2
00:00:05,361 --> 00:00:09,441
I'm the main teacher.

3
00:00:40,000 --> 00:00:43,000
Today: convolutions
and pooling.

4
01:02:50,000 --> 01:02:55,000
Skip connections are residual connections.
"""


# ---------------------------------------------------------------- pure helpers


def test_parse_srt_reads_times_and_joins_lines():
    cues = rec.parse_srt(SRT)
    assert len(cues) == 4
    assert cues[0][0] == pytest.approx(1.631) and cues[0][1] == pytest.approx(4.841)
    assert cues[2][2] == "Today: convolutions and pooling."
    assert cues[3][0] == 3770


def test_parse_srt_skips_empty_and_garbage():
    assert rec.parse_srt("") == []
    assert rec.parse_srt("1\n00:00:01,000 --> 00:00:02,000\n\n\nnot a cue") == []


def test_blocks_merge_by_30_seconds_and_drop_auto_notice():
    b = rec.blocks(rec.parse_srt(SRT))
    assert [round(s) for s, _ in b] == [2, 40, 3770]
    assert b[0][1] == "Welcome to the deep learning course. I'm the main teacher."
    assert "Auto-generated" not in " ".join(t for _, t in b)


def test_timestamps_round_trip():
    assert rec.fmt_ts(5.9) == "00:05"
    assert rec.fmt_ts(3770) == "1:02:50"
    assert rec.parse_ts("1:02:50") == 3770
    assert rec.parse_ts("53:00") == 3180
    assert rec.parse_ts("90") == 90


def test_ms_date():
    d = rec.ms_date("/Date(1788181345000)/")
    assert d.year == 2026 and d.tzinfo is not None
    assert rec.ms_date(None) is None and rec.ms_date("nope") is None


FOLDERS = [
    {"Id": "a", "Name": "02456 Deep learning, Fall 2026", "SessionCount": 5},
    {"Id": "b", "Name": "02450 Introduction to Machine Learning and Data Mining Spring 24", "SessionCount": 13},
    {"Id": "c", "Name": "02450 Introduktion til machine learning og data mining", "SessionCount": 0},
    {"Id": "d", "Name": "02002 Computer Programming (Polytechnical Foundation) Fall 23", "SessionCount": 14},
    {"Id": "e", "Name": "NLP course 2026 Autumn", "SessionCount": 0},
    {"Id": "f", "Name": None, "SessionCount": 1},
]


@pytest.mark.parametrize("course,want", [
    ("02456 Deep learning, Fall 2026", "a"),
    ("02456  deep learning, fall 2026", "a"),                                   # whitespace and case
    ("02450 Introduction to Machine Learning and Data Mening, Spring 2024", "b"),  # old naming + typo
    ("02002 Computer Programming (Polytechnical Foundation) Fall 23", "d"),
    ("NLP course 2026 Autumn", "e"),
    ("02456 Deep learning, Fall 2025", None),                                   # other term
    ("42010 Business studies, Fall 2026", None),
])
def test_match_folder(course, want):
    f = rec.match_folder(FOLDERS, course)
    assert (f and f["Id"]) == want


def test_course_key():
    assert rec.course_key("02450 Intro, Spring 2024") == ("02450", "spring24")
    assert rec.course_key("02450 Intro Spring 24") == ("02450", "spring24")
    assert rec.course_key("12345 X, Autumn 2026") == ("12345", "fall26")
    assert rec.course_key("NLP course 2026 Autumn") is None


def test_chapters_prefer_ai_then_slide_titles():
    ai = {"AIChapters": [{"Start": 60, "Summary": " B "}, {"Start": 1, "Summary": "A"}],
          "Timestamps": [{"EventTargetType": "SmartOcrToc", "Time": 5, "Caption": "Slide"}]}
    assert rec.chapters(ai) == [(1, "A"), (60, "B")]
    ocr = {"AIChapters": None, "Timestamps": [
        {"EventTargetType": "SmartOcrToc", "Time": 5, "Caption": "Slide 1"},
        {"EventTargetType": "AIChapters", "Time": 9, "Caption": None},
        {"EventTargetType": "SmartOcrToc", "Time": 7, "Caption": "  "}]}
    assert rec.chapters(ocr) == [(5, "Slide 1")]
    assert rec.chapters({}) == []


def _rec(**kw):
    base = {"id": "d1", "name": "Week 4: CNNs", "start": "/Date(1789995370000)/", "duration": 3840,
            "language": 0, "url": "https://x/Viewer.aspx?id=d1"}
    base.update(kw)
    return base


def test_render_and_file_name():
    md = rec.render(_rec(), "02456 Deep learning, Fall 2026", [(1, "Intro")],
                    rec.blocks(rec.parse_srt(SRT)))
    assert md.startswith("# Week 4: CNNs\n")
    assert "64 min | captions: English" in md and "Personal study use only" in md
    assert "- [00:01] Intro" in md
    assert "[1:02:50] Skip connections are residual connections." in md
    assert rec.file_name(_rec()) == "2026-09-21 Week 4_ CNNs.md"
    assert "language id 99" in rec.render(_rec(language=99), "c", [], [(0, "x")])


def test_transcript_slice():
    md = rec.render(_rec(), "c", [], rec.blocks(rec.parse_srt(SRT)))
    part = rec.transcript_slice(md, rec.parse_ts("00:30"), rec.parse_ts("10:00"))
    assert "Today: convolutions" in part and "Welcome" not in part and "Skip connections" not in part
    assert part.startswith("# Week 4")
    assert rec.transcript_slice(md, None, None) == md


# ---------------------------------------------------------------- sync with a fake Panopto


class FakePanopto:
    def __init__(self, rows, captions=None):
        self.rows = rows
        self.caps = captions if captions is not None else {"d1": SRT}
        self.calls = []

    def sessions(self, folder_id):
        self.calls.append(("sessions", folder_id))
        return self.rows

    def delivery(self, did):
        self.calls.append(("delivery", did))
        return {"AvailableCaptions": [{"Language": 0}] if did in self.caps else [],
                "AIChapters": [{"Start": 1, "Summary": "Intro"}]}

    def captions(self, did, lang):
        self.calls.append(("captions", did))
        return self.caps.get(did, "")


def _row(did, name, captions=True, start="/Date(1789995370000)/"):
    return {"DeliveryID": did, "SessionName": name, "StartTime": start, "Duration": 600,
            "HasCaptions": captions, "ViewerUrl": f"https://x/Viewer.aspx?id={did}"}


def test_sync_course_writes_index_and_transcripts(tmp_path):
    pan = FakePanopto([_row("d1", "Week 1"), _row("d2", "Week 2", captions=False)])
    root = tmp_path / "02456 Deep learning, Fall 2026"
    ch = rec.sync_course(pan, "02456 Deep learning, Fall 2026", root, FOLDERS)
    idx = json.loads((root / "recordings" / "recordings.json").read_text())
    assert [r["id"] for r in idx] == ["d1", "d2"]
    assert idx[0]["file"] == "2026-09-21 Week 1.md" and idx[1]["file"] is None
    text = (root / "recordings" / idx[0]["file"]).read_text()
    assert "- [00:01] Intro" in text and "[1:02:50] Skip connections" in text
    assert ch == ["recording transcript: 2026-09-21 Week 1.md", "recording (no captions yet): Week 2"]
    assert ("sessions", "a") in pan.calls and ("captions", "d2") not in pan.calls

    # Second run: nothing new, nothing fetched again.
    pan2 = FakePanopto(pan.rows)
    assert rec.sync_course(pan2, "02456 Deep learning, Fall 2026", root, FOLDERS) == []
    assert [c[0] for c in pan2.calls] == ["sessions"]

    # Captions arrive later for d2: fetched then.
    pan3 = FakePanopto([_row("d1", "Week 1"), _row("d2", "Week 2")], {"d1": SRT, "d2": SRT})
    assert rec.sync_course(pan3, "02456 Deep learning, Fall 2026", root, FOLDERS) == \
        ["recording transcript: 2026-09-21 Week 2.md"]


def test_sync_course_no_folder_or_no_sessions_writes_nothing(tmp_path):
    root = tmp_path / "c"
    assert rec.sync_course(FakePanopto([]), "42010 Business studies, Fall 2026", root, FOLDERS) == []
    assert rec.sync_course(FakePanopto([]), "02456 Deep learning, Fall 2026", root, FOLDERS) == []
    assert not (root / "recordings").exists()


def test_sync_course_survives_one_failing_recording(tmp_path, capsys):
    class Broken(FakePanopto):
        def delivery(self, did):
            if did == "d1":
                raise RuntimeError("boom")
            return super().delivery(did)

    pan = Broken([_row("d1", "Week 1"), _row("d3", "Week 3")], {"d1": SRT, "d3": SRT})
    ch = rec.sync_course(pan, "02456 Deep learning, Fall 2026", tmp_path / "c", FOLDERS)
    assert ch == ["recording transcript: 2026-09-21 Week 3.md"]
    assert "boom" in capsys.readouterr().out


def test_sync_courses_uses_guarded_browser(dl, tmp_path):
    with pytest.raises(AssertionError, match="playwright"):
        dl.core.recordings.sync_courses([("x", tmp_path)])


def test_scrape_skips_recordings_on_flag_and_tolerates_errors(dl, monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(dl.core.recordings, "sync_courses", lambda courses, force: called.append(courses) or
                        (_ for _ in ()).throw(RuntimeError("panopto down")))

    class Api:
        lp, le = "1", "1"

        def enrollments(self):
            return []

    monkeypatch.setattr(dl.core, "D2L", lambda client: Api())
    monkeypatch.setattr(dl.core, "session_client", lambda: None)
    args = dl.core.scrape_args(course=[], current=False, out=str(tmp_path), sync=False, no_text=True)
    dl.core.cmd_scrape(args)  # error from Panopto is logged, not raised
    assert called == [[]]
    dl.core.cmd_scrape(dl.core.scrape_args(course=[], current=False, out=str(tmp_path), sync=False,
                                           no_text=True, no_recordings=True))
    assert called == [[]]


# ---------------------------------------------------------------- MCP tools


@pytest.fixture
def out(tmp_path, monkeypatch):
    o = tmp_path / "out"
    c = o / "DTU_e26_02456 02456 Deep learning, Fall 2026"
    write_json(c / ".manifest.json", {"ou": 326353})
    rec.sync_course(FakePanopto([_row("d1", "Week 1"), _row("d2", "Week 2", captions=False)]),
                    "02456 Deep learning, Fall 2026", c, FOLDERS)
    monkeypatch.setattr(m, "OUT", o)
    return o


def test_list_recordings(out):
    t = m.list_recordings("02456")
    assert "5 recordings" not in t and "2 recordings" in t
    assert "Week 1 | 10 min | recordings/2026-09-21 Week 1.md" in t
    assert "Week 2 | 10 min | no transcript yet" in t


def test_list_recordings_none(out, tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    write_json(empty / "x" / ".manifest.json", {"ou": 1})
    monkeypatch.setattr(m, "OUT", empty)
    assert "No recordings saved" in m.list_recordings()


def test_get_transcript_by_name_date_number_and_range(out):
    assert "[1:02:50] Skip connections" in m.get_transcript("02456", "week 1")
    assert "[1:02:50] Skip connections" in m.get_transcript("02456", "2026-09-21")
    assert "[1:02:50] Skip connections" in m.get_transcript("02456", "1")
    part = m.get_transcript("02456", "week 1", start="00:30", end="5:00")
    assert "Today: convolutions" in part and "Skip connections" not in part
    assert "no transcript yet" in m.get_transcript("02456", "2")
    assert "truncated" in m.get_transcript("02456", "week 1", max_chars=50)
    with pytest.raises(ValueError, match="No recordings match"):
        m.get_transcript("02456", "week 9")


def test_search_finds_transcript_with_timestamp(out):
    t = m.search("residual connections", "02456")
    assert "recordings/2026-09-21 Week 1.md (at 1:02:50)" in t


def test_recordings_index_is_not_a_course_file(out):
    files = m.list_files("02456")
    assert "recordings/2026-09-21 Week 1.md" in files and "recordings.json" not in files


def test_search_keeps_room_for_transcripts_when_slides_fill_the_limit(out):
    c = out / "DTU_e26_02456 02456 Deep learning, Fall 2026"
    for i in range(30):
        f = c / "content" / f"notes{i:02d}.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("residual connections everywhere")
    t = m.search("residual connections", "02456", limit=6)
    assert t.count("\n- ") == 6
    assert t.count("recordings/") == 1 and "(at 1:02:50)" in t   # its quota (6 // 3 = 2), only 1 hit exists
    assert m.search("Today", "02456", limit=6).count("recordings/") == 1  # no material hits: transcripts fill
