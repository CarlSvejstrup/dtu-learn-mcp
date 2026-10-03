"""The optional after-refresh hook: the shared tool knows nothing about pages or videos."""
import json
import subprocess

from dtulearn import core


def _paths(tmp_path, monkeypatch, hook: bool):
    hook_file = tmp_path / "hooks" / "after-refresh"
    if hook:
        hook_file.parent.mkdir()
        hook_file.write_text("#!/bin/sh\nexit 0\n")
        hook_file.chmod(0o755)
    for name, val in {"AFTER_REFRESH": hook_file, "OUT": tmp_path, "HOME": tmp_path,
                      "STATUS": tmp_path / "STATUS.md", "LAST_AUTO": tmp_path / ".last_auto",
                      "AUTO_LOG": tmp_path / "auto.log"}.items():
        monkeypatch.setattr(core, name, val)
    return hook_file


def test_no_hook_means_disabled_and_no_queue_in_status(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch, hook=False)
    assert not core.hook_enabled()
    core.write_status("ok", "0 new items")
    status = (tmp_path / "STATUS.md").read_text()
    assert "Lecture queue" not in status and "Next refresh" in status


def test_non_executable_hook_is_ignored(tmp_path, monkeypatch):
    hook = _paths(tmp_path, monkeypatch, hook=True)
    hook.chmod(0o644)
    assert not core.hook_enabled()


def test_hook_runs_with_limit_when_lectures_wait(tmp_path, monkeypatch):
    hook = _paths(tmp_path, monkeypatch, hook=True)
    (tmp_path / "new_lectures.json").write_text(json.dumps([{"course": "C", "lecture": "L1", "status": "pending"}]))
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)))
    core._run_hook()
    assert calls and calls[0][0] == [str(hook), "--limit", str(core.HOOK_LIMIT)]
    assert calls[0][1]["env"]["DTU_LEARN_HOME"]


def test_hook_not_run_when_nothing_waits(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch, hook=True)
    (tmp_path / "new_lectures.json").write_text(json.dumps([{"course": "C", "lecture": "L1", "status": "done"}]))
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    core._run_hook()
    assert calls == []


def test_status_shows_queue_when_hook_queue_exists(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch, hook=True)
    (tmp_path / "new_lectures.json").write_text(json.dumps(
        [{"course": "NLP course", "lecture": "content/Week 7/Slides", "status": "pending"}]))
    core.write_status("ok", "1 new item")
    assert "Lecture queue" in (tmp_path / "STATUS.md").read_text()
