"""Private stdlib-only HTTP worker. Key arrives on stdin, never command line."""

import json
import socket
import sys
import time
import urllib.error
import urllib.request


ERRORS = {
    400: ("api_request_rejected", "DeepSeek rejected the request."),
    401: ("api_authentication_failed", "DeepSeek API key authentication failed."),
    402: ("api_balance_insufficient", "DeepSeek account balance is insufficient."),
    403: ("api_access_denied", "DeepSeek denied access."),
    429: ("api_rate_limited", "DeepSeek rate limit reached; retry later."),
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_completion(payload):
    started = time.monotonic()
    stage = "opening_response"
    def mark(value):
        nonlocal stage
        stage = value
        # Private fixed vocabulary only. Never emit headers, payloads, URLs or model content.
        sys.stderr.write(json.dumps({"stage": value}) + "\n")
        sys.stderr.flush()

    def failed(code, message, http_status=None):
        metadata = {"request_stage": stage, "elapsed_seconds": round(time.monotonic() - started, 3)}
        if http_status is not None:
            metadata["http_status"] = http_status
        return {"error": {"code": code, "message": message}, "metadata": metadata}
    if payload.get("base_url") not in ("https://api.deepseek.com", "https://api.deepseek.com/v1"):
        return {"error": {"code": "api_configuration_error", "message": "Invalid API endpoint."}}
    body = {"model": payload["model"], "messages": payload["messages"],
            "response_format": {"type": "json_object"}, "thinking": {"type": "disabled"},
            "max_tokens": 2048, "temperature": 0, "stream": False}
    request = urllib.request.Request(payload["base_url"] + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + payload["api_key"], "Content-Type": "application/json"})
    try:
        mark("opening_response")
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=payload["timeout_seconds"]) as response:
            mark("reading_body")
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError()
        mark("decoding_response")
        data = json.loads(raw)
        choice = data["choices"][0]
        if choice["finish_reason"] != "stop":
            return failed("api_incomplete_response", "Incomplete model response.")
        content = choice["message"]["content"]
        if not isinstance(content, str) or not content.strip() or len(content) > 100_000:
            raise ValueError()
        # Only allow known numeric metadata; never return headers or raw service errors.
        usage = data.get("usage") or {}
        safe_usage = {k: usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                      if type(usage.get(k)) is int and usage[k] >= 0}
        return {"content": content, "metadata": {"model": payload["model"], "usage": safe_usage,
                "request_stage": "completed", "elapsed_seconds": round(time.monotonic() - started, 3)}}
    except urllib.error.HTTPError as exc:
        code, message = ERRORS.get(exc.code, (
            "api_unavailable" if exc.code >= 500 else "api_request_rejected", "DeepSeek API unavailable or request rejected."))
        return failed(code, message, exc.code)
    except (TimeoutError, socket.timeout):
        return failed("api_timeout", "DeepSeek request timed out.")
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            return failed("api_timeout", "DeepSeek request timed out.")
        return failed("api_connection_failed", "Cannot connect to DeepSeek.")
    except (ValueError, TypeError, KeyError, IndexError):
        return failed("api_invalid_response", "Invalid DeepSeek response.")


def main():
    try:
        payload = json.loads(sys.stdin.buffer.read(200_001))
        result = request_completion(payload)
    except Exception:
        result = {"error": {"code": "api_worker_failed", "message": "API worker failed."}}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8"))


if __name__ == "__main__":
    main()
