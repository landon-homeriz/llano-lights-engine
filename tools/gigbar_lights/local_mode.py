"""Local mode: the phone controls the show over the room's Wi-Fi, with no internet (1.8.0).

Today the phone reaches the laptop only through llano.app, so a venue whose internet drops
loses phone control (the lights never stop: the show runs here). Local mode serves a small
control page from this laptop on the local network, so a phone on the same Wi-Fi (the venue's,
the laptop's own hotspot, a phone hotspot or a travel router) drives the show directly.

- Key: a random local key (~/.gigbar_lights/local_key.json) is needed for every call. It
  reaches a phone two ways: llano.app hands it to his paired phone while it is online (the
  laptop's status carries it, with the laptop's local addresses), or he scans the QR code in
  the window. "New key" (or unlinking from Llano) changes it, and old phones stop working.
- What it can do (1.20.0, the Light studio, Llano PM #23195): everything the phone does over the
  internet, with the same buttons. His rule, 2026-11-12: one phone app, the same buttons on either
  path, nothing disappearing when the connection switches, and settings must work over Wi-Fi too. So
  it takes the studio's commands (/api/studio, the one list every screen sends), starts the live show
  (/api/go), Stops it (/api/stop, 1.15.0), and reads and changes the saved settings (/api/settings,
  the same checked ops Llano sends). It serves the one console file every screen draws
  (/studio_console.js). The older calls (/api/key, /api/scene) stay for a phone app from before 1.20.
  It never reaches anything outside this app.
- The phone app (llano.app/lights, installed from Chrome) calls this server straight from the
  secure page once Chrome's local network permission is allowed (Chrome 142+), so one app does
  internet and local (Llano PM #22371). Only the origins in APP_ORIGINS may read the answers
  (CORS); the key is still needed for every call. LLANO_LIGHTS_APP_ORIGINS adds origins.
- It listens on every local address on one port (LOCAL_PORTS). The window's own server stays
  on 127.0.0.1 with its own token; this one never serves the window.

Kill switch: LLANO_LIGHTS_LOCAL=0 in the environment, or Phone control off in the window.
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional

from . import ports
from . import settings_contract as contract

LOCAL_PORTS = ports.LOCAL_PORTS   # 8790-8799 on the laptop (ports.py)
KEYS = set("bsth+-")             # the show keys a phone may send (scenes go through /api/scene)
MAX_POST = 1024
MAX_SETTINGS_POST = 256 * 1024   # a saved layout is the biggest settings change
PAGE = Path(__file__).resolve().parent / "windows" / "src" / "remote.html"   # a source copy; the app passes its own
APP_ORIGINS = ("https://llano.app",)


def app_origins() -> set[str]:
    extra = os.environ.get("LLANO_LIGHTS_APP_ORIGINS", "")
    return set(APP_ORIGINS) | {o.strip().rstrip("/") for o in extra.split(",") if o.strip().startswith(("https://", "http://localhost"))}


def enabled() -> bool:
    return os.environ.get("LLANO_LIGHTS_LOCAL", "1") != "0"


class LocalKey:
    """The key a phone needs, kept beside the saved layouts."""

    def __init__(self, root: Optional[Path] = None):
        self.path = (Path(root) if root else Path.home() / ".gigbar_lights") / "local_key.json"

    def get(self) -> str:
        try:
            k = json.loads(self.path.read_text(encoding="utf-8")).get("key")
            if isinstance(k, str) and len(k) >= 16:
                return k
        except (OSError, ValueError, AttributeError):  # ok: none yet, make one
            pass
        return self.rotate()

    def rotate(self) -> str:
        k = secrets.token_urlsafe(18)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"key": k}), encoding="utf-8")
        tmp.replace(self.path)
        return k


def addresses() -> list[str]:
    """This laptop's IPv4 addresses on local networks, most likely first (a Windows hotspot is
    192.168.137.1). Loopback and link-local are left out: a phone can't reach those."""
    found: list[str] = []
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        found = [i[4][0] for i in infos]
    except OSError:
        pass
    try:  # the address the default route would use; no packet is sent
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.168.255.255", 9))
            found.insert(0, s.getsockname()[0])
    except OSError:
        pass
    out = []
    for a in found:
        if a.startswith(("127.", "169.254.", "0.")) or a in out:
            continue
        out.append(a)
    return sorted(out, key=lambda a: (not a.startswith("192.168.137."), not a.startswith(("192.168.", "10.", "172."))))


