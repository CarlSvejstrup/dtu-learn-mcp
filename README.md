# dtu-learn

Ask Claude about your own DTU courses. dtu-learn downloads your DTU Learn (Brightspace/D2L) courses to your computer: slides, files, announcements, assignments, deadlines and grades. Then Claude (or another AI app) can answer questions such as "what is due this week?" or "which slide explains attention?". It uses Brightspace's own REST API with a browser session that you log into yourself (DTU SSO + MFA).

**Unofficial.** dtu-learn is a personal student project. It is not made, endorsed or supported by DTU or D2L. Use it only with your own account, keep the load low, and follow DTU's rules (see [DTU rules you must follow](#dtu-rules-you-must-follow)). Use at your own risk.

**Privacy:** you log in with your own DTU account. Everything stays on your computer in `~/.dtu-learn/`. Nothing goes anywhere except requests to DTU Learn. There is no server and no shared login.

## How it fits together

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/architecture-dark.svg">
  <img alt="DTU Learn, Panopto and a daily schedule feed dtu-learn refresh. It writes ~/.dtu-learn/out and STATUS.md. Sync copies into your notes, the MCP server gives Claude access, and an optional after-refresh hook hands the new-lecture queue to your own script." src="docs/architecture-light.svg" width="100%">
</picture>

Everything inside the box runs on your own computer. Sync and the hook are optional: without them you
still get the download, `STATUS.md` and the MCP server.

## Quickstart

You need a DTU account and Google Chrome (or Edge).

### A. Claude Code plugin (recommended)

1. In Claude Code, run:
   ```
   /plugin marketplace add CarlSvejstrup/dtu-learn-sync
   /plugin install dtu-learn@dtu-learn
   ```
2. Restart Claude Code.
3. Ask: **"Set up DTU Learn for me."** The setup skill installs uv and dtu-learn, and runs `dtu-learn setup` with you. You type your DTU password and MFA in the browser window yourself. The setup sees the plugin, so it does not connect Claude Code a second time.
4. Restart Claude Code again. Ask: "What is due this week?"

### B. Any agent (Cursor, Codex, Claude Desktop and others)

1. Install the skills:
   ```bash
   npx skills add CarlSvejstrup/dtu-learn-sync
   ```
