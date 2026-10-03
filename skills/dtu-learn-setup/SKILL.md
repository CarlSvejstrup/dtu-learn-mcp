---
name: dtu-learn-setup
description: Installs and sets up the dtu-learn tool for a DTU student, and fixes it when it breaks. The agent runs the commands for the user step by step, so no technical skill is needed. Covers installing uv, installing dtu-learn from GitHub, the guided first run (DTU login, course pick, first download, connecting Claude Code, Claude Desktop or Cursor, auto-refresh) and checks with dtu-learn doctor. Use when the user says "set up DTU Learn", "install dtu-learn", "connect my DTU courses", "make Claude read DTU Learn", "dtu-learn is not working", "the DTU tools don't show up", "login expired" and login fails, "dtu-learn command not found", or when the dtu-learn MCP tools are missing. For questions about course content, use dtu-learn.
---

# DTU Learn setup

Install dtu-learn and run the first setup for the user. Run the commands yourself. Explain each step in one short sentence. Ask before you install anything.

## Safety

- The user types their own DTU password and MFA code in the browser window that dtu-learn opens. Never ask for them. Never type them. Never read `state.json` or the browser profile.
- All data stays in `~/.dtu-learn/` on the user's machine.
- Ask for a clear "yes" before each install command and before `dtu-learn setup` changes app settings.

## Procedure

1. **Check what is there.** Run:
   ```bash
   uv --version; git --version; dtu-learn status
   ```
   If `dtu-learn status` already works, go to step 5 (verify). If it reports no data or no login, go to step 4.

2. **Install uv** (only if missing). Ask first. Then run:
   - macOS or Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
   - Windows (PowerShell): `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`

   Tell the user to open a new terminal if `uv` is still not found, or run the command with its full path (`~/.local/bin/uv`).

3. **Install dtu-learn.** Ask first. Then run:
   ```bash
   uv tool install git+https://github.com/CarlSvejstrup/dtu-learn-sync
   ```
   If `dtu-learn` is not found after this, run `uv tool update-shell` and open a new terminal.

4. **Run the guided setup.** Tell the user before you start: "A browser window opens. Log in to DTU and finish MFA there. I wait up to 5 minutes." Then run, with a command timeout of at least 10 minutes:
   ```bash
   dtu-learn setup --yes
   ```
   `--yes` takes the default answer to every question, so it works without a terminal prompt. Add `--no-clients` to skip connecting AI apps. The setup:
   - checks for Chrome or Edge (it installs Playwright Chromium if neither is found)
   - opens the DTU login and waits until the user finishes MFA
   - shows this semester's courses and downloads them
   - connects Claude Code, Claude Desktop and Cursor if they are installed. It skips Claude Code when the dtu-learn plugin is enabled, because the plugin connects it.
   - leaves the optional daily auto-refresh off. The user refreshes by asking you (MCP `refresh`). Only if the user wants automatic morning refreshes with notifications: run `dtu-learn schedule install` (or add `--schedule` to the setup command).
   - prints example questions

   If the user prefers to answer each question, ask them to run `dtu-learn setup` in their own terminal and tell you when it is done.

5. **Verify.** Run:
   ```bash
   dtu-learn doctor
   ```
   Fix each item it reports with the table below. Run it again until it is clean.

6. **Finish.** Tell the user to restart the AI app (Claude Code, Claude Desktop or Cursor) so the new tools load. Then suggest a first question: "What is due this week?"

## Troubleshooting

| Problem | Fix |
|---|---|
| `command not found: dtu-learn` | Run `uv tool update-shell`, open a new terminal. Or use `~/.local/bin/dtu-learn`. |
| Chrome missing | Install Google Chrome, or let the setup install Playwright Chromium. Edge also works. |
| Login window closed too early | Run `dtu-learn login`. Keep the window open until it closes by itself. |
| MFA timed out | Run `dtu-learn login` again and approve the MFA prompt faster. |
| "Login expired" later | Run `dtu-learn login`. In Claude, ask: "log me in to DTU Learn". |
| No courses found | Run `dtu-learn courses --current`. If it is empty, the semester has not started in DTU Learn. Use `dtu-learn scrape --course <id>` with an id from `dtu-learn courses`. |
| DTU tools do not show up in the app | Restart the app fully (quit, not only close the window). Run `dtu-learn doctor` to check the registration. In Claude Desktop, check Settings > Developer. |
| Claude Desktop cannot start the server | GUI apps may not see `~/.local/bin`. Use the full path to `dtu-learn` in the app config (`which dtu-learn` shows it). Run `dtu-learn setup` again to rewrite it. |
| Auto-refresh does not run | Run `dtu-learn schedule status`. Reinstall with `dtu-learn schedule remove` and `dtu-learn schedule install`. |

**Windows:** run commands in PowerShell. The data folder is `%USERPROFILE%\.dtu-learn`. Auto-refresh uses Task Scheduler.

**Linux:** auto-refresh uses crontab. Login needs a desktop session, because it opens a browser window.

## Example prompts

- "Set up DTU Learn for me."
- "Install the DTU Learn tool and connect it to Claude Desktop."
- "dtu-learn says login expired and the browser closes. Fix it."
- "The DTU tools are not in Claude. What is wrong?"
