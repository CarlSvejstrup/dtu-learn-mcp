import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from dtulearn import clients, paths


@pytest.fixture
def which(monkeypatch):
    table = {}
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: table.get(name))
    return table


def test_mcp_entry_python_fallback(dl, which):
    assert clients.mcp_entry() == {"command": sys.executable, "args": ["-m", "dtulearn", "mcp"],
                                   "env": {"DTU_LEARN_HOME": str(dl.home)}}


def test_mcp_entry_installed_exe(dl, which):
    which["dtu-learn"] = "/opt/bin/dtu-learn"
    assert clients.mcp_entry() == {"command": "/opt/bin/dtu-learn", "args": ["mcp"],
                                   "env": {"DTU_LEARN_HOME": str(dl.home)}}


def test_mcp_entry_legacy_shim(dl, which, monkeypatch):
    which["uv"] = "/opt/bin/uv"
    monkeypatch.setenv("DTU_LEARN_SHIM", "/repo/dtu_learn.py")
    e = clients.mcp_entry()
    assert e["command"] == "/opt/bin/uv"
    assert e["args"] == ["run", "--directory", "/repo", "dtu_learn.py", "mcp"]


def test_merge_json_keeps_other_servers_and_backs_up(tmp_path, which):
    which["dtu-learn"] = "/opt/bin/dtu-learn"
    cfg = tmp_path / "claude_desktop_config.json"
    original = {"theme": "dark", "mcpServers": {"other": {"command": "x", "args": []},
                                                "dtu-learn": {"command": "stale"}}}
    cfg.write_text(json.dumps(original))
    clients._merge_json(cfg)
    data = json.loads(cfg.read_text())
    assert data["theme"] == "dark"
    assert data["mcpServers"]["other"] == {"command": "x", "args": []}
    assert data["mcpServers"]["dtu-learn"] == clients.mcp_entry()
    assert json.loads((tmp_path / "claude_desktop_config.json.bak").read_text()) == original


def test_merge_json_new_and_empty_file(tmp_path, which):
    new = tmp_path / "deep" / ".cursor" / "mcp.json"
    clients._merge_json(new)
    assert set(json.loads(new.read_text())["mcpServers"]) == {"dtu-learn"}
    assert not new.with_suffix(".json.bak").exists()
    empty = tmp_path / "empty.json"
    empty.write_text("  \n")
    clients._merge_json(empty)
    assert "dtu-learn" in json.loads(empty.read_text())["mcpServers"]


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    h = tmp_path / "userhome"
    h.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: h))
    return h


def test_detect_all_present(fake_home, which, monkeypatch):
    monkeypatch.setattr(clients.platform, "system", lambda: "Darwin")
    which["claude"] = "/opt/bin/claude"
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    desktop = fake_home / "Library/Application Support/Claude/claude_desktop_config.json"
    desktop.parent.mkdir(parents=True)
    desktop.write_text(json.dumps({"mcpServers": {"dtu-learn": {}}}))
    (fake_home / ".cursor").mkdir()
    (fake_home / ".cursor/mcp.json").write_text(json.dumps({"mcpServers": {"other": {}}}))

    got = {c.name: (c.present, c.connected) for c in clients.detect()}
    assert got == {"Claude Code": (True, True), "Claude Desktop": (True, True), "Cursor": (True, False)}
    assert calls == [["/opt/bin/claude", "mcp", "get", "dtu-learn"]]


def test_detect_nothing_installed(fake_home, which, monkeypatch):
    monkeypatch.setattr(clients.platform, "system", lambda: "Linux")
    got = {c.name: (c.present, c.connected, c.detail) for c in clients.detect()}
    assert got["Claude Code"][:2] == (False, False)          # no claude binary: subprocess never called
    assert got["Claude Desktop"] == (False, False, str(fake_home / ".config/Claude/claude_desktop_config.json"))
    assert got["Cursor"][:2] == (False, False)


def test_detect_claude_not_connected_and_broken_json(fake_home, which, monkeypatch):
    monkeypatch.setattr(clients.platform, "system", lambda: "Linux")
    which["claude"] = "/opt/bin/claude"
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr=""))
    cfg = fake_home / ".config/Claude/claude_desktop_config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("{not json")
    got = {c.name: (c.present, c.connected) for c in clients.detect()}
    assert got["Claude Code"] == (True, False)
    assert got["Claude Desktop"] == (True, False)
