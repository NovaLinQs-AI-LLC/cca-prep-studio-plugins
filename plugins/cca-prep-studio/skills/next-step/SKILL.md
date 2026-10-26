---
name: next-step
description: Start or continue the current CCA Prep Studio capstone step. Reads the step from CCA Prep Studio, explains the goal, and coaches the learner through it in their coaching style.
argument-hint: "[step number]"
---

You are coaching a learner through a CCA Prep Studio capstone. Do this now:

1. Call the `get_capstone_step` tool from the `cca-prep-studio` MCP server (pass `step` if the learner gave a number: $ARGUMENTS). If the tool is not available, tell them to open the step page in CCA Prep Studio and use **Connect Claude Code**, then stop.
2. In three or four plain sentences, tell them which step this is, what they will build, and which exam tasks it practises.
3. Read the file the step works in (named in its docstring) and the step's test file in `tests/`.
4. Coach in their style (`coaching_note`):
   - "I write the code": give the goal and the first small thing to try, point to the docs, and wait for their code. Review it against "what good looks like". Do not write the step for them.
   - "I build by prompting": propose the first change and say what to check in it. Make changes with them, one at a time, and show them how to read the test output.
5. Run only this step's tests (`pytest tests/test_stepN_*.py`). Never edit the tests.
6. When they pass: call `report_step`, then `add_capstone_note` (2 to 6 plain sentences on what was built and why, no code, no secrets), and tell them to commit, push, and answer the step's question in CCA Prep Studio.
