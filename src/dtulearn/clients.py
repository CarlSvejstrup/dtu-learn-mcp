"""Connect the dtu-learn MCP server to AI apps: Claude Code, Claude Desktop, Cursor."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .paths import HOME, self_command

SERVER = "dtu-learn"


def mcp_entry() -> dict:
    cmd = self_command() + ["mcp"]
    return {"command": cmd[0], "args": cmd[1:], "env": {"DTU_LEARN_HOME": str(HOME)}}


def _claude_desktop_config() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
    if system == "Windows":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "Claude/claude_desktop_config.json"
    return Path.home() / ".config/Claude/claude_desktop_config.json"


@dataclass
class Client:
    name: str
    present: bool
    connected: bool
    detail: str = ""


def _json_client(name: str, path: Path, present: bool) -> Client:
    connected = False
    if path.exists():
        try:
            connected = SERVER in (json.loads(path.read_text() or "{}").get("mcpServers") or {})
        except ValueError:
            pass
    return Client(name, present, connected, str(path))


def plugin_enabled() -> bool:
    """True when the dtu-learn Claude Code plugin is enabled (it brings its own MCP server)."""
    for f in (Path.home() / ".claude/settings.json", Path.home() / ".claude/settings.local.json"):
        try:
            enabled = json.loads(f.read_text()).get("enabledPlugins") or {}
        except (OSError, ValueError):
            continue
        if any(k.split("@")[0] == SERVER and v for k, v in enabled.items()):
            return True
    return False


def detect() -> list[Client]:
    out = []
    claude = shutil.which("claude")
    connected, detail = False, "claude mcp (user scope)"
    if claude and plugin_enabled():
        connected, detail = True, "via the dtu-learn plugin"
    elif claude:
        # User-scope entry, or the plugin loaded from a folder (CLAUDE_CODE_PLUGIN_DIRS / --plugin-dir).
        for name, how in ((SERVER, detail), (f"plugin:{SERVER}:{SERVER}", "via the dtu-learn plugin")):
            r = subprocess.run([claude, "mcp", "get", name], capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                connected, detail = True, how
                break
    out.append(Client("Claude Code", bool(claude), connected, detail))
    desktop = _claude_desktop_config()
    out.append(_json_client("Claude Desktop", desktop, desktop.parent.exists()))
    cursor = Path.home() / ".cursor/mcp.json"
    out.append(_json_client("Cursor", cursor, cursor.parent.exists()))
    return out


def _merge_json(path: Path) -> None:
    data = {}
    if path.exists():
        raw = path.read_text()
        data = json.loads(raw) if raw.strip() else {}
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    data.setdefault("mcpServers", {})[SERVER] = mcp_entry()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def connect(name: str, replace: bool = False) -> str:
    if name == "Claude Code":
        e = mcp_entry()
        claude = shutil.which("claude") or "claude"
        if replace:
            subprocess.run([claude, "mcp", "remove", "-s", "user", SERVER], capture_output=True, timeout=60)
        # Name first: -e takes several values and would swallow the name.
        cmd = [claude, "mcp", "add", SERVER, "-s", "user", "-e", f"DTU_LEARN_HOME={HOME}",
               "--", e["command"], *e["args"]]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or r.stdout.strip())
        return "Claude Code: connected (start a new session to see the tools)."
    if name == "Claude Desktop":
        _merge_json(_claude_desktop_config())
        return "Claude Desktop: connected (quit and reopen the app)."
    if name == "Cursor":
        _merge_json(Path.home() / ".cursor/mcp.json")
        return "Cursor: connected (reload the window)."
    raise ValueError(name)
