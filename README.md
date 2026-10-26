# CCA Prep Studio plugins for Claude Code

The plugin that coaches you through a CCA Prep Studio capstone.

```bash
claude plugin marketplace add NovaLinQs-AI-LLC/cca-prep-studio-plugins
claude plugin install cca-prep-studio@cca-prep-studio
```

Then, in your capstone repo, connect Claude Code from the capstone step page in CCA Prep Studio and run `/cca-prep-studio:next-step`.

What it adds:
- `/cca-prep-studio:next-step`: reads your current step from CCA Prep Studio and coaches you through it in your coaching style.
- A coaching skill that keeps the work honest: one step at a time, tests never edited.
- A hook that notices when a step's tests pass and reminds Claude to report the step and leave a note in your Workbook.

It cannot change your scores: a step counts only after its tests pass on GitHub and you answer its question in CCA Prep Studio.
