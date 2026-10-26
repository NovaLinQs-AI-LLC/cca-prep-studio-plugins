"""The Support Console: try your capstone agent as a customer, and see what happens behind the scenes.

Started by /cca-prep-studio:console from inside your project, with the project's own Python:
    .venv/bin/python <plugin>/console/server.py --project .
It serves one page at http://127.0.0.1:<port> and listens on your computer only.

Everything runs YOUR code from src/support_agent: the loop, the tools, the errors, the hooks,
the handoff and the case facts. Practice mode puts a scripted stand-in in Claude's place
(practice.py, no API key needed); Live mode calls Claude with the key in your .env.
The console never prints, logs or sends your key anywhere but to Anthropic, and only in Live mode.
Python's standard library only: nothing extra to install.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import practice  # noqa: E402

CONTENT = json.loads((HERE / "content.json").read_text())
STEPS = {s["n"]: s for s in CONTENT["steps"]}
TRIES = {t["id"]: (s["n"], t) for s in CONTENT["steps"] for t in s["tries"]}
NOTES = {p.stem: p.read_text() for p in (HERE / "notes").glob("*.md")}
MAX_TURN_EVENTS = 200


# --- the learner's project -----------------------------------------------------

class Project:
    def __init__(self, root: Path):
        self.root = root
        self.src = root / "src"
        if not (self.src / "support_agent").is_dir():
            raise SystemExit(f"No src/support_agent in {root}. Start the console from your capstone project folder.")
        sys.path.insert(0, str(self.src))
        self._load_env()

    def _load_env(self) -> None:
        env = self.root / ".env"
        if not env.exists():
            return
        for line in env.read_text().splitlines():
            m = re.match(r"^\s*(ANTHROPIC_API_KEY|CAPSTONE_MODEL)\s*=\s*(.*)\s*$", line)
            if m and m.group(2) and not os.environ.get(m.group(1)):
                os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")

    def signature(self) -> float:
        return max((p.stat().st_mtime for p in self.src.rglob("*.py")), default=0.0)

    def fresh_modules(self) -> dict[str, Any]:
        """Import the learner's code again, so edits show up without restarting the console."""
        for name in list(sys.modules):
            if name == "support_agent" or name.startswith("support_agent."):
                del sys.modules[name]
        return {n: importlib.import_module(f"support_agent.{n}") for n in ("agent", "backend", "loop", "policy", "tools", "context")}

    def ref(self, key: str | None) -> str | None:
        """'src/support_agent/hooks.py:33' for a named place in the learner's code, read from the file as it is now."""
        if not key or key not in CONTENT["refs"]:
            return None
        rel, pattern = CONTENT["refs"][key]
        path = self.root / rel
        if not path.exists():
            return None
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(pattern, line):
                return f"{rel}:{i}"
        return rel

    def numbered(self, rel: str, limit: int = 160) -> str:
        path = self.root / rel
        if not path.exists():
            return ""
        lines = path.read_text().splitlines()[:limit]
        return "\n".join(f"{i:4d}  {l}" for i, l in enumerate(lines, 1))

    def where(self, tb: traceback.StackSummary) -> str | None:
        for frame in reversed(tb):
            p = Path(frame.filename).resolve()
            if self.src in p.parents:
                return f"{p.relative_to(self.root)}:{frame.lineno}"
        return None


# --- tests ---------------------------------------------------------------------

def step_files(root: Path, step: int | None) -> list[str]:
    pat = f"test_step{step}_*.py" if step else "test_step*_*.py"
    return sorted(str(p.relative_to(root)) for p in (root / "tests").glob(pat))


