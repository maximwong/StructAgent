"""Owned Windows worker, with a kill-on-close Job Object for its descendants."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

from .bridge import REPO, collect, git, read, remaining, save, write_patch


def redact(text, secret=""):
    if secret:
        text = text.replace(secret, "[REDACTED]")
    return re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[REDACTED]", text)


def owned_job():
    if os.name != "nt":
        raise RuntimeError("This first developer bridge requires Windows Job Objects")
    import win32api
    import win32job
    handle = win32job.CreateJobObject(None, "")
    info = win32job.QueryInformationJobObject(handle, win32job.JobObjectExtendedLimitInformation)
    info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(handle, win32job.JobObjectExtendedLimitInformation, info)
    win32job.AssignProcessToJobObject(handle, win32api.GetCurrentProcess())
    return handle  # Keep alive until worker exits; do not close during result persistence.


def execute(directory):
    request = read(directory / "request.json")
    task_id = request["task_id"]
    state = {"task_id": task_id, "status": "running", "started_at": time.time()}
    save(directory / "state.json", state)
    secret = ""
    harness = None
    holder = {}
    done = threading.Event()
    stop_status = None
    process_job = None
    deadline = request["created_at"] + request["timeout_seconds"]
    workspace = directory / "workspace"
    try:
        process_job = owned_job()
        from config import load_settings
        from deepseek_harness import DeepSeekHarness
        settings = load_settings(Path(request["repo"]) / ".env")
        secret = settings.api_key
        runtime = read(Path(request["repo"]) / ".dsh-tasks" / "config.json")
        launcher = Path(runtime["dsh_bin"])
        if not launcher.is_file():
            raise ValueError("Configured DSH CLI does not exist")
        # Independent clone, not a shared worktree: no source index or refs are writable through Git.
        source = Path(request["repo"])
        subprocess.run(["git", "-c", "safe.directory=" + source.as_posix(),
                        "-c", "safe.directory=" + (source / ".git").as_posix(), "clone", "--no-hardlinks",
                        "--quiet", "--no-checkout", source.as_posix(), str(workspace)],
                       check=True, capture_output=True, timeout=remaining(deadline))
        git(workspace, "checkout", "--detach", request["base_commit"], deadline=deadline)
        git(workspace, "remote", "remove", "origin", deadline=deadline)
        if (directory / "cancel").exists() or time.time() >= deadline:
            state["status"] = "cancelled" if (directory / "cancel").exists() else "timed_out"
            return process_job
        # Keep only OS/runtime variables. The job does not inherit unrelated service credentials.
        keep = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "USERPROFILE",
                "LOCALAPPDATA", "APPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PATHEXT"}
        for key in list(os.environ):
            if key.upper() not in keep:
                del os.environ[key]
        prompt = (
            "You are a delegated development agent. Work only in the current independent clone. "
            "Read AGENTS.md first and relevant source. Do not access .env, other workspaces, user data, "
            "credentials, desktop applications, network, or remote repositories. Do not commit, push, "
            "install dependencies, or create child agents. Do not change engineering algorithms unless "
            "the task explicitly requests it. Only edit these paths: " + json.dumps(request["allowed_paths"]) +
            ". Run focused tests using the supplied Python executable if appropriate. "
            "Return a concise summary, exact tests run and results, and unresolved issues. "
            "Do not claim tests you did not run. Task:\n" + request["task"])
        harness = DeepSeekHarness(
            dsh_bin=str(launcher), profile="sdk-minimal", cwd=str(workspace),
            dsh_home=str(directory / "harness-home"),
            patches=(str(REPO / "devtools" / "dsh" / "privacy.patch.yml"),),
            provider="deepseek-official", model=runtime.get("model", "deepseek-flash"),
            # Harness uses the Messages API; the product uses Chat Completions at a different root.
            api_key=secret, base_url="https://api.deepseek.com/anthropic", max_tokens=request["max_tokens"],
            initialize_timeout_seconds=min(30, remaining(deadline)),
            request_timeout_seconds=30, shutdown_timeout_seconds=1,
        )
        def notification(item):
            # Evidence stays private; never expose complete event streams as MCP output.
            value = redact(json.dumps({"method": item.method, "payload": item.payload}, ensure_ascii=False), secret)
            with (directory / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(value + "\n")

        def run():
            try:
                holder["result"] = harness.run(prompt, session_id=task_id, on_notification=notification)
            except Exception as exc:
                holder["error"] = redact(str(exc), secret)[:3000]
            finally:
                done.set()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        while not done.wait(0.2):
            if (directory / "cancel").exists():
                stop_status = "cancelled"
                break
            if time.time() >= deadline:
                stop_status = "timed_out"
                break
        harness.close()
        thread.join(timeout=3)
        if thread.is_alive():
            # Avoid reading files while a child can still edit; Job Object cleans up on process exit.
            state.update(status=stop_status or "failed", error="Runtime did not stop; inspect private workspace")
        else:
            result = holder.get("result")
            state.update(status=stop_status or ("completed" if result and result.finish_reason == "completed" else "failed"))
            if result:
                state["summary"] = redact(result.final_response, secret)[:12000]
                state["finish_reason"] = result.finish_reason
                if result.finish_reason != "completed":
                    for event in reversed(result.events):
                        if event.get("type") == "turn/end":
                            reason = event.get("data", {}).get("reason", {})
                            state["error"] = redact(json.dumps(reason, ensure_ascii=False), secret)[:3000]
                            break
            if holder.get("error"):
                state["error"] = holder["error"]
            evidence = collect(workspace, request["base_commit"], request["allowed_paths"], deadline=deadline)
            # Git patch hunks require LF, including when the reviewed working file currently uses LF.
            write_patch(directory / "changes.patch", redact(evidence.pop("diff"), secret))
            state.update(evidence)
            if evidence["scope_violations"]:
                state["status"] = "scope_violation"
    except (TimeoutError, subprocess.TimeoutExpired) as exc:
        state.update(status=stop_status or "timed_out", error=redact(str(exc), secret)[:3000])
    except Exception as exc:
        state.update(status="failed", error=redact(str(exc), secret)[:3000])
    finally:
        if harness:
            try:
                harness.close()
            except Exception as exc:
                state.update(status="failed", error="Runtime cleanup failed: " + redact(str(exc), secret)[:1500])
        state["finished_at"] = time.time()
        save(directory / "state.json", state)
        lock = directory.parent / "active.lock"
        if lock.exists() and lock.read_text(encoding="ascii").strip() == task_id:
            lock.unlink()
        # process_job must stay referenced until interpreter exit, including exceptions.
        return process_job


if __name__ == "__main__":
    _job = execute(Path(sys.argv[1]).resolve())
