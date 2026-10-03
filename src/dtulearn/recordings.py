"""Lecture recordings from Panopto (DTU's video platform): list them per course and save their captions as text.

Read-only and text-only: it fetches what the Panopto web player itself fetches (session list, delivery info,
caption file) with the user's own browser session. It never downloads audio or video.

Each DTU Learn course has a Panopto folder with exactly the course's DTU Learn name, e.g.
"02456 Deep learning, Fall 2026". Output per course:
- recordings/recordings.json  index of every recording (also those without captions yet)
- recordings/<date> <name>.md  chapters + transcript in ~30 s blocks with [h:mm:ss] timestamps
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PANOPTO = "https://dtu.cloud.panopto.eu"
AREA = "recordings"
INDEX = "recordings.json"
BLOCK_SECONDS = 30
PAUSE = 0.3  # seconds between requests: one at a time, gently
LANGUAGES = {0: "English", 16: "Danish"}  # Panopto language ids seen at DTU
CPH = ZoneInfo("Europe/Copenhagen")


class PanoptoLoginNeeded(Exception):
    """Panopto did not accept the DTU session."""


# ---------------------------------------------------------------- pure helpers


def ms_date(s: str | None) -> datetime | None:
    """'/Date(1788181345000)/' -> aware datetime."""
    m = re.search(r"-?\d+", s or "")
    return datetime.fromtimestamp(int(m.group()) / 1000, tz=timezone.utc) if m else None


def fmt_ts(seconds: float) -> str:
    s = int(seconds)
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def parse_ts(s: str) -> float:
    """'1:02:03', '02:03' or '123' -> seconds."""
    parts = [float(p) for p in s.strip().split(":")]
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


_SRT_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def parse_srt(text: str) -> list[tuple[float, float, str]]:
    cues = []
    for chunk in re.split(r"\n\s*\n", text.replace("\r", "").strip()):
        lines = chunk.split("\n")
        for i, line in enumerate(lines):
            m = _SRT_TIME.search(line)
            if m:
                g = [int(x) for x in m.groups()]
                start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                words = " ".join(x.strip() for x in lines[i + 1:] if x.strip())
                if words:
                    cues.append((start, end, words))
                break
    return cues


def blocks(cues: list[tuple[float, float, str]], every: int = BLOCK_SECONDS) -> list[tuple[float, str]]:
    """Merge caption cues into paragraphs that start at least `every` seconds apart."""
    out: list[tuple[float, list[str]]] = []
    for start, _, words in cues:
        if words.startswith("[Auto-generated transcript"):
            words = re.sub(r"^\[Auto-generated transcript[^\]]*\]\s*", "", words)
            if not words:
                continue
        if not out or start - out[-1][0] >= every:
            out.append((start, [words]))
        else:
            out[-1][1].append(words)
    return [(s, " ".join(ws)) for s, ws in out]


def norm(name: str) -> str:
    return re.sub(r"\s+", " ", name or "").strip().casefold()


_TERM = re.compile(r"\b(spring|fall|autumn|summer|january|june)\s*,?\s*(?:20)?(\d{2})\b", re.I)
_SEASON = {"autumn": "fall"}


def course_key(name: str) -> tuple[str, str] | None:
    """('02450', 'spring24') from '02450 Intro..., Spring 2024' or '02450 Intro... Spring 24'."""
    num = re.match(r"\s*(\d{5})\b", name or "")
    term = _TERM.search(name or "")
    if not (num and term):
        return None
    season = term.group(1).lower()
    return num.group(1), _SEASON.get(season, season) + term.group(2)


def match_folder(folders: list[dict], course_name: str) -> dict | None:
    """The Panopto folder for a DTU Learn course: same name (whitespace/case ignored), else
    same course number and term (older folders say 'Spring 24' and may spell the title differently)."""
    want = norm(course_name)
    hits = [f for f in folders if norm(f.get("Name")) == want]
    if not hits and (key := course_key(course_name)):
        hits = [f for f in folders if course_key(f.get("Name") or "") == key]
    return max(hits, key=lambda f: f.get("SessionCount") or 0) if hits else None


def safe(name: str) -> str:
    name = re.sub(r'[/\\:*?"<>|\x00-\x1f]', "_", name).strip(" .")
    return name[:150] or "untitled"


def file_name(rec: dict) -> str:
    d = ms_date(rec.get("start"))
    day = d.astimezone(CPH).strftime("%Y-%m-%d") if d else "undated"
    return f"{day} {safe(rec['name'])}.md"


def chapters(delivery: dict) -> list[tuple[float, str]]:
    """Chapter titles: Panopto's AI chapters, else slide titles it read from the screen."""
    ai = [(c.get("Start") or 0, c["Summary"].strip()) for c in delivery.get("AIChapters") or [] if c.get("Summary")]
    if ai:
        return sorted(ai)
    ocr = [(t.get("Time") or 0, (t.get("Caption") or "").strip()) for t in delivery.get("Timestamps") or []
           if t.get("EventTargetType") == "SmartOcrToc" and (t.get("Caption") or "").strip()]
    return sorted(ocr)


