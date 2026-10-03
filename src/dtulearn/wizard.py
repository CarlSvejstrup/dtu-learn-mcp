"""`dtu-learn setup`, `status` and `doctor`: the guided first run and health checks."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime

from . import clients, core, schedule
from .paths import HOME, OUT, STATE, ensure_home

EXAMPLES = [
    "What are my deadlines this week?",
    "Summarise the new announcements in all my courses.",
    "What did the teacher say about the exam in 02132?",
    "Explain page 12 of the latest Deep Learning slides.",
    "Quiz me on this week's NLP lecture.",
]


def _ask(question: str, default: bool, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return default
    hint = "[Y/n]" if default else "[y/N]"
    ans = input(f"{question} {hint} ").strip().lower()
    return default if not ans else ans.startswith("y")


def _step(n: int, text: str) -> None:
    print(f"\n[{n}/6] {text}")


def _browser_ok(quiet: bool = False) -> bool:
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as pw:
            for channel in core.BROWSER_CHANNELS:
                try:
                    pw.chromium.launch(channel=channel, headless=True).close()
                    if not quiet:
                        print(f"  ok: {channel or 'Playwright Chromium'}")
                    return True
                except Exception:  # noqa: BLE001
                    continue
    except Exception:  # noqa: BLE001
        pass
    return False


def _install_chromium() -> bool:
    print("  Installing Playwright Chromium (about 150 MB)...")
    return subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"]).returncode == 0


def cmd_setup(args) -> None:
    ensure_home()
    y = args.yes
    print(f"DTU Learn setup. Your data stays on this computer, in {HOME}")

    _step(1, "Browser")
    if not _browser_ok():
        print("  No Chrome or Edge found.")
        if not (_ask("  Install Playwright Chromium now?", True, y) and _install_chromium() and _browser_ok()):
            sys.exit("Setup needs a browser. Install Google Chrome, then run: dtu-learn setup")

    _step(2, "DTU login")
    me = core.whoami() if STATE.exists() else None
    if me:
        print(f"  Already logged in as {me.get('FirstName')} {me.get('LastName')} ({me.get('UniqueName')}).")
    else:
        print("  A browser window opens. Log in with your DTU account and finish MFA there.")
        print("  Your password goes only to DTU. dtu-learn saves the session cookie, never your password.")
        me = core.login()
        print(f"  Logged in as {me.get('FirstName')} {me.get('LastName')} ({me.get('UniqueName')}).")

    _step(3, "Courses")
    api = core.D2L(core.session_client())
    current = core.current_semester(api.enrollments())
    if not current:
        sys.exit("No courses found for this semester. Run `dtu-learn courses` to see all enrolments.")
    for e in current:
        print(f"  - {e['OrgUnit']['Name']}  (id {e['OrgUnit']['Id']})")

    _step(4, "First download")
    if _ask(f"  Download these {len(current)} courses now? It takes about a minute.", True, y):
        core.cmd_scrape(core.scrape_args(sync=False))

    _step(5, "Connect your AI apps")
    if args.no_clients:
        print("  Skipped (--no-clients).")
    else:
        found = [c for c in clients.detect() if c.present]
        if not found:
            print("  No Claude Code, Claude Desktop or Cursor found. Connect later with: dtu-learn connect")
        for c in found:
            if c.connected:
                print(f"  {c.name}: already connected.")
            elif _ask(f"  Connect {c.name}?", True, y):
                try:
                    print("  " + clients.connect(c.name))
                except Exception as e:  # noqa: BLE001
                    print(f"  {c.name}: could not connect ({e}).")

    _step(6, "Auto-refresh")
    if args.no_schedule:
        print("  Skipped (--no-schedule).")
    elif schedule.installed():
        print("  Already on: " + schedule.status())
    elif _ask("  Refresh once a day in the background, with a notification when something is new?", True, y):
        try:
            print("  " + schedule.install())
        except Exception as e:  # noqa: BLE001
            print(f"  Could not install the schedule ({e}). Run `dtu-learn auto` yourself now and then.")

    print("\nDone. Ask your AI assistant, for example:")
    for q in EXAMPLES:
        print(f"  - {q}")
    print("\nCheck everything any time with: dtu-learn doctor")


def _last_refresh() -> str:
    p = OUT / "CHANGES.md"
    if not p.exists():
        return "never"
    t = datetime.fromtimestamp(p.stat().st_mtime)
    hours = (datetime.now() - t).total_seconds() / 3600
    return f"{t:%Y-%m-%d %H:%M} ({hours:.0f} h ago)"


def _course_dirs() -> list[str]:
    return sorted(m.parent.name for m in OUT.glob("*/.manifest.json")) if OUT.exists() else []


def status_dict(check_session: bool) -> dict:
    d = {"data_dir": str(HOME), "logged_in": None, "user": None, "last_refresh": _last_refresh(),
         "courses": _course_dirs(), "schedule": schedule.status()}
    if check_session:
        if not STATE.exists():
            d["logged_in"] = False
        else:
            me = core.whoami()
            d["logged_in"] = bool(me)
            d["user"] = f"{me.get('FirstName')} {me.get('LastName')} ({me.get('UniqueName')})" if me else None
    return d


def cmd_status(args) -> None:
    d = status_dict(check_session=not args.offline)
    if args.json:
        print(json.dumps(d, indent=2))
        return
    login = {True: f"yes, as {d['user']}", False: "no, run: dtu-learn login", None: "not checked"}[d["logged_in"]]
    print(f"Data dir:      {d['data_dir']}\nLogged in:     {login}\nLast refresh:  {d['last_refresh']}\n"
          f"Courses:       {len(d['courses'])}\nAuto-refresh:  {d['schedule']}")
    for c in d["courses"]:
        print(f"  - {c}")


def cmd_doctor(_args) -> None:
    problems = 0

    def check(ok: bool, label: str, fix: str = "") -> None:
        nonlocal problems
        print(f"{'ok ' if ok else 'FIX'}  {label}" + ("" if ok or not fix else f"\n     -> {fix}"))
        problems += not ok

    check(sys.version_info >= (3, 11), f"Python {sys.version.split()[0]}", "Install Python 3.11+ (uv does this for you).")
    check(HOME.exists(), f"Data dir {HOME}", "Run: dtu-learn setup")
    check(_browser_ok(quiet=True), "Browser (Chrome, Edge or Playwright Chromium)",
          "Install Google Chrome, or run: python -m playwright install chromium")
    me = core.whoami() if STATE.exists() else None
    check(bool(me), "DTU Learn session" + (f" ({me.get('UniqueName')})" if me else ""), "Run: dtu-learn login")
    n = len(_course_dirs())
    check(n > 0, f"Downloaded courses: {n}", "Run: dtu-learn scrape --current")
    last = _last_refresh()
    check(last != "never", f"Last refresh: {last}", "Run: dtu-learn scrape --current")
    apps = [c for c in clients.detect() if c.present]
    check(any(c.connected for c in apps), "Connected to an AI app: " +
          (", ".join(c.name for c in apps if c.connected) or "none"), "Run: dtu-learn connect")
    for c in apps:
        if not c.connected:
            print(f"--   {c.name} not connected (optional): dtu-learn connect {c.name.lower().replace(' ', '-')}")
    if schedule.installed():
        print("ok   Auto-refresh schedule")
    else:
        print("--   Auto-refresh is off (optional): dtu-learn schedule install")
    print(f"\n{'All good.' if not problems else f'{problems} thing(s) to fix.'}")


def cmd_connect(args) -> None:
    for c in clients.detect():
        if args.app and c.name.lower().replace(" ", "-") != args.app:
            continue
        if not c.present:
            print(f"{c.name}: not installed.")
        elif c.connected and not args.force:
            print(f"{c.name}: already connected.")
        else:
            try:
                print(clients.connect(c.name, replace=args.force))
            except Exception as e:  # noqa: BLE001
                print(f"{c.name}: could not connect ({e}).")
