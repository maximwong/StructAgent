"""Minimal MCP stdio transport: no application runtime dependencies or network listener."""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from devtools.dsh.bridge import Jobs

TOOLS = [
    {"name": "start_deepseek_task", "description": "Delegate a bounded development task to local DeepSeek Harness in an independent clone. Returns task_id immediately. Never applies changes. Shell has local OS access, not a security sandbox.",
     "inputSchema": {"type": "object", "properties": {
         "task": {"type": "string", "minLength": 1, "maxLength": 16000},
         "allowed_paths": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 30},
         "timeout_seconds": {"type": "integer", "minimum": 30, "maximum": 900, "default": 300},
         "max_tokens": {"type": "integer", "minimum": 256, "maximum": 8192, "default": 4096}},
         "required": ["task", "allowed_paths"], "additionalProperties": False}},
    {"name": "get_deepseek_task", "description": "Read delegated task state, summary, changed paths, scope violations and private patch path. Inspect and verify the patch before integrating.",
     "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"}}, "required": ["task_id"], "additionalProperties": False}},
    {"name": "cancel_deepseek_task", "description": "Request cancellation of this bridge's task; worker closes its owned runtime/process tree. Does not close the DSH desktop application.",
     "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"}}, "required": ["task_id"], "additionalProperties": False}},
]


def handle(message, jobs):
    method = message.get("method")
    if method == "initialize":
        version = message.get("params", {}).get("protocolVersion", "2024-11-05")
        if version not in {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}:
            version = "2024-11-05"
        return {"protocolVersion": version, "capabilities": {"tools": {}},
                "serverInfo": {"name": "structagent-dsh-dev", "version": "0.1.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        params = message.get("params", {})
        args = params.get("arguments", {})
        operations = {"start_deepseek_task": jobs.start, "get_deepseek_task": jobs.get,
                      "cancel_deepseek_task": jobs.cancel}
        try:
            if params.get("name") not in operations:
                raise ValueError("unknown tool")
            value = operations[params["name"]](**args)
            return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}], "isError": False}
        except Exception as exc:
            # Infrastructure messages are bounded; no credential values enter the server.
            return {"content": [{"type": "text", "text": str(exc)[:1500]}], "isError": True}
    raise ValueError("unsupported method")


def main():
    jobs = Jobs()
    for line in sys.stdin:
        message = None
        try:
            message = json.loads(line)
            if "id" not in message:  # initialized/cancel notifications never have a response
                continue
            response = {"jsonrpc": "2.0", "id": message["id"], "result": handle(message, jobs)}
        except Exception:
            response = {"jsonrpc": "2.0", "id": message.get("id") if isinstance(message, dict) else None,
                        "error": {"code": -32602, "message": "Invalid MCP request"}}
        print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
