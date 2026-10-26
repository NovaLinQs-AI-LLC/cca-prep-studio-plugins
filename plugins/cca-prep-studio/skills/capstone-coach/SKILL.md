---
name: capstone-coach
description: Use when working in a CCA Prep Studio capstone repo (a README that says "a CCA Prep Studio capstone", tests named tests/test_stepN_*.py). Keeps coaching honest - one step at a time, never editing tests, tying each change to its exam task.
user-invocable: false
---

This repository is a CCA Prep Studio capstone. While you work in it:

- The learner is practising for the Claude Certified Architect – Foundations exam. Understanding matters more than finishing fast: explain the reason behind each change in plain words and name the exam task it practises (each file's docstring says which).
- Work on the current step only (ask `get_capstone_step` if unsure). Do not start a later step's TODOs.
- Never edit, skip or weaken anything in `tests/`. If a test looks wrong, say so and stop.
- Never read, print or commit `.env` or keys.
- After a step's tests pass, report it with `report_step` and leave one short `add_capstone_note`. Reporting never verifies a step; the learner verifies it in CCA Prep Studio by pushing (tests on GitHub) and answering the step's question.
