"""PostToolUse hook: when one capstone step's tests pass, remind Claude to report it.

Reads the hook input (JSON on stdin). If the Bash command ran pytest on a
single tests/test_stepN_*.py file and the output shows passes and no
failures, it adds context telling Claude to call report_step and
add_capstone_note. Anything else: no output. It never blocks a tool.
"""

import json
import re
import sys


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    command = str((data.get("tool_input") or {}).get("command", ""))
    steps = set(re.findall(r"tests/test_step(\d+)_", command))
    if "pytest" not in command or len(steps) != 1:
        return
    response = data.get("tool_response") or {}
    output = f"{response.get('stdout', '')}\n{response.get('stderr', '')}" if isinstance(response, dict) else str(response)
    if not re.search(r"\b\d+ passed\b", output) or re.search(r"\b\d+ (failed|error|errors)\b", output):
        return
    step = steps.pop()
    message = (
        f"Capstone step {step}: its tests pass on this machine. Call report_step (scenario customer-support, step {step}) "
        "and add_capstone_note (2 to 6 plain sentences, no code or secrets). Then tell the learner to commit and push "
        "so the tests run on GitHub, and to answer the step's question in CCA Prep Studio."
    )
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": message}}))


if __name__ == "__main__":
    main()
