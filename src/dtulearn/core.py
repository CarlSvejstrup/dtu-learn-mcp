"""Scraper core: DTU Learn session, Brightspace API client, scrape, sync and auto-run."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
import platform
import html
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import httpx
from playwright.sync_api import BrowserContext, sync_playwright

from . import recordings, textcache, vault
from .paths import AFTER_REFRESH, AUTO_LOG, HOME, LAST_AUTO, LOCK, OUT, PROFILE, STATE, STATUS, SYNC_CONFIG, child_env, ensure_home

BASE = "https://learn.inside.dtu.dk"
COURSE_OFFERING = 3
SEMESTER_WINDOW = timedelta(days=120)
WORKERS = 3  # DTU IT policy: "must not unnecessarily burden DTU's systems"; 3 parallel requests is gentle
URL_RE = re.compile(r"""https?://[^\s"'<>()\]\[]+|(?<=href=["'])/[^"']+""")
AUTO_EVERY = timedelta(hours=12)  # every morning; blocks a second refresh the same day
MAX_NEW_LECTURES = 4   # more new lecture folders than this in one run = a re-download, not new teaching: baseline them
HOOK_LIMIT = 2         # queued lectures the after-refresh hook may process per auto run (passed as --limit)
MAX_LOG_BYTES = 2_000_000
SYNC_SKIP = {"toc.json", "news.json", "folders.json", "my_submissions.json", "grades.json", ".manifest.json", ".DS_Store",
             "recordings.json"}
SKIP_HOSTS = ("youtube.com", "youtu.be", "panopto", "kaltura", "zoom.us", "teams.microsoft.com",
              "ids.brightspace.com", "forms.gle", "docs.google.com/forms")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


# ---------------------------------------------------------------- session


class SessionExpired(Exception):
    """The DTU Learn session is gone and could not be renewed without the user."""


class NoBrowser(Exception):
    """No usable Chrome, Edge or Playwright Chromium."""


BROWSER_CHANNELS = ("chrome", "msedge", None)  # None = Playwright's own Chromium


def open_context(pw, headless: bool) -> BrowserContext:
    ensure_home()
    errors = []
    for channel in BROWSER_CHANNELS:
        try:
            ctx = pw.chromium.launch_persistent_context(
                str(PROFILE), channel=channel, headless=headless, accept_downloads=True)
            break
        except Exception as e:  # noqa: BLE001 - try the next browser
            errors.append(f"{channel or 'chromium'}: {str(e).splitlines()[0]}")
    else:
        raise NoBrowser("No browser found. Install Google Chrome, or run: dtu-learn setup "
                        "(it can install Playwright Chromium).\n" + "\n".join(errors))
    # Chrome drops session cookies when it closes, so restore the saved ones.
    if STATE.exists():
        ctx.add_cookies(json.loads(STATE.read_text())["cookies"])
    return ctx


def save_state(ctx: BrowserContext) -> None:
    ctx.storage_state(path=str(STATE))
    STATE.chmod(0o600)


def logged_in(ctx: BrowserContext) -> bool:
    r = ctx.request.get(f"{BASE}/d2l/api/lp/1.0/users/whoami", fail_on_status_code=False)
    return r.ok


def ensure_session(ctx: BrowserContext) -> None:
    if logged_in(ctx):
        return
    # SSO cookies in the profile can often re-issue a D2L session silently.
    page = ctx.new_page()
    page.goto(f"{BASE}/d2l/login", wait_until="domcontentloaded")
    try:
        page.wait_for_url(re.compile(r"/d2l/home"), timeout=30_000)
    except Exception:
        pass
    page.close()
    if not logged_in(ctx):
        raise SessionExpired("Your DTU Learn session expired. Run: dtu-learn login")
    save_state(ctx)


def session_client() -> httpx.Client:
    """Validate/refresh the session in the browser, then hand the cookies to httpx."""
    with sync_playwright() as pw:
        ctx = open_context(pw, headless=True)
        ensure_session(ctx)
        cookies = ctx.cookies()
        ctx.close()
    jar = httpx.Cookies()
    for c in cookies:
        jar.set(c["name"], c["value"], domain=c["domain"], path=c["path"])
    limits = httpx.Limits(max_connections=WORKERS * 2, max_keepalive_connections=WORKERS * 2)
    return httpx.Client(cookies=jar, headers={"User-Agent": UA}, follow_redirects=True,
                        timeout=httpx.Timeout(30, read=120), limits=limits)


def whoami() -> dict | None:
    """Current user if the saved session works (renews it silently when possible), else None."""
    try:
        with sync_playwright() as pw:
            ctx = open_context(pw, headless=True)
            try:
                ensure_session(ctx)
                return ctx.request.get(f"{BASE}/d2l/api/lp/1.0/users/whoami").json()
            except SessionExpired:
                return None
            finally:
                ctx.close()
    except NoBrowser:
        raise
    except Exception:  # noqa: BLE001
        return None