def run_tests(project: Project, step: int | None) -> dict[str, Any]:
    files = step_files(project.root, step)
    if not files:
        return {"error": "No test files found in tests/."}
    with tempfile.TemporaryDirectory() as tmp:
        xml = Path(tmp) / "r.xml"
        started = time.time()
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml}", *files], cwd=project.root, capture_output=True, text=True, timeout=180)
        took = round(time.time() - started, 1)
        if not xml.exists():
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-6:]
            return {"error": "The tests could not run. " + " ".join(tail)}
        root = ET.parse(xml).getroot()
    grouped: dict[str, dict[str, Any]] = {}
    for case in root.iter("testcase"):
        name = case.get("name", "")
        base = name.split("[")[0]
        stepn = int(m.group(1)) if (m := re.search(r"test_step(\d)", case.get("classname", "") + case.get("file", ""))) else None
        bad = case.find("failure") if case.find("failure") is not None else case.find("error")
        g = grouped.setdefault(base, {"name": base, "step": stepn, "passed": True, "message": None})
        if bad is not None:
            g["passed"] = False
            g["message"] = g["message"] or plain_failure(bad.get("message", "") or (bad.text or ""))
    out = []
    for g in grouped.values():
        meta = CONTENT["tests"].get(g["name"], {})
        out.append({**g, "title": meta.get("title", g["name"].replace("test_", "").replace("_", " ")), "checks": meta.get("checks"), "ask": meta.get("ask"), "ref": project.ref(meta.get("ref"))})
    return {"files": files, "took": took, "tests": out, "passed": sum(t["passed"] for t in out), "total": len(out)}


def plain_failure(msg: str) -> str:
    if "NotImplementedError" in msg:
        return "This step's code isn't written yet."
    if "JSONDecodeError" in msg:
        return "The tool's error came back as plain text (like \"Operation failed\"), not JSON, so it has no errorCategory or isRetryable yet."
    first = msg.strip().splitlines()[0] if msg.strip() else "The test failed."
    first = re.sub(r"^(AssertionError|assert)\s*:?\s*", "", first)
    return first[:300] or "The test failed."


# --- one conversation ------------------------------------------------------------

class ClientProxy:
    """Stands where the Anthropic client goes, so each request is recorded and Practice can swap in its stand-in."""

    def __init__(self, session: "Session"):
        self.session = session
        self.target: Any = None
        self.messages = self

    def create(self, **kwargs: Any) -> Any:
        if self.target is None:
            raise RuntimeError("No Claude to call: switch to Live with an API key, or pick a Try this prompt.")
        r = self.target.messages.create(**kwargs)
        blocks = list(getattr(r, "content", []) or [])
        said = " ".join(getattr(b, "text", "") for b in blocks if getattr(b, "type", "") == "text").strip()
        asks = [getattr(b, "name", "") for b in blocks if getattr(b, "type", "") == "tool_use"]
        self.session.emit({"type": "model", "stop_reason": getattr(r, "stop_reason", None), "text": said[:400], "asks": asks})
        return r


