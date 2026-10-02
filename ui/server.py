"""Loopback-only HTTP UI with bounded JSON requests and same-origin mutation checks."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from .service import UIError

STATIC = Path(__file__).with_name("static")


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, service, port=8765):
        self.service = service
        self.token = secrets.token_hex(32)
        super().__init__(("127.0.0.1", port), Handler)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    server_version = "StructAgent/0.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args):
        pass  # Avoid persisting user input, query strings or local session tokens.

    def reply(self, code, payload, content_type="application/json; charset=utf-8"):
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8") if isinstance(payload, dict) else payload
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _host(self):
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if self.headers.get("Host") not in allowed:
            raise UIError("此界面仅供本机访问。", 403)

    def _auth(self, mutation=False):
        self._host()
        if not secrets.compare_digest(self.headers.get("X-StructAgent-Token", ""), self.server.token):
            raise UIError("页面会话已失效，请刷新页面。", 403)
        if mutation and self.headers.get("Origin") != "http://" + self.headers["Host"]:
            raise UIError("请从本机StructAgent页面操作。", 403)

    def do_GET(self):
        try:
            self._host()
            path = urlsplit(self.path).path
            if path == "/health":
                return self.reply(200, {"application": "StructAgent", "protocol": 1})
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/full-input.js": ("full-input.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8")}
            if path in assets:
                name, content_type = assets[path]
                body = (STATIC / name).read_bytes().replace(b"__SESSION_TOKEN__", self.server.token.encode("ascii"))
                return self.reply(200, body, content_type)
            self._auth()
            if path == "/api/status":
                return self.reply(200, self.server.service.status())
            if path == "/api/input-form" and self.server.service.input_form:
                return self.reply(200, self.server.service.input_form())
            if path.startswith("/api/jobs/"):
                return self.reply(200, self.server.service.view(path.removeprefix("/api/jobs/")))
            raise UIError("找不到此页面。", 404)
        except UIError as exc:
            self.reply(exc.status, {"error": str(exc)})
        except (OSError, ValueError, KeyError):
            self.reply(500, {"error": "本机运行记录无法读取，请保留现场供检查。"})

    def do_POST(self):
        try:
            self._auth(mutation=True)
            if self.headers.get("Transfer-Encoding") or self.headers.get_content_type() != "application/json":
                raise UIError("请求格式不正确。", 415)
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 20000:
                raise UIError("输入内容过长或为空。", 413)
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            path = urlsplit(self.path).path
            if path == "/api/jobs":
                return self.reply(202, self.server.service.start(body))
            if path.startswith("/api/jobs/") and path.endswith("/open-cad"):
                return self.reply(200, self.server.service.open_drawing(path[len("/api/jobs/"):-len("/open-cad")]))
            if path == "/api/recover":
                return self.reply(202, self.server.service.start_recovery())
            if path == "/api/stop":
                self.server.service.prepare_shutdown()
                self.reply(200, {"success": True})
                self.server.shutdown()
                return
            raise UIError("找不到此操作。", 404)
        except UIError as exc:
            self.reply(exc.status, {"error": str(exc)})
        except (ValueError, UnicodeError):
            self.reply(400, {"error": "请求内容不是有效的JSON。"})
        except OSError:
            self.reply(500, {"error": "无法写入本机运行目录，请检查路径和可用空间。"})
