"""Loopback server for the Payment Matching browser and native app."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import json
import os
import re
import secrets
import socketserver
import tempfile

from ledger import ROOT, RUNTIME, export_csv, import_csv, ledger_state, preview_csv, record_allocation, seed_demo

HOST = "127.0.0.1"
PORT = 8334
PREFERENCES = RUNTIME / "preferences.json"
DEFAULT_PREFERENCES = {"compact": False, "reduceMotion": False}
MAX_BODY = 2_000_000


def _read_preferences():
    try:
        if PREFERENCES.stat().st_size > 2048:
            return dict(DEFAULT_PREFERENCES)
        value = json.loads(PREFERENCES.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) != set(DEFAULT_PREFERENCES):
            return dict(DEFAULT_PREFERENCES)
        if any(type(value[key]) is not bool for key in DEFAULT_PREFERENCES):
            return dict(DEFAULT_PREFERENCES)
        return value
    except (OSError, ValueError, TypeError):
        return dict(DEFAULT_PREFERENCES)


def _write_preferences(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT_PREFERENCES):
        raise ValueError("Settings must contain only compact and reduceMotion booleans")
    if any(type(value[key]) is not bool for key in DEFAULT_PREFERENCES):
        raise ValueError("Settings values must be booleans")
    payload = json.dumps(value, separators=(",", ":")).encode("utf-8")
    if len(payload) > 2048:
        raise ValueError("Settings are too large")
    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(RUNTIME, 0o700)
    fd, temp_name = tempfile.mkstemp(prefix=".preferences-", dir=RUNTIME)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, PREFERENCES)
        os.chmod(PREFERENCES, 0o600)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
    return value


def make_server(port: int = 0) -> ThreadingHTTPServer:
    """Bind a fresh loopback listener. The caller owns its thread and shutdown."""
    seed_demo()

    class LocalServer(ThreadingHTTPServer):
        daemon_threads = True

        def server_bind(self):
            socketserver.TCPServer.server_bind(self)
            self.server_name = HOST
            self.server_port = self.socket.getsockname()[1]

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, _format, *_args):
            return

        def _valid_host(self):
            authority = self.headers.get("Host", "")
            port_text = str(self.server.server_port)
            return authority in (f"127.0.0.1:{port_text}", f"localhost:{port_text}")

        def _valid_origin(self):
            port_text = str(self.server.server_port)
            return self.headers.get("Origin") in (
                f"http://127.0.0.1:{port_text}",
                f"http://localhost:{port_text}",
            )

        def _send(self, status, body, kind="application/json; charset=utf-8", extra=()):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'")
            for key, value in extra:
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def _json(self, value, status=200):
            return self._send(status, json.dumps(value, ensure_ascii=False, separators=(",", ":")))

        def do_GET(self):
            if not self._valid_host():
                return self._json({"error": "Invalid host"}, 403)
            route = urlparse(self.path).path
            if route == "/":
                page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
                page = page.replace("__TOKEN__", self.server.request_token)
                return self._send(200, page, "text/html; charset=utf-8")
            assets = {
                "/app.css": ("static/app.css", "text/css; charset=utf-8"),
                "/app.js": ("static/app.js", "text/javascript; charset=utf-8"),
            }
            if route in assets:
                path, kind = assets[route]
                return self._send(200, (ROOT / path).read_bytes(), kind)
            if route == "/api/state":
                return self._json(ledger_state())
            if route == "/api/settings":
                return self._json({"preferences": _read_preferences(), "saved": PREFERENCES.is_file()})
            if route == "/api/export.csv":
                data = export_csv().encode("utf-8")
                return self._send(200, data, "text/csv; charset=utf-8", (("Content-Disposition", 'attachment; filename="payment-matching-export.csv"'),))
            match = re.fullmatch(r"/fixtures/(invoices|payments|payments-revised)\.csv", route)
            if match:
                return self._send(200, (ROOT / "fixtures" / f"{match.group(1)}.csv").read_bytes(), "text/csv; charset=utf-8")
            return self._json({"error": "Not found"}, 404)

        def do_POST(self):
            if not self._valid_host() or not self._valid_origin():
                return self._json({"error": "Invalid request origin"}, 403)
            if not secrets.compare_digest(self.headers.get("X-Request-Token", ""), self.server.request_token):
                return self._json({"error": "Request token required"}, 403)
            try:
                size = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                size = -1
            if size < 0 or size > MAX_BODY:
                return self._json({"error": "Request must be under 2 MB"}, 413)
            try:
                body = json.loads(self.rfile.read(size))
            except (ValueError, OSError):
                return self._json({"error": "Invalid JSON"}, 400)
            if not isinstance(body, dict):
                return self._json({"error": "Request body must be an object"}, 400)
            route = urlparse(self.path).path
            try:
                if route == "/api/settings":
                    return self._json({"preferences": _write_preferences(body), "saved": True})
                if route == "/api/preview":
                    return self._json(preview_csv(body.get("csv"), body.get("record_type"), body.get("mapping")))
                if route == "/api/import":
                    return self._json(import_csv(body.get("csv"), body.get("record_type"), body.get("source_name"), body.get("mapping")))
                if route == "/api/allocate":
                    return self._json(record_allocation(body.get("payment_row"), body.get("invoice_row"), body.get("amount_text"), body.get("reason")))
            except (ValueError, KeyError, TypeError) as exc:
                return self._json({"error": str(exc)}, 400)
            return self._json({"error": "Not found"}, 404)

    server = LocalServer((HOST, port), Handler)
    server.request_token = secrets.token_urlsafe(32)
    return server


def serve(port: int = PORT):
    server = make_server(port=port)
    try:
        print(f"Payment Matching listening at http://{HOST}:{server.server_port}", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()
