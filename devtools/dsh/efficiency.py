"""Compact delegation policy and usage evidence; no engineering or credentials."""
from copy import deepcopy

EFFORTS = {"off", "low", "high", "max"}


def reasoning_effort(runtime):
    value = runtime.get("reasoning_effort", "off")
    if type(value) is not str or value not in EFFORTS:
        raise ValueError("DSH reasoning_effort must be off, low, high or max")
    return value


def task_prompt(request):
    return (
        "Execute this already-approved routine task in the independent clone. Read AGENTS.md once; "
        "the human explicitly delegates this task to YOU, so do not delegate it again. "
        "Read only the named sources needed for the task, not the entire roadmap/history. "
        "The input/output contract is settled: implement it directly, do not repeatedly redesign it. "
        "For a genuine ambiguity, report one blocking question and stop; do not invent engineering values. "
        "Only edit: " + ", ".join(request["allowed_paths"]) + ". "
        "No .env/credentials/user data/other workspaces/network/desktop applications/dependency installs/child agents. "
        "No commits/pushes. Preserve engineering algorithms and scope. "
        "Run only the supplied focused validation. Return <=12 lines: changed paths, tests actually run, "
        "results, unresolved issues. Put code in files, not the final response. Task:\n" + request["task"]
    )


class UsageEvidence:
    """Count final assistant messages only; nested stream chunks duplicate usage."""
    def __init__(self):
        self.seen = set()
        self.messages = 0
        self.totals = {}

    def observe(self, method, payload):
        event = payload.get("event", {}) if isinstance(payload, dict) else {}
        if method != "session.event" or not isinstance(event, dict) or event.get("type") != "assistant/message":
            return
        seq = event.get("seq")
        if type(seq) is not int or seq in self.seen:
            return
        self.seen.add(seq)
        self.messages += 1
        data = event.get("data", {})
        usage = data.get("usage") if isinstance(data, dict) else None
        if not isinstance(usage, dict):
            return
        for key in ("inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens", "totalTokens"):
            value = usage.get(key)
            if type(value) is int and value >= 0:
                self.totals[key] = self.totals.get(key, 0) + value

    def summary(self):
        return {"assistant_requests": self.messages, "usage": deepcopy(self.totals) if self.totals else None,
                "usage_source": "unique final assistant/message events; reported tokens, not billed currency"}
