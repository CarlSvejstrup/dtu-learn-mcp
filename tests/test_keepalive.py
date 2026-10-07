import json
import os
from types import SimpleNamespace

import httpx


def _state(dl):
    dl.paths.ensure_home()
    dl.core.STATE.write_text(json.dumps({"cookies": [
        {"name": "d2lSessionVal", "value": "old", "domain": "learn.inside.dtu.dk", "path": "/"}]}))


def _fake_get(dl, monkeypatch, status, cookies=None, calls=None):
    def get(url, **kw):
        if calls is not None:
            calls.append(url)
        r = httpx.Response(status, request=httpx.Request("GET", url))
        for name, value in (cookies or {}).items():
            r.cookies.set(name, value, domain="learn.inside.dtu.dk")
        return r
    monkeypatch.setattr(dl.core.httpx, "get", get)


def test_alive_keeps_window_and_renewed_cookie(dl, monkeypatch):
    _state(dl)
    _fake_get(dl, monkeypatch, 200, {"d2lSessionVal": "new"})
    assert dl.core.keepalive() is True
    k = json.loads(dl.core.KEEPALIVE.read_text())
    first = k["alive_since"]
    assert json.loads(dl.core.STATE.read_text())["cookies"][0]["value"] == "new"
    assert dl.core.keepalive() is True
    assert json.loads(dl.core.KEEPALIVE.read_text())["alive_since"] == first


def test_expired_is_recorded_and_not_pinged_again_until_login(dl, monkeypatch):
    _state(dl)
    os.utime(dl.core.STATE, (1, 1))  # saved long before
    calls = []
    _fake_get(dl, monkeypatch, 302, calls=calls)
    assert dl.core.keepalive() is False
    assert "dead_at" in json.loads(dl.core.KEEPALIVE.read_text())
    assert dl.core.keepalive() is None and len(calls) == 1
    _state(dl)  # a new login rewrites state.json
    _fake_get(dl, monkeypatch, 200, calls=calls)
    assert dl.core.keepalive() is True and len(calls) == 2


def test_no_network_changes_nothing(dl, monkeypatch):
    _state(dl)
    def boom(url, **kw):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(dl.core.httpx, "get", boom)
    assert dl.core.keepalive() is None
    assert not dl.core.KEEPALIVE.exists()


def test_skips_while_a_refresh_holds_the_lock(dl, monkeypatch):
    _state(dl)
    lock = dl.core._take_lock()
    try:
        assert dl.core.keepalive() is None
    finally:
        lock.close()


def test_no_session_no_call(dl):
    assert dl.core.keepalive() is None
