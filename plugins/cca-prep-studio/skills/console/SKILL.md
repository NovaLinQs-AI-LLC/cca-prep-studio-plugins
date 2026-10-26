---
name: console
description: Open the Support Console, a page in the learner's browser for trying their capstone agent as a customer. They send prompts, break tools on purpose, run a step's tests with plain-words results, and see what happened behind the scenes. Use when the learner wants to try or test their agent by hand, or after a step's tests pass.
argument-hint: "[live]"
allowed-tools: Bash(.venv/bin/python */console/server.py *), Bash(curl -s http://127.0.0.1:*)
---

Open the Support Console for this capstone project:

1. Check you are inside the learner's capstone project: a `CLAUDE.md` naming a CCA Prep Studio capstone and a `src/support_agent` folder. If not, tell them to start Claude Code from their project folder and stop.
2. If there is no `.venv` folder yet, get Python ready first (Python 3.11 or newer, then `python3 -m venv .venv` and `.venv/bin/pip install -e ".[dev]"`; on Windows use `.venv\Scripts\pip`), explaining each command in one line.
3. If `curl -s http://127.0.0.1:8765/api/state` already answers, a console is running: reuse it. Otherwise start it in the background with the project's Python (on Windows `.venv\Scripts\python`):
   `.venv/bin/python "${CLAUDE_PLUGIN_ROOT}/console/server.py" --project .`
   Its first line of output gives the address (http://127.0.0.1:8765, or the next free port).
4. Open the address in their browser: `open <url>` on macOS, `start <url>` on Windows, `xdg-open <url>` on Linux.
5. In two or three short lines, tell them: pick the step at the top; the **Try this** prompts on the left say what to expect before and after the step is built; **Break something** makes the next call to a tool fail on purpose; **Run tests** shows each test in plain words with where to look. Practice needs no API key; Live uses the key in `.env` and lets them type anything, and **What just happened?** has Claude explain the turn. The console picks up code changes by itself, so it can stay open while they build.

Practice is always there and needs no key. If the learner ran this with `live` ($ARGUMENTS), or asks for Live mode, walk them through adding an API key after the console is open:
- Check whether the key is already there without reading it: `curl -s http://127.0.0.1:<port>/api/state` reports `"hasKey": true` or `false`. Never open, read, print or commit `.env`, and never ask the learner to paste a key into this chat.
- If it's missing, explain in one line that Live calls Claude with their own key, billed to their Anthropic account. Then, one step at a time:
  1. Open https://console.anthropic.com/settings/keys (Claude Console › Settings › API keys), sign in, and create a key. Copy it.
  2. If there is no `.env` yet, create it from the example: `cp .env.example .env` (Windows: `copy .env.example .env`). That file is already in `.gitignore`.
  3. Open `.env` in their editor, paste the key right after `ANTHROPIC_API_KEY=` with no spaces or quotes, and save.
  4. Click **Live** in the console. It reads `.env` again, so nothing needs restarting. Check `hasKey` once more and confirm.
- Once Live works, suggest one message to type, and point out the **What just happened?** button under each reply.