def login(timeout_s: int = 300) -> dict:
    """Open a browser window, wait for the user to finish DTU login + MFA, save the session."""
    with sync_playwright() as pw:
        ctx = open_context(pw, headless=False)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(f"{BASE}/d2l/login")
            page.bring_to_front()
            log(f"Log in to DTU Learn in the browser window (DTU login + MFA). Waiting up to {timeout_s // 60} min...")
            try:
                page.wait_for_url(re.compile(r"learn\.inside\.dtu\.dk/d2l/home"), timeout=timeout_s * 1000)
            except Exception as e:  # noqa: BLE001
                raise SessionExpired("Login was not finished in time, or the window was closed. "
                                     "Run: dtu-learn login") from e
            if not logged_in(ctx):
                raise SessionExpired("Reached DTU Learn, but the API rejected the session. Try: dtu-learn login")
            save_state(ctx)
            return ctx.request.get(f"{BASE}/d2l/api/lp/1.0/users/whoami").json()
        finally:
            ctx.close()


def cmd_login(args) -> None:
    me = login(getattr(args, "timeout", 300))
    print(f"Logged in as {me.get('FirstName')} {me.get('LastName')} ({me.get('UniqueName')}). Session saved.")


# ---------------------------------------------------------------- API


class ApiError(Exception):
    def __init__(self, status: int, path: str):
        super().__init__(f"{status} {path}")
        self.status = status


class D2L:
    def __init__(self, client: httpx.Client):
        self.http = client
        self.pool = ThreadPoolExecutor(WORKERS)
        latest = {v["ProductCode"]: v["LatestVersion"] for v in self.get("/d2l/api/versions/")}
        self.lp = latest.get("lp", "1.30")
        self.le = latest.get("le", "1.50")

    def _req(self, url: str) -> httpx.Response:
        url = url if url.startswith("http") else BASE + url
        for attempt in range(4):
            try:
                r = self.http.get(url)
            except httpx.TransportError:
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
                continue
            if r.status_code in (429, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            return r
        return r

    def get(self, path: str):
        r = self._req(path)
        if not r.is_success:
            raise ApiError(r.status_code, path)
        return r.json()

    def try_get(self, path: str, label: str):
        try:
            return self.get(path)
        except ApiError as e:
            log(f"    - {label}: skipped ({e.status})")
            return None

    def download(self, path: str, dest_dir: Path, fallback_name: str) -> Path | None:
        try:
            r = self._req(path)
        except httpx.TransportError as e:
            log(f"    ! download failed ({type(e).__name__}): {fallback_name}")
            return None
        if not r.is_success:
            log(f"    ! download failed ({r.status_code}): {fallback_name}")
            return None
        name = filename_from_headers(r.headers) or fallback_name
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / safe(name)
        dest.write_bytes(r.content)
        return dest

    def enrollments(self) -> list[dict]:
        items, bookmark = [], ""
        while True:
            q = f"?bookmark={bookmark}" if bookmark else ""
            page = self.get(f"/d2l/api/lp/{self.lp}/enrollments/myenrollments/{q}")
            items += page["Items"]
            if not page["PagingInfo"]["HasMoreItems"]:
                return items
            bookmark = page["PagingInfo"]["Bookmark"]


def filename_from_headers(headers) -> str | None:
    cd = headers.get("content-disposition", "")
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd, re.I) or re.search(r'filename="?([^";]+)"?', cd, re.I)
    return unquote(m.group(1)) if m else None


def safe(name: str) -> str:
    name = re.sub(r'[/\\:*?"<>|\x00-\x1f]', "_", name).strip(" .")
    return name[:180] or "untitled"


# ---------------------------------------------------------------- courses


def start_of(e: dict) -> datetime | None:
    d = e["Access"].get("StartDate")
    return datetime.fromisoformat(d.replace("Z", "+00:00")) if d else None


def current_semester(enrollments: list[dict]) -> list[dict]:
    """Course offerings that started within SEMESTER_WINDOW of the newest one."""
    courses = [e for e in enrollments if e["OrgUnit"]["Type"]["Id"] == COURSE_OFFERING and start_of(e)]
    if not courses:
        return []
    newest = max(start_of(e) for e in courses)
    return [e for e in courses if start_of(e) >= newest - SEMESTER_WINDOW]


def course_dir(out: Path, ou: dict) -> Path:
    code = ou.get("Code") or str(ou["Id"])
    return out / safe(f"{code} {ou['Name']}")


# ---------------------------------------------------------------- scrape