2. Install uv (skip if you have it):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh                     # macOS, Linux
   powershell -c "irm https://astral.sh/uv/install.ps1 | iex"          # Windows
   ```
3. Install dtu-learn and run the guided setup:
   ```bash
   uv tool install git+https://github.com/CarlSvejstrup/dtu-learn-sync
   dtu-learn setup
   ```
   The setup asks which apps to connect (Claude Code, Claude Desktop, Cursor).
4. Restart your AI app.

Or ask your agent: "Set up DTU Learn for me." The `dtu-learn-setup` skill does steps 2 to 4.

### C. CLI only

Do steps 2 and 3 of path B. Say no to the AI apps. Then use the commands in the [CLI reference](#cli-reference). Your files are in `~/.dtu-learn/out/`.

## Ask it

- "What is due this week, and have I handed it in?"
- "What is new on DTU Learn since yesterday?"
- "Any announcements in deep learning this week?"
- "Which lecture in 02132 covers pipelining? Give me the slide page."
- "Explain attention from the NLP slides, then quiz me."
- "Give me my DTU week." (weekly brief with a plan)
- "What are my grades in 42010?"
- "Did the deadline for the 02456 project move?"

Skills in this repo: `dtu-learn` (questions), `dtu-learn-week` (weekly brief), `dtu-learn-study` (study and quiz from slides), `dtu-learn-setup` (install and fixes).

## CLI reference

| Command | What it does |
|---|---|
| `dtu-learn setup [--yes]` | Guided first run: browser check, DTU login, course pick, first download, connect AI apps, auto-refresh |
| `dtu-learn login` | Open the DTU login in a browser. Use it when the login has expired |
| `dtu-learn status` | Login OK?, last refresh, courses, data folder |
| `dtu-learn doctor` | Check uv, browser, login and app connections. Prints fixes |
| `dtu-learn courses [--current]` | List courses with org unit ids |
| `dtu-learn scrape --current` | Download this semester (newest start date, 120-day window) |
| `dtu-learn scrape --course ID...` | Download one or more courses by id |
| `dtu-learn scrape --all [--sync]` | Download every active course |
| `dtu-learn recordings [--course ID...]` | Lecture recording transcripts from Panopto (this semester by default). `scrape` does this too |
| `dtu-learn sync [--dry-run]` | Copy new files into your own folders (see [Sync](#sync)) |
| `dtu-learn schedule install\|remove\|status` | Auto-refresh once a day |
| `dtu-learn connect [claude-code\|claude-desktop\|cursor]` | Connect the MCP server to your AI apps (setup does this too) |
| `dtu-learn mcp` | Run the MCP server over stdio (the apps start it for you) |

Scrape flags: `--force` re-downloads files already downloaded, `--no-linked` skips `linked/`, `--no-recordings` skips Panopto, `--no-vault` (with `--sync`) only copies files.

Update: `uv tool upgrade dtu-learn`. Remove: `dtu-learn schedule remove`, then `uv tool uninstall dtu-learn`, then delete `~/.dtu-learn/`.

## What you get

All data is in `~/.dtu-learn/` (set `DTU_LEARN_HOME` to use another folder): the browser profile, the session cookies (`state.json`), `out/` and `sync.json`.

Per course, in `out/<code> <name>/`:

- `content/`: the module tree with every file, plus `links.md` (links, quizzes, LTI) and the raw `toc.json`
- `announcements/`: `announcements.md` and attachments
- `assignments/<folder>/`: instructions, attachments, `my_submissions.json`
- `grades.json`
- `linked/`: PDFs linked from content, announcements and instructions (arXiv abs links become PDFs). `index.md` maps each file to its source link
- `videos.md`: YouTube, video.dtu.dk, Panopto, Kaltura, Zoom-recording and Vimeo links found in the course
- `recordings/`: lecture recordings from Panopto. `recordings.json` lists every recording; `<date> <title>.md` holds its chapters and the transcript in 30-second blocks with `[h:mm:ss]` timestamps

A re-run only fetches files whose `LastModifiedDate` changed (`.manifest.json`).

**What's new.** Every scrape writes `out/CHANGES.md` (this run) and adds it to the top of `out/changelog.md`: new or updated files, new announcements, new assignments, changed deadlines, new linked PDFs. The first run of a course only sets the baseline.

**Lecture recordings.** DTU records lectures in Panopto (`dtu.cloud.panopto.eu`, also `panopto.dtu.dk`), not in DTU Learn. Each course has a Panopto folder with the course's DTU Learn name (older ones say `Spring 24`; matched by course number and term). Panopto makes automatic captions, so dtu-learn saves the caption text, not the video: it calls the same endpoints the Panopto player calls (session list, delivery info, caption file), with your own DTU login, one request at a time. It never downloads audio or video. A recording without captions yet is listed and fetched on a later run. DTU's rule: recordings are for personal use unless the teacher approves more, so keep transcripts to yourself.

**MCP tools.** `status`, `login`, `refresh(course?)`, `list_courses`, `whats_new`, `get_announcements(course?, limit, since?)`, `get_deadlines(course?, include_past)` (Copenhagen time, with your submission status), `list_files(course, query?)`, `read_file(course, path, max_chars, page_start?, page_end?)` (PDF text per page), `list_recordings(course?)`, `get_transcript(course, recording, start?, end?)` (a lecture transcript, or a time range of it) and `search(query, course?, limit)` (announcements, assignment text, lecture transcripts with timestamp, and the text of PDF, md, txt and py files). `course` can be the org unit id, the course number (`02132`) or part of the name (`nlp`, `deep learning`). Extracted PDF text is cached in `out/<course>/.text/`.

**Not covered:** quizzes, discussions, calendar, video files (only Panopto caption text), Locker.

## Data and privacy

- You log in with your own DTU account. Each person has their own login. There is no shared login and no server.
- The session, the downloaded files and the cache stay on your computer. Only requests to DTU Learn leave it.
- dtu-learn downloads only what you can already see in DTU Learn.
- Course material belongs to the course. Do not share it, or your `out/` folder, outside the course.
- Follow DTU's rules for IT use. Do not refresh more often than you need; the schedule refreshes once a day, only changed files, 3 requests at a time.
- `state.json` and the browser profile hold a live DTU session. Never share or commit them.

## Schedule

`dtu-learn schedule install` sets up `dtu-learn auto`: macOS launchd, Linux crontab or Windows Task Scheduler. `auto` refreshes once a day and shows a desktop notification when there is news or when the login has expired. `dtu-learn schedule status` and `dtu-learn schedule remove` check and remove it.

## Troubleshooting

| Problem | Fix |
|---|---|
| `command not found: dtu-learn` | Run `uv tool update-shell` and open a new terminal |
| "Login expired" | Run `dtu-learn login`, or ask Claude "log me in to DTU Learn". Finish MFA in the browser |
| Login window closes or MFA times out | Run `dtu-learn login` again. Keep the window open until it closes by itself |
| DTU tools do not show in the app | Quit and reopen the app. Run `dtu-learn doctor` |
| Claude Desktop cannot start the server | Use the full path to `dtu-learn` (`which dtu-learn`) in its config, or run `dtu-learn setup` again |
| Anything else | Run `dtu-learn doctor` and follow what it prints |

## Optional: copy into your own notes

You do not need this to use dtu-learn with Claude. It is for people who keep course notes in a folder, for example an Obsidian vault.

### Sync

`sync.json` maps an org unit id to a destination folder (see `sync.example.json`). Sync copies new or changed files and never deletes. It skips a file whose content already exists anywhere under the destination's parent (for example a slide you renamed into `material/lectures/`). Raw API JSON (`toc.json`, `news.json`, ...) stays in `out/`. `scrape --sync` does both.

### Vault output

When a sync destination is `<course>/material/learn`, sync also writes to `<course>/`:

- `announcements.md`: every announcement as Markdown, newest first. Rewritten on each sync, only if something changed.
- `backlog.md`: upcoming assignment deadlines added under `## Next`, tagged `<!-- learn:dropbox:<ou>:<id> -->`. A moved deadline updates the tagged line. A deadline is skipped if the backlog already names it with the same date.

