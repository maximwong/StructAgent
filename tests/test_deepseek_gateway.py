import io
import json
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import urllib.error

from config import ConfigurationError, DeepSeekSettings, load_settings
from llm import DeepSeekGateway, GatewayError
from llm import _deepseek_worker as worker
from llm.json_utils import strict_object


KEY = "test-credential-not-real"
PAYLOAD = {"api_key": KEY, "base_url": "https://api.deepseek.com", "model": "deepseek-flash",
           "timeout_seconds": 5, "messages": [{"role": "user", "content": "Return JSON"}]}


class ConfigurationTests(unittest.TestCase):
    def test_local_env_loaded_and_environment_overrides_without_executing_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(f'# comment\nDEEPSEEK_API_KEY="{KEY}"\nDEEPSEEK_TIMEOUT_SECONDS=5\n', encoding="utf-8")
            settings = load_settings(path, environ={})
            self.assertEqual(settings.api_key, KEY)
            self.assertEqual(settings.timeout_seconds, 5)
            self.assertNotIn(KEY, repr(settings))
            self.assertEqual(load_settings(path, environ={"DEEPSEEK_MODEL": "deepseek-v4-pro"}).model, "deepseek-v4-pro")

    def test_missing_key_and_malformed_duplicate_env_are_safe_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            for content in ("", f"DEEPSEEK_API_KEY={KEY}\nDEEPSEEK_API_KEY={KEY}", KEY,
                            f"DEEPSEEK_API_KEY={KEY}\nDEEPSEEK_TIMEOUT_SECONDS={KEY}"):
                with self.subTest(content=content):
                    path.write_text(content, encoding="utf-8")
                    with self.assertRaises(ConfigurationError) as context:
                        load_settings(path, environ={})
                    self.assertNotIn(KEY, str(context.exception))

    def test_endpoint_whitelist_no_http_redirect_host_or_userinfo(self):
        for url in ("http://api.deepseek.com", "https://evil.example", "https://api.deepseek.com.evil.example",
                    "https://api.deepseek.com@evil.example", "https://api.deepseek.com/foo"):
            with self.subTest(url=url), self.assertRaises(ConfigurationError):
                DeepSeekSettings(KEY, base_url=url)

    def test_model_and_finite_bounded_timeout(self):
        with self.assertRaises(ConfigurationError):
            DeepSeekSettings(KEY, model="unverified-model")
        for timeout in (True, 0, 61, float("nan"), float("inf"), "5"):
            with self.subTest(timeout=timeout), self.assertRaises(ConfigurationError):
                DeepSeekSettings(KEY, timeout_seconds=timeout)


class JsonTests(unittest.TestCase):
    def test_strict_json_rejects_ambiguous_incomplete_or_nonobject_outputs(self):
        for content in ("", "```json\n{}\n```", '[]', 'null', '{"a":1,"a":2}', '{"x":{"a":1,"a":2}}',
                        '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}', '{"x":', " " * 100_001, "{} trailing"):
            with self.subTest(content=content[:50]), self.assertRaises(ValueError):
                strict_object(content)
        self.assertEqual(strict_object('{"span_x":6000}'), {"span_x": 6000})


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.gateway = DeepSeekGateway(DeepSeekSettings(KEY, timeout_seconds=2))

    def response(self, data):
        return SimpleNamespace(returncode=0, stdout=json.dumps(data).encode(), stderr=b"never print stderr")

    @patch("llm.gateway.subprocess.run")
    def test_timeout_stage_is_safe_and_preserved(self, run):
        run.side_effect = subprocess.TimeoutExpired("worker", 2, stderr=b'{"stage":"opening_response"}\n{"stage":"reading_body"}\n')
        with self.assertRaises(GatewayError) as context:
            self.gateway.complete(PAYLOAD["messages"])
        self.assertEqual(context.exception.metadata["request_stage"], "reading_body")
        self.assertGreaterEqual(context.exception.metadata["elapsed_seconds"], 0)
        self.assertNotIn(KEY, json.dumps(context.exception.metadata))

    @patch("llm.gateway.subprocess.run")
    def test_malformed_diagnostic_and_untrusted_metadata_are_filtered(self, run):
        run.side_effect = subprocess.TimeoutExpired("worker", 2, stderr='{"stage":[]}\n' + KEY)
        with self.assertRaises(GatewayError) as context:
            self.gateway.complete(PAYLOAD["messages"])
        self.assertEqual(context.exception.metadata["request_stage"], "worker")
        run.side_effect = None
        run.return_value = self.response({"content": "{}", "metadata": {"request_stage": [], "secret": KEY,
            "usage": {"prompt_tokens": True, "total_tokens": 3, "secret": KEY}}})
        _, metadata = self.gateway.complete(PAYLOAD["messages"])
        self.assertEqual(metadata["usage"], {"total_tokens": 3})
        self.assertNotIn(KEY, json.dumps(metadata))

    @patch("llm.gateway.subprocess.run")
    def test_worker_protocol_and_key_only_on_stdin(self, run):
        run.return_value = self.response({"content": '{"ok":true}', "metadata": {"model": "deepseek-flash"}})
        parsed, metadata = self.gateway.complete(PAYLOAD["messages"])
        self.assertEqual(parsed, {"ok": True})
        self.assertEqual(metadata["model"], "deepseek-flash")
        self.assertNotIn(KEY, repr(run.call_args.args))
        self.assertEqual(json.loads(run.call_args.kwargs["input"])["api_key"], KEY)
        self.assertEqual(run.call_args.kwargs["timeout"], 2)
        self.assertIn("-I", run.call_args.args[0])

    @patch("llm.gateway.subprocess.run")
    def test_timeout_and_start_failure_are_sanitized(self, run):
        for exception, code in ((subprocess.TimeoutExpired("worker", 2, output=KEY), "api_timeout"),
                                (OSError(KEY), "api_worker_failed")):
            run.side_effect = exception
            with self.assertRaises(GatewayError) as context:
                self.gateway.complete(PAYLOAD["messages"])
            self.assertEqual(context.exception.code, code)
            self.assertNotIn(KEY, str(context.exception))

    @patch("llm.gateway.subprocess.run")
    def test_invalid_protocol_json_truncation_and_credential_echo_rejected(self, run):
        for data in ({"content": "[]", "metadata": {}}, {"content": '{"x":NaN}', "metadata": {}},
                     {"content": '{"x":1,"x":2}', "metadata": {}}, {"content": KEY, "metadata": {}}, {},
                     {"error": {"code": 4, "message": KEY}}):
            run.return_value = self.response(data)
            with self.assertRaises(GatewayError) as context:
                self.gateway.complete(PAYLOAD["messages"])
            self.assertEqual(context.exception.code, "api_invalid_json")
            self.assertNotIn(KEY, str(context.exception))

    @patch("llm.gateway.subprocess.run")
    def test_standardized_worker_error_redacts_secret(self, run):
        run.return_value = self.response({"error": {"code": "api_authentication_failed", "message": KEY}})
        with self.assertRaises(GatewayError) as context:
            self.gateway.complete(PAYLOAD["messages"])
        self.assertEqual(context.exception.code, "api_authentication_failed")
        self.assertEqual(str(context.exception), "[REDACTED]")

    def test_stalled_real_worker_is_bounded_by_total_wall_time(self):
        with tempfile.TemporaryDirectory() as directory:
            worker_path = Path(directory) / "stall.py"
            worker_path.write_text("import sys,time\nsys.stdin.buffer.read()\ntime.sleep(30)\n", encoding="utf-8")
            fake_path = SimpleNamespace(with_name=lambda _: worker_path)
            start = time.monotonic()
            with patch("llm.gateway.Path", return_value=fake_path), self.assertRaises(GatewayError) as context:
                self.gateway.complete(PAYLOAD["messages"])
            self.assertEqual(context.exception.code, "api_timeout")
            self.assertLess(time.monotonic() - start, 6)


