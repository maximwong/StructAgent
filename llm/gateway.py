"""Bounded cloud calls; no SDK dependency, automatic retry or raw-response logging."""

import json
from pathlib import Path
import subprocess
import sys
import time

from .json_utils import strict_object


class GatewayError(ValueError):
    def __init__(self, code, message, metadata=None):
        self.code = code
        self.metadata = metadata or {}
        super().__init__(message)


class DeepSeekGateway:
    def __init__(self, settings):
        self.settings = settings

    def complete(self, messages):
        started = time.monotonic()
        stages = {"opening_response", "reading_body", "decoding_response", "completed"}
        def safe_metadata(raw=None, stderr=None):
            raw = raw if isinstance(raw, dict) else {}
            metadata = {"model": self.settings.model, "elapsed_seconds": round(time.monotonic() - started, 3),
                        "request_stage": "worker"}
            if isinstance(raw.get("request_stage"), str) and raw["request_stage"] in stages:
                metadata["request_stage"] = raw["request_stage"]
            diagnostic = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else stderr or ""
            for line in diagnostic.splitlines()[-8:]:
                try:
                    stage = strict_object(line).get("stage")
                    if isinstance(stage, str) and stage in stages:
                        metadata["request_stage"] = stage
                except ValueError:
                    pass
            if type(raw.get("http_status")) is int and 100 <= raw["http_status"] <= 599:
                metadata["http_status"] = raw["http_status"]
            usage = raw.get("usage")
            if isinstance(usage, dict):
                metadata["usage"] = {k: usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                                     if type(usage.get(k)) is int and usage[k] >= 0}
            return metadata
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
        except subprocess.TimeoutExpired as exc:
            # subprocess.run kills and waits for its child on timeout, including stalled HTTP headers.
            raise GatewayError("api_timeout", "DeepSeek request exceeded the total time limit.", safe_metadata(stderr=exc.stderr)) from None
        except OSError:
            raise GatewayError("api_worker_failed", "Cannot start API worker.") from None
        try:
            if process.returncode != 0:
                raise ValueError()
            reply = strict_object(process.stdout.decode("utf-8"))
            if "error" in reply:
                code = reply["error"]["code"]
                message = reply["error"]["message"]
                allowed_codes = {"api_request_rejected", "api_authentication_failed", "api_balance_insufficient",
                                 "api_access_denied", "api_rate_limited", "api_unavailable", "api_timeout",
                                 "api_connection_failed", "api_invalid_response", "api_incomplete_response",
                                 "api_worker_failed", "api_configuration_error"}
                if code not in allowed_codes or not isinstance(message, str):
                    raise ValueError()
                # Defense in depth: never expose our own credential even in a malformed worker reply.
                raise GatewayError(code, message.replace(self.settings.api_key, "[REDACTED]"), safe_metadata(reply.get("metadata")))
            content = reply["content"]
            if self.settings.api_key in content:
                raise ValueError()
            return strict_object(content), safe_metadata(reply["metadata"])
        except (ValueError, UnicodeError, KeyError, TypeError) as exc:
            if isinstance(exc, GatewayError):
                raise
            raise GatewayError("api_invalid_json", "Model output is not a complete, strict JSON object.") from None
