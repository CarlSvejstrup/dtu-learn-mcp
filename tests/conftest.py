"""Shared fixtures. Offline only: no DTU Learn, no browser, no claude CLI, no crontab/launchctl.

DTU_LEARN_HOME is pointed at a throwaway folder *before* any dtulearn module is imported
(paths are computed at import time), and every test reloads the package against its own
tmp home, so nothing ever touches ~/.dtu-learn or the repo's out/.
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

_BOOT_HOME = Path(tempfile.mkdtemp(prefix="dtulearn-test-home-"))
os.environ["DTU_LEARN_HOME"] = str(_BOOT_HOME)
for _var in ("DTU_LEARN_OUT", "DTU_LEARN_SHIM"):
    os.environ.pop(_var, None)

from dtulearn import clients, cli, core, mcp_server, paths, schedule, vault  # noqa: E402

_REAL_HOME_DATA = (Path.home() / ".dtu-learn").resolve()


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_BOOT_HOME, ignore_errors=True)


def _blocked(name):
    def fail(*a, **k):
        raise AssertionError(f"test tried to call {name} for real: {a[:1]}")
    return fail


@pytest.fixture(autouse=True)
def dl(tmp_path, monkeypatch):
    """Fresh tmp DTU_LEARN_HOME, package reloaded against it, external calls blocked."""
    home = tmp_path / "dtu-home"
    monkeypatch.setenv("DTU_LEARN_HOME", str(home))
    monkeypatch.delenv("DTU_LEARN_OUT", raising=False)
    monkeypatch.delenv("DTU_LEARN_SHIM", raising=False)
    for mod in (paths, vault, core, clients, schedule, mcp_server, cli):
        importlib.reload(mod)
    assert paths.HOME == home and paths.OUT == home / "out"
    assert _REAL_HOME_DATA not in [paths.HOME.resolve(), *paths.HOME.resolve().parents]

    # Guard rails: anything that would leave the machine or spawn a process fails loudly.
    # Tests that need subprocess.run replace it again with their own fake.
    monkeypatch.setattr(subprocess, "run", _blocked("subprocess.run"))
    monkeypatch.setattr(subprocess, "Popen", _blocked("subprocess.Popen"))
    monkeypatch.setattr(core, "sync_playwright", _blocked("playwright"))
    monkeypatch.setattr(core.httpx.Client, "send", _blocked("httpx"))
    return SimpleNamespace(home=home, paths=paths, core=core, vault=vault, clients=clients,
                           schedule=schedule, mcp=mcp_server, cli=cli)


# ---------------------------------------------------------------- helpers


def write_json(p: Path, data) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return p


def _pdf_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[str]) -> bytes:
    """Minimal valid PDF with one line of Helvetica text per page (pypdf can extract it)."""
    n = len(pages)
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        ("<< /Type /Pages /Kids [" + " ".join(f"{4 + 2 * i} 0 R" for i in range(n)) + f"] /Count {n} >>").encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, text in enumerate(pages):
        content = f"BT /F1 12 Tf 72 720 Td ({_pdf_escape(text)}) Tj ET".encode()
        objs.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                     f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>").encode())
        objs.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


@pytest.fixture
def pdf_bytes():
    return make_pdf