def scrape_content(api: D2L, ou_id: int, root: Path, manifest: dict, force: bool, ch: list[str]) -> None:
    toc = api.try_get(f"/d2l/api/le/{api.le}/{ou_id}/content/toc", "content")
    if toc is None:
        return
    (root / "content").mkdir(parents=True, exist_ok=True)
    (root / "content" / "toc.json").write_text(json.dumps(toc, indent=2, ensure_ascii=False))
    links: list[str] = []
    seen = manifest.setdefault("topics", {})
    jobs: list[tuple[str, str, Path, str]] = []

    def walk(modules: list[dict], path: Path, depth: int) -> None:
        for m in modules:
            mdir = path / safe(m["Title"])
            links.append(f"{'#' * min(depth + 2, 6)} {m['Title']}\n")
            for t in m.get("Topics", []):
                tid, title = str(t["TopicId"]), t["Title"]
                stamp = t.get("LastModifiedDate") or ""
                if t.get("TypeIdentifier") == "Link" or not t.get("Url", "").startswith("/content/"):
                    url = t.get("Url", "")
                    links.append(f"- [{title}]({BASE + url if url.startswith('/') else url})\n")
                    continue
                prev = seen.get(tid)
                if prev and prev["stamp"] == stamp and Path(prev["path"]).exists() and not force:
                    continue
                ext = Path(unquote(t.get("Url", ""))).suffix
                jobs.append((tid, stamp, mdir, safe(title) + ext))
            walk(m.get("Modules", []), mdir, depth + 1)

    walk(toc.get("Modules", []), root / "content", 0)
    (root / "content" / "links.md").write_text("".join(links))

    def fetch(job):
        tid, stamp, mdir, fallback = job
        dest = api.download(f"/d2l/api/le/{api.le}/{ou_id}/content/topics/{tid}/file?stream=true", mdir, fallback)
        if dest:
            log(f"    + {dest.relative_to(root)}")
        return tid, stamp, dest

    n_new = 0
    for tid, stamp, dest in api.pool.map(fetch, jobs):
        if dest:
            seen[tid] = {"path": str(dest), "stamp": stamp}
            ch.append(f"File: {dest.relative_to(root)}")
            n_new += 1
    log(f"    content: {n_new} new/updated files")


COURSEFILE_RE = re.compile(r"quickLink\.d2l\?[^\"'<>]*?type=coursefile&(?:amp;)?fileId=([^\"'&<>]+)")


def scrape_course_files(api: D2L, ou_id: int, root: Path, manifest: dict, force: bool, ch: list[str]) -> None:
    """Files linked as 'course files' from module/topic descriptions (e.g. 02456 slides)."""
    toc_path = root / "content" / "toc.json"
    if not toc_path.exists():
        return
    seen = manifest.setdefault("coursefiles", {})
    jobs: dict[str, Path] = {}

    def walk(modules: list[dict], path: Path) -> None:
        for m in modules:
            mdir = path / safe(m["Title"])
            texts = [(m.get("Description") or {}).get("Html") or ""]
            texts += [(t.get("Description") or {}).get("Html") or "" for t in m.get("Topics", [])]
            for fid in COURSEFILE_RE.findall("".join(texts)):
                jobs.setdefault(unquote(fid.replace("+", " ")), mdir)
            walk(m.get("Modules", []), mdir)

    walk(json.loads(toc_path.read_text()).get("Modules", []), root / "content")
    todo = [(fid, d) for fid, d in jobs.items()
            if force or fid not in seen or not Path(seen[fid]).exists()]

    def fetch(job):
        fid, mdir = job
        url = f"/d2l/common/dialogs/quickLink/quickLink.d2l?ou={ou_id}&type=coursefile&fileId={fid}"
        return fid, api.download(url, mdir, Path(fid).name)

    n_new = 0
    for fid, dest in api.pool.map(fetch, todo):
        if dest and dest.suffix.lower() != ".d2l":
            seen[fid] = str(dest)
            ch.append(f"File: {dest.relative_to(root)}")
            n_new += 1
            log(f"    + {dest.relative_to(root)}")
    if jobs:
        log(f"    course files: {n_new} new ({len(jobs)} linked)")


def scrape_news(api: D2L, ou_id: int, root: Path, manifest: dict, ch: list[str]) -> None:
    items = api.try_get(f"/d2l/api/le/{api.le}/{ou_id}/news/", "announcements")
    if items is None:
        return
    d = root / "announcements"
    d.mkdir(parents=True, exist_ok=True)
    (d / "news.json").write_text(json.dumps(items, indent=2, ensure_ascii=False))
    known = manifest.get("news")
    if known is not None:
        for it in items:
            if it["Id"] not in known:
                ch.append(f"Announcement: {it['Title']} ({(it.get('StartDate') or '')[:10]})")
    manifest["news"] = [it["Id"] for it in items]
    md, jobs = [], []
    for it in sorted(items, key=lambda x: x.get("StartDate") or "", reverse=True):
        md.append(f"## {it['Title']}\n*{it.get('StartDate', '')}*\n\n{(it.get('Body') or {}).get('Html', '')}\n")
        for a in it.get("Attachments", []):
            target = d / str(it["Id"]) / safe(a["FileName"])
            if not target.exists():
                jobs.append((f"/d2l/api/le/{api.le}/{ou_id}/news/{it['Id']}/attachments/{a['FileId']}",
                             target.parent, a["FileName"]))
            md.append(f"- attachment: `{target.relative_to(d)}`\n")
    list(api.pool.map(lambda j: api.download(*j), jobs))
    (d / "announcements.md").write_text("\n".join(md))
    log(f"    announcements: {len(items)}")


