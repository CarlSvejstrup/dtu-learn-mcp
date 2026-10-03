"""Run `dtu-learn auto` every day at a fixed hour: launchd (macOS), crontab (Linux), Task Scheduler (Windows).

`auto` itself decides whether 12 h have passed since the last refresh, so a missed or late morning still refreshes once.
"""

from __future__ import annotations

import platform
import shlex
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

from .paths import AUTO_LOG, HOME, LAST_AUTO, ensure_home, self_command

LABEL = "com.dtu-learn.auto"
LEGACY_LABELS = ("dk.svejstrup.dtu-learn",)
PLIST_DIR = Path.home() / "Library/LaunchAgents"
CRON_MARK = "# dtu-learn auto"
WIN_TASK = "dtu-learn-auto"


def _plist(label: str) -> Path:
    return PLIST_DIR / f"{label}.plist"


def install(hour: int = 7) -> str:
    ensure_home()
    cmd = self_command() + ["auto"]
    system = platform.system()
    if system == "Darwin":
        for old in (*LEGACY_LABELS, LABEL):
            if _plist(old).exists():
                subprocess.run(["launchctl", "unload", str(_plist(old))], capture_output=True)
                _plist(old).unlink()
        args = "".join(f"<string>{escape(a)}</string>" for a in cmd)
        PLIST_DIR.mkdir(parents=True, exist_ok=True)
        _plist(LABEL).write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key><array>{args}</array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>{hour}</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key><string>{escape(str(AUTO_LOG))}</string>
  <key>StandardErrorPath</key><string>{escape(str(AUTO_LOG))}</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:{escape(str(Path.home() / ".local/bin"))}:/usr/bin:/bin</string>
    <key>DTU_LEARN_HOME</key><string>{escape(str(HOME))}</string>
  </dict>
</dict></plist>
""")
        subprocess.run(["launchctl", "load", str(_plist(LABEL))], check=True)
        where = str(_plist(LABEL))
    elif system == "Linux":
        line = (f"30 {hour} * * * DTU_LEARN_HOME={shlex.quote(str(HOME))} {shlex.join(cmd)} "
                f">> {shlex.quote(str(AUTO_LOG))} 2>&1 {CRON_MARK}")
        _set_crontab([*_crontab_without_mark(), line])
        where = "your crontab"
    elif system == "Windows":
        tr = subprocess.list2cmdline(cmd)
        subprocess.run(["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST", f"{hour:02d}:30", "/TN", WIN_TASK,
                        "/TR", tr], check=True, capture_output=True)
        where = f"Task Scheduler task '{WIN_TASK}'"
    else:
        raise RuntimeError(f"Scheduling is not supported on {system}. Run `dtu-learn auto` yourself.")
    return f"Installed in {where}: checks daily at {hour:02d}:30 and refreshes once a day."


def remove() -> str:
    system = platform.system()
    if system == "Darwin":
        for label in (*LEGACY_LABELS, LABEL):
            if _plist(label).exists():
                subprocess.run(["launchctl", "unload", str(_plist(label))], capture_output=True)
                _plist(label).unlink()
    elif system == "Linux":
        _set_crontab(_crontab_without_mark())
    elif system == "Windows":
        subprocess.run(["schtasks", "/Delete", "/F", "/TN", WIN_TASK], capture_output=True)
    return "Removed the auto-refresh schedule."


def installed() -> bool:
    system = platform.system()
    if system == "Darwin":
        return any(subprocess.run(["launchctl", "list", label], capture_output=True).returncode == 0
                   for label in (LABEL, *LEGACY_LABELS))
    if system == "Linux":
        return any(CRON_MARK in l for l in _crontab())
    if system == "Windows":
        return subprocess.run(["schtasks", "/Query", "/TN", WIN_TASK], capture_output=True).returncode == 0
    return False


def status() -> str:
    last = LAST_AUTO.read_text().strip() if LAST_AUTO.exists() else "never"
    return f"{'installed' if installed() else 'not installed'} | last auto run: {last}"


def _crontab() -> list[str]:
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return r.stdout.splitlines() if r.returncode == 0 else []


def _crontab_without_mark() -> list[str]:
    return [l for l in _crontab() if CRON_MARK not in l]


def _set_crontab(lines: list[str]) -> None:
    subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True)
