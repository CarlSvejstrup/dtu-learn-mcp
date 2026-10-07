"""`dtu-learn` command line."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .paths import OUT, SYNC_CONFIG

HELP = """Your DTU Learn courses on disk, in your notes, and in your AI assistant.

first time:   dtu-learn setup
everyday:     ask your AI assistant, or: dtu-learn scrape --current
health check: dtu-learn doctor
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dtu-learn", description=HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"dtu-learn {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="command")

    st = sub.add_parser("setup", help="guided first run: login, courses, download, connect AI apps, schedule")
    st.add_argument("--yes", "-y", action="store_true", help="accept the default answer to every question (the optional schedule stays off)")
    st.add_argument("--no-clients", action="store_true", help="do not connect AI apps")
    st.add_argument("--no-schedule", action="store_true", help="do not offer the auto-refresh schedule")
    st.add_argument("--schedule", action="store_true", help="also install the optional daily auto-refresh")

    lg = sub.add_parser("login", help="open a browser and log in to DTU Learn (DTU login + MFA)")
    lg.add_argument("--timeout", type=int, default=300, help="seconds to wait for you to finish (default 300)")

    s = sub.add_parser("status", help="login, last refresh, courses, schedule")
    s.add_argument("--json", action="store_true")
    s.add_argument("--offline", action="store_true", help="do not check the session (faster)")

    sub.add_parser("doctor", help="check everything and print how to fix problems")

    cn = sub.add_parser("connect", help="connect the MCP server to Claude Code, Claude Desktop and Cursor")
    cn.add_argument("app", nargs="?", choices=["claude-code", "claude-desktop", "cursor"])
    cn.add_argument("--force", action="store_true", help="rewrite the entry even if it exists")

    c = sub.add_parser("courses", help="list your enrolments")
    c.add_argument("--all-types", action="store_true", help="include groups, departments etc.")
    c.add_argument("--current", action="store_true", help="only this semester's courses")

    sc = sub.add_parser("scrape", help="download content, announcements, assignments, grades, linked PDFs")
    sc.add_argument("--current", action="store_true", help="this semester's courses")
    sc.add_argument("--course", type=int, nargs="+", help="org unit id(s), e.g. 338557")
    sc.add_argument("--all", action="store_true", help="every active course offering")
    sc.add_argument("--include-inactive", action="store_true")
    sc.add_argument("--out", default=str(OUT))
    sc.add_argument("--force", action="store_true", help="re-download files already downloaded")
    sc.add_argument("--no-linked", action="store_true", help="skip PDFs linked from course pages")
    sc.add_argument("--no-text", action="store_true", help="skip extracting PDF text for search")
    sc.add_argument("--no-recordings", action="store_true", help="skip lecture recording transcripts (Panopto)")
    sc.add_argument("--sync", action="store_true", help="run sync after the download")
    sc.add_argument("--dry-run", action="store_true", help="with --sync: only show what would be copied")
    sc.add_argument("--config", default=str(SYNC_CONFIG))
    sc.add_argument("--no-vault", action="store_true", help="with --sync: only copy files")

    rc = sub.add_parser("recordings", help="lecture recordings from Panopto: list them, save their captions as text")
    rc.add_argument("--course", type=int, nargs="+", help="org unit id(s); default: this semester's courses")
    rc.add_argument("--out", default=str(OUT))
    rc.add_argument("--force", action="store_true", help="fetch transcripts again even if saved")

    y = sub.add_parser("sync", help="copy downloaded files into your own folders (sync.json)")
    y.add_argument("--config", default=str(SYNC_CONFIG))
    y.add_argument("--out", default=str(OUT))
    y.add_argument("--dry-run", action="store_true", help="only show what would be copied")
    y.add_argument("--no-vault", action="store_true", help="only copy files: no announcements.md / backlog deadlines")

    sch = sub.add_parser("schedule", help="auto-refresh once a day (launchd, cron or Task Scheduler)")
    sch.add_argument("action", choices=["install", "remove", "status"])
    sch.add_argument("--hour", type=int, default=7, help="hour of the daily check (default 7, i.e. 07:30)")

    au = sub.add_parser("auto", help="what the schedule runs: refresh when 12 h have passed, then notify")
    au.add_argument("--now", action="store_true", help="ignore the 12 h check")

    sub.add_parser("keepalive", help="what the schedule runs every hour: keep the saved DTU Learn session alive")
    sub.add_parser("mcp", help="run the MCP server over stdio (your AI app starts this)")
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.cmd == "scrape" and not (args.course or args.all or args.current):
        build_parser().error("scrape needs --current, --course ID... or --all")
    if args.cmd == "mcp":
        from .mcp_server import main as mcp_main
        return mcp_main()

    from . import core, recordings, schedule, wizard

    handlers = {
        "setup": wizard.cmd_setup, "login": core.cmd_login, "status": wizard.cmd_status, "doctor": wizard.cmd_doctor,
        "connect": wizard.cmd_connect, "courses": core.cmd_courses, "scrape": core.cmd_scrape, "sync": core.cmd_sync,
        "recordings": recordings.cmd_recordings,
        "auto": core.cmd_auto, "keepalive": core.cmd_keepalive,
        "schedule": lambda a: print({"install": lambda: schedule.install(a.hour), "remove": schedule.remove,
                                     "status": schedule.status}[a.action]()),
    }
    try:
        handlers[args.cmd](args)
    except (core.SessionExpired, recordings.PanoptoLoginNeeded) as e:
        sys.exit(f"\n{e}")
    except core.NoBrowser as e:
        sys.exit(f"\n{e}")
    except KeyboardInterrupt:
        sys.exit("\nStopped.")


if __name__ == "__main__":
    main()
