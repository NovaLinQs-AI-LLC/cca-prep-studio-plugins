"""PostToolUse hook: after Claude edits project code, remind it to point with path:line.

Reads the hook input (JSON on stdin). When an Edit, Write or MultiEdit
touched a file under src/, it adds one line of context: when telling the
learner what to check, start each item with path:line read from the file as
it is now. Anything else: no output. It never blocks a tool.
"""

import json
import sys


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    path = str((data.get("tool_input") or {}).get("file_path", ""))
    if "/src/" not in path.replace("\\", "/"):
        return
    message = (
        "When you tell the learner what to check in this change, start each item with a clickable path:line "
        "or path:start-end (for example src/support_agent/loop.py:76-82), read from the file as it is now."
    )
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": message}}))


if __name__ == "__main__":
    main()
