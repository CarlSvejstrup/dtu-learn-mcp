"""Where dtu-learn keeps its data. Everything lives under one home folder.

Default `~/.dtu-learn`. Override with the env var DTU_LEARN_HOME.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

HOME = Path(os.environ.get("DTU_LEARN_HOME") or Path.home() / ".dtu-learn").expanduser()
PROFILE = HOME / ".profile"          # browser profile (keeps the Microsoft SSO cookie)
STATE = HOME / "state.json"          # D2L session cookies, mode 600
OUT = Path(os.environ.get("DTU_LEARN_OUT") or HOME / "out").expanduser()
SYNC_CONFIG = HOME / "sync.json"
NOTIFY_CONFIG = HOME / "notify.json"  # optional {"ntfy_topic": "..."}: phone push for warnings
AFTER_REFRESH = HOME / "hooks" / "after-refresh"  # optional executable, run by `dtu-learn auto`
LAST_AUTO = HOME / ".last_auto"
AUTO_LOG = HOME / "auto.log"
STATUS = HOME / "STATUS.md"          # plain-language state of the automation, for you and for Claude
LOCK = HOME / ".refresh.lock"
PKG_PARENT = Path(__file__).resolve().parent.parent  # directory that contains the dtulearn package


def ensure_home() -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    try:
        HOME.chmod(0o700)
    except OSError:
        pass


def self_command() -> list[str]:
    """The command that starts this CLI again (for MCP configs and schedulers)."""
    shim = os.environ.get("DTU_LEARN_SHIM")  # set by the legacy `uv run dtu_learn.py` entry point
    if shim:
        uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
        return [uv, "run", "--directory", str(Path(shim).parent), Path(shim).name]
    exe = shutil.which("dtu-learn")
    if exe:
        return [exe]
    return [sys.executable, "-m", "dtulearn"]


def child_env() -> dict[str, str]:
    """Environment for `python -m dtulearn` subprocesses, so they find this package and data home."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in [str(PKG_PARENT), env.get("PYTHONPATH", "")] if p)
    env["DTU_LEARN_HOME"] = str(HOME)
    return env
