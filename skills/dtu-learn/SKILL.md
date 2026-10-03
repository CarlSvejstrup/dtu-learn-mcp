---
name: dtu-learn
description: Answers questions about the user's own DTU courses from their DTU Learn (Brightspace) data on their own machine. Covers deadlines, hand-ins, announcements, lecture slides, course files, assignments, grades and what is new since the last refresh. Uses the dtu-learn MCP tools, and falls back to the dtu-learn CLI and the files in ~/.dtu-learn/out/ when the tools are absent. Use when the user says "when is the deadline", "what is due this week", "did I hand in", "any new announcements", "what's new on DTU Learn", "what did the teacher post", "find the slide about X", "which lecture covers Y", "my grades in 02132", or names a DTU course number or course name. For setup or login problems, use dtu-learn-setup. For a weekly overview, use dtu-learn-week. For studying a topic from slides, use dtu-learn-study.
---

# DTU Learn

Answer questions about the user's DTU courses with data from DTU Learn. The data is on the user's machine. Only `refresh` and `login` talk to DTU Learn.

## Tools (MCP server `dtu-learn`)

| Tool | Use it for |
|---|---|
| `status()` | Session OK?, last refresh time, courses, data folder |
| `login()` | Opens a browser window on the user's machine for DTU login. Returns when done |
| `refresh(course?)` | Download new material. Returns what changed. Can take a few minutes |
| `list_courses()` | Courses with id, course number, name and counts |
| `whats_new()` | New files, announcements, assignments and moved deadlines since the last refresh |
| `get_announcements(course?, limit=10, since?)` | Announcements, newest first |
| `get_deadlines(course?, include_past=False)` | Deadlines in Copenhagen time, with submission status |
| `list_files(course, query?)` | Files in a course, filtered by a word in the path |
| `read_file(course, path, max_chars=20000, page_start?, page_end?)` | Text of a file. PDFs have `[page N]` markers |
| `list_recordings(course?)` | Lecture recordings (Panopto) with date, length and transcript file |
| `get_transcript(course, recording, start?, end?)` | Transcript of one lecture with `[h:mm:ss]` timestamps and chapters. `recording` is part of the title, a date or its number; `start`/`end` like `"12:00"` |
| `search(query, course?, limit=20)` | Whole-word search in announcements, assignment text, lecture transcripts and file text. Returns file, page or timestamp, and snippet |

`course` accepts the org unit id, the course number (`"02132"`) or part of the name (`"deep learning"`).

## Rules

1. **Check freshness first.** For time-sensitive questions (deadlines, "new", "this week", announcements), call `status()`. If the last refresh is older than about 1 day, call `refresh()` before you answer. Tell the user you are refreshing.
2. **Login expired.** If `status` or `refresh` says the login has expired, tell the user: "A browser window opens now. Log in to DTU and finish MFA there." Then call `login()`, then `refresh()`. Never ask for the password or MFA code. The user types them in the browser.
3. **Times.** Give every time in Copenhagen time with the weekday, for example "Friday 10 October, 23:59". Say "in 3 days" when it helps.
4. **Cite sources.** For content from slides or files, give the file name and page: `Lecture 4.pdf, p. 12`. For a lecture transcript, give the lecture and timestamp: `Week 4 lecture, 53:10`. For announcements, give the course and date. Transcripts are automatic captions: words can be wrong, so prefer the slides for formulas and names.
5. **Say when it is not there.** If DTU Learn has no answer, say "This is not in DTU Learn" and say where you looked. Do not fill the gap from general knowledge without labelling it as such.
6. **Never invent deadlines, dates, grades or slide content.** Quote only what the tools return.
7. **Keep answers short.** Lead with the answer. Add detail only when asked.

## Procedures

**Deadline question** ("When is the 02132 assignment due?")
1. `status()`. Refresh if stale.
2. `get_deadlines(course="02132")`.
3. Answer with name, date, weekday, time and submission status.

**What is new** ("Anything new on DTU Learn?")
1. `status()`. Refresh if stale. `refresh()` returns the changes.
2. If you did not refresh, call `whats_new()`.
3. Group by course. Put announcements and moved deadlines first, then new files.

**Find material** ("Which lecture covers backpropagation?")
1. `search(query="backpropagation", course="deep learning")`.
2. If there are no hits, try a synonym or a shorter word, then `list_files(course, query="lecture")`.
3. `read_file(course, path, page_start=N, page_end=N+2)` to confirm before you answer.
4. Answer with file and page.

**What was said in a lecture** ("What did he say about pooling in week 4?")
1. `search(query="pooling", course="deep learning")` finds the lecture and timestamp.
   Transcripts are automatic captions and mishear terms ("RNNs" came out as "onions" in 02456 week 5). With no transcript hit, use the slides to find the week, then read that lecture with `get_transcript` around the chapter title.
2. `get_transcript(course, recording="week 4", start="<a minute before>", end="<a few minutes after>")`.
3. Answer with what was said and the timestamp. Recordings are for personal use only: never offer to share a transcript.

**Announcements** ("What did the NLP teacher post this week?")
1. `get_announcements(course="nlp", since="<date 7 days ago, YYYY-MM-DD>")`.
2. Summarize each in one or two lines, with date.

## Fallback without MCP tools

If the `dtu-learn` tools are not available, use the CLI and read files directly.

1. Run `dtu-learn status`. If the command is missing, use the dtu-learn-setup skill.
2. Run `dtu-learn scrape --current` to refresh. If it says the login expired, run `dtu-learn login` and tell the user to finish the login in the browser window.
3. Read the data in `~/.dtu-learn/out/` (or `$DTU_LEARN_HOME/out/`):
   - `CHANGES.md`: new since the last refresh
   - `<code> <name>/announcements/announcements.md`
   - `<code> <name>/assignments/<folder>/`: instructions, attachments, `my_submissions.json`
   - `<code> <name>/content/`: files by module, plus `links.md`
   - `<code> <name>/linked/`: PDFs linked from pages, `index.md` maps them to sources
   - `<code> <name>/grades.json`, `<code> <name>/videos.md`
4. Dates in the raw JSON files are in UTC (they end in `Z`). Convert them to Copenhagen time before you answer.

## Example prompts

- "When is the next hand-in in computer systems, and have I submitted it?"
- "Any new announcements in deep learning since Monday?"
- "Find where the slides explain attention, and give me the page."
- "What is new on DTU Learn?"
- "What are my grades in 42010?"