`--no-vault` turns this off.

### After-refresh hook

Make an executable file `~/.dtu-learn/hooks/after-refresh` to run your own step after each scheduled refresh.
When it exists, every refresh also groups new lecture slides per lecture in `out/new_lectures.json`
(status `pending`), and `dtu-learn auto` calls the hook with `--limit 2` when lectures wait. The hook
also runs when the DTU login has expired, because it needs no DTU session. Without the file, none of this happens.

### Legacy entry points

The old scripts in a clone of this repo (`git clone https://github.com/CarlSvejstrup/dtu-learn-sync`) keep working:

```bash
uv run dtu_learn.py login                    # once, or when the session expires
uv run dtu_learn.py courses --current        # this semester's courses + org unit ids
uv run dtu_learn.py scrape --current         # this semester
uv run dtu_learn.py scrape --course 338557   # one or more ids
uv run dtu_learn.py scrape --all             # every active course
uv run dtu_learn.py sync [--dry-run]         # copy new files into your own folders (sync.json)
uv run dtu_learn.py scrape --current --sync  # both
uv run dtu_learn.py schedule install         # run `auto` daily (launchd, 07:30 check)
```

The legacy scripts keep their data in the repo folder unless `DTU_LEARN_HOME` is set.

Legacy schedule: `uv run dtu_learn.py schedule install` writes `~/Library/LaunchAgents/dk.svejstrup.dtu-learn.plist`. It starts `auto` every day at 07:30. `auto` runs scrape + sync when 12 h have passed since the last run (`.last_auto`), so every morning. macOS notifications: number of new items, or "Login expired". Log: `auto.log`. Also `schedule status`, `schedule remove`, `auto --now`.

Legacy MCP server: `mcp_server.py`, registered with `claude mcp add dtu-learn -- uv run --directory "$PWD" mcp_server.py`. For Claude Desktop, add it to `claude_desktop_config.json` (Settings > Developer > Edit Config) with your own path and restart the app. If Claude Desktop cannot find `uv`, use its full path (`which uv`).

```json
{
  "mcpServers": {
    "dtu-learn": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/dtu-learn-sync", "mcp_server.py"]
    }
  }
}
```

Set `DTU_LEARN_OUT` to read or write `out/` in another folder. In a clone, `.profile/`, `state.json` and `out/` are gitignored. Never commit them: they hold a live DTU session.

## How it works