def scrape_assignments(api: D2L, ou_id: int, root: Path, manifest: dict, ch: list[str]) -> None:
    folders = api.try_get(f"/d2l/api/le/{api.le}/{ou_id}/dropbox/folders/", "assignments")
    if folders is None:
        return
    d = root / "assignments"
    d.mkdir(parents=True, exist_ok=True)
    (d / "folders.json").write_text(json.dumps(folders, indent=2, ensure_ascii=False))
    known = manifest.get("due")
    due = {str(f["Id"]): f.get("DueDate") for f in folders}
    if known is not None:
        for f in folders:
            fid = str(f["Id"])
            if fid not in known:
                ch.append(f"New assignment: {f['Name']} (due {(f.get('DueDate') or 'none')[:16]})")
            elif known[fid] != due[fid]:
                ch.append(f"Deadline changed: {f['Name']}: {known[fid]} -> {due[fid]}")
    manifest["due"] = due
    jobs = []
    for f in folders:
        fdir = d / safe(f["Name"])
        fdir.mkdir(parents=True, exist_ok=True)
        instr = (f.get("CustomInstructions") or {}).get("Html", "")
        (fdir / "README.md").write_text(f"# {f['Name']}\n\nDue: {f.get('DueDate')}\n\n{instr}\n")
        for a in f.get("Attachments", []):
            if not (fdir / safe(a["FileName"])).exists():
                jobs.append((f"/d2l/api/le/{api.le}/{ou_id}/dropbox/folders/{f['Id']}/attachments/{a['FileId']}",
                             fdir, a["FileName"]))
        subs = api.try_get(f"/d2l/api/le/{api.le}/{ou_id}/dropbox/folders/{f['Id']}/submissions/mysubmissions/",
                           f"submissions {f['Name']}")
        if subs:
            (fdir / "my_submissions.json").write_text(json.dumps(subs, indent=2, ensure_ascii=False))
    list(api.pool.map(lambda j: api.download(*j), jobs))
    log(f"    assignments: {len(folders)}")


def scrape_grades(api: D2L, ou_id: int, root: Path) -> None:
    g = api.try_get(f"/d2l/api/le/{api.le}/{ou_id}/grades/values/myGradeValues/", "grades")
    if g is not None:
        (root / "grades.json").write_text(json.dumps(g, indent=2, ensure_ascii=False))
        log(f"    grades: {len(g)}")


def find_urls(text: str) -> set[str]:
    out = set()
    # JSON files hold HTML with escaped quotes (href=\"/content/...\"); unescape so relative links are found.
    for m in URL_RE.findall(html.unescape(text).replace('\\"', '"').replace("\\/", "/")):
        u = m.rstrip(".,;:\\")
        out.add(urljoin(BASE, u) if u.startswith("/") else u)
    return out


def pdf_candidate(url: str) -> str | None:
    """URL to fetch if this link may be a PDF, else None."""
    u = urlparse(url)
    host, path = u.netloc.lower(), u.path
    if any(h in host + path for h in SKIP_HOSTS):
        return None
    if host.endswith("learn.inside.dtu.dk") and "type=coursefile" in u.query:
        return None  # handled by scrape_course_files
    if host.endswith("learn.inside.dtu.dk"):
        return url if path.startswith("/content/") and path.lower().endswith(".pdf") else None
    m = re.match(r"/(?:abs|pdf)/([\w.\-/]+?)(?:v\d+)?(?:\.pdf)?$", path) if host.endswith("arxiv.org") else None
    if m:
        return f"https://arxiv.org/pdf/{m.group(1)}"
    return url


def probe_pdf(http: httpx.Client, url: str) -> tuple[bytes, str | None] | None:
    """Stream the URL and keep it only if it starts with the PDF magic bytes."""
    try:
        with http.stream("GET", url, timeout=httpx.Timeout(10, read=60)) as r:
            if not r.is_success:
                return None
            chunks = r.iter_bytes()
            head = next(chunks, b"")
            if not head.lstrip().startswith(b"%PDF"):
                return None
            return head + b"".join(chunks), filename_from_headers(r.headers)
    except (httpx.HTTPError, StopIteration):
        return None


