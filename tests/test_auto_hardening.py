"""Hardening of the scheduled run: flood guard, baseline, refresh lock, STATUS.md, retry cap."""
import json
from datetime import datetime, timedelta

import pytest

from dtulearn import core


def _report(n):
    return {"02132 Computer systems": [f"File: content/Lectures/Lecture {i}/02132 - Lecture {i} - 2026.pdf"
                                       for i in range(1, n + 1)]}


def test_normal_week_queues_pending(tmp_path):
    touched = core.queue_new_lectures(tmp_path, _report(2))
    assert [e["status"] for e in touched] == ["pending", "pending"]


def test_flood_of_new_lectures_becomes_baseline(tmp_path):
    touched = core.queue_new_lectures(tmp_path, _report(core.MAX_NEW_LECTURES + 1))
    assert touched == []
    queue = json.loads((tmp_path / "new_lectures.json").read_text())
    assert {e["status"] for e in queue} == {"baseline"}


def test_reupload_of_baseline_lecture_does_not_requeue(tmp_path):
    core.queue_new_lectures(tmp_path, _report(core.MAX_NEW_LECTURES + 1))
    report = {"02132 Computer systems": ["File: content/Lectures/Lecture 1/02132 - Lecture 1 - 2026 v2.pdf"]}
    core.queue_new_lectures(tmp_path, report)
    queue = json.loads((tmp_path / "new_lectures.json").read_text())
    lec1 = [e for e in queue if e["lecture"].endswith("Lecture 1")][0]
    assert lec1["status"] == "baseline" and len(lec1["files"]) == 2


def test_seed_baseline_is_idempotent(tmp_path):
    root = tmp_path / "C1 Course one"
    (root / "content" / "Week 1").mkdir(parents=True)
    (root / ".manifest.json").write_text("{}")
    (root / "content" / "Week 1" / "Lecture 1 slides.pdf").write_bytes(b"%PDF")
    (root / "content" / "Week 1" / "Exercise 1.pdf").write_bytes(b"%PDF")
    assert core.seed_lecture_baseline(tmp_path) == 1
    assert core.seed_lecture_baseline(tmp_path) == 0
    queue = json.loads((tmp_path / "new_lectures.json").read_text())
    assert queue[0]["status"] == "baseline" and queue[0]["files"] == ["content/Week 1/Lecture 1 slides.pdf"]


def test_refresh_lock_blocks_second_run(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "LOCK", tmp_path / ".refresh.lock")
    monkeypatch.setattr(core, "ensure_home", lambda: None)
    first = core._take_lock()
    with pytest.raises(core.RefreshLocked):
        core._take_lock()
    first.close()
    core._take_lock().close()


def test_status_file(tmp_path, monkeypatch):
    for name, val in {"STATUS": tmp_path / "STATUS.md", "LAST_AUTO": tmp_path / ".last_auto",
                      "OUT": tmp_path, "AUTO_LOG": tmp_path / "auto.log"}.items():
        monkeypatch.setattr(core, name, val)
    core.LAST_AUTO.write_text((datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds"))
    (tmp_path / "new_lectures.json").write_text(json.dumps([
        {"course": "NLP course", "lecture": "content/Week 7/Slides", "files": [], "status": "pending"},
        {"course": "NLP course", "lecture": "content/Week 1/Slides", "files": [], "status": "baseline"}]))
    core.write_status("login expired", "no refresh until you log in")
    text = (tmp_path / "STATUS.md").read_text()
    assert "Login needed:** YES" in text
    assert "| NLP course | Week 7 | pending |" in text
    assert "1 older lectures are baseline" in text
    core.write_status("ok", "2 new items", ["02132: File: x.pdf"])
    text = (tmp_path / "STATUS.md").read_text()
    assert "Login needed:** no" in text and "- 02132: File: x.pdf" in text
    core.write_status("skipped", "not due yet")
    assert "not checked" in (tmp_path / "STATUS.md").read_text()


def test_next_check_is_0730():
    assert core._next_check(datetime(2026, 10, 5, 6, 0)) == datetime(2026, 10, 5, 7, 30)
    assert core._next_check(datetime(2026, 10, 5, 8, 0)) == datetime(2026, 10, 6, 7, 30)