def render(rec: dict, course: str, chaps: list[tuple[float, str]], paras: list[tuple[float, str]]) -> str:
    d = ms_date(rec.get("start"))
    when = d.astimezone(CPH).strftime("%a %Y-%m-%d %H:%M") if d else "no date"
    lang = LANGUAGES.get(rec.get("language"), f"language id {rec.get('language')}")
    head = [f"# {rec['name']}", "",
            f"{course} | {when} | {round((rec.get('duration') or 0) / 60)} min | captions: {lang}",
            f"Panopto: {rec['url']}", "",
            "Captions are Panopto's automatic speech recognition unless the teacher edited them. "
            "Personal study use only: do not share recordings or transcripts outside the course.", ""]
    if chaps:
        head += ["## Chapters", ""] + [f"- [{fmt_ts(s)}] {t}" for s, t in chaps] + [""]
    head += ["## Transcript", ""] + [f"[{fmt_ts(s)}] {t}\n" for s, t in paras]
    return "\n".join(head).rstrip() + "\n"


def transcript_slice(text: str, start: float | None, end: float | None) -> str:
    """Keep the header and only the transcript blocks between start and end (seconds)."""
    if start is None and end is None:
        return text
    head, sep, body = text.partition("## Transcript")
    keep = []
    for para in body.strip().split("\n\n"):
        m = re.match(r"\[([\d:]+)\]", para.strip())
        if not m:
            continue
        t = parse_ts(m.group(1))
        if (start is None or t >= start) and (end is None or t <= end):
            keep.append(para.strip())
    return head + sep + "\n\n" + "\n\n".join(keep) + "\n"


# ---------------------------------------------------------------- Panopto (web player endpoints)