def scrape_linked_pdfs(api: D2L, root: Path, manifest: dict, ch: list[str]) -> None:
    urls: set[str] = set()
    for f in [*root.glob("content/toc.json"), *root.glob("announcements/news.json"),
              *root.glob("assignments/folders.json"), *root.glob("content/**/*.html"),
              *root.glob("content/**/*.md"), *root.glob("assignments/**/*.md")]:
        urls |= find_urls(f.read_text(errors="ignore"))
    seen = manifest.setdefault("linked", {})
    targets = {}
    for url in urls:
        t = pdf_candidate(url)
        if t:
            targets.setdefault(t, url)
    todo = [t for t in targets if t not in seen]
    d = root / "linked"
    n_new = 0
    for target, res in zip(todo, api.pool.map(lambda t: probe_pdf(api.http, t), todo)):
        if not res:
            seen[target] = ""
            continue
        body, name = res
        name = name or unquote(Path(urlparse(target).path).name) or "linked"
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        dest = d / safe(name)
        if dest.exists() and dest.read_bytes() != body:
            dest = d / safe(f"{dest.stem}-{hashlib.sha1(target.encode()).hexdigest()[:6]}.pdf")
        d.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        seen[target] = str(dest.relative_to(root))
        ch.append(f"Linked PDF: {seen[target]}")
        n_new += 1
        log(f"    + {seen[target]}")
    index = [f"- [{Path(p).name}]({Path(p).relative_to('linked')}) <- {targets.get(t, t)}\n"
             for t, p in seen.items() if p]
    if index:
        (d / "index.md").write_text("# Linked PDFs\n\n" + "".join(sorted(index)))
    log(f"    linked PDFs: {n_new} new ({len(todo)} links checked, {len(urls)} found)")


# ---------------------------------------------------------------- commands


def cmd_courses(args) -> None:
    api = D2L(session_client())
    enrolled = api.enrollments()
    current = {e["OrgUnit"]["Id"] for e in current_semester(enrolled)}
    for e in enrolled:
        ou, acc = e["OrgUnit"], e["Access"]
        if not args.all_types and ou["Type"]["Id"] != COURSE_OFFERING:
            continue
        if args.current and ou["Id"] not in current:
            continue
        flag = "" if acc.get("IsActive") else "  (inactive)"
        print(f"{ou['Id']:>8}  {ou['Type']['Code']:<16} {ou.get('Code') or '':<24} {ou['Name']}{flag}")


def scrape_course(api: D2L, ou: dict, out: Path, args) -> list[str]:
    ou_id = ou["Id"]
    root = course_dir(out, ou)
    root.mkdir(parents=True, exist_ok=True)
    mpath = root / ".manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {}
    manifest["ou"] = ou_id
    ch: list[str] = []
    log(f"\n== {ou_id} {ou['Name']}")
    t0 = time.time()
    try:
        scrape_content(api, ou_id, root, manifest, args.force, ch)
        scrape_course_files(api, ou_id, root, manifest, args.force, ch)
        scrape_news(api, ou_id, root, manifest, ch)
        scrape_assignments(api, ou_id, root, manifest, ch)
        scrape_grades(api, ou_id, root)
        if not args.no_linked:
            scrape_linked_pdfs(api, root, manifest, ch)
        n_video = vault.write_videos(root)
        if n_video:
            log(f"    video links: {n_video}")
    finally:
        mpath.write_text(json.dumps(manifest, indent=2))
    log(f"    done in {time.time() - t0:.0f}s")
    return ch


class RefreshLocked(RuntimeError):
    pass


