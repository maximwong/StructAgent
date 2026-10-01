"""Bounded cloud calls; no SDK dependency, automatic retry or raw-response logging."""

import json
from pathlib import Path
import subprocess
import sys

from .json_utils import strict_object


class GatewayError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class DeepSeekGateway:
    def __init__(self, settings):
        self.settings = settings

    def complete(self, messages):
        payload = {"api_key": self.settings.api_key, "base_url": self.settings.base_url,
                   "model": self.settings.model, "timeout_seconds": self.settings.timeout_seconds,
                   "messages": messages}
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(body) > 200_000:
            raise GatewayError("api_request_too_large", "API request is too large.")
        try:
            process = subprocess.run(
                [sys.executable, "-I", str(Path(__file__).with_name("_deepseek_worker.py"))],
                input=body, capture_output=True, timeout=self.settings.timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
        except subprocess.TimeoutExpired:
            # subprocess.run kills and waits for its child on timeout, including stalled HTTP headers.
            raise GatewayError("api_timeout", "DeepSeek request exceeded the total time limit.") from None
        except OSError:
            raise GatewayError("api_worker_failed", "Cannot start API worker.") from None
        try:
            if process.returncode != 0:
                raise ValueError()
            reply = strict_object(process.stdout.decode("utf-8"))
            if "error" in reply:
                code = reply["error"]["code"]
                message = reply["error"]["message"]
                if not isinstance(code, str) or not code.startswith("api_") or not isinstance(message, str):
                    raise ValueError()
                # Defense in depth: never expose our own credential even in a malformed worker reply.
                raise GatewayError(code, message.replace(self.settings.api_key, "[REDACTED]"))
            content = reply["content"]
            if self.settings.api_key in content:
                raise ValueError()
            return strict_object(content), reply["metadata"]
        except (ValueError, UnicodeError, KeyError, TypeError) as exc:
            if isinstance(exc, GatewayError):
                raise
            raise GatewayError("api_invalid_json", "Model output is not a complete, strict JSON object.") from None