- Chrome (system install, `channel="chrome"`) with a persistent browser profile.
- Session cookies are saved to `state.json` (mode 600), because Chrome drops session cookies on exit. If the D2L session is gone, the Microsoft SSO cookie in the profile usually gets a new one without a window.
- Playwright only checks and refreshes the session. The cookies then go to httpx, which downloads 3 files in parallel (kept low on purpose: DTU's IT policy says not to burden its systems unnecessarily).
- All data comes from `/d2l/api/{lp,le}/<latest>/...`. Versions are found via `/d2l/api/versions/`.
- Recordings: the same browser opens Panopto's login page, which signs in silently through the DTU login. Then `Api/Folders`, `Services/Data.svc/GetSessions`, `Pages/Viewer/DeliveryInfo.aspx` and `Pages/Transcription/GenerateSRT.ashx`, the player's own endpoints. Panopto's public REST API needs an admin-registered key, so it is not used.
- A tool that is turned off in a course (403) is logged and skipped.

## Scheduled run: what it does and how to see where it is

`dtu-learn schedule install` adds a launchd job that checks every day at 07:30 (or when the Mac wakes)
and refreshes every morning (at most once per 12 hours). After every check it writes **`STATUS.md`** in the data
folder: result, whether you must log in, next refresh, what was new, and (with an after-refresh hook) the lecture queue. Ask Claude
"what is the dtu-learn status?" (MCP `status` tool) or open the file.

Safety rails:
- One refresh at a time (lock file), so the schedule, the MCP `refresh` tool and a manual run never collide.
- With an after-refresh hook: more than 4 new lecture folders in one run counts as a re-download (lost
  manifest, `--force`), not new teaching, so they are marked `baseline` and not queued. Lectures that
  existed before the queue are `baseline` too (`seed_lecture_baseline`). The hook gets at most 2 per run.
- When the login has expired, the refresh stops and you get a notification. `auto.log` rotates at 2 MB.

## DTU rules you must follow

These come from DTU's own pages (checked 2026-10-03). They apply to everyone who uses this tool.

- **Your own login only.** Log in yourself on DTU's real login page. Never share your session files
  (`state.json`, `.profile/`) or your password with anyone.
- **Your own copy only.** Course files are for your own study. Do not send downloaded files to others:
  each friend downloads with their own account. Never commit `out/` or put it in a shared folder.
- **No teachers' material into AI tools without permission.** DTU's IT security policy: sharing
  "also includes uploading material to AI chatbots", and DTU's copyright page allows uploading only your
  own work, public domain and CC-0 material. Slides, notes and recordings belong to the teacher.
  Ask the teacher before you let Claude, ChatGPT or any other AI read them (this includes the MCP
  server's `read_file` and `search`).
- **No other people's personal data into AI tools.** Announcements, participant lists and recordings
  can contain names. DTU: personal data "must not be entered into AI tools or other external services
  unless this has been approved".
- **Keep the load low.** Do not raise the number of parallel requests or run it more often than needed.

Sources: [DTU IT security policy](https://student.dtu.dk/en/studieregler/IT-sikkerhedspolitik),
[DTU: generative AI and copyright](https://www.inside.dtu.dk/informationshaandtering/ophavsret/generativ-ai),
[DTU: copyright when you are a student](https://www.inside.dtu.dk/en/information-management/copyright/copyright-when-you-are-a-student).
Not legal advice. When in doubt, ask ophavsret@dtu.dk or DTU IT via the Service Portal.

## Development

```bash
git clone https://github.com/CarlSvejstrup/dtu-learn-sync && cd dtu-learn-sync
uv tool install --editable .     # dtu-learn on PATH, follows your edits
uv run --group dev pytest -q     # 155 offline tests: no network, browser or schedulers
claude plugin validate . --strict
```

## Status

- 2026-10-03: built and verified on NLP (338557): 13 content files, 7 announcements, 5 assignments, grades. Incremental re-run fetched 0 files. `courses` lists 28 course offerings back to 2023.
- 2026-10-03: `--current`, linked PDFs, parallel httpx downloads. 02132 (77 MB, 31 files) in 3 s with `--force`; full `--current` incremental run 15 s.
- 2026-10-03: change digest (`CHANGES.md`, `changelog.md`) and `sync` with content dedupe. Tested on a copy of the NLP material folder: 22 copied, 15 recognised as already present (also renamed slides).
- 2026-10-03: vault output, `videos.md`, every-other-day launchd job (tested from launchd), MCP server (8 tools, tested over stdio). Sync ignores dot-folders such as the MCP text cache.
- 2026-10-03: lecture transcripts from Panopto (`recordings`, `list_recordings`, `get_transcript`, transcripts in `search`). Verified on 02456 Fall 2026 (5 recordings, all with captions), 02182 Spring 2026 (14, Danish captions) and 02450 Spring 2024 (13, folder matched by number and term). Re-run fetches nothing. 154 tests.
- 0.2.0: installable package (`dtu-learn` command), data in `~/.dtu-learn/`, guided setup, Claude Code plugin and Agent Skills.
- 2026-10-03: v0.2.0 package `dtu-learn`, guided setup, MCP `status`/`login`, Claude Code plugin, 4 Agent Skills, cross-platform schedule, 125 tests. Verified: GitHub install, setup from an empty home, all 10 MCP tools over stdio, plugin install in an isolated Claude config (MCP connected), `npx skills add --list` finds 4 skills.
- 2026-10-03: personal extras live outside this repo and plug in through the generic after-refresh hook.