class WorkerHttpTests(unittest.TestCase):
    def setUp(self):
        self.diagnostics = io.StringIO()
        patcher = patch("llm._deepseek_worker.sys.stderr", self.diagnostics)
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch("llm._deepseek_worker.urllib.request.build_opener")
    def test_wrapped_socket_timeout_is_not_connection_failure(self, build):
        build.return_value.open.side_effect = urllib.error.URLError(TimeoutError(KEY))
        reply = worker.request_completion(PAYLOAD)
        self.assertEqual(reply["error"]["code"], "api_timeout")
        self.assertEqual(reply["metadata"]["request_stage"], "opening_response")
        self.assertNotIn(KEY, self.diagnostics.getvalue())
    def open_response(self, data):
        stream = io.BytesIO(json.dumps(data).encode())
        opener = Mock()
        opener.open.return_value = stream
        return opener

    @patch("llm._deepseek_worker.urllib.request.build_opener")
    def test_request_json_mode_and_metadata_allowlist(self, build):
        build.return_value = self.open_response({"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}],
            "usage": {"prompt_tokens": 5, "total_tokens": 7, "secret": KEY, "completion_tokens": True}, "headers": {"secret": KEY}})
        reply = worker.request_completion(PAYLOAD)
        self.assertEqual(reply["metadata"]["usage"], {"prompt_tokens": 5, "total_tokens": 7})
        self.assertNotIn(KEY, json.dumps(reply))
        request = build.return_value.open.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertEqual(request.headers["Authorization"], "Bearer " + KEY)

    @patch("llm._deepseek_worker.urllib.request.build_opener")
    def test_http_errors_drop_raw_bodies_and_do_not_retry(self, build):
        codes = {400: "api_request_rejected", 401: "api_authentication_failed", 402: "api_balance_insufficient",
                 403: "api_access_denied", 429: "api_rate_limited", 500: "api_unavailable", 302: "api_request_rejected"}
        for status, code in codes.items():
            with self.subTest(status=status):
                opener = Mock()
                opener.open.side_effect = urllib.error.HTTPError("url", status, KEY, {}, io.BytesIO(KEY.encode()))
                build.return_value = opener
                reply = worker.request_completion(PAYLOAD)
                self.assertEqual(reply["error"]["code"], code)
                self.assertNotIn(KEY, json.dumps(reply))
                self.assertEqual(opener.open.call_count, 1)

    @patch("llm._deepseek_worker.urllib.request.build_opener")
    def test_timeout_connection_failure_and_invalid_server_output(self, build):
        for exception, code in ((TimeoutError(KEY), "api_timeout"), (urllib.error.URLError(KEY), "api_connection_failed")):
            build.return_value.open.side_effect = exception
            self.assertEqual(worker.request_completion(PAYLOAD)["error"]["code"], code)
        for data, code in (({}, "api_invalid_response"),
                           ({"choices": [{"finish_reason": "length", "message": {"content": '{"x":'}}]}, "api_incomplete_response"),
                           ({"choices": [{"finish_reason": "stop", "message": {"content": ""}}]}, "api_invalid_response")):
            build.return_value = self.open_response(data)
            self.assertEqual(worker.request_completion(PAYLOAD)["error"]["code"], code)

    def test_redirect_and_invalid_endpoint_never_send_key(self):
        self.assertIsNone(worker.NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.example"))
        with patch("llm._deepseek_worker.urllib.request.build_opener") as build:
            result = worker.request_completion({**PAYLOAD, "base_url": "https://evil.example"})
            self.assertEqual(result["error"]["code"], "api_configuration_error")
            build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
