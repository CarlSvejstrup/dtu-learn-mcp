import plistlib
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from dtulearn import paths, schedule


@pytest.fixture
def exe(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: "/opt/bin/dtu-learn" if name == "dtu-learn" else None)
    return "/opt/bin/dtu-learn"


@pytest.fixture
def crontab(monkeypatch):
    """Fake `crontab -l` / `crontab -` with an in-memory table."""
    state = SimpleNamespace(lines=None, writes=[])

    def run(cmd, **kw):
        assert cmd[0] == "crontab", cmd
        if cmd[1] == "-l":
            if state.lines is None:
                return SimpleNamespace(returncode=1, stdout="", stderr="no crontab for user")
            return SimpleNamespace(returncode=0, stdout="\n".join(state.lines) + "\n", stderr="")
        assert cmd[1] == "-"
        state.writes.append(kw["input"])
        state.lines = kw["input"].splitlines()
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(schedule.platform, "system", lambda: "Linux")
    monkeypatch.setattr(subprocess, "run", run)
    return state


def marked(lines):
    return [l for l in lines if schedule.CRON_MARK in l]


def test_linux_install_replaces_old_line(dl, exe, crontab):
    crontab.lines = ["MAILTO=me", "0 * * * * backup.sh", f"30 7 * * * /old/dtu-learn auto {schedule.CRON_MARK}"]
    msg = schedule.install(8)
    assert "your crontab" in msg and "08:30" in msg
    assert crontab.lines[:2] == ["MAILTO=me", "0 * * * * backup.sh"]
    [line] = marked(crontab.lines)
    assert line == (f"30 8-22 * * * DTU_LEARN_HOME={dl.home} /opt/bin/dtu-learn auto "
                    f">> {dl.paths.AUTO_LOG} 2>&1 {schedule.CRON_MARK}")
    assert crontab.writes[-1].endswith("\n")
    assert dl.home.is_dir()   # ensure_home ran, in the tmp home

    schedule.install(9)
    assert len(marked(crontab.lines)) == 1 and marked(crontab.lines)[0].startswith("30 9-22 ")
    assert schedule.installed() is True


def test_linux_install_without_existing_crontab(dl, exe, crontab):
    schedule.install()
    assert len(crontab.lines) == 1 and crontab.lines[0].startswith("30 7-22 * * * ")


def test_linux_remove(dl, exe, crontab):
    crontab.lines = ["0 * * * * backup.sh"]
    schedule.install()
    assert schedule.remove() == "Removed the auto-refresh schedule."
    assert crontab.lines == ["0 * * * * backup.sh"]
    assert schedule.installed() is False


def test_linux_home_with_spaces_is_quoted(tmp_path, exe, crontab, monkeypatch):
    monkeypatch.setattr(schedule, "HOME", tmp_path / "my home")
    monkeypatch.setattr(schedule, "AUTO_LOG", tmp_path / "my home" / "auto.log")
    schedule.install()
    [line] = marked(crontab.lines)
    assert f"DTU_LEARN_HOME='{tmp_path / 'my home'}'" in line
    assert f">> '{tmp_path / 'my home' / 'auto.log'}' 2>&1" in line


@pytest.fixture
def launchd(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(schedule.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(schedule, "PLIST_DIR", tmp_path / "LaunchAgents")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(cmd) or SimpleNamespace(returncode=0))
    return calls


def test_darwin_install_writes_plist(dl, exe, launchd):
    legacy = schedule.PLIST_DIR / "dk.svejstrup.dtu-learn.plist"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("<plist/>")
    msg = schedule.install(6)
    plist = schedule.PLIST_DIR / f"{schedule.LABEL}.plist"
    assert str(plist) in msg
    assert not legacy.exists()
    assert ["launchctl", "unload", str(legacy)] in launchd
    assert launchd[-1] == ["launchctl", "load", str(plist)]
    data = plistlib.loads(plist.read_bytes())
    assert data["Label"] == schedule.LABEL
    assert data["ProgramArguments"] == paths.self_command() + ["auto"] == ["/opt/bin/dtu-learn", "auto"]
    assert data["StartCalendarInterval"] == [{"Hour": h, "Minute": 30} for h in range(6, 23)]
    assert data["EnvironmentVariables"]["DTU_LEARN_HOME"] == str(dl.home)
    assert data["StandardOutPath"] == str(dl.paths.AUTO_LOG)


def test_darwin_plist_escapes_xml(tmp_path, exe, launchd, monkeypatch):
    weird = tmp_path / "R&D <home>"
    monkeypatch.setattr(schedule, "HOME", weird)
    schedule.install()
    data = plistlib.loads((schedule.PLIST_DIR / f"{schedule.LABEL}.plist").read_bytes())
    assert data["EnvironmentVariables"]["DTU_LEARN_HOME"] == str(weird)


def test_darwin_remove(dl, exe, launchd):
    schedule.install()
    plist = schedule.PLIST_DIR / f"{schedule.LABEL}.plist"
    assert plist.exists()
    schedule.remove()
    assert not plist.exists()
    assert launchd[-1] == ["launchctl", "unload", str(plist)]
