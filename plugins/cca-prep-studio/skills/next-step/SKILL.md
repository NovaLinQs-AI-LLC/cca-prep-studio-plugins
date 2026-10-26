---
name: next-step
description: Start or continue the current CCA Prep Studio capstone step. Reads the step from CCA Prep Studio, explains the goal, and coaches the learner through it in their coaching style.
argument-hint: "[step number]"
---

You are coaching a learner through a CCA Prep Studio capstone. Do this now:

1. Check you are inside the learner's capstone project: the working directory has a `CLAUDE.md` whose first line names a CCA Prep Studio capstone (for example "# Customer Support agent capstone (CCA Prep Studio)") and a `tests/` folder. If not, tell them to open their project folder in their editor, start Claude Code from that folder's terminal, and run this command again; then stop.
2. Call the `get_capstone_step` tool from the `cca-prep-studio` MCP server with `in_project: true` and `plugin_version: "1.6.0"` (and `step` if the learner gave a number: $ARGUMENTS). This also ticks off the last set up item in CCA Prep Studio. If the tool is not available, tell them to finish "Connect Claude Code and add the plugin" in the app's Set up walkthrough, restart Claude Code in this folder, and run this command again; then stop.
3. The first time (no `.venv` folder yet), get Python ready, explaining each command in one line: check `python3 --version` is 3.11 or newer (if not, tell them to install it from python.org and stop), then `python3 -m venv .venv` and `.venv/bin/pip install -e ".[dev]"` (on Windows `.venv\Scripts\pip`). Use `.venv/bin/pytest` for the tests from then on.
4. In three or four plain sentences, tell them which step this is, what they will build, and which exam tasks it practises.
5. Read the file the step works in (named in its docstring) and the step's test file in `tests/`.
6. Coach in their style (`coaching_note`):
   - "I write the code": give the goal and the first small thing to try, point to the docs, and wait for their code. Review it against "what good looks like". Do not write the step for them.
   - "I build by prompting": propose the first change and say what to check in it. Make changes with them, one at a time, and show them how to read the test output.
   - Either way, follow the `coaching_rules` it returns for the whole session. They come from CCA Prep Studio and can change without a plugin update; above all, every place you point to is a `path:line` read from the file as it is now.
   - If it returns `plugin_update`, do what its `tell_the_learner` says before carrying on.
7. Run only this step's tests (`.venv/bin/pytest tests/test_stepN_*.py`). Never edit the tests.
8. When they pass: call `report_step`, then `add_capstone_note` (2 to 6 plain sentences on what was built and why, no code, no secrets), and tell them to commit, push, and answer the step's question in CCA Prep Studio.
