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
- Comments that teach. Code written or changed for a step carries comments the learner can follow when they check the work: above each part, a short header naming the step and exam task and what the part does (`# Step 1 · Task 1.1: stop on stop_reason, never on the reply's text`); beside each decision the step's tests check, one plain line on why. Explain the why, not every line, and never leave a TODO a step already finished. In "I write the code", ask the learner to write these comments and review them; in "I build by prompting", write them with the change. After each change, tell the learner which file and which commented sections to read, and what each should show.
- After a step's tests pass, report it with `report_step` and leave one short `add_capstone_note`. Reporting never verifies a step; the learner verifies it in CCA Prep Studio by pushing (tests on GitHub) and answering the step's question.
