"""
TRINETRA — local web server for the trainee interface.

    python -m trinetra.app                 # serves http://127.0.0.1:8765 and opens the browser

Runs entirely on this machine with the Python standard library; no
internet is needed (three.js is vendored in trinetra/web/vendor).

  GET  /                  the interface
  GET  /static/<file>     files under trinetra/web
  GET  /api/scenarios     scenario list for the start screen
  GET  /api/state         one state snapshot (JSON)
  GET  /api/stream        state ~10 times a second (Server-Sent Events)
  GET  /api/aar           after-action timeline of the finished mission (null while running)
  GET  /api/thermal.jpg   latest thermal camera frame
  POST /api/action        trainee and session actions (JSON)
"""

import json
import logging
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .runner import SimRunner, list_scenarios

WEB_DIR = (Path(__file__).resolve().parents[1] / "web").resolve()
STREAM_HZ = 10
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
        ".json": "application/json", ".txt": "text/plain; charset=utf-8"}

logger = logging.getLogger("trinetra.web")


class Handler(BaseHTTPRequestHandler):
    runner: SimRunner = None             # set on the subclass made by make_server()
    server_version = "TRINETRA"

    def log_message(self, fmt, *args):
        logger.debug("%s " + fmt, self.address_string(), *args)

    # ── helpers ──
    def _send(self, status: int, body: bytes, ctype: str, cache: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status: int = 200) -> None:
        self._send(status, json.dumps(obj).encode(), "application/json")

    def _static(self, rel: str) -> None:
        path = (WEB_DIR / rel).resolve()
        if WEB_DIR not in path.parents or not path.is_file():
            self._send(404, b"not found", "text/plain")
            return
        self._send(200, path.read_bytes(), MIME.get(path.suffix, "application/octet-stream"),
                   cache="vendor" in path.parts)

    # ── routes ──
    def do_GET(self):
        route = urlparse(self.path).path
        if route in ("/", "/index.html"):
            self._static("index.html")
        elif route.startswith("/static/"):
            self._static(route[len("/static/"):])
        elif route == "/api/scenarios":
            self._json(list_scenarios())
        elif route == "/api/state":
            self._json(self.runner.state())
        elif route == "/api/aar":
            self._json(self.runner.aar())
        elif route == "/api/thermal.jpg":
            jpg = self.runner.thermal_jpeg()
            if jpg:
                self._send(200, jpg, "image/jpeg")
            else:
                self._send(204, b"", "image/jpeg")
        elif route == "/api/stream":
            self._stream()
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if urlparse(self.path).path != "/api/action":
            self._send(404, b"not found", "text/plain")
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            action = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(action, dict):
                raise ValueError("action must be a JSON object")
        except (ValueError, json.JSONDecodeError) as e:
            self._json({"ok": False, "error": f"bad request: {e}"}, 400)
            return
        self._json(self.runner.act(action))

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                data = json.dumps(self.runner.state(), separators=(",", ":"))
                self.wfile.write(f"data: {data}\n\n".encode())
                self.wfile.flush()
                time.sleep(1.0 / STREAM_HZ)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return


def make_server(runner: SimRunner, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"runner": runner})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def serve(port: int = 8765, open_browser: bool = True, log_dir: str = "output/trinetra") -> None:
    runner = SimRunner(log_dir=log_dir)
    server = make_server(runner, port=port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"TRINETRA is running at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("\nStopping TRINETRA")
    finally:
        runner.close()
        server.server_close()