def _take_lock():
    ensure_home()
    fh = LOCK.open("w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        raise RefreshLocked("another dtu-learn refresh is running")
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


def cmd_scrape(args) -> dict[str, list[str]]:
    lock = _take_lock()  # one refresh at a time (schedule, MCP refresh, manual run)
    try:
        return _scrape(args)
    finally:
        lock.close()


def _scrape(args) -> dict[str, list[str]]:
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    api = D2L(session_client())
    log(f"API versions: lp {api.lp}, le {api.le}")
    enrolled = {e["OrgUnit"]["Id"]: e for e in api.enrollments()}
    if args.course:
        ids = args.course
    elif args.current:
        ids = [e["OrgUnit"]["Id"] for e in current_semester(list(enrolled.values()))]
    else:
        ids = [i for i, e in enrolled.items()
               if e["OrgUnit"]["Type"]["Id"] == COURSE_OFFERING
               and (args.include_inactive or e["Access"].get("IsActive"))]
    t0 = time.time()
    report, roots = {}, {}
    for ou_id in ids:
        ou = enrolled.get(ou_id, {}).get("OrgUnit") or {"Id": ou_id, "Name": str(ou_id)}
        report[ou["Name"]] = scrape_course(api, ou, out, args)
        roots[ou["Name"]] = course_dir(out, ou)
    if not getattr(args, "no_recordings", False):
        try:
            for name, items in recordings.sync_courses(list(roots.items()), args.force).items():
                report.setdefault(name, []).extend(items)
        except Exception as e:  # noqa: BLE001 - recordings are extra; DTU Learn data is already saved
            log(f"\nRecordings skipped: {e}")
    write_changes(out, report)
    if not getattr(args, "no_text", False):
        t1 = time.time()
        n = textcache.warm(list(roots.values()))
        if n:
            log(f"PDF text for search: {n} files in {time.time() - t1:.0f}s")
    for e in (queue_new_lectures(out, report, roots) if hook_enabled() else []):
        log(f"New lecture slides queued: {e['course']}: {e['lecture']} ({len(e['files'])} files)")
    log(f"\nAll done in {time.time() - t0:.0f}s -> {out}")
    if args.sync:
        cmd_sync(args)
    return report


SLIDE_EXT = {".pdf", ".ppt", ".pptx"}
SLIDE_HINT = re.compile(r"lecture|slide|week|forel|uge|lektion", re.I)
NOT_SLIDE = re.compile(r"exercise|solution|answer|problem|exam|assignment|syllabus|template|contract|ch\d|chapter", re.I)


def queue_new_lectures(out: Path, report: dict[str, list[str]], roots: dict[str, Path] | None = None) -> list[dict]:
    """Group newly seen lecture slides per lecture folder in out/new_lectures.json (status: pending)."""
    qpath = out / "new_lectures.json"
    queue = json.loads(qpath.read_text()) if qpath.exists() else []
    by_key = {(q["course"], q["lecture"]): q for q in queue}
    touched, created = [], []
    for course, items in report.items():
        for item in items:
            if not item.startswith("File: "):
                continue
            rel = item.split(": ", 1)[1]
            path = Path(rel)
            if path.suffix.lower() not in SLIDE_EXT or not rel.startswith("content/"):
                continue
            if not SLIDE_HINT.search(rel) or NOT_SLIDE.search(path.name):
                continue
            key = (course, str(path.parent))
            entry = by_key.get(key)
            if entry is None:
                entry = {"course": course, "lecture": key[1], "files": [],
                         "out_dir": str((roots or {}).get(course, "")),
                         "found": datetime.now().isoformat(timespec="seconds"), "status": "pending"}
                by_key[key] = entry
                queue.append(entry)
                created.append(entry)
            if rel not in entry["files"]:
                entry["files"].append(rel)
                if entry not in touched:
                    touched.append(entry)
    if len(created) > MAX_NEW_LECTURES:  # a lost manifest or --force, not a week of teaching
        for e in created:
            e["status"] = "baseline"
        log(f"{len(created)} new lecture folders in one run: treated as a re-download, marked baseline "
            "(set one back to pending in out/new_lectures.json to process it)")
        touched = [e for e in touched if e not in created]
    if touched or created:
        qpath.write_text(json.dumps(queue, indent=2, ensure_ascii=False))
    return touched


def seed_lecture_baseline(out: Path) -> int:
    """Mark every lecture folder that already has slides as 'baseline', so a later re-upload of an old
    lecture never triggers a new page or video. Safe to run again."""
    qpath = out / "new_lectures.json"
    queue = json.loads(qpath.read_text()) if qpath.exists() else []
    known = {(q["course"], q["lecture"]) for q in queue}
    added = 0
    for root in sorted(p for p in out.glob("*/") if (p / ".manifest.json").exists()):
        course = root.name.split(" ", 1)[-1]
        for f in sorted((root / "content").rglob("*")):
            rel = str(f.relative_to(root))
            if (f.suffix.lower() not in SLIDE_EXT or not SLIDE_HINT.search(rel) or NOT_SLIDE.search(f.name)):
                continue
            key = (course, str(f.relative_to(root).parent))
            if key in known:
                continue
            known.add(key)
            queue.append({"course": course, "lecture": key[1], "files": [rel], "out_dir": str(root),
                          "found": datetime.now().isoformat(timespec="seconds"), "status": "baseline"})
            added += 1
    qpath.write_text(json.dumps(queue, indent=2, ensure_ascii=False))
    return added


def write_changes(out: Path, report: dict[str, list[str]]) -> None:
    """CHANGES.md = what this run found; changelog.md = every run, newest first."""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    body = [f"## {stamp}\n"]
    for name, items in report.items():
        if items:
            body.append(f"\n### {name}\n" + "".join(f"- {i}\n" for i in items))
    if len(body) == 1:
        body.append("\nNothing new.\n")
    text = "".join(body)
    (out / "CHANGES.md").write_text("# DTU Learn: new since last run\n\n" + text)
    log_path = out / "changelog.md"
    old = log_path.read_text().split("\n", 2)[2] if log_path.exists() else ""
    log_path.write_text("# DTU Learn changelog\n\n" + text + "\n" + old)
    log("\n" + text)


# ---------------------------------------------------------------- schedule


def notify(title: str, text: str) -> None:
    """Desktop notification. Best effort: never fails the caller."""
    text = text[:240]
    try:
        system = platform.system()
        if system == "Darwin":
            script = f"display notification {json.dumps(text)} with title {json.dumps(title)}"
            subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
        elif system == "Linux" and shutil.which("notify-send"):
            subprocess.run(["notify-send", title, text], check=False, capture_output=True)
        elif system == "Windows":
            ps = ("[reflection.assembly]::loadwithpartialname('System.Windows.Forms') | Out-Null;"
                  "$n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Information;"
                  f"$n.Visible = $true; $n.ShowBalloonTip(8000, {json.dumps(title)}, {json.dumps(text)}, 'Info');"
                  "Start-Sleep -Seconds 9; $n.Dispose()")
            subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps])
    except Exception:  # noqa: BLE001
        pass


