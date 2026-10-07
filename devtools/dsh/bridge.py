"""Small async job bridge. Task copies isolate edits, not operating-system access."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

REPO = Path(__file__).resolve().parents[2]
TERMINAL = {"completed", "failed", "cancelled", "timed_out", "scope_violation", "interrupted"}


def save(path, value):
    path = Path(path)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def git(repo, *args):
    result = subprocess.run(["git", "-c", "safe.directory=" + str(repo), "-C", str(repo), *args],
                            capture_output=True, encoding="utf-8", errors="replace", timeout=60)
    if result.returncode:
        raise RuntimeError("Git operation failed: " + result.stderr[:1000])
    return result.stdout


def validate(task, allowed_paths, timeout_seconds, max_tokens):
    if not isinstance(task, str) or not task.strip() or len(task) > 16000:
        raise ValueError("task must contain 1..16000 characters")
    if not isinstance(allowed_paths, list) or not 1 <= len(allowed_paths) <= 30:
        raise ValueError("allowed_paths must list 1..30 exact files or directory prefixes ending in /")
    for path in allowed_paths:
        if (not isinstance(path, str) or not path or "\\" in path or ":" in path
                or path.startswith("/") or any(p in ("", ".", "..") for p in path.rstrip("/").split("/"))
                or path.split("/")[0] in (".git", ".env", ".dsh-tasks", "sources")
                or any(p.startswith(".env") or p.startswith(".venv") for p in path.split("/"))):
            raise ValueError("allowed_paths contains an invalid or private path")
    for name, value, low, high in (("timeout_seconds", timeout_seconds, 30, 900),
                                   ("max_tokens", max_tokens, 256, 8192)):
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"{name} must be an integer in {low}..{high}")


def allowed(path, paths):
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in paths)


def collect(workspace, base_commit, paths):
    # Stage only inside this independent clone; diff includes tracked, new and committed edits.
    git(workspace, "add", "-A", "--", ".")
    changed = git(workspace, "diff", "--cached", "--name-only", "--no-renames", "-z", base_commit).split("\0")
    changed = [p for p in changed if p]
    violations = [p for p in changed if not allowed(p, paths)]
    for p in changed:
        candidate = workspace / p
        if candidate.is_symlink():
            violations.append(p)
    diff = git(workspace, "diff", "--cached", "--binary", "--no-ext-diff", "--no-renames", base_commit)
    return {"changed_files": changed, "scope_violations": sorted(set(violations)),
            "diff": diff}


class Jobs:
    def __init__(self, repo=REPO, root=None):
        self.repo = Path(repo).resolve()
        self.root = Path(root).resolve() if root else self.repo / ".dsh-tasks"
        self.root.mkdir(parents=True, exist_ok=True)

    def directory(self, task_id):
        if not isinstance(task_id, str) or not re.fullmatch(r"[0-9a-f]{32}", task_id):
            raise ValueError("invalid task_id")
        directory = self.root / task_id
        if not directory.is_dir():
            raise ValueError("unknown task_id")
        return directory

    def start(self, task, allowed_paths, timeout_seconds=300, max_tokens=4096):
        validate(task, allowed_paths, timeout_seconds, max_tokens)
        task_id = uuid.uuid4().hex
        lock = self.root / "active.lock"
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            previous = lock.read_text(encoding="ascii").strip()
            if re.fullmatch(r"[0-9a-f]{32}", previous) and self.get(previous)["status"] in TERMINAL:
                # Serial start/cancel requests are required; stale records remain inspectable.
                lock.unlink()
                return self.start(task, allowed_paths, timeout_seconds, max_tokens)
            raise ValueError("A dsh task is already active; inspect or cancel it first") from None
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(task_id)
        directory = self.root / task_id
        directory.mkdir()
        try:
            request = {"task_id": task_id, "task": task, "allowed_paths": allowed_paths,
                       "timeout_seconds": timeout_seconds, "max_tokens": max_tokens,
                       "base_commit": git(self.repo, "rev-parse", "HEAD").strip(),
                       "repo": str(self.repo), "created_at": time.time()}
            save(directory / "request.json", request)
            save(directory / "state.json", {"task_id": task_id, "status": "queued"})
            # No key in argv or log files. Worker loads credentials privately from the source repo.
            with (directory / "worker.log").open("w", encoding="utf-8") as output:
                proc = subprocess.Popen([sys.executable, "-m", "devtools.dsh.worker", str(directory)],
                    cwd=self.repo, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            save(directory / "owner.json", {"pid": proc.pid, "started_at": time.time()})
        except Exception:
            save(directory / "state.json", {"task_id": task_id, "status": "failed", "error": "Task could not start"})
            if lock.read_text(encoding="ascii").strip() == task_id:
                lock.unlink()
            raise
        return self.get(task_id)

    def get(self, task_id):
        directory = self.directory(task_id)
        state = read(directory / "state.json")
        request = read(directory / "request.json")
        # Finite task lifetime also bounds records after an abrupt interpreter/host failure.
        if state["status"] not in TERMINAL and time.time() > request["created_at"] + request["timeout_seconds"] + 90:
            state = dict(state, status="interrupted", error="Worker did not record a terminal state; inspect local evidence")
            save(directory / "state.json", state)
        return dict(state, task_directory=str(directory), base_commit=request["base_commit"],
                    workspace=str(directory / "workspace"), patch_path=str(directory / "changes.patch"))

    def cancel(self, task_id):
        directory = self.directory(task_id)
        state = self.get(task_id)
        if state["status"] not in TERMINAL:
            (directory / "cancel").touch(exist_ok=True)
            return dict(state, cancellation_requested=True)
        return state


def main():
    parser = argparse.ArgumentParser(description="Delegate a bounded developer task to DeepSeek Harness")
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start")
    start.add_argument("--task", required=True)
    start.add_argument("--allow", action="append", required=True)
    start.add_argument("--timeout", type=int, default=300)
    start.add_argument("--max-tokens", type=int, default=4096)
    for command in ("get", "cancel"):
        commands.add_parser(command).add_argument("task_id")
    args = parser.parse_args()
    jobs = Jobs()
    if args.command == "start":
        result = jobs.start(args.task, args.allow, args.timeout, args.max_tokens)
    else:
        result = getattr(jobs, args.command)(args.task_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
