"""Static workbench server + transparent /api proxy for the desktop app.

The production Vite build in frontend/dist is served directly, and /api/v1/*
requests are forwarded to the loopback Flask API. Browser Origin/Referer/
Sec-Fetch-Site headers are stripped exactly like the Vite dev proxy did, so the
Flask session layer sees a same-origin local request.

No third-party packages, no Node.js at runtime -- Python stdlib only.
"""
from __future__ import annotations

import http.client
import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "frontend" / "dist"
API_PORT = int(os.environ.get("BIRTHCO_PORT", "5210"))
PORT = int(os.environ.get("BIRTHCO_FRONTEND_PORT", "4273"))
HOST = "127.0.0.1"

_STRIP = {"origin", "referer", "sec-fetch-site", "sec-fetch-mode",
          "sec-fetch-dest", "host", "connection", "content-length",
          "transfer-encoding", "accept-encoding"}
_FORWARD = {"accept", "content-type", "cookie", "x-csrf-token",
            "idempotency-key", "user-agent"}

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("font/woff2", ".woff2")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ZhongmuDesktop/1.0"

    def log_message(self, fmt, *args):
        pass  # keep the desktop launcher log quiet

    def _send(self, status: int, body: bytes, content_type: str,
              extra: list[tuple[str, str]] | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        for key, value in extra or []:
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _proxy(self, method: str):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {name: value for name, value in self.headers.items()
                   if name.lower() in _FORWARD and name.lower() not in _STRIP}
        headers["Host"] = f"{HOST}:{API_PORT}"
        conn = http.client.HTTPConnection(HOST, API_PORT, timeout=60)
        try:
            conn.request(method, self.path, body=body, headers=headers)
            response = conn.getresponse()
            payload = response.read()
            extras = []
            for key, value in response.getheaders():
                low = key.lower()
                if low in {"content-length", "transfer-encoding", "connection", "content-type"}:
                    continue
                extras.append((key, value))
            self._send(response.status, payload,
                       response.getheader("Content-Type") or "application/json; charset=utf-8",
                       extras)
        except (OSError, http.client.HTTPException) as exc:
            payload = ('{"error":{"code":"STORAGE_UNAVAILABLE","cause_hint":'
                       '"本地后端未就绪，请重新启动桌面应用","next_action":"重试",'
                       '"retryable":true,"field_errors":[]},"request_id":"desktop"}').encode("utf-8")
            self._send(503, payload, "application/json; charset=utf-8")
            print(f"[desktop] proxy error: {exc}", file=sys.stderr, flush=True)
        finally:
            conn.close()

    def _ping(self):
        """Ownership probe: lets the launcher tell this app from a stale proxy."""
        body = json.dumps({
            "app": "zhongmu-desktop",
            "api_port": API_PORT,
            "web_port": PORT,
        }).encode("utf-8")
        self._send(200, body, "application/json; charset=utf-8")

    def _static(self):
        path = self.path.split("?", 1)[0]
        relative = path.lstrip("/") or "index.html"
        target = (DIST / relative).resolve()
        try:
            target.relative_to(DIST.resolve())
        except ValueError:
            target = DIST / "index.html"
        if not target.is_file():
            # SPA routes (/workspace/tasks/xyz) fall back to the app shell.
            target = DIST / "index.html"
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        self._send(200, target.read_bytes(), content_type)

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/__desktop/ping":
            return self._ping()
        self._proxy("GET") if self.path.startswith("/api/") else self._static()

    def do_HEAD(self):
        if self.path.split("?", 1)[0] == "/__desktop/ping":
            return self._ping()
        self._proxy("HEAD") if self.path.startswith("/api/") else self._static()

    def do_POST(self):
        self._proxy("POST") if self.path.startswith("/api/") else self._send(404, b"", "text/plain")

    def do_PUT(self):
        self._proxy("PUT") if self.path.startswith("/api/") else self._send(404, b"", "text/plain")

    def do_PATCH(self):
        self._proxy("PATCH") if self.path.startswith("/api/") else self._send(404, b"", "text/plain")

    def do_DELETE(self):
        self._proxy("DELETE") if self.path.startswith("/api/") else self._send(404, b"", "text/plain")


def main():
    if not (DIST / "index.html").is_file():
        raise SystemExit(f"frontend/dist/index.html 不存在：{DIST}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f"[desktop] workbench http://{HOST}:{PORT} -> api {HOST}:{API_PORT}", flush=True)
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