def scrape_args(**kw) -> argparse.Namespace:
    """Defaults for a scrape run started from code (auto, setup, MCP)."""
    base = dict(course=None, current=True, all=False, include_inactive=False, out=str(OUT), force=False,
                no_linked=False, no_recordings=False, sync=SYNC_CONFIG.exists(), dry_run=False, config=str(SYNC_CONFIG),
                no_vault=False)
    base.update(kw)
    return argparse.Namespace(**base)


def _next_check(now: datetime) -> datetime:
    t = now.replace(hour=7, minute=30, second=0, microsecond=0)
    return t if t > now else t + timedelta(days=1)


def write_status(result: str, detail: str = "", items: list[str] | None = None) -> None:
    """STATUS.md: the automation's state in plain language, rewritten after every scheduled check.
    Read it (or ask Claude to) to see where things stand."""
    now = datetime.now()
    last = datetime.fromisoformat(LAST_AUTO.read_text().strip()) if LAST_AUTO.exists() else None
    due = (last + AUTO_EVERY) if last else now
    nxt = _next_check(now)
    while nxt < due:
        nxt += timedelta(days=1)
    qpath = OUT / "new_lectures.json"
    q = json.loads(qpath.read_text()) if qpath.exists() else []
    active = [e for e in q if e.get("status") != "baseline"]
    lines = [
        "# dtu-learn status", "",
        f"- **Checked:** {now:%Y-%m-%d %H:%M}",
        f"- **Result:** {result}" + (f" ({detail})" if detail else ""),
        f"- **Last successful refresh:** {last:%Y-%m-%d %H:%M}" if last else "- **Last successful refresh:** never",
        f"- **Next refresh:** {nxt:%a %Y-%m-%d %H:%M} (daily check at 07:30, refresh when {AUTO_EVERY.total_seconds() / 3600:.0f} h have passed)",
        "- **Login needed:** " + ("YES: run `dtu-learn login`" if result.startswith("login expired")
                                  else "not checked (no refresh this time)" if result == "skipped" else "no"),
        "", "## New in the last refresh", "",
    ]
    lines += [f"- {i}" for i in (items or [])] or ["Nothing new."]
    if not qpath.exists():  # no after-refresh hook: no lecture queue to report
        lines += ["", f"Full log: `{AUTO_LOG}`. Last changes: `{OUT / 'CHANGES.md'}`."]
        STATUS.write_text("\n".join(lines) + "\n")
        return
    lines += ["", "## Lecture queue (after-refresh hook)", ""]
    if active:
        lines += ["| Course | Lecture | Status | Tries | Page | Video |", "|---|---|---|---|---|---|"]
        for e in active:
            lec = Path(e["lecture"])
            name = lec.parent.name if lec.name.lower() == "slides" else lec.name
            lines.append(f"| {e['course'].split(',')[0]} | {name} | {e['status']} | "
                         f"{e.get('attempts', 0)} | {e.get('page', '')} | {e.get('video', '')} |")
    else:
        lines.append("Empty.")
    lines += ["", f"Statuses: pending, page_done, no_credits, done, page_failed, video_failed, gave_up "
              f"(after 3 tries). {len(q) - len(active)} older lectures are baseline (never generated).",
              f"Full log: `{AUTO_LOG}`. Last changes: `{OUT / 'CHANGES.md'}`."]
    STATUS.write_text("\n".join(lines) + "\n")


def _rotate_log() -> None:
    try:
        if AUTO_LOG.exists() and AUTO_LOG.stat().st_size > MAX_LOG_BYTES:
            AUTO_LOG.replace(AUTO_LOG.with_suffix(".log.1"))
    except OSError:
        pass


def hook_enabled() -> bool:
    """An executable ~/.dtu-learn/hooks/after-refresh turns on the lecture queue and runs after `auto`."""
    return AFTER_REFRESH.is_file() and os.access(AFTER_REFRESH, os.X_OK)


