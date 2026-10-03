---
name: dtu-learn-week
description: Writes a weekly brief of the user's DTU courses from their DTU Learn data. Lists deadlines in the next 7 days with submission status, announcements from the last 7 days, new course material per course, and a short suggested plan for the week. Uses the dtu-learn MCP tools and refreshes first when the data is old. Use when the user says "my week", "weekly brief", "what's this week at DTU", "plan my week", "what do I need to do this week", "week overview", "uge-overblik", "hvad skal jeg nå i denne uge", or on a Monday-morning routine. For a single question about one deadline or file, use dtu-learn.
---

# DTU Learn weekly brief

Build a one-screen brief of the coming week from DTU Learn. Use only data the tools return.

## Procedure

1. `status()`. If the last refresh is older than about 1 day, call `refresh()`. If the login has expired, tell the user a browser window opens for DTU login and MFA, call `login()`, then `refresh()`.
2. `get_deadlines()` for all courses. Keep deadlines from now until 7 days ahead. Also keep passed deadlines from the last 2 days that are not submitted.
3. `get_announcements(since="<date 7 days ago, YYYY-MM-DD>", limit=30)`.
4. `whats_new()` for new files, new assignments and moved deadlines.
5. `list_courses()` so every course appears, also courses with nothing new.
6. Write the brief with the template below.

## Rules

- Times in Copenhagen time with weekday: "Thu 9 Oct 23:59".
- Mark submission status per deadline: submitted, not submitted, or unknown.
- Put a moved deadline first, with old and new date.
- Summarize each announcement in one line. Quote dates, rooms and exam info exactly.
- Name new files by their real file name. Do not guess what a file contains. Read it with `read_file` if the plan depends on it.
- The plan is a suggestion. Base it only on the deadlines and material above. Keep it to 3 to 5 lines.
- If a section is empty, write "Nothing" and keep the section.

## Template

```markdown
# Week <ISO week>: <Mon date> to <Sun date>
Data refreshed: <time from status>

## Deadlines (next 7 days)
| When | Course | What | Status |
|---|---|---|---|
| Thu 9 Oct 23:59 | 02132 | Assignment 2 | not submitted |

Moved: <course> <name>, <old date> -> <new date>

## Announcements (last 7 days)
- **02456** Mon 6 Oct: Exercise session moved to building 308, room 11.

## New material
- **02132**: Lecture 5.pdf, Lab 3.pdf
- **42010**: Nothing

## Suggested plan
1. Mon to Tue: finish Assignment 2 (02132), due Thursday.
2. Wed: read Lecture 5 slides before Thursday's lecture.
3. Fri: start the 02456 exercise set.
```

## Example prompts

- "Give me my DTU week."
- "What do I need to do this week, and in what order?"
- "Weekly brief for my courses, please."
- "Hvad skal jeg nå i denne uge på DTU?"