class LocalServer:
    """The phone's page and its few calls, on every local address. `state` returns what the
    phone shows; `send` hands a key ("b", "scene:party", ...) to the running show and returns
    False when no show is running."""

    def __init__(self, key: LocalKey, state: Callable[[], dict], send: Callable[[str], bool], page: Path = PAGE,
                 stop: Optional[Callable[[], dict]] = None, studio: Optional[Callable[[dict], tuple]] = None,
                 go: Optional[Callable[[str], tuple]] = None, settings: Optional[Callable[[Optional[list]], tuple]] = None,
                 console: Optional[Path] = None):
        self.key, self.state, self.send, self.page = key, state, send, page
        self.stop_show = stop   # Stop the show (1.15.0): the window's own Stop, so it frees a stuck run too
        # The Light studio (1.20.0): each returns (http code, body), the app's own answers and words.
        self.studio, self.go, self.settings = studio, go, settings
        self.console = console if console is not None else page.with_name("studio_console.js")
        self.server: Optional[ThreadingHTTPServer] = None
        self.port = 0

    def start(self) -> bool:
        if self.server is not None:
            return True
        srv = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, body: bytes, ctype: str, code: int = 200):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self._cors()
                self.end_headers()
                self.wfile.write(body)

            def _cors(self) -> bool:
                origin = self.headers.get("Origin") or ""
                if origin not in app_origins():
                    return False
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                return True

            def do_OPTIONS(self):
                # The phone app's preflight: it sends the key header and JSON from llano.app.
                self.send_response(204)
                if self._cors():
                    self.send_header("Access-Control-Allow-Methods", "GET, POST")
                    self.send_header("Access-Control-Allow-Headers", "X-Llano-Key, Content-Type")
                    self.send_header("Access-Control-Max-Age", "600")
                    if self.headers.get("Access-Control-Request-Private-Network") == "true":
                        self.send_header("Access-Control-Allow-Private-Network", "true")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def _json(self, body: dict, code: int = 200):
                self._send(json.dumps(body).encode(), "application/json", code)

            def _keyed(self) -> bool:
                if secrets.compare_digest(self.headers.get("X-Llano-Key") or "", srv.key.get()):
                    return True
                self._json({"error": "this phone has an old key or none: scan the code on the laptop again"}, 403)
                return False

            def do_GET(self):
                path = self.path.split("?")[0]
                if path in ("/", "/index.html"):
                    try:
                        return self._send(srv.page.read_bytes(), "text/html; charset=utf-8")
                    except OSError:
                        return self._send(b"page missing", "text/plain", 500)
                if path == "/studio_console.js":   # the one console every screen draws; nothing secret in it
                    try:
                        return self._send(srv.console.read_bytes(), "text/javascript; charset=utf-8")
                    except OSError:
                        return self._send(b"missing from this copy", "text/plain", 500)
                if path == "/api/state":
                    if self._keyed():
                        self._json(srv.state())
                    return
                if path == "/api/settings":
                    if self._keyed():
                        if srv.settings is None:
                            return self._json({"error": "this laptop can't share its settings over Wi-Fi"}, 501)
                        code, body = srv.settings(None)
                        self._json(body, code)
                    return
                self._send(b"not found", "text/plain", 404)

            def do_POST(self):
                if not self._keyed():
                    return
                path = self.path.split("?")[0]
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    most = MAX_SETTINGS_POST if path == "/api/settings" else MAX_POST
                    msg = json.loads(self.rfile.read(n)) if 0 < n <= most else {}
                except (ValueError, OSError):
                    msg = {}
                msg = msg if isinstance(msg, dict) else {}
                door = {"/api/studio": (srv.studio, lambda: msg), "/api/go": (srv.go, lambda: str(msg.get("mode") or "")),
                        "/api/settings": (srv.settings, lambda: msg.get("ops") if isinstance(msg.get("ops"), list) else [])}.get(path)
                if door is not None:   # the Light studio's doors (1.20.0): the app answers, in its own words
                    fn, arg = door
                    if fn is None:
                        return self._json({"error": "this laptop can't do that from a phone"}, 501)
                    try:
                        code, body = fn(arg())
                    except Exception as e:  # noqa: BLE001 -- ok: the phone hears why, the server keeps serving
                        return self._json({"error": f"That didn't go through on the laptop: {e}"}, 500)
                    return self._json(body if isinstance(body, dict) else {}, code)
                if path == "/api/stop":
                    if srv.stop_show is None:
                        return self._json({"error": "this laptop can't stop the show from a phone"}, 501)
                    try:
                        out = srv.stop_show()
                    except Exception as e:  # noqa: BLE001 -- ok: the phone hears why, the server keeps serving
                        return self._json({"error": f"Stop didn't go through on the laptop: {e}"}, 500)
                    return self._json({"ok": True, **(out if isinstance(out, dict) else {})})
                if path == "/api/key":
                    k = str(msg.get("k") or "")[:1]
                    if k not in KEYS:
                        return self._json({"error": "not a key the phone can send"}, 400)
                    item = k
                elif path == "/api/scene":
                    name = msg.get("scene") or ""
                    if name and name not in contract.SCENES:
                        return self._json({"error": "no such scene"}, 400)
                    item = "scene:" + name
                else:
                    return self._send(b"not found", "text/plain", 404)
                if not srv.send(item):
                    return self._json({"error": "nothing is running on the laptop: start the show there"}, 409)
                self._json({"ok": True})

        for port in LOCAL_PORTS:
            try:
                self.server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
                break
            except OSError:
                continue
        if self.server is None:
            return False
        self.server.daemon_threads = True
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, name="local-mode", daemon=True).start()
        return True

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server, self.port = None, 0

    def public(self, with_key: bool = False) -> dict:
        """For the window, and (with the key) for Llano to hand to his paired phone."""
        out = {"on": self.server is not None, "port": self.port,
               "addresses": addresses() if self.server is not None else []}
        out["urls"] = [f"http://{a}:{self.port}/" for a in out["addresses"]]
        if with_key and self.server is not None:
            out["key"] = self.key.get()
        return out