class Session:
    def __init__(self, project: Project, mode: str):
        self.project = project
        self.mode = mode
        self.mods = project.fresh_modules()
        self.signature = project.signature()
        self.backend = self.mods["backend"].demo_backend()
        self.client = ClientProxy(self)
        self.agent = self.mods["agent"].SupportAgent(self.client, self.backend)
        self.turns: list[dict[str, Any]] = []
        self.current: list[dict[str, Any]] | None = None
        self.pending_breaks: list[list[Any]] = []
        self._instrument()

    def emit(self, event: dict[str, Any]) -> None:
        if self.current is not None and len(self.current) < MAX_TURN_EVENTS:
            self.current.append(event)

    def _instrument(self) -> None:
        box = self.agent.toolbox
        backend = self.backend
        original_fail = backend._maybe_fail

        def maybe_fail(op: str) -> None:
            try:
                original_fail(op)
            except Exception as e:  # recorded, then raised as before
                self.emit({"type": "backend_fail", "op": op, "kind": type(e).__name__, "message": str(e)})
                raise

        backend._maybe_fail = maybe_fail

        def wrap_hook(hook: Any) -> Any:
            def traced(call: Any, b: Any) -> Any:
                d = hook(call, b)
                if not getattr(d, "allow", True):
                    self.emit({"type": "hook", "hook": getattr(hook, "__name__", "hook"), "tool": call.name, "reason": getattr(d, "reason", ""), "redirect": getattr(getattr(d, "redirect", None), "name", None)})
                return d

            traced.__name__ = getattr(hook, "__name__", "hook")
            return traced

        box.hooks = [wrap_hook(h) for h in box.hooks]
        original_execute = box.execute

        def execute(calls: list[Any]) -> list[Any]:
            outs = []
            for c in calls:
                verified_before = sorted(box.verified)
                self.emit({"type": "call", "id": c.id, "name": c.name, "input": c.input, "verified": verified_before})
                tickets = len(backend.escalations)
                o = original_execute([c])[0]
                data = practice.parse(o.content)
                self.emit({"type": "error" if o.is_error else "result", "id": c.id, "name": c.name, "content": o.content[:1500], "data": data if isinstance(data, (dict, list)) else None})
                for t in backend.escalations[tickets:]:
                    self.emit({"type": "handoff", "ticket": t})
                outs.append(o)
            return outs

        box.execute = execute

    def stale(self) -> bool:
        return self.project.signature() != self.signature

    def send(self, text: str, try_id: str | None = None) -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        self.current = events
        for op, kind, times in self.pending_breaks:
            self.backend.fail_next(op, kind, times)
            events.append({"type": "broke", "op": op, "kind": kind, "times": times})
        self.pending_breaks = []
        tickets = len(self.backend.escalations)
        models_before = 0
        try:
            if try_id == "s6-recall":
                self._small_talk(events)
            if self.mode == "practice":
                self.client.target = practice.claude_for(try_id) if try_id in practice.PLANS else None
            started = len(events)
            reply = self.agent.handle(text)
            models_before = sum(1 for e in events[started:] if e["type"] == "model")
            if len(self.backend.escalations) > tickets and not any(e["type"] == "handoff" for e in events):
                for t in self.backend.escalations[tickets:]:
                    events.append({"type": "handoff", "ticket": t, "direct": models_before == 0})
            events.append({"type": "agent", "text": reply})
        except NotImplementedError as e:
            m = re.search(r"Step (\d)", str(e))
            events.append({"type": "not_built", "step": int(m.group(1)) if m else None, "message": str(e)})
        except Exception as e:
            name = type(e).__name__
            if name == "LoopLimitError":
                events.append({"type": "loop_limit", "message": str(e)})
            else:
                events.append({"type": "crash", "error": f"{name}: {e}"[:400], "where": self.project.where(traceback.extract_tb(e.__traceback__))})
        finally:
            self.current = None
        events.append({"type": "history", "kept": len(self.agent.messages)})
        turn = {"user": text, "try": try_id, "mode": self.mode, "events": events, "at": time.time()}
        turn["kinds"] = classify(self, turn)
        self.turns.append(turn)
        return turn

    def _small_talk(self, events: list[dict[str, Any]]) -> None:
        """Twelve turns of chit-chat first, so the early details scroll out of the history (step 6)."""
        self.client.target = practice.claude_for("s6-several")
        self.agent.handle("I'm dana@example.com. My headphones (O-5001) broke and where's my laptop, O-5002?")
        filler = practice.PracticeClaude([], lambda t, s: "Happy to help with that.")
        self.client.target = filler
        for i in range(12):
            self.agent.handle(["Thanks!", "One more question.", "How long do refunds take?", "Do you ship abroad?", "OK.", "Great."][i % 6])
        del events[:]
        events.append({"type": "note", "text": "13 earlier turns: the headphones refund and laptop question, then small talk."})

    def snapshot(self) -> dict[str, Any]:
        b = self.backend
        box = self.agent.toolbox
        try:
            facts = box.facts.render()
        except Exception as e:  # the learner's render() may be half-written
            facts = f"(render() raised {type(e).__name__})"
        return {
            "customers": [{"id": c.customer_id, "name": c.name, "email": c.email} for c in b.customers.values()],
            "orders": [{"id": o.order_id, "customer": o.customer_id, "item": o.item, "amount": o.amount, "status": o.status} for o in b.orders.values()],
            "refunds": b.refunds,
            "escalations": b.escalations,
            "verified": sorted(box.verified),
            "facts": facts,
            "messages": len(self.agent.messages),
            "breaks": self.pending_breaks,
            "tools": [{"name": t["name"], "description": t.get("description", "")} for t in self.mods["tools"].TOOLS],
            "limit": getattr(self.mods["policy"], "REFUND_LIMIT", 500),
        }