def _run_hook() -> None:
    """Run the user's after-refresh hook when queued lectures wait. It reads out/new_lectures.json and gets
    --limit HOOK_LIMIT. It needs no DTU session, so it also runs when the login has expired."""
    queue = OUT / "new_lectures.json"
    if not (hook_enabled() and queue.exists()):
        return
    if any(q["status"] in ("pending", "page_done", "no_credits", "page_failed", "video_failed")
           for q in json.loads(queue.read_text())):
        log(f"Queued lectures found: running {AFTER_REFRESH} (at most {HOOK_LIMIT})")
        subprocess.run([str(AFTER_REFRESH), "--limit", str(HOOK_LIMIT)], cwd=HOME, env=child_env(), check=False)


def cmd_auto(args) -> None:
    """Scheduled entry point: refresh + sync once a day, notify on news or expired login,
    then run the optional after-refresh hook. Always leaves STATUS.md behind."""
    _rotate_log()
    if LAST_AUTO.exists() and not args.now:
        last = datetime.fromisoformat(LAST_AUTO.read_text().strip())
        if datetime.now() - last < AUTO_EVERY:
            log(f"{datetime.now():%Y-%m-%d %H:%M} skip: last run {last:%Y-%m-%d %H:%M}")
            write_status("skipped", f"last refresh {last:%a %H:%M}, not due yet")
            return
    log(f"\n===== auto run {datetime.now():%Y-%m-%d %H:%M}")
    try:
        report = cmd_scrape(scrape_args())
    except RefreshLocked as e:
        log(str(e))
        write_status("skipped", str(e))
        return
    except SessionExpired as e:
        notify("DTU Learn", "Login expired. Run: dtu-learn login (or ask your AI assistant to log you in)")
        log(f"session error: {e}")
        write_status("login expired", "no refresh until you log in; queued lectures still run")
        _run_hook()
        write_status("login expired", "no refresh until you log in; queued lectures still run")
        raise
    except Exception as e:
        notify("DTU Learn", f"Refresh failed: {type(e).__name__}. See {AUTO_LOG}")
        write_status("failed", f"{type(e).__name__}: {str(e)[:120]}")
        raise
    LAST_AUTO.write_text(datetime.now().isoformat(timespec="seconds"))
    items = [f"{name.split(',')[0]}: {i}" for name, lst in report.items() for i in lst]
    if items:
        notify(f"DTU Learn: {len(items)} new", "; ".join(items[:3]) + (" ..." if len(items) > 3 else ""))
    write_status("ok", f"{len(items)} new items", items)
    _run_hook()
    write_status("ok", f"{len(items)} new items", items)


# ---------------------------------------------------------------- sync


def sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sync_course(src: Path, dest: Path, dry_run: bool) -> tuple[list[str], list[str]]:
    """Copy new/changed files from src into dest. Never deletes or overwrites a
    file you placed yourself elsewhere in dest's parent: identical content there is skipped."""
    files = [f for f in src.rglob("*") if f.is_file() and f.name not in SYNC_SKIP
             and not any(part.startswith(".") for part in f.relative_to(src).parts)]
    sizes = {f.stat().st_size for f in files}
    elsewhere: dict[str, Path] = {}
    if dest.parent.exists():
        for f in dest.parent.rglob("*"):
            if f.is_file() and dest not in f.parents and f.stat().st_size in sizes:
                elsewhere[sha1(f)] = f
    copied, dupes = [], []
    for f in sorted(files):
        rel = f.relative_to(src)
        target = dest / rel
        if target.exists() and target.stat().st_size == f.stat().st_size and sha1(target) == sha1(f):
            continue
        h = sha1(f)
        if h in elsewhere and not target.exists():
            dupes.append(f"{rel} (already at {elsewhere[h].relative_to(dest.parent)})")
            continue
        copied.append(str(rel))
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
    return copied, dupes


def cmd_sync(args) -> None:
    cfg_path = Path(args.config).expanduser()
    if not cfg_path.exists():
        sys.exit(f"No sync config at {cfg_path}. Copy sync.example.json from the repo and edit the paths.")
    cfg = json.loads(cfg_path.read_text())
    out = Path(args.out).expanduser().resolve()
    by_ou = {}
    for m in out.glob("*/.manifest.json"):
        ou = json.loads(m.read_text()).get("ou")
        if ou:
            by_ou[str(ou)] = m.parent
    for ou, dest in cfg.items():
        if ou.startswith("_"):
            continue
        src = by_ou.get(ou)
        if not src:
            log(f"\n== {ou}: not scraped yet, skipped")
            continue
        dest = Path(dest).expanduser()
        copied, dupes = sync_course(src, dest, args.dry_run)
        notes = []
        if not args.dry_run and not getattr(args, "no_vault", False):
            notes = vault.update_course(src, dest, int(ou), src.name.split(" ", 1)[-1])
        verb = "would copy" if args.dry_run else "copied"
        log(f"\n== {src.name} -> {dest}\n    {verb} {len(copied)}, skipped {len(dupes)} already in your folders")
        for c in copied:
            log(f"    + {c}")
        for d in dupes:
            log(f"    = {d}")
        for note in notes:
            log(f"    vault: {note}")
