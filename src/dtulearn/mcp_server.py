"""Local stdio MCP server over your downloaded DTU Learn data.

Started by your AI app as `dtu-learn mcp`. Reads ~/.dtu-learn/out. Only `refresh` and `login`
talk to DTU Learn, by running the CLI as a subprocess.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import os
import re
import shutil
import sys
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP

from . import recordings as rec
from . import textcache
from .paths import HOME, OUT as _OUT, STATE, child_env

OUT = _OUT.resolve() if _OUT.exists() else _OUT
CPH = ZoneInfo("Europe/Copenhagen")
CACHE_DIR = textcache.CACHE_DIR
FILE_AREAS = ("content", "assignments", "linked", "announcements", rec.AREA)
SKIP_NAMES = {"toc.json", "news.json", "folders.json", "my_submissions.json", "grades.json",
              ".manifest.json", ".DS_Store", rec.INDEX}
TEXT_EXT = {".md", ".txt", ".py", ".html", ".htm", ".csv", ".tex", ".json", ".jsonl", ".ipynb",
            ".r", ".m", ".c", ".h", ".s", ".asm", ".java", ".js", ".ts", ".yaml", ".yml", ".sql"}
SEARCH_EXT = {".pdf", ".md", ".txt", ".py"}
MAX_TEXT_BYTES = 5_000_000
REFRESH_TIMEOUT = 600
LOGIN_TIMEOUT = 300
NEED_DATA = "No downloaded courses yet. Call the `login` tool if needed, then `refresh`."

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dtu-learn-mcp")
logging.getLogger("pypdf").setLevel(logging.ERROR)

mcp = FastMCP("dtu-learn", instructions=(
    "Your DTU Learn courses (Brightspace at DTU): deadlines, announcements, slides, assignments. "
    "Start with `status` when data may be stale; `refresh` downloads news; `login` opens a browser for DTU login + MFA. "
    "Times are Europe/Copenhagen. Cite file and page when you use slide content. "
    "Lecture recordings (Panopto) come as transcripts: list_recordings, get_transcript; cite the timestamp."))


# ---------------------------------------------------------------- helpers


class _Text(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.href: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")
        if tag == "a":
            self.href = dict(attrs).get("href")

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            self.parts.append(f" ({self.href})")
            self.href = None
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(s: str | None) -> str:
    if not s:
        return ""
    p = _Text()
    p.feed(s)
    text = html.unescape("".join(p.parts)).replace("\xa0", " ").replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def fmt_dt(s: str | None) -> str:
    d = parse_dt(s)
    return d.astimezone(CPH).strftime("%a %Y-%m-%d %H:%M") if d else "no date"


def read_json(p: Path, default=None):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return default


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


class Course:
    def __init__(self, path: Path):
        self.path = path
        self.dir = path.name
        self.ou = (read_json(path / ".manifest.json", {}) or {}).get("ou")
        first, _, rest = self.dir.partition(" ")
        num = re.search(r"(?<!\d)(\d{5})(?!\d)", self.dir)
        self.number = num.group(1) if num else None
        self.name = re.sub(rf"^{self.number}\s+", "", rest) if self.number else rest or first
        self.code = self.number or (self.name.split()[0] if self.name else first)

    @property
    def label(self) -> str:
        return f"{self.code} {self.name}"

    def files(self) -> list[Path]:
        out = []
        for area in FILE_AREAS:
            base = self.path / area
            if base.is_dir():
                out += [f for f in base.rglob("*") if f.is_file() and f.name not in SKIP_NAMES]
        return sorted(out)

    def news(self) -> list[dict]:
        return read_json(self.path / "announcements" / "news.json", []) or []

    def folders(self) -> list[dict]:
        return read_json(self.path / "assignments" / "folders.json", []) or []

    def recordings(self) -> list[dict]:
        return read_json(self.path / rec.AREA / rec.INDEX, []) or []


def courses() -> list[Course]:
    if not OUT.is_dir():
        return []
    return sorted((Course(p) for p in OUT.iterdir() if (p / ".manifest.json").exists()), key=lambda c: c.code)


def available(cs: list[Course]) -> str:
    return "; ".join(f"{c.label} (id {c.ou})" for c in cs) or "none yet (call `refresh`)"


def resolve(course: str | int | None) -> list[Course]:
    """None -> all courses. Otherwise exactly one course, or ValueError."""
    cs = courses()
    if course is None or str(course).strip() == "":
        if not cs:
            raise ValueError(NEED_DATA)
        return cs
    q = str(course).strip().lower()
    hits = [c for c in cs if q.isdigit() and (str(c.ou) == q or c.number == q)]
    if not hits:
        hits = [c for c in cs if q in c.dir.lower()]
    if len(hits) == 1:
        return hits
    if not hits:
        raise ValueError(f"No course matches {course!r}. Available: {available(cs)}")
    raise ValueError(f"{course!r} matches several courses: {available(hits)}. Be more specific.")


def one(course: str | int) -> Course:
    return resolve(course)[0]


def safe_path(c: Course, rel: str) -> Path:
    p = (c.path / rel).resolve()
    if p != c.path.resolve() and c.path.resolve() not in p.parents:
        raise ValueError("Path escapes the course folder.")
    if CACHE_DIR in p.relative_to(c.path.resolve()).parts:
        raise ValueError("That is the text cache, not course material.")
    if not p.is_file():
        raise ValueError(f"No such file in {c.label}: {rel}. Use list_files to see paths.")
    return p


# ---------------------------------------------------------------- text extraction


def pdf_pages(c: Course, p: Path) -> list[str]:
    """Page texts, from the shared cache under <course>/.text/ (filled by refresh)."""
    return textcache.pages(c.path, p)


def plain_text(p: Path) -> str | None:
    if p.suffix.lower() not in TEXT_EXT or p.stat().st_size > MAX_TEXT_BYTES:
        return None
    raw = p.read_bytes()
    if b"\x00" in raw[:4096]:
        return None
    return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- tools


@mcp.tool()
def list_courses() -> str:
    """List scraped DTU Learn courses: org unit id, course code, name, and counts of files, announcements, assignments."""
    cs = courses()
    if not cs:
        return NEED_DATA
    lines = [f"{len(cs)} courses (data in {OUT}):"]
    for c in cs:
        lines.append(f"- {c.code}  {c.name}  [id {c.ou}]  files: {len(c.files())}, "
                     f"announcements: {len(c.news())}, assignments: {len(c.folders())}")
    return "\n".join(lines)


@mcp.tool()
def whats_new() -> str:
    """What the last scrape found: new files, announcements, assignments, changed deadlines (out/CHANGES.md)."""
    p = OUT / "CHANGES.md"
    return p.read_text() if p.exists() else "No CHANGES.md yet. Run refresh first."


@mcp.tool()
def get_announcements(course: str | None = None, limit: int = 10, since: str | None = None) -> str:
    """Course announcements as plain text, newest first.

    course: org unit id, course number ("02132") or part of the name ("nlp"); omit for all courses.
    since: ISO date (e.g. "2026-09-20"); only announcements on or after it.
    """
    cs = resolve(course)
    cutoff = None
    if since:
        try:
            cutoff = date.fromisoformat(since[:10])
        except ValueError:
            raise ValueError(f"since must be an ISO date like 2026-09-20, got {since!r}") from None
    items = []
    for c in cs:
        for n in c.news():
            if n.get("IsHidden"):
                continue
            d = parse_dt(n.get("StartDate") or n.get("CreatedDate"))
            if cutoff and (not d or d.astimezone(CPH).date() < cutoff):
                continue
            items.append((d or datetime.min.replace(tzinfo=timezone.utc), c, n))
    items.sort(key=lambda x: x[0], reverse=True)
    if not items:
        return "No announcements" + (f" since {since}" if since else "") + "."
    out = []
    for d, c, n in items[: max(1, limit)]:
        body = html_to_text((n.get("Body") or {}).get("Html")) or (n.get("Body") or {}).get("Text", "").strip()
        att = [a["FileName"] for a in n.get("Attachments", [])]
        block = f"## {n.get('Title')}\n{c.label} | {fmt_dt(n.get('StartDate'))}\n\n{body}"
        if att:
            block += "\n\nAttachments: " + ", ".join(f"announcements/{n['Id']}/{a}" for a in att)
        out.append(block)
    more = f"\n\n({len(items) - limit} older not shown; raise limit)" if len(items) > limit else ""
    return "\n\n---\n\n".join(out) + more


@mcp.tool()
def get_deadlines(course: str | None = None, include_past: bool = False) -> str:
    """Assignment deadlines sorted by due date, in Copenhagen time, with your submission status.

    course: id, course number or name part; omit for all courses. include_past: also show passed deadlines.
    """
    now = datetime.now(timezone.utc)
    rows, undated = [], []
    for c in resolve(course):
        for f in c.folders():
            if f.get("IsHidden"):
                continue
            subs = read_json(c.path / "assignments" / re.sub(r'[/\\:*?"<>|\x00-\x1f]', "_", f["Name"]).strip(" .")[:180]
                             / "my_submissions.json", []) or []
            sent = [s.get("SubmissionDate") for e in subs for s in e.get("Submissions", [])]
            status = f"submitted {fmt_dt(max(sent))}" if sent else "not submitted"
            d = parse_dt(f.get("DueDate"))
            entry = (d, c, f, status)
            if d is None:
                undated.append(entry)
            elif include_past or d >= now:
                rows.append(entry)
    rows.sort(key=lambda r: r[0])
    lines = []
    for d, c, f, status in rows:
        tag = " (passed)" if d < now else ""
        lines.append(f"- {fmt_dt(f.get('DueDate'))}{tag} | {c.code} | {f['Name']} | {status}")
    for _, c, f, status in undated:
        lines.append(f"- no due date | {c.code} | {f['Name']} | {status}")
    if not lines:
        return "No upcoming deadlines." + ("" if include_past else " (include_past=true shows passed ones)")
    return "Times are Europe/Copenhagen.\n" + "\n".join(lines)


@mcp.tool()
def list_files(course: str, query: str | None = None) -> str:
    """Files downloaded for a course (content, assignments, linked PDFs), as paths relative to the course folder, with size.

    query: optional case-insensitive substring filter on the path.
    """
    c = one(course)
    q = (query or "").lower()
    files = [f for f in c.files() if q in str(f.relative_to(c.path)).lower()]
    if not files:
        return f"No files in {c.label}" + (f" matching {query!r}" if query else "") + "."
    lines = [f"{c.label}: {len(files)} files (folder: {c.path})"]
    lines += [f"- {f.relative_to(c.path)}  ({human_size(f.stat().st_size)})" for f in files]
    return "\n".join(lines)


@mcp.tool()
def read_file(course: str, path: str, max_chars: int = 20000,
              page_start: int | None = None, page_end: int | None = None) -> str:
    """Text of one course file (path as given by list_files). PDFs come with [page N] markers;
    page_start/page_end (1-based, inclusive) pick a page range. Output is cut at max_chars."""
    c = one(course)
    p = safe_path(c, path)
    rel = p.relative_to(c.path.resolve())
    if p.suffix.lower() == ".pdf":
        pages = pdf_pages(c, p)
        n = len(pages)
        a = max(1, page_start or 1)
        b = min(n, page_end or n)
        if a > n:
            return f"{rel} has {n} pages; page_start {a} is past the end."
        head = f"{rel} ({n} pages, showing {a}-{b})\n\n"
        text = head + "\n\n".join(f"[page {i}]\n{pages[i - 1].strip()}" for i in range(a, b + 1))
    else:
        t = plain_text(p)
        if t is None:
            return (f"{rel} is a {p.suffix or 'binary'} file ({human_size(p.stat().st_size)}) that cannot be read as text. "
                    f"Open it directly: {p}")
        text = f"{rel}\n\n{t}"
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[truncated at {max_chars} of {len(text)} chars; use page_start/page_end or raise max_chars]"
    return text


def _snippet(text: str, i: int, n: int, width: int = 90) -> str:
    s = text[max(0, i - width): i + n + width]
    s = re.sub(r"\s+", " ", s).strip()
    return ("..." if i > width else "") + s + ("..." if i + n + width < len(text) else "")


def _pattern(query: str, whole_word: bool) -> re.Pattern:
    """Whole words by default ("exam" does not hit "example"). A trailing * means prefix: "exam*"."""
    q = " ".join(query.split())  # collapse runs of whitespace: one \s+ between words
    prefix = q.endswith("*")
    body = re.escape(q.rstrip("*").strip())
    body = re.sub(r"\\\s+|\\ ", r"\\s+", body)  # any whitespace between words
    if not whole_word:
        return re.compile(body, re.I)
    return re.compile(rf"(?<!\w){body}" + ("" if prefix else r"(?!\w)"), re.I)


def _hits(text: str, pat: re.Pattern, cap: int = 2) -> list[str]:
    out, pos = [], 0
    while len(out) < cap:
        m = pat.search(text, pos)
        if not m:
            break
        out.append(_snippet(text, m.start(), m.end() - m.start()))
        pos = m.end() + 200
    return out


@mcp.tool()
def search(query: str, course: str | None = None, limit: int = 20) -> str:
    """Search announcements, assignment instructions, lecture recording transcripts, and the text of PDF, md, txt and py files.
    Whole words, case-insensitive ("exam" does not match "example"). End with * to match word starts:
    "exam*" matches exam, exams, examination and example.
    Returns where it matched (file and page for PDFs, timestamp for transcripts) with a snippet. course: id, number or name part; omit for all."""
    if not query.strip().rstrip("*").strip():
        raise ValueError("query is empty")
    out = _search(_pattern(query, True), course, limit)
    if out:
        return _fmt_results(query, out, limit)
    loose = _search(_pattern(query, False), course, limit)
    if loose:
        return f"No whole-word matches for {query!r}; these contain it inside other words:\n" + \
            _fmt_results(query, loose, limit).split("\n", 1)[1]
    return _fmt_results(query, [], limit)


def _search(q: re.Pattern, course: str | None, limit: int) -> list[str]:
    """Hits from course material and from lecture transcripts, collected apart so that neither crowds
    out the other: transcripts get up to a third of `limit`, and slots one side leaves empty go to the other."""
    material: list[str] = []
    talk: list[str] = []

    def add(where: str, snippets: list[str], bucket: list[str]) -> bool:
        for s in snippets:
            if len(bucket) >= limit:
                break
            bucket.append(f"- {where}\n  {s}")
        return len(material) >= limit and len(talk) >= limit

    def done() -> list[str]:
        n_talk = min(len(talk), max(limit // 3 or 1, limit - len(material)))
        return material[:limit - n_talk] + talk[:n_talk]

    for c in resolve(course):
        for n in c.news():
            text = f"{n.get('Title', '')}\n{html_to_text((n.get('Body') or {}).get('Html'))}"
            if add(f"{c.code} | announcement: {n.get('Title')} ({fmt_dt(n.get('StartDate'))})", _hits(text, q),
                   material):
                return done()
        for f in c.folders():
            text = f"{f['Name']}\n{html_to_text((f.get('CustomInstructions') or {}).get('Html'))}"
            if add(f"{c.code} | assignment instructions: {f['Name']}", _hits(text, q), material):
                return done()
        for p in c.files():
            ext = p.suffix.lower()
            if ext not in SEARCH_EXT:
                continue
            rel = p.relative_to(c.path)
            if rel.parts[0] in ("announcements", "assignments") and rel.name in ("announcements.md", "README.md"):
                continue  # generated copies of the announcements/instructions searched above
            if rel.parts[0] == rec.AREA:
                t = plain_text(p) or ""
                for para in t.partition("## Transcript")[2].split("\n\n"):
                    m = re.match(r"\s*\[([\d:]+)\]", para)
                    if m and add(f"{c.code} | {rel} (at {m.group(1)})", _hits(para, q, cap=1), talk):
                        return done()
                continue
            if ext == ".pdf":
                for i, page in enumerate(pdf_pages(c, p), 1):
                    if add(f"{c.code} | {rel} (page {i})", _hits(page, q, cap=1), material):
                        return done()
            else:
                t = plain_text(p)
                if t and add(f"{c.code} | {rel}", _hits(t, q), material):
                    return done()
    return done()


@mcp.tool()
def list_recordings(course: str | None = None) -> str:
    """Lecture recordings (Panopto) per course: date, title, length, and whether a transcript is saved.
    course: id, course number or name part; omit for all courses."""
    lines = []
    for c in resolve(course):
        rs = c.recordings()
        if not rs:
            continue
        lines.append(f"## {c.label}: {len(rs)} recordings")
        for r in rs:
            d = rec.ms_date(r.get("start"))
            when = d.astimezone(CPH).strftime("%a %Y-%m-%d") if d else "no date"
            mins = round((r.get("duration") or 0) / 60)
            txt = f"{rec.AREA}/{r['file']}" if r.get("file") else "no transcript yet"
            lines.append(f"- {when} | {r['name']} | {mins} min | {txt}")
    if not lines:
        return "No recordings saved. `refresh` fetches them from Panopto (only courses whose teacher records)."
    return "\n".join(lines)


@mcp.tool()
def get_transcript(course: str, recording: str, start: str | None = None, end: str | None = None,
                   max_chars: int = 40000) -> str:
    """Transcript of one lecture recording, with [h:mm:ss] timestamps and chapter titles.

    recording: part of the title or date ("week 4", "2026-09-21"), or its number in list_recordings (1 = oldest).
    start/end: optional time range like "12:00" or "1:05:00" to read only part of the lecture."""
    c = one(course)
    rs = [r for r in c.recordings() if r.get("file")]
    if not rs:
        raise ValueError(f"No transcripts saved for {c.label}. Call `refresh`, or list_recordings to check.")
    q = recording.strip().lower()
    if q.isdigit() and 1 <= int(q) <= len(c.recordings()):
        hits = [c.recordings()[int(q) - 1]]
    else:
        hits = [r for r in rs if q in r["name"].lower() or q in r["file"].lower()]
    if len(hits) != 1:
        names = "; ".join(r["file"] for r in (hits or rs))
        raise ValueError(f"{'Several' if hits else 'No'} recordings match {recording!r}: {names}")
    if not hits[0].get("file"):
        return f"{hits[0]['name']} has no transcript yet (Panopto has no captions for it)."
    p = safe_path(c, f"{rec.AREA}/{hits[0]['file']}")
    text = rec.transcript_slice(p.read_text(), rec.parse_ts(start) if start else None,
                                rec.parse_ts(end) if end else None)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[truncated at {max_chars} chars; use start/end to read a time range]"
    return text


def _fmt_results(query: str, results: list[str], limit: int) -> str:
    if not results:
        return f"No matches for {query!r}."
    tail = f"\n(stopped at limit={limit})" if len(results) >= limit else ""
    return f"{len(results)} matches for {query!r}:\n" + "\n".join(results) + tail


async def _run_cli(args: list[str], timeout: int) -> tuple[int | None, str]:
    cmd = [sys.executable, "-m", "dtulearn", *args]
    log.info("run: %s", " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd, env=child_env(), stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        raw, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return None, ""
    return proc.returncode, raw.decode(errors="replace")


@mcp.tool()
async def status() -> str:
    """Is the DTU Learn session valid, when was the last and next scheduled refresh, which courses are downloaded,
    and where the lecture page/video queue stands (STATUS.md from the scheduled run). Takes a few seconds."""
    from .paths import STATUS
    code, output = await _run_cli(["status"], 120)
    live = "Status check timed out." if code is None else output.strip()
    sched = STATUS.read_text().strip() if STATUS.exists() else "No scheduled run has written STATUS.md yet."
    return (live + "\n\n---\n\n" + sched +
            "\n\nIf 'Logged in' is no: call `login`. If the last refresh is old: call `refresh`.")


@mcp.tool()
async def login() -> str:
    """Open a browser window on the user's computer for DTU login + MFA, and wait (up to 5 min) until they finish.
    Tell the user to look for the window and complete the login there. Never ask for their password."""
    code, output = await _run_cli(["login", "--timeout", str(LOGIN_TIMEOUT)], LOGIN_TIMEOUT + 60)
    if code is None:
        return "Login timed out. Ask the user to try again and finish the DTU login in the browser window."
    last = output.strip().splitlines()[-1] if output.strip() else ""
    if code == 0:
        return last + "\nNow call `refresh` to download the latest course data."
    return f"Login did not finish: {last}"


@mcp.tool()
async def refresh(course: str | None = None) -> str:
    """Download the latest from DTU Learn (this semester, or one course) and return what changed. Takes up to a few minutes.
    course: id, course number or name part; omit for all of this semester's courses."""
    args = ["--course", str(one(course).ou)] if course else ["--current"]
    code, output = await _run_cli(["scrape", *args, "--out", str(OUT)], REFRESH_TIMEOUT)
    if code is None:
        return f"Refresh timed out after {REFRESH_TIMEOUT // 60} min and was stopped. Try one course at a time."
    if "session expired" in output.lower() or "dtu-learn login" in output:
        return "The DTU Learn session has expired. Call `login` (the user finishes DTU login + MFA in a browser window), then `refresh` again."
    if "No browser found" in output:
        return "No browser found on this computer. Ask the user to install Google Chrome, or run `dtu-learn setup`."
    tail = "\n".join(output.strip().splitlines()[-25:])
    state = "Refresh finished." if code == 0 else f"Refresh failed (exit code {code})."
    changes = (OUT / "CHANGES.md").read_text() if code == 0 and (OUT / "CHANGES.md").exists() else ""
    return f"{state}\n\nLast lines of output:\n{tail}" + (f"\n\n{changes}" if changes else "")


def main() -> None:
    log.info("dtu-learn MCP server, data dir %s (home %s, session file %s)", OUT, HOME,
             "present" if STATE.exists() else "missing")
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