# --- what just happened ------------------------------------------------------------

def classify(s: Session, turn: dict[str, Any]) -> list[str]:
    """The explanations that fit this turn, most important first."""
    ev = turn["events"]
    try_id = turn.get("try")
    kinds: list[str] = []
    types = [e["type"] for e in ev]
    if "not_built" in types:
        return ["not_built"]
    if "crash" in types:
        return ["crash"]
    if "loop_limit" in types:
        kinds.append("loop_limit")
    agent_text = next((e["text"] for e in ev if e["type"] == "agent"), "") or ""
    calls = [e for e in ev if e["type"] == "call"]
    results = [e for e in ev if e["type"] in ("result", "error")]
    limit = s.snapshot()["limit"]

    if try_id == "s1-sounds-done":
        kinds.append("s1_stopped_early" if agent_text.startswith("All done") else "s1_kept_going")
    elif try_id == "s1-two":
        kinds.append("s1_parallel")
    elif try_id == "s1-simple":
        kinds.append("s1_ran")
    if try_id == "s5-human":
        direct = any(e["type"] == "handoff" and e.get("direct") for e in ev) or ("handoff" in types and "model" not in types)
        kinds.append("s5_now" if direct else "s5_missed")
    if try_id == "s6-recall":
        kept = next((e["kept"] for e in ev if e["type"] == "history"), 0)
        kinds.append("s6_facts" if "$640.00" in s.snapshot()["facts"] else "s6_growing" if kept > 24 else "s6_forgot")
    if try_id == "s6-several":
        kinds.append("s6_facts" if "$" in s.snapshot()["facts"] else "s6_forgot")

    blocked: set[str] = set()
    last_call = None
    for e in ev:
        if e["type"] == "call":
            last_call = e["id"]
        if e["type"] == "hook" and last_call:
            blocked.add(last_call)
        if e["type"] == "hook":
            if e["hook"] == "refund_limit" or e.get("redirect") == "escalate_to_human":
                kinds.append("s4_over_blocked")
            elif e["hook"] == "verified_customer_first":
                kinds.append("s4_other_blocked" if try_id == "s4-someone-else" or e.get("tool") == "process_refund" and any(c.get("verified") for c in calls) else "s4_unverified_blocked")
    fails = {e["op"] for e in ev if e["type"] == "backend_fail" and e["kind"] == "BackendTimeout"}
    for r in results:
        d = r.get("data") if isinstance(r.get("data"), dict) else {}
        if r["type"] == "error" and r["id"] in blocked:
            continue
        if r["type"] == "error":
            cat = d.get("errorCategory") if d else None
            if cat is None:
                kinds.append("s3_generic")
            elif "sent to a person" in str(d.get("message", "")):
                kinds.append("s4_over_blocked")
            elif cat == "transient":
                kinds.append("s3_transient")
            elif cat == "business":
                kinds.append("s3_business")
            elif cat == "validation":
                kinds.append("s3_validation")
            elif cat == "permission":
                kinds.append("s3_permission")
        else:
            if r["name"] in fails:
                kinds.append("s3_retried_inside")
            if r["name"] == "get_customer":
                if d.get("matches"):
                    kinds.append("s3_matches")
                elif try_id == "s3-two-danas":
                    kinds.append("s3_picked_one")
            if r["name"] == "process_refund":
                call = next((c for c in calls if c["id"] == r["id"]), {})
                amount = float(call.get("input", {}).get("amount", 0) or 0)
                who = call.get("input", {}).get("customer_id")
                if amount > limit:
                    kinds.append("s4_over_passed")
                elif not call.get("verified"):
                    kinds.append("s4_unverified_passed")
                elif who and who not in call.get("verified", []):
                    kinds.append("s4_other_passed")
                elif try_id == "s3-refusal":
                    kinds.append("s3_refund_slipped")
                elif try_id == "s5-frustrated":
                    kinds.append("s5_solved")
    if "handoff" in types and try_id != "s5-human":
        kinds.append("s5_ticket")
    seen: list[str] = []
    for k in kinds:
        if k not in seen:
            seen.append(k)
    return seen


