"""Practice mode: a stand-in for Claude that needs no API key.

It is not a language model. Each "Try this" prompt comes with a short plan
(which tools to ask for, in what order, and how to answer), and the stand-in
follows it while reading what YOUR code returns: a structured error it can
act on, a bare "Operation failed", a refusal from a hook. So what you see in
Practice is how your own loop, tools, errors and hooks behave; only Claude's
side is scripted. Live mode uses the real Claude with your API key.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Callable


def text(t: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=t)


def tool_use(id: str, name: str, /, **input: Any) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


def reply(*blocks: SimpleNamespace, stop_reason: str) -> SimpleNamespace:
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason, usage=None)


def parse(content: Any) -> Any:
    try:
        return json.loads(content) if isinstance(content, str) else None
    except ValueError:
        return None


class Turn:
    """What the stand-in can see of the current customer turn: the tool results so far."""

    def __init__(self, messages: list[dict[str, Any]]):
        # Everything after the customer's latest plain-text message.
        start = max((i for i, m in enumerate(messages) if m["role"] == "user" and isinstance(m["content"], str)), default=0)
        self.calls: list[dict[str, Any]] = []  # {"name", "input", "result", "is_error"}
        pending: dict[str, dict[str, Any]] = {}
        for m in messages[start + 1 :]:
            if m["role"] == "assistant":
                for b in m["content"]:
                    if getattr(b, "type", None) == "tool_use" or (isinstance(b, dict) and b.get("type") == "tool_use"):
                        bid = b.id if hasattr(b, "id") else b["id"]
                        pending[bid] = {"name": b.name if hasattr(b, "name") else b["name"], "input": b.input if hasattr(b, "input") else b["input"]}
            elif isinstance(m["content"], list):
                for r in m["content"]:
                    if isinstance(r, dict) and r.get("type") == "tool_result" and r.get("tool_use_id") in pending:
                        c = pending.pop(r["tool_use_id"])
                        c["result"] = r.get("content")
                        c["is_error"] = bool(r.get("is_error"))
                        self.calls.append(c)

    @property
    def last(self) -> dict[str, Any] | None:
        return self.calls[-1] if self.calls else None

    def data(self, name: str) -> Any:
        for c in reversed(self.calls):
            if c["name"] == name and not c["is_error"]:
                return parse(c["result"])
        return None

    def tries(self, tool: str, /, **input: Any) -> int:
        return sum(1 for c in self.calls if c["name"] == tool and all(c["input"].get(k) == v for k, v in input.items()))


Step = tuple  # ("tool", name, input) | ("tools", [(name, input), ...]) | ("say_and_tool", text, name, input)


def _made(step: Step, turn: Turn) -> bool:
    items = step[1] if step[0] == "tools" else [(step[2], step[3])] if step[0] == "say_and_tool" else [(step[1], step[2])]
    return all(turn.tries(n, **i) > 0 for n, i in items)


class PracticeClaude:
    """Follows a plan of tool calls, reacts to errors the way Claude would, then answers with ``finish``."""

    def __init__(self, plan: list[Step], finish: Callable[[Turn, str], str]):
        self.plan = plan
        self.finish = finish
        self.messages = self
        self.n = 0
        self.system = ""

    def _id(self) -> str:
        self.n += 1
        return f"toolu_practice_{self.n:03d}"

    def create(self, **kwargs: Any) -> SimpleNamespace:
        turn = Turn(kwargs.get("messages", []))
        last = turn.last
        if last and last["is_error"]:
            answer = self._after_error(turn, last)
            if answer is not None:
                return answer
        self.system = kwargs.get("system", "")
        # The first plan step whose calls have not all been made yet (a retried call counts once).
        used = next((k for k, step in enumerate(self.plan) if not _made(step, turn)), len(self.plan))
        if used < len(self.plan):
            step = self.plan[used]
            if step[0] == "tool":
                return reply(tool_use(self._id(), step[1], **step[2]), stop_reason="tool_use")
            if step[0] == "tools":
                return reply(*[tool_use(self._id(), n, **i) for n, i in step[1]], stop_reason="tool_use")
            if step[0] == "say_and_tool":
                return reply(text(step[1]), tool_use(self._id(), step[2], **step[3]), stop_reason="tool_use")
        # The answer may read the system prompt and the whole conversation it was sent.
        return reply(text(self.finish(turn, f"{self.system}\n{kwargs.get('messages', '')}")), stop_reason="end_turn")

    def _after_error(self, turn: Turn, last: dict[str, Any]) -> SimpleNamespace | None:
        data = parse(last["result"])
        if not isinstance(data, dict) or "errorCategory" not in data:
            # A bare "Operation failed": nothing to decide with.
            return reply(text("I'm sorry, something went wrong on our side and I couldn't finish that. Please try again later."), stop_reason="end_turn")
        cat = data.get("errorCategory")
        msg = str(data.get("message", ""))
        if "sent to a person" in msg:
            say = data.get("customerMessage") or "That refund is more than I can approve myself, so I've passed it to a colleague who can. They'll be in touch shortly."
            return reply(text(say), stop_reason="end_turn")
        if cat == "transient" and data.get("isRetryable") and turn.tries(last["name"], **last["input"]) < 2:
            return reply(tool_use(self._id(), last["name"], **last["input"]), stop_reason="tool_use")
        if cat == "transient":
            return reply(text("Our order system isn't answering right now. I've tried twice; could you give it a few minutes and ask me again?"), stop_reason="end_turn")
        if cat == "business":
            return reply(text(data.get("customerMessage") or f"I'm not able to do that: {msg}"), stop_reason="end_turn")
        if cat == "validation":
            if last["name"] == "lookup_order":
                return reply(text("I couldn't find that order. Order numbers look like O-5001; could you check yours?"), stop_reason="end_turn")
            if last["name"] == "get_customer":
                return reply(text("I couldn't find an account with those details. Could you give me the email on your account?"), stop_reason="end_turn")
            return reply(text(f"Something in that request wasn't right: {msg}"), stop_reason="end_turn")
        if cat == "permission":
            if "verif" in msg.lower() or "get_customer" in msg:
                return reply(text("Before I can do that, I need to confirm who you are. What's the email on your account?"), stop_reason="end_turn")
            return reply(text("I'm not able to do that from here. I can pass it to a colleague if you'd like."), stop_reason="end_turn")
        return None


# --- the plans behind each "Try this" prompt ------------------------------------

def _order(turn: Turn) -> dict[str, Any] | None:
    d = turn.data("lookup_order")
    if isinstance(d, dict):
        return d.get("order") or (d.get("orders") or [None])[0]
    return None


def _where(turn: Turn, system: str = "") -> str:
    o = _order(turn)
    if not o:
        return "I couldn't find that order."
    if o.get("status") == "delivered":
        return f"Order {o.get('order_id')}, your {o.get('item', 'order').lower()}, was delivered on {o.get('delivered_on')}."
    return f"Order {o.get('order_id')}, your {o.get('item', 'order').lower()}, has {o.get('status')} and is on its way."


def _refunded(turn: Turn, system: str = "") -> str:
    d = turn.data("process_refund") or {}
    amount = d.get("amount")
    return f"Done. I've refunded ${float(amount):.2f} ({d.get('refund_id', 'refund')}). You'll see it on your card in a few days." if amount else "Done, your refund is on its way."


def _two(turn: Turn, system: str = "") -> str:
    seen = [parse(c["result"]) for c in turn.calls if c["name"] == "lookup_order" and not c["is_error"]]
    parts = []
    for d in seen:
        o = (d or {}).get("order") or {}
        if o:
            parts.append(f"{o.get('order_id')} ({o.get('item')}) is {o.get('status')}")
    return ("Here's both: " + "; ".join(parts) + ".") if parts else "I couldn't find those orders."


def _matches(turn: Turn, system: str = "") -> str:
    d = turn.data("get_customer") or {}
    if isinstance(d, dict) and d.get("matches"):
        return f"I found {len(d['matches'])} customers called Dana Ortiz. To make sure I have the right account, what's your email?"
    c = (d or {}).get("customer") or {}
    return f"Thanks, {c.get('name', 'there')}. I've found your account ({c.get('customer_id')})."


def _several(turn: Turn, system: str = "") -> str:
    return "Two things, one at a time: 1) your headphones (O-5001) are within the return window, so I've refunded $120.00; 2) your laptop (O-5002) was delivered on 2026-10-06."


PLANS: dict[str, tuple[list[Step], Callable[..., str]]] = {
    # Step 1 · the loop
    "s1-simple": ([("tool", "get_customer", {"email": "dana@example.com"}), ("tool", "lookup_order", {"order_id": "O-5001"})], _where),
    "s1-sounds-done": ([("tool", "get_customer", {"email": "dana@example.com"}), ("say_and_tool", "All done! Let me just check one thing.", "lookup_order", {"order_id": "O-5001"})], _where),
    "s1-two": ([("tool", "get_customer", {"email": "dana@example.com"}), ("tools", [("lookup_order", {"order_id": "O-5001"}), ("lookup_order", {"order_id": "O-5002"})])], _two),
    # Step 3 · errors
    "s3-where": ([("tool", "get_customer", {"email": "sam@example.com"}), ("tool", "lookup_order", {"order_id": "O-5003"})], _where),
    "s3-timeout": ([("tool", "get_customer", {"email": "sam@example.com"}), ("tool", "lookup_order", {"order_id": "O-5003"})], _where),
    "s3-down": ([("tool", "get_customer", {"email": "sam@example.com"}), ("tool", "lookup_order", {"order_id": "O-5003"})], _where),
    "s3-refusal": ([("tool", "get_customer", {"email": "sam@example.com"}), ("tool", "process_refund", {"customer_id": "C-1002", "order_id": "O-5004", "amount": 58.0, "reason": "broken"})], _refunded),
    "s3-bad-id": ([("tool", "get_customer", {"email": "sam@example.com"}), ("tool", "lookup_order", {"order_id": "5003"})], _where),
    "s3-two-danas": ([("tool", "get_customer", {"name": "Dana Ortiz"})], _matches),
    # Step 4 · hooks
    "s4-under": ([("tool", "get_customer", {"email": "dana@example.com"}), ("tool", "process_refund", {"customer_id": "C-1001", "order_id": "O-5001", "amount": 120.0, "reason": "broken"})], _refunded),
    "s4-over": ([("tool", "get_customer", {"email": "dana@example.com"}), ("tool", "process_refund", {"customer_id": "C-1001", "order_id": "O-5002", "amount": 640.0, "reason": "screen cracked"})], _refunded),
    "s4-no-id": ([("tool", "process_refund", {"customer_id": "C-1001", "order_id": "O-5001", "amount": 120.0, "reason": "broken"})], _refunded),
    "s4-someone-else": ([("tool", "get_customer", {"email": "dana@example.com"}), ("tool", "process_refund", {"customer_id": "C-1002", "order_id": "O-5003", "amount": 35.0, "reason": "changed my mind"})], _refunded),
    # Step 5 · handoffs (the explicit request never reaches Claude once step 5 is built)
    "s5-human": ([], lambda t, s: "I understand. Let me see what I can do first: what's the email on your account?"),
    "s5-frustrated": ([("tool", "get_customer", {"email": "dana@example.com"}), ("tool", "process_refund", {"customer_id": "C-1001", "order_id": "O-5001", "amount": 120.0, "reason": "broken"})], _refunded),
    "s5-over": ([("tool", "get_customer", {"email": "dana@example.com"}), ("tool", "process_refund", {"customer_id": "C-1001", "order_id": "O-5002", "amount": 640.0, "reason": "screen cracked"})], _refunded),
    # Step 6 · long conversations
    "s6-several": ([("tool", "get_customer", {"email": "dana@example.com"}), ("tools", [("lookup_order", {"order_id": "O-5001"}), ("lookup_order", {"order_id": "O-5002"})]), ("tool", "process_refund", {"customer_id": "C-1001", "order_id": "O-5001", "amount": 120.0, "reason": "broken"})], _several),
    "s6-recall": ([], lambda t, s: "Your laptop, order O-5002, was $640.00; it's in the case facts I keep for this conversation." if "$640.00" in s else "Your laptop, order O-5002, was $640.00." if "640.0" in s else "I'm sorry, I no longer have the details from earlier in our chat. Could you give me the order number again?"),
}


def claude_for(try_id: str) -> PracticeClaude:
    plan, finish = PLANS[try_id]
    return PracticeClaude(plan, finish)