class Panopto:
    """Panopto through a Playwright browser context that holds the user's DTU login."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.rq = ctx.request

    def ensure_login(self) -> None:
        """Panopto signs in silently through the DTU login when its own cookie is missing or old."""
        page = self.ctx.new_page()
        try:
            page.goto(f"{PANOPTO}/Panopto/Pages/Auth/Login.aspx?ReturnUrl=%2FPanopto%2FPages%2FHome.aspx",
                      wait_until="domcontentloaded", timeout=60_000)
            try:
                page.wait_for_url(re.compile(r"panopto\.eu/Panopto/Pages/Home\.aspx"), timeout=30_000)
            except Exception:  # noqa: BLE001 - checked below
                pass
        finally:
            page.close()
        if not any(c["name"] == ".ASPXAUTH" for c in self.ctx.cookies(PANOPTO)):
            raise PanoptoLoginNeeded("Panopto did not accept the DTU login. Run: dtu-learn login")

    def _sleep(self):
        time.sleep(PAUSE)

    def folders(self) -> list[dict]:
        r = self.rq.get(f"{PANOPTO}/Panopto/Api/Folders?parentId=null&folderSet=1&includeMyFolder=false"
                        "&includePersonalFolders=true&page=0&sort=Depth&names[0]=SessionCount")
        self._sleep()
        if not r.ok:
            raise RuntimeError(f"Panopto folder list failed: HTTP {r.status}")
        return r.json()

    def sessions(self, folder_id: str) -> list[dict]:
        rows, page = [], 0
        while True:
            body = {"queryParameters": {
                "query": None, "sortColumn": 1, "sortAscending": True, "maxResults": 100, "page": page,
                "startDate": None, "endDate": None, "folderID": folder_id, "bookmarked": False,
                "getFolderData": False, "isSharedWithMe": False, "isSubscriptionsPage": False,
                "includeArchived": True, "includeArchivedStateCount": False, "sessionListOnlyArchived": False,
                "includePlaylists": True}}
            r = self.rq.post(f"{PANOPTO}/Panopto/Services/Data.svc/GetSessions", data=body,
                             headers={"Content-Type": "application/json"})
            self._sleep()
            if not r.ok:
                raise RuntimeError(f"Panopto session list failed: HTTP {r.status}")
            d = r.json()["d"]
            rows += d["Results"]
            if len(d["Results"]) < 100 or len(rows) >= (d.get("TotalNumber") or 0):
                return rows
            page += 1

    def delivery(self, delivery_id: str) -> dict:
        r = self.rq.post(f"{PANOPTO}/Panopto/Pages/Viewer/DeliveryInfo.aspx",
                         form={"deliveryId": delivery_id, "responseType": "json"})
        self._sleep()
        d = r.json() if r.ok else {}
        if "Delivery" not in d:
            raise RuntimeError(f"Panopto delivery info failed for {delivery_id}: {d.get('ErrorMessage') or r.status}")
        return d["Delivery"]

    def captions(self, delivery_id: str, language: int) -> str:
        r = self.rq.get(f"{PANOPTO}/Panopto/Pages/Transcription/GenerateSRT.ashx?id={delivery_id}&language={language}")
        self._sleep()
        return r.text() if r.ok else ""


# ---------------------------------------------------------------- per course


def record_of(row: dict) -> dict:
    return {"id": row["DeliveryID"], "name": (row.get("SessionName") or "untitled").strip(),
            "start": row.get("StartTime"), "duration": row.get("Duration"),
            "has_captions": bool(row.get("HasCaptions")),
            "url": row.get("ViewerUrl") or f"{PANOPTO}/Panopto/Pages/Viewer.aspx?id={row['DeliveryID']}"}


def sync_course(pan: Panopto, course_name: str, root: Path, folders: list[dict], force: bool = False) -> list[str]:
    """Update <root>/recordings for one course. Returns change lines for CHANGES.md."""
    folder = match_folder(folders, course_name)
    if not folder:
        return []
    rows = [r for r in pan.sessions(folder["Id"]) if r.get("DeliveryID")]
    if not rows:
        return []
    area = root / AREA
    area.mkdir(parents=True, exist_ok=True)
    ipath = area / INDEX
    old = {r["id"]: r for r in (json.loads(ipath.read_text()) if ipath.exists() else [])}
    index, changes = [], []
    for row in rows:
        rec = record_of(row)
        prev = old.get(rec["id"], {})
        rec["file"] = prev.get("file")
        rec["language"] = prev.get("language")
        have = rec["file"] and (area / rec["file"]).exists()
        if rec["has_captions"] and (force or not have):
            try:
                dl = pan.delivery(rec["id"])
                langs = [c["Language"] for c in dl.get("AvailableCaptions") or []]
                srt = pan.captions(rec["id"], langs[0]) if langs else ""
                paras = blocks(parse_srt(srt))
            except Exception as e:  # noqa: BLE001 - one recording must not stop the rest
                print(f"    ! recording {rec['name']}: {e}", flush=True)
                paras = []
            if paras:
                rec["language"] = langs[0]
                rec["file"] = file_name(rec)
                (area / rec["file"]).write_text(render(rec, course_name, chapters(dl), paras))
                changes.append(f"recording transcript: {rec['file']}")
        elif rec["id"] not in old:
            changes.append(f"recording (no captions yet): {rec['name']}")
        index.append(rec)
    ipath.write_text(json.dumps(index, indent=2, ensure_ascii=False))
    n_txt = sum(1 for r in index if r.get("file"))
    print(f"    recordings: {len(index)} in Panopto, {n_txt} with transcript, {len(changes)} new", flush=True)
    return changes


def sync_courses(courses: list[tuple[str, Path]], force: bool = False) -> dict[str, list[str]]:
    """courses: (DTU Learn course name, course folder). Opens its own browser session."""
    from . import core

    report: dict[str, list[str]] = {}
    with core.sync_playwright() as pw:
        ctx = core.open_context(pw, headless=True)
        try:
            core.ensure_session(ctx)
            pan = Panopto(ctx)
            pan.ensure_login()
            folders = pan.folders()
            for name, root in courses:
                print(f"\n== recordings: {name}", flush=True)
                report[name] = sync_course(pan, name, root, folders, force)
        finally:
            ctx.close()
    return report


def cmd_recordings(args) -> None:
    from . import core

    out = Path(args.out).expanduser().resolve()
    api = core.D2L(core.session_client())
    enrolled = {e["OrgUnit"]["Id"]: e for e in api.enrollments()}
    if args.course:
        ids = args.course
    else:
        ids = [e["OrgUnit"]["Id"] for e in core.current_semester(list(enrolled.values()))]
    courses = []
    for i in ids:
        ou = enrolled.get(i, {}).get("OrgUnit")
        if not ou:
            print(f"Not enrolled in {i}, skipped")
            continue
        root = core.course_dir(out, ou)
        root.mkdir(parents=True, exist_ok=True)
        m = root / ".manifest.json"
        if not m.exists():  # so the MCP server sees the course even before a full scrape
            m.write_text(json.dumps({"ou": i}))
        courses.append((ou["Name"], root))
    report = sync_courses(courses, force=args.force)
    total = sum(len(v) for v in report.values())
    print(f"\nRecordings done: {total} new across {len(courses)} courses -> {out}")