def explanation(s: Session, turn: dict[str, Any], kind: str) -> dict[str, Any]:
    e = CONTENT["explain"][kind]
    step = e.get("step") or (turn.get("try") and TRIES.get(turn["try"], (None,))[0])
    body = e["body"]
    if kind == "not_built":
        nb = next((x for x in turn["events"] if x["type"] == "not_built"), {})
        step = nb.get("step") or step
        body = body.replace("{notBuilt}", STEPS.get(step, {}).get("notBuilt", "This part isn't written yet."))
    if "{kept}" in body:
        body = body.replace("{kept}", str(next((x["kept"] for x in turn["events"] if x["type"] == "history"), "all the")))
    if kind == "crash":
        cr = next((x for x in turn["events"] if x["type"] == "crash"), {})
        body = body.replace("{error}", cr.get("error", "an error"))
        ref = cr.get("where")
    else:
        ref = s.project.ref(e.get("ref"))
    return {"kind": kind, "title": e["title"], "body": body, "step": step, "tasks": e.get("tasks") or (STEPS.get(step, {}).get("tasks") if step else []), "refs": [ref] if ref else []}


def explain_live(s: Session, turn: dict[str, Any], current_step: int) -> dict[str, Any]:
    """Claude explains a Live turn: grounded on our guide notes, pointing at the learner's own code."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {"error": "Add ANTHROPIC_API_KEY to .env to have Claude explain."}
    import anthropic

    kinds = turn.get("kinds") or []
    steps = {current_step} | {CONTENT["explain"][k].get("step") for k in kinds if CONTENT["explain"][k].get("step")}
    tasks = sorted({t for n in steps if n in STEPS for t in STEPS[n]["tasks"]})
    files = sorted({CONTENT["refs"][CONTENT["explain"][k]["ref"]][0] for k in kinds if CONTENT["explain"][k].get("ref")} | {"src/support_agent/loop.py"})[:3]
    code = "\n\n".join(f"### {f}\n{s.project.numbered(f)}" for f in files)
    notes = "\n\n".join(NOTES[t] for t in tasks if t in NOTES)
    trace = json.dumps({"customer_said": turn["user"], "events": turn["events"], "built_steps": BUILT.get("built")}, default=str)[:24000]
    system = (
        "You explain to a learner, in plain words, what just happened when they tried their customer support agent in the Support Console. "
        "They are building it step by step for the Claude Certified Architect – Foundations exam and may not be a programmer. "
        "Use only what the trace shows, the code listed, and the study notes given; if something is unclear, say so instead of guessing. "
        "Tie it to the step and exam task it practises. Point to code only as path:line using the numbers in the listings. "
        "Reply with JSON only: {\"title\": one line, \"what_happened\": 2-4 sentences, \"why\": 1-3 sentences, \"lesson\": one sentence tying it to the exam task, \"look_at\": [{\"ref\": \"path:line\", \"what\": short phrase}]}."
    )
    user = f"Current step: {current_step} · {STEPS.get(current_step, {}).get('title', '')}\nExam tasks: {', '.join(tasks)}\n\nStudy notes (from the official guide, in our words):\n{notes}\n\nCode:\n{code}\n\nTrace of this turn (JSON):\n{trace}"
    model = getattr(s.mods["loop"], "MODEL", "claude-opus-5-5")
    try:
        r = anthropic.Anthropic().messages.create(model=model, max_tokens=1500, system=system, messages=[{"role": "user", "content": user}])
    except Exception as e:
        return {"error": f"Claude could not explain this time ({type(e).__name__}). Try again."}
    raw = "".join(getattr(b, "text", "") for b in r.content)
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        out = json.loads(m.group(0)) if m else {}
    except ValueError:
        out = {}
    if not out:
        return {"title": "What just happened", "body": raw.strip()[:2000], "refs": [], "tasks": tasks, "byClaude": True}
    refs = []
    for item in out.get("look_at") or []:
        ref = str(item.get("ref", ""))
        mm = re.match(r"^(src/[\w/]+\.py):(\d+)", ref)
        if mm and (s.project.root / mm.group(1)).exists() and int(mm.group(2)) <= len((s.project.root / mm.group(1)).read_text().splitlines()):
            refs.append({"ref": ref, "what": str(item.get("what", ""))[:120]})
    body = " ".join(x for x in (out.get("what_happened"), out.get("why")) if x)
    return {"title": str(out.get("title", "What just happened"))[:140], "body": body[:1600], "lesson": str(out.get("lesson", ""))[:300], "lookAt": refs[:4], "tasks": tasks, "byClaude": True}


# --- the web server ----------------------------------------------------------------

LOCK = threading.Lock()
BUILT: dict[str, Any] = {"built": {}, "running": False, "signature": None}
STATE: dict[str, Any] = {}


def refresh_built(project: Project) -> None:
    """Runs every step's tests in the background to know which steps are built."""
    if BUILT["running"]:
        return
    BUILT["running"] = True

    def work() -> None:
        try:
            sig = project.signature()
            r = run_tests(project, None)
            built: dict[int, bool] = {}
            for t in r.get("tests", []):
                if t["step"]:
                    built[t["step"]] = built.get(t["step"], True) and t["passed"]
            BUILT.update(built=built, signature=sig)
        finally:
            BUILT["running"] = False

    threading.Thread(target=work, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    server_version = "SupportConsole/1"

    def log_message(self, *args: Any) -> None:  # quiet
        pass

    def _ok_host(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("cache-control", "no-store")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self._ok_host():
            return self._json({"error": "forbidden"}, 403)
        if self.path in ("/", "/index.html"):
            body = (HERE / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/content":
            return self._json({"steps": CONTENT["steps"]})
        if self.path == "/api/state":
            s: Session = STATE["session"]
            if BUILT["signature"] != STATE["project"].signature():
                refresh_built(STATE["project"])
            return self._json({"root": str(STATE["project"].root), "mode": s.mode, "hasKey": bool(os.environ.get("ANTHROPIC_API_KEY")), "built": BUILT["built"], "checking": BUILT["running"], "stale": s.stale(), "turns": len(s.turns), "data": s.snapshot()})
        self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        if not self._ok_host() or "application/json" not in (self.headers.get("content-type") or ""):
            return self._json({"error": "forbidden"}, 403)
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        except ValueError:
            return self._json({"error": "bad json"}, 400)
        project: Project = STATE["project"]
        with LOCK:
            s: Session = STATE["session"]
            if self.path == "/api/reset" or (self.path in ("/api/send", "/api/try") and s.stale()):
                fresh = s.stale()
                STATE["session"] = s = Session(project, body.get("mode") or s.mode)
                if self.path == "/api/reset":
                    return self._json({"ok": True})
                if fresh:
                    body["_fresh"] = True
            if self.path == "/api/mode":
                mode = body.get("mode")
                if mode not in ("practice", "live"):
                    return self._json({"error": "unknown mode"}, 400)
                if mode == "live" and not os.environ.get("ANTHROPIC_API_KEY"):
                    return self._json({"error": "Live mode needs ANTHROPIC_API_KEY in your project's .env file."}, 400)
                STATE["session"] = Session(project, mode)
                return self._json({"ok": True})
            if self.path == "/api/send":
                if s.mode != "live":
                    return self._json({"error": "Typing your own message needs Live mode. In Practice, pick a Try this prompt."}, 400)
                text = str(body.get("text", "")).strip()[:2000]
                if not text:
                    return self._json({"error": "Type a message first."}, 400)
                import anthropic

                s.client.target = anthropic.Anthropic()
                turn = s.send(text)
                return self._json(self._turn(s, turn, body))
            if self.path == "/api/try":
                tid = body.get("id")
                if tid not in TRIES:
                    return self._json({"error": "unknown prompt"}, 400)
                stepn, t = TRIES[tid]
                if t.get("action") == "tools":
                    return self._json({"tools": s.snapshot()["tools"], "explain": explanation(s, {"events": [], "try": tid}, "s2_tools")})
                if t.get("live") and s.mode != "live":
                    return self._json({"error": "This one needs Live mode: it shows which tool the real Claude picks."}, 400)
                if t.get("break"):
                    s.pending_breaks.append(t["break"])
                if s.mode == "live":
                    import anthropic

                    s.client.target = anthropic.Anthropic()
                    text = "What did my laptop cost?" if tid == "s6-recall" else t["prompt"]
                else:
                    text = "What did my laptop cost?" if tid == "s6-recall" else t["prompt"]
                turn = s.send(text, tid)
                return self._json(self._turn(s, turn, body))
            if self.path == "/api/break":
                op, kind = body.get("op"), body.get("kind")
                if op not in ("get_customer", "lookup_order", "process_refund", "escalate_to_human") or kind not in ("timeout", "denied"):
                    return self._json({"error": "unknown break"}, 400)
                s.pending_breaks.append([op, kind, int(body.get("times") or 1)])
                return self._json({"ok": True})
            if self.path == "/api/customer":
                name, email = str(body.get("name", "")).strip()[:60], str(body.get("email", "")).strip()[:80]
                if not name or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
                    return self._json({"error": "Give a name and an email like alex@example.com."}, 400)
                n = 1001 + len(s.backend.customers)
                while f"C-{n}" in s.backend.customers:
                    n += 1
                s.backend.customers[f"C-{n}"] = s.mods["backend"].Customer(f"C-{n}", name, email)
                return self._json({"ok": True, "id": f"C-{n}"})
            if self.path == "/api/explain":
                i = int(body.get("turn", -1))
                if not s.turns or not (-len(s.turns) <= i < len(s.turns)):
                    return self._json({"error": "No such turn."}, 400)
                return self._json(explain_live(s, s.turns[i], int(body.get("step") or 1)))
            if self.path == "/api/tests":
                step = body.get("step")
                return self._json(run_tests(project, int(step) if step else None))
        self._json({"error": "not found"}, 404)

    def _turn(self, s: Session, turn: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
        cards = [explanation(s, turn, k) for k in turn["kinds"][:2]]
        return {"turn": {k: turn[k] for k in ("user", "try", "mode", "events", "kinds")}, "index": len(s.turns) - 1, "explain": cards, "fresh": bool(body.get("_fresh"))}


def main() -> None:
    ap = argparse.ArgumentParser(description="CCA Prep Studio Support Console")
    ap.add_argument("--project", default=".")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    project = Project(Path(args.project).resolve())
    STATE["project"] = project
    STATE["session"] = Session(project, "practice")
    refresh_built(project)
    server = None
    for port in range(args.port, args.port + 20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if server is None:
        raise SystemExit("No free port between 8765 and 8784.")
    print(f"Support Console: http://127.0.0.1:{server.server_address[1]}  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
