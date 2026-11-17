"""Llano Lights for Windows: a desktop window around tools.gigbar_lights.

The window (app.html, in an Edge app window) starts every mode with a button, shows the
12 lights drawn from the exact DMX bytes the show would send to the ENTTEC (so a run
with no box plugged in still proves the looks), says what is set up, and installs
signed updates from his server (updater.py).

  python gigbar_app.py            the window
  python gigbar_app.py menu       the old numbered text menu
  python gigbar_app.py demo       no Mixxx, no lights: a fake 128 BPM song
  python gigbar_app.py demo --song drop   the same with a real song (groove, drop, slow)
  python gigbar_app.py preview    real Mixxx, no lights plugged in
  python gigbar_app.py live       real Mixxx + the ENTTEC
  python gigbar_app.py test       light each fixture in turn (needs the ENTTEC)
  python gigbar_app.py analyze    work out song sections for the Mixxx library
  python gigbar_app.py check      what is installed and found
  python gigbar_app.py designer   Show Designer: place the lights, watch the room (demo song)
  python gigbar_app.py show NAME  play a saved show (Shows page) front to back, nothing plugged in
  add --seconds N to stop after N seconds, --no-browser to skip opening the window;
  --no-window runs the window's server without opening a window (tests)
"""
from __future__ import annotations

import argparse
import collections
import ctypes
import faulthandler
import importlib.util
import json
import os
import queue
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STARTED = time.monotonic()  # the launch clock for the startup timing lines (1.11.4)
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from tools.gigbar_lights import __main__ as gl  # noqa: E402
from tools.gigbar_lights import demo_songs, folder_picker, hotspot, local_mode, moments, settings_contract, show_settings, shows, updater, windows_apps  # noqa: E402
try:   # the settings sync with llano.app; the open-source engine ships without it and runs laptop-only
    from tools.gigbar_lights import llano_sync  # noqa: E402
except ImportError:   # ok: offline_link is the same seam with no network behind it
    from tools.gigbar_lights import offline_link as llano_sync  # noqa: E402
from tools.gigbar_lights import probe as probes  # noqa: E402
from tools.gigbar_lights import drive_songs, set_arranger, setup_guide, song_folder  # noqa: E402
from tools.gigbar_lights import patch_sheet, run_of_show, wedding_night  # noqa: E402
from tools.gigbar_lights import mixxx_load, night_plans, ports as port_set  # noqa: E402
from tools.gigbar_lights import stage_glow, studio as studio_mod, studio_peek, tonight as tonight_mod  # noqa: E402
from tools.gigbar_lights.enttec import EnttecPro, NullOutput, OutputLoop, PluggableOutput, find_port  # noqa: E402
from tools.gigbar_lights import dmx_outputs  # noqa: E402
from tools.gigbar_lights.media_session import MediaSessions  # noqa: E402
from tools.gigbar_lights.looks import LINEUP_SPOTS  # noqa: E402
from tools.gigbar_lights.mixxx_db import MixxxLibrary  # noqa: E402
from tools.gigbar_lights.mixxx_link import DEFAULT_PORT_HINT, MidiInput  # noqa: E402
from tools.gigbar_lights.rig import DERBY_COLORS, KINDS, LASER_COLORS, active_counts, default_rig  # noqa: E402
from tools.gigbar_lights.show import Show, default_cache_dir  # noqa: E402
from tools.gigbar_lights.show_script import ScriptCache  # noqa: E402
from tools.gigbar_lights.system_audio import LoopbackCapture, MixxxWatch, SystemFeed  # noqa: E402
from tools.gigbar_lights.venue import ANCHOR_REACH, DOCTOR_MIN_TAPS, REF_POINTS, HeadCal, Layout, LayoutStore, has_lineup, keep_lineup, presets, rig_numbering, slug as venue_slug, stage_layout  # noqa: E402
from tools.gigbar_lights.version import BUILD, BUILT_CT, CHANNEL, VERSION, label  # noqa: E402

PREVIEW_HTML = HERE / "preview.html"
APP_HTML = HERE / "app.html"
REMOTE_HTML = HERE / "remote.html"   # local mode's phone page (1.8.0)
SHOWS_HTML = HERE / "shows.html"     # Shows: a playlist designed into a whole show, saved by name (1.11.0)
# The Light studio (1.20.0, Llano PM #23195): the Live screen, and the one console every screen
# draws (this window, the phone over Wi-Fi, llano.app/lights), so no screen has buttons another lacks.
STUDIO_HTML = HERE / "studio.html"
# The window's own service worker (Llano BL #12377): when the engine is down, a page load in the window
# shows Llano Lights' plain "not running" screen with Try again, never Edge's "Hmmm... can't reach this page".
SW_JS = HERE / "sw.js"
GUIDE_HTML = HERE / "guide.html"     # the setup guide: cables to a built night, each step checked (1.21, PM #23415)
STUDIO_JS = HERE / "studio_console.js"
# the window's title bar and taskbar take the page's icon; without one Edge shows a globe
ICONS = {"/favicon.ico": ("llano-lights.ico", "image/x-icon"),
         "/icons/icon-16.png": ("icon-16.png", "image/png"),
         "/icons/icon-32.png": ("icon-32.png", "image/png"),
         "/icons/icon-512.png": ("icon-512.png", "image/png")}
ICON_DIR = HERE / "icons"
PORTS = port_set.WINDOW_PORTS   # 8765-8784 on the laptop (ports.py)
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
ALIVE_ORIGIN = re.compile(r"^http://(?:127\.0\.0\.1|localhost):\d{1,5}$")   # another of the window's ports
MAPPING_FILES = ("Llano-Light-Link.js", "Llano-Light-Link.midi.xml")
MAX_POST = 256 * 1024   # a 60-song show with its sections
UPDATE_RECHECK_S = 30 * 60   # an open app asks the update server again this often (1.16.2)
AUDIO_TYPES = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".wav": "audio/wav",
               ".flac": "audio/flac", ".ogg": "audio/ogg", ".opus": "audio/ogg", ".wma": "audio/x-ms-wma"}


def night_failure_words(e: BaseException, what: str) -> str:
    """Why a build of the night stopped, naming the song or hold it was on when that is known (Llano BL
    #11473: "Something went wrong that the build did not expect" told him nothing). `what` is the build's
    last progress line ("Reading Artist - Title", "Writing ...", "Writing the hold for First dance").
    A cause wedding_night.plain_error already names in full (the disk is full, Mixxx holds a file, a song
    with no part) is said as it is; the generic line is kept only when nothing is known."""
    import errno  # noqa: PLC0415
    plain = wedding_night.plain_error(e)
    if isinstance(e, (wedding_night.NightBusy, wedding_night.NeedsPart, MemoryError)) or \
            (isinstance(e, OSError) and e.errno == errno.ENOSPC):
        return plain
    m = re.match(r"(Reading|Writing the hold for|Writing) (.+)$", what.strip())
    if not m or m.group(2).startswith(("the backup", "the handoff")):
        return plain
    verb, name = m.group(1), m.group(2)
    if verb != "Writing the hold for":
        artist, sep, title = name.partition(" - ")
        name = f"{title.strip()} by {artist.strip()}" if sep and title.strip() and artist.strip() else name
    if verb == "Reading":
        return f"The file for {name} could not be read. Replace that file, or take the song out of the show, then build again."
    if verb == "Writing the hold for":
        return f"The silent hold for {name} could not be written. {plain}"
    return f"{name} could not be written into the night's folder. {plain}"


def qr_svg(text: str) -> str:
    """A QR code as SVG for the window (local mode pairing). "" when segno is missing from this
    copy: the window then shows the address and key as text instead."""
    if not text:
        return ""
    try:
        import io  # noqa: PLC0415
        import segno  # noqa: PLC0415
    except ImportError:
        return ""
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="svg", scale=6, border=2, dark="#07080b", light="#ffffff")
    return buf.getvalue().decode()


def layout_payload(lay: Layout) -> dict:
    """A layout plus what the page needs to draw it: each fixture's facing and head spots."""
    d = lay.to_dict()
    d["derived"] = {"facing": {f: lay.facing(f) for f in lay.spots},
                    "heads": [list(p) for _, _, p in lay.all_heads()],
                    # calibration (1.12.1): the dots, where today's aim puts each head on them (the
                    # line-up page starts its raw nudging there), and each head's worst miss
                    "dots": {n: list(lay.ref_target(n)) for n in REF_POINTS},
                    "aims": {f"bar{b}": [{n: list(lay.aim(b, p, lay.ref_target(n), m)) for n in REF_POINTS}
                                         for m, p in enumerate(lay.heads(b))] for b in (1, 2)},
                    "miss": {f"bar{b}": [lay.fit_head(b, m) for m in range(2)] for b in (1, 2)},
                    # each calibrated head's confirmed-spot pulls, so the picture bends its beams the way
                    # the heads are aimed (venue.beam_of; BL #12381: without them a left-side spot drew overshooting)
                    "pull": {f"bar{b}": [lay.anchor_pulls(b, m) for m in range(2)] for b in (1, 2)},
                    "pull_reach": ANCHOR_REACH,
                    # the Light doctor's poses for each head (BL #11615)
                    "doctor": {f"bar{b}": [[list(p) for p in lay.doctor_poses(b, m)] for m in range(2)] for b in (1, 2)}}
    return d


def doctor_rows(rows) -> list[dict]:
    """The Light doctor's samples from the page: each pose's raw pan/tilt, and where on the floor
    he tapped its beam (x, y in meters), or no x/y when he skipped it."""
    if not isinstance(rows, list) or not 0 < len(rows) <= 20:
        raise ValueError("samples must be a list of the poses")
    out = []
    for r in rows:
        p, t = float(r["p"]), float(r["t"])
        if not (0 <= p <= 1 and 0 <= t <= 1):
            raise ValueError("a pose's pan and tilt are 0 to 1")
        row = {"p": p, "t": t}
        if r.get("x") is not None:
            row["x"], row["y"] = float(r["x"]), float(r["y"])
        out.append(row)
    return out


def doctor_report(lay: Layout, bar: int, m: int, rows: list[dict], miss: float) -> dict:
    """What the Light doctor sent and saw, for Llano: every DMX pan/tilt it drove the head to,
    where he tapped (or skipped), and what it worked out."""
    return {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "version": VERSION,
            "layout": lay.name, "bar": bar, "head": m + 1,
            "poses": [{"pan": round(r["p"] * 255), "tilt": round(r["t"] * 255),
                       **({"x": round(r["x"], 2), "y": round(r["y"], 2)} if "x" in r else {"skipped": True})}
                      for r in rows],
            "fit": lay.spots[f"bar{bar}"].cal[m].to_dict(), "miss_deg": round(miss, 1)}


def mixxx_controllers_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", "")) / "Mixxx" / "controllers"
    return Path.home() / ".mixxx" / "controllers"


def app_data_dir() -> Path:
    """Per-user folder for the window profile and the log; never inside the install."""
    if sys.platform == "win32":
        d = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Llano Lights"
    else:
        d = Path.home() / ".local" / "state" / "llano-lights"
    d.mkdir(parents=True, exist_ok=True)
    return d


def enable_windows_colors() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        k.SetConsoleTitleW("Llano Lights")
    except Exception:
        pass


# --- preview window ---------------------------------------------------------------------

class ExclusiveServer(ThreadingHTTPServer):
    """http.server sets SO_REUSEADDR, which on Windows lets a second copy bind a port that is
    already listening; refuse that so each copy gets its own port and the probe finds the first."""
    allow_reuse_address = False

    def server_bind(self):
        if sys.platform == "win32":
            import socket
            self.socket.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", -5), 1)
        super().server_bind()


class Preview:
    """Serves preview.html and the latest DMX frame on 127.0.0.1; keys typed there come back.
    With `app` it also serves the desktop window (app.html + /api/*) and outlives each run.
    Every POST must carry the per-launch token baked into the page, and every request must
    name 127.0.0.1 or localhost as its Host, so no web page he visits can drive the lights."""

    def __init__(self, mode: str, store: "LayoutStore | None" = None, on_layout=None, app=None):
        self.app = app
        self.token = secrets.token_urlsafe(24)
        self.mode = mode
        self.store = store or LayoutStore()
        self.on_layout = on_layout          # called with the Layout the show should aim from
        self.layout = self.store.current()  # what the show is using right now
        self.tried = False                  # self.layout is his unsaved try (Show Designer, calibration)
        self.universe = bytes(512)
        self.status = "starting"
        self.feed = None  # a live show's SystemFeed: what is playing, for llano.app/lights
        self.live = None  # a running show's buttons and beat, for the window (live_state)
        self.frames = 0
        self.sent_frames = 0
        self.trail: "collections.deque" = collections.deque(maxlen=TRAIL_FRAMES)  # [ms, head bytes...] per frame
        self.doctor: "dict | None" = None   # the last Light doctor run (BL #11615)
        self.peek: "studio_peek.Peek | None" = None   # a pad previewed in the picture only (1.20.0)
        self.keys: "queue.Queue[str]" = queue.Queue()
        preview = self

        class Handler(BaseHTTPRequestHandler):
            timeout = 5  # a request that never sends its body can't hold a thread forever

            def log_message(self, *a):
                pass

            def _send(self, body: bytes, ctype: str, code: int = 200):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                # only this app may frame its pages (it frames /preview); no site can clickjack Stop or Live
                self.send_header("Content-Security-Policy", "frame-ancestors 'self'")
                self.send_header("X-Frame-Options", "SAMEORIGIN")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _page(self, path: Path):
                try:   # every window page carries the app's title, so an update closes it (Llano BL #12377)
                    html = path.read_text(encoding="utf-8").replace("__LLANO_TOKEN__", preview.token) \
                        .replace("__LLANO_TITLE__", window_title())
                except OSError:   # a page missing from the build: say so, never an empty response
                    return self._send(f"This copy of Llano Lights is missing {path.name}. Click Check for updates, "
                                      "or download the newest zip from Llano.".encode(), "text/plain; charset=utf-8", 500)
                self._send(html.encode(), "text/html; charset=utf-8")

            def _song(self, name: str):
                """A demo song's audio, with byte ranges so the player can loop and seek."""
                song = next((s for s in demo_songs.load() if s.file == name), None)
                if song is None:
                    return self._send(b"not found", "text/plain", 404)
                self._audio(song.path.read_bytes(), "audio/mpeg")

            def _show_song(self, track_id: str):
                """A show song's file from his Mixxx library, by library id only (never a path from
                the page), so the window can play the show right here."""
                lt = shows.track(MixxxLibrary(), int(track_id)) if track_id.isascii() and track_id.isdigit() else None
                if lt is None or lt.location is None or not lt.location.is_file():
                    return self._send(b"not found", "text/plain", 404)
                try:
                    data = lt.location.read_bytes()
                except OSError:
                    return self._send(b"can't read that file", "text/plain", 404)
                self._audio(data, AUDIO_TYPES.get(lt.location.suffix.lower(), "application/octet-stream"))

            def _point_song(self, key: str):
                """A show song's own file, for Review's play-from-here (Llano PM #23751): only a file the
                points action found for that song key (never a path from the page)."""
                path = preview.app.point_files.get(urllib.parse.unquote(key))
                if path is None or not path.is_file():
                    return self._send(b"not found", "text/plain", 404)
                try:
                    data = path.read_bytes()
                except OSError:
                    return self._send(b"can't read that file", "text/plain", 404)
                self._audio(data, AUDIO_TYPES.get(path.suffix.lower(), "application/octet-stream"))

            def _audio(self, data: bytes, ctype: str):
                start, end = 0, len(data) - 1
                rng = (self.headers.get("Range") or "").strip()
                if rng.startswith("bytes="):
                    a, _, b = rng[6:].split(",")[0].partition("-")
                    try:
                        start, end = (int(a), min(int(b) if b else end, end)) if a else (max(0, len(data) - int(b)), end)
                    except ValueError:
                        start, end = 0, len(data) - 1
                    if start > end or start >= len(data):
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{len(data)}")
                        self.end_headers()
                        return
                self.send_response(206 if rng.startswith("bytes=") else 200)
                self.send_header("Content-Type", ctype)
                self.send_header("Accept-Ranges", "bytes")
                if rng.startswith("bytes="):
                    self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
                self.send_header("Content-Length", str(end - start + 1))
                self.end_headers()
                try:
                    self.wfile.write(data[start:end + 1])
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the player moved on mid-chunk

            def _alive(self):
                """Is the engine up, and on which port: the "not running" screen asks every port of the
                window's (a restart may come back on another one), so only this answer, which carries no
                state and no token, may be read from another 127.0.0.1 port."""
                body = json.dumps({"product": updater.PRODUCT, "version": VERSION}).encode()
                origin = self.headers.get("Origin") or ""
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                if ALIVE_ORIGIN.match(origin):
                    self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _json(self, body: dict, code: int = 200):
                self._send(json.dumps(body).encode(), "application/json", code)

            def _local(self) -> bool:
                host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
                if host in LOCAL_HOSTS:
                    if preview.app:
                        preview.app.touch()
                    return True
                self._send(b"forbidden", "text/plain", 403)
                return False

            def do_GET(self):
                if not self._local():
                    return
                if self.path.split("?")[0] == "/api/alive":   # sw.js's "not running" screen (Llano BL #12377)
                    return self._alive()
                if preview.app and self.path.startswith("/api/app"):
                    return self._json(preview.app.state())
                if preview.app and self.path.split("?")[0] == "/api/guide":   # the setup guide's steps (1.21)
                    return self._json(preview.app.guide_public())
                if preview.app and self.path.split("?")[0] == "/api/studio":   # what the Live screen polls
                    return self._json(preview.app.studio_state())
                if preview.app and self.path.split("?")[0] == "/api/settings":   # the Live screen's Saved panel
                    code, body = preview.app._local_settings(None)
                    return self._json(body, code)
                if preview.app and self.path.startswith("/api/qr?"):   # local mode's pairing codes (1.8.0)
                    from urllib.parse import parse_qs, urlparse
                    svg = qr_svg((parse_qs(urlparse(self.path).query).get("d") or [""])[0][:300])
                    return self._send(svg.encode(), "image/svg+xml") if svg else self._send(b"no qr", "text/plain", 404)
                if self.path.startswith("/state"):
                    preview.sent_frames += 1
                    u, peeking = preview.peek_frame()
                    body = json.dumps({"u": list((u or preview.universe)[:192]), "status": preview.status,
                                       "mode": preview.mode, "frames": preview.frames,
                                       "counts": rig_public()["counts"],
                                       # a previewed pad draws its own frames, never the heads' real trail
                                       "now": frame_ms(), "trail": [] if peeking else list(preview.trail),
                                       "previewing": peeking,
                                       # the spots he steers, for the stage picture's rings and marks
                                       **({"spots": preview.app.stage_now()} if preview.app else {})}).encode()
                    self._send(body, "application/json")
                elif self.path.startswith("/layout"):
                    from urllib.parse import parse_qs, urlparse
                    name = (parse_qs(urlparse(self.path).query).get("name") or [""])[0]
                    lay = preview.store.get(name) if name else preview.layout
                    if lay is None:
                        return self._send(b'{"error": "no such layout"}', "application/json", 404)
                    body = {"layout": layout_payload(lay), "in_use": preview.layout.name, "counts": rig_public()["counts"],
                            "last_lineup": preview.last_lineup_info(),
                            "layouts": [{"name": l.name, "label": l.label, "preset": l.preset}
                                        for l in preview.store.all().values()]}
                    self._send(json.dumps(body).encode(), "application/json")
                elif self.path in ("/", "/index.html") or self.path.startswith("/?"):
                    # The Live screen is the front page once the studio is on (studio.enabled, read
                    # once at launch); the classic window is then Set up, at /setup.
                    # First run (1.21, PM #23415): the setup guide opens first until he finishes it or
                    # presses Not now; every later launch opens on the Live screen as before.
                    if preview.app and preview.app.guide_first():
                        return self._page(GUIDE_HTML)
                    self._page((STUDIO_HTML if preview.app.studio.live else APP_HTML) if preview.app else PREVIEW_HTML)
                elif preview.app and self.path.split("?")[0] == "/setup":
                    self._page(APP_HTML)
                elif preview.app and self.path.split("?")[0] == "/guide":
                    self._page(GUIDE_HTML)
                elif preview.app and self.path.split("?")[0] == "/studio":
                    self._page(STUDIO_HTML)
                elif self.path.split("?")[0] == "/sw.js":   # at the root, so it covers every page (BL #12377)
                    try:
                        # its probe of the window's other ports counts from this copy's base
                        self._send(SW_JS.read_bytes().replace(b"8765 + i", f"{PORTS[0]} + i".encode()),
                                   "text/javascript; charset=utf-8")
                    except OSError:
                        self._send(b"missing from this copy", "text/plain", 404)
                elif preview.app and self.path.split("?")[0] == "/studio_console.js":
                    try:
                        self._send(STUDIO_JS.read_bytes(), "text/javascript; charset=utf-8")
                    except OSError:
                        self._send(b"missing from this copy", "text/plain", 500)
                elif self.path.split("?")[0] == "/api/patch":   # each light's address, mode and spot (BL #12378)
                    rs, lay = patch_now(preview.app, preview.store)
                    self._json({"rows": rs, "layout": lay, "overlaps": patch_sheet.overlaps(rs)})
                elif self.path.split("?")[0] == "/patch.html":   # the printable patch sheet (BL #12378)
                    rs, lay = patch_now(preview.app, preview.store)
                    self._send(patch_sheet.sheet_html(rs, lay).encode(), "text/html; charset=utf-8")
                elif self.path.split("?")[0] in ("/preview", "/lineup.html"):   # /lineup.html: the line-up view
                    self._page(PREVIEW_HTML)
                elif preview.app and self.path.split("?")[0] == "/shows":
                    self._page(SHOWS_HTML)
                elif preview.app and self.path.startswith("/show-audio/"):
                    self._show_song(self.path.split("?")[0][len("/show-audio/"):])
                elif preview.app and self.path.startswith("/song-audio/"):
                    self._point_song(self.path.split("?")[0][len("/song-audio/"):])
                elif self.path.startswith("/demo-songs/"):
                    self._song(self.path.split("?")[0][len("/demo-songs/"):])
                elif self.path.split("?")[0] in ICONS:
                    name, ctype = ICONS[self.path.split("?")[0]]
                    try:
                        self._send((ICON_DIR / name).read_bytes(), ctype)
                    except OSError:
                        self._send(b"not found", "text/plain", 404)
                else:
                    self._send(b"not found", "text/plain", 404)

            def do_POST(self):
                if not self._local():
                    return
                if not secrets.compare_digest(self.headers.get("X-Llano-Token") or "", preview.token):
                    return self._send(b"forbidden", "text/plain", 403)
                if preview.app and self.path.startswith("/api/"):
                    code, body = preview.app.post(self.path[5:].split("?")[0], self._body())
                    return self._json(body, code)
                if self.path.startswith("/key?k="):
                    from urllib.parse import unquote
                    k = unquote(self.path[7:])[:1]
                    if k:
                        preview.keys.put(k)
                    self._send(b"ok", "text/plain")
                elif self.path.startswith("/scene?s="):   # a scene pad (1.6.0); "" = back to the show
                    from urllib.parse import unquote
                    name = unquote(self.path[9:])[:20]
                    if name and name not in settings_contract.SCENES:
                        return self._send(b"no such scene", "text/plain", 400)
                    preview.keys.put("scene:" + name)
                    self._send(b"ok", "text/plain")
                elif self.path.startswith("/lineup?"):   # the line-up check (1.7.0): b=0|1|2&s=spot, b= ends it
                    from urllib.parse import parse_qs, urlparse
                    q = parse_qs(urlparse(self.path).query)
                    bar, spot = (q.get("b") or [""])[0], (q.get("s") or [""])[0]
                    if bar and (bar not in ("0", "1", "2") or spot not in LINEUP_SPOTS):
                        return self._send(b"no such light or spot", "text/plain", 400)
                    if preview.app:   # the window: line-up runs the lights itself when nothing else does
                        code, body = preview.app.lineup(bar, spot)
                        return self._json(body, code)
                    preview.keys.put(f"lineup:{bar}:{spot}" if bar else "lineup:")
                    self._send(b"ok", "text/plain")
                elif self.path.startswith("/lights?"):   # the line-up page's Lights on switch (1.12.3)
                    from urllib.parse import parse_qs, urlparse
                    on = (parse_qs(urlparse(self.path).query).get("on") or [""])[0]
                    if on not in ("0", "1", "2"):   # 2: the whole bar (1.14.1)
                        return self._send(b"on must be 0, 1 or 2", "text/plain", 400)
                    if preview.app:
                        code, body = preview.app.setup_lights(on != "0", whole=on == "2")
                        return self._json(body, code)
                    preview.keys.put("lights:" + on)
                    self._send(b"ok", "text/plain")
                elif self.path.startswith("/calibrate?"):   # one head by raw pan/tilt (1.12.1); b= ends it
                    from urllib.parse import parse_qs, urlparse
                    q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
                    key = "cal:"
                    if q.get("b"):
                        try:
                            bar, m, pan, tilt = int(q["b"]), int(q.get("m", "")), float(q.get("p", "")), float(q.get("t", ""))
                        except ValueError:
                            return self._send(b"bad head or value", "text/plain", 400)
                        if bar not in (1, 2) or m not in (0, 1) or not (0 <= pan <= 1 and 0 <= tilt <= 1):
                            return self._send(b"bad head or value", "text/plain", 400)
                        key = f"cal:{bar}:{m}:{pan:.5f}:{tilt:.5f}"
                    if preview.app:
                        code, body = preview.app.calibrate(key)
                        return self._json(body, code)
                    preview.keys.put(key)
                    self._send(b"ok", "text/plain")
                elif self.path == "/aim":   # Line up my lights, one spot (1.16.0): the heads being lined up
                    msg = self._body()
                    key = "aim:" + (json.dumps(msg) if msg.get("poses") else "")
                    if key != "aim:" and gl.parse_aim(key[4:]) is None:
                        return self._send(b"bad poses", "text/plain", 400)
                    if preview.app:
                        code, body = preview.app.aim(key)
                        return self._json(body, code)
                    preview.keys.put(key)
                    self._send(b"ok", "text/plain")
                elif self.path == "/layout":
                    code, body = preview.layout_post(self)
                    self._send(json.dumps(body).encode(), "application/json", code)
                else:
                    self._send(b"not found", "text/plain", 404)

            def _body(self) -> dict:
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    if not 0 < n <= MAX_POST:
                        return {}
                    msg = json.loads(self.rfile.read(n))
                    return msg if isinstance(msg, dict) else {}
                except (ValueError, OSError):
                    return {}

        self.server = None
        for port in PORTS:
            try:
                self.server = ExclusiveServer(("127.0.0.1", port), Handler)
                break
            except OSError:
                continue
        if self.server is None:
            raise RuntimeError(f"No free local port for the preview window ({port_set.span(PORTS)}).")
        self.url = f"http://127.0.0.1:{self.server.server_port}/"
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def layout_post(self, req) -> tuple[int, dict]:
        """try = aim the show from this layout now (not saved); save = keep it as his own
        and use it from now on; use = switch to a preset or saved layout by name."""
        carried = []   # Stage setup: the heads whose line-up came along (BL #12400)
        try:
            n = int(req.headers.get("Content-Length") or 0)
            if not 0 < n <= MAX_POST:
                raise ValueError("empty or too large")
            msg = json.loads(req.rfile.read(n))
            action = msg.get("action")
            if action == "spotaim":   # one spot (1.16.0): each head's pose for a floor spot; changes nothing
                lay = Layout.from_dict(msg.get("layout"))
                x, y = float(msg["target"]["x"]), float(msg["target"]["y"])
                z = float(msg["target"].get("z") or 0.0)   # Set how far the heads go (PM #23796): over heads
                if not (0 <= x <= lay.room[0] and 0 <= y <= lay.room[1] and 0 <= z <= lay.room[2]):
                    raise ValueError("the spot is outside the room")
                # A saved center that can't be used (venue.cal_problem, 1.16.4): the page says so, and
                # aims that head by the guess, so Line up starts it facing the floor, not backwards.
                bad = {f"{b}:{m}": why for b in (1, 2) for m in (0, 1) if (why := lay.cal_problem(b, m))}
                poses = {f"{b}:{m}": lay.aim(b, lay.heads(b)[m], (x, y, z), m) for b in (1, 2) for m in (0, 1)}
                for key in bad:   # the guess, turned round to face the spot the way the other heads do
                    b, m = map(int, key.split(":"))
                    guess = Layout.from_dict(lay.to_dict())
                    guess.spots[f"bar{b}"].cal[m] = HeadCal()
                    poses[key] = lay.facing_pose(*guess.aim(b, guess.heads(b)[m], (x, y, z), m))
                return 200, {"ok": True, "poses": {k: [round(v, 5) for v in p] for k, p in poses.items()}, "cal_problems": bad}
            if action in ("rename", "delete"):   # My venues (BL #12380): the show keeps aiming as it was
                name = str(msg.get("name") or "")
                if action == "rename":
                    lay = self.store.rename(name, msg.get("label"))
                    if self.layout.name == name and not self.tried:
                        self.layout = lay
                    if self.app:
                        self.app.layout_changed(lay, saved=True, use=False)
                else:
                    if self.layout.name == name:
                        raise ValueError("the show is aiming from this venue: use another one first, then delete it")
                    self.store.delete(name)
                    if self.app:
                        self.app.layout_removed(name)
                return 200, {"ok": True, "in_use": self.layout.name, "name": name,
                             **({"label": lay.label} if action == "rename" else {})}
            if action == "use":
                lay = self.store.use(str(msg.get("name") or ""))
                if not has_lineup(lay):   # a venue never lined up: his last line-up comes along (PM #23745)
                    last = self.store.last_lineup()
                    carried = lay.carry_lineup(last[0]) if last else []
            elif action == "restore_lineup":   # Bring back my line-up (PM #23745): the last one he saved, on this room
                lay = Layout.from_dict(msg.get("layout"))
                last = self.store.last_lineup()
                if last is None:
                    raise ValueError("there is no saved line-up to bring back yet")
                for b in (1, 2):
                    lay.spots[f"bar{b}"].cal = [HeadCal(), HeadCal()]
                carried = keep_lineup(lay, last[0])
                if not carried:
                    raise ValueError("your last line-up doesn't fit this room: line up again with Line up my lights")
            elif action == "flip":   # the Mirror button: around the calibrated center (1.12.1)
                lay = Layout.from_dict(msg.get("layout"))
                bar = msg.get("bar")
                if bar not in (1, 2):
                    raise ValueError("bar must be 1 or 2")
                lay.flip_pan(bar)
            elif action == "doctor":   # the Light doctor (BL #11615): one head, from where he tapped its beams
                lay = Layout.from_dict(msg.get("layout"))
                bar, m = msg.get("bar"), msg.get("m")
                if bar not in (1, 2) or m not in (0, 1):
                    raise ValueError("bar must be 1 or 2 and m 0 or 1")
                rows = doctor_rows(msg.get("samples"))
                if sum("x" in r for r in rows) < DOCTOR_MIN_TAPS:   # the doctor's 5 poses work everything out
                    raise ValueError(f"tap at least {DOCTOR_MIN_TAPS} beams so the doctor can work this head out")
                cal, miss = lay.fit_taps(bar, m, [(r["p"], r["t"], (r["x"], r["y"])) for r in rows if "x" in r])
                cal.anchors = list(lay.spots[f"bar{bar}"].cal[m].anchors)   # the spots he lined up stay (BL #11766)
                lay.spots[f"bar{bar}"].cal[m] = cal
                self.doctor = doctor_report(lay, bar, m, rows, miss)
                print(f"Light doctor: GigBAR {bar} head {m + 1} from {sum('x' in r for r in rows)} taps, "
                      f"misses by {miss:.1f} degrees at most: {json.dumps(self.doctor)}")
                if self.app:
                    self.app.doctor = self.doctor
            elif action == "tapaim":   # tap to aim (11-09): where a pose's beam landed, then where it should
                lay = Layout.from_dict(msg.get("layout"))
                bar, m = msg.get("bar"), msg.get("m")
                if bar not in (1, 2) or m not in (0, 1):
                    raise ValueError("bar must be 1 or 2 and m 0 or 1")
                rows = [r for r in doctor_rows(msg.get("samples")) if "x" in r]
                cal, miss = lay.fit_taps(bar, m, [(r["p"], r["t"], (r["x"], r["y"])) for r in rows])
                cal.anchors = list(lay.spots[f"bar{bar}"].cal[m].anchors)   # the spots he lined up stay (BL #11766)
                lay.spots[f"bar{bar}"].cal[m] = cal
                want = msg.get("want")
                pose = None
                if want is not None:
                    pose = [round(v, 5) for v in lay.aim(bar, lay.heads(bar)[m], (float(want["x"]), float(want["y"]), 0.0), m)]
                self.doctor = {**doctor_report(lay, bar, m, rows, miss), "kind": "tap to aim",
                               **({"want": {"x": round(float(want["x"]), 2), "y": round(float(want["y"]), 2)},
                                   "aimed": {"pan": round(pose[0] * 255), "tilt": round(pose[1] * 255)}} if pose else {})}
                print(f"Tap to aim: GigBAR {bar} head {m + 1} from {len(rows)} taps: {json.dumps(self.doctor)}")
                if self.app:
                    self.app.doctor = self.doctor
            elif action == "converge":   # one spot (1.16.0): every head lined up on it; facing, height, heads
                lay = Layout.from_dict(msg.get("layout"))
                rows = msg.get("samples")
                if not isinstance(rows, list) or not 0 < len(rows) <= 40:
                    raise ValueError("samples must list each head's pose on the spot")
                samples = [(int(r["b"]), int(r["m"]), float(r["p"]), float(r["t"]), (float(r["x"]), float(r["y"])))
                           for r in rows]
                if any(not (0 <= p <= 1 and 0 <= t <= 1) for _, _, p, t, _ in samples):
                    raise ValueError("a pose's pan and tilt are 0 to 1")
                if any(not (0 <= x <= lay.room[0] and 0 <= y <= lay.room[1]) for *_, (x, y) in samples):   # NaN fails too
                    raise ValueError("the spot is outside the room")
                found = lay.converge(samples)
                self.doctor = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "version": VERSION,
                               "kind": "one spot", "layout": lay.name, "found": found,
                               "poses": [{"bar": b, "head": m + 1, "pan": round(p * 255), "tilt": round(t * 255),
                                          "x": round(x, 2), "y": round(y, 2)} for b, m, p, t, (x, y) in samples]}
                print(f"One spot: {json.dumps(self.doctor)}")
                if self.app:
                    self.app.doctor = self.doctor
            elif action == "stage":   # Stage setup (BL #12344): three numbers in meters draw the room; aimed now, not saved
                # numbered from the end his cords start at (BL #12396), never re-derived left to right
                lay = stage_layout(msg.get("stage_w"), msg.get("floor_d"), msg.get("bar_h"), numbering=rig_numbering())
                # His line-up comes along (BL #12400): how each head turns on its bar, from the room playing now,
                # else his saved room with a line-up. Without it every head fell back to the guess, which
                # points head 1 of each GigBAR backwards on his rig.
                last = self.store.last_lineup()
                for src in (self.layout, *([last[0]] if last else []), *self.store.saved().values()):
                    if src is not None and any(src.cal(b, m) for b in (1, 2) for m in (0, 1)):
                        carried = lay.carry_lineup(src)
                        break
            elif action == "numbers":   # Flip the Tetra / stick numbers (BL #12378): aimed now, not saved
                lay = Layout.from_dict(msg.get("layout"))
                kind = msg.get("kind")
                if kind not in ("tetra", "stick"):
                    raise ValueError("kind must be tetra or stick")
                lay.renumber(kind)
                side = lay.number_side(kind)
                # The end light 1 starts at is a rig fact (BL #12396): the next Stage setup and every
                # ready-made room number from it, and llano.app keeps it like any other setting.
                if side and self.app:
                    self.app.link.local_change([{"path": f"rig.numbering.{kind}", "value": side}])
            elif action in ("try", "save"):
                lay = Layout.from_dict(msg.get("layout"))
                if action == "save":
                    cleared = msg.get("cleared") or []
                    if not isinstance(cleared, list) or any(b not in (1, 2) for b in cleared):
                        raise ValueError("cleared lists the GigBARs he cleared, 1 or 2")
                    lay = self.store.save(lay, cleared=cleared)
                    self.store.use(lay.name)
                    if lay.kept_lineup:
                        print(f"Saved {lay.label}: kept the line-up of GigBAR {', '.join(map(str, lay.kept_lineup))} "
                              f"(the page sent the room without it)")
            else:
                raise ValueError("action must be use, try, stage, numbers, flip, doctor, tapaim, spotaim, converge, save, rename or delete")
        except (ValueError, TypeError, AttributeError, KeyError) as e:
            return 400, {"error": str(e)}
        except OSError as e:  # file in use (antivirus, indexer), disk full: say so on the page
            return 500, {"error": f"couldn't save the layout file: {e}"}
        self.layout, self.tried = lay, action in ("try", "stage", "numbers", "flip", "doctor", "tapaim", "converge", "restore_lineup")
        if self.on_layout:
            self.on_layout(lay)
        if self.app and action in ("use", "save"):
            self.app.layout_changed(lay, saved=action == "save")
        out = {"ok": True, "layout": layout_payload(lay), "in_use": lay.name}
        if action in ("stage", "use"):
            out["carried"] = len(carried)
        if action == "restore_lineup":
            out["restored"] = carried   # the GigBARs whose line-up came back
        if action == "save":
            out["kept_lineup"] = lay.kept_lineup
        out["last_lineup"] = self.last_lineup_info()
        if action in ("doctor", "tapaim", "converge"):
            out["doctor"] = self.doctor
        if action == "tapaim" and pose is not None:
            out["pose"] = pose
        return 200, out

    def last_lineup_info(self) -> Optional[dict]:
        """The last line-up he saved (PM #23745), for Bring back my line-up: which room and when, or None."""
        try:
            last = self.store.last_lineup()
        except Exception:  # noqa: BLE001 -- ok: the button just doesn't show
            return None
        return None if last is None else {"label": last[0].label, "name": last[0].name, "at": last[1]}

    def peek_frame(self) -> tuple:
        """(the previewed pad's frame, its name), or (None, "") when no pad is being previewed. A
        preview nobody renews ends by itself, and one that fails ends at once: the picture goes
        back to what the lights are doing."""
        peek = self.peek
        if peek is None:
            return None, ""
        if peek.over():
            self.peek = None
            return None, ""
        try:
            with PEEK_LOCK:
                return peek.render(), peek.name
        except Exception as e:  # noqa: BLE001 -- ok: a preview is a nicety; the real picture comes back
            print(f"Pad preview ended: {type(e).__name__}: {e}")
            self.peek = None
            return None, ""

    def begin(self, mode: str, on_layout) -> None:
        """A new run on the long-lived window server. An unsaved try carries over (1.12.3): picking
        a head to calibrate starts the line-up run, and that start used to drop the dots set
        before it (his 11-08 layout kept only GigBAR 1's head 2)."""
        if not self.tried:
            self.layout = self.store.current()
        self.mode, self.on_layout, self.status, self.frames, self.live = mode, on_layout, "starting", 0, None

    def end(self) -> None:
        self.mode, self.on_layout, self.status, self.universe, self.live = "", None, "stopped", bytes(512), None
        self.trail.clear()
        while not self.keys.empty():  # a key pressed after the show stopped must not reach the next one
            self.keys.get()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


PEEK_LOCK = threading.Lock()   # one picture request renders a previewed pad at a time

STALL_FRAMES = 40   # about a second of frames the ENTTEC refused in a row: say so once
# The heads' pan/tilt bytes of every frame sent, stamped, so the picture can play them back
# smoothly (BL #11615): a poll every 30 ms caught one 40 Hz frame at a time and the beams jumped.
HEAD_BYTES = (23, 24, 29, 30, 63, 64, 69, 70)   # pan, tilt of head 1 and 2 on GigBAR 1, then GigBAR 2
TRAIL_FRAMES = 16                               # ~0.4 s of frames, more than one poll's worth
PIC_SLACK = 7.0                                 # the picture's glide stays this close to the byte sent (glide.PAN_GATE_STEPS + rounding)


def frame_ms() -> int:
    """The clock the trail is stamped with; /state sends it so the page can line its own up."""
    return int(time.monotonic() * 1000)


class TeeOutput:
    """Sends each frame to the real output (ENTTEC or nothing) and keeps it for the preview.
    A frame the box refuses is dropped, never raised (1.12.4, his 11-08 log: one ENTTEC write
    timeout ended Control a light); after STALL_FRAMES in a row the log and status say so."""

    def __init__(self, inner, preview: Preview, picture=None):
        self.inner, self.preview = inner, preview
        self.picture = picture   # Show.picture_slots: the heads unrounded, for the picture (1.16.3)
        self.errors = self.failing = 0
        if isinstance(inner, PluggableOutput) and inner.on_change is None:
            inner.on_change = self._box_changed

    @property
    def port(self) -> str:
        return self.inner.port   # a box plugged in mid-run shows its own port

    def _box_changed(self, port: str) -> None:
        """The box arrived or went mid-run (PluggableOutput): the log, the status line and the
        window's lights dot say so, and the calm note clears once the lights are on."""
        if port:
            print(f"The lights box is connected on {port}: the lights follow the show now.")
            self.preview.status = f"Lights connected on {port}"
        else:
            print("The lights box stopped answering (unplugged?). The show keeps going in the room picture; "
                  "plug it back in and the lights pick up by themselves.")
            self.preview.status = LIGHTS_GONE
        app = getattr(self.preview, "app", None)
        if app is not None:
            app.lights_changed(port)

    def send(self, universe: bytes) -> None:
        universe = probes.apply(bytes(universe))   # a Llano session's probe (1.14.0), over whatever runs
        self.preview.universe = universe
        self.preview.frames += 1
        row = [frame_ms(), *(universe[i] for i in HEAD_BYTES)]
        pic = self.picture() if self.picture else None
        if pic:
            # The picture's own columns after the bytes: the glide unrounded and without its hold-
            # and-move gate, so a slow move sweeps on screen and both heads move together (1.16.3).
            # A slot a probe or anything else moved away from the glide draws its byte.
            row += [round(pic[i], 2) if i in pic and abs(pic[i] - universe[i]) <= PIC_SLACK else universe[i]
                    for i in HEAD_BYTES]
        self.preview.trail.append(row)
        try:
            self.inner.send(universe)
        except Exception as e:  # noqa: BLE001 -- a stalled or unplugged box: the next frame retries
            self.errors += 1
            self.failing += 1
            if self.failing == STALL_FRAMES:
                print(f"The ENTTEC box on {self.port} stopped taking data ({type(e).__name__}). "
                      "Plug it straight into the laptop, not a hub, or unplug it and plug it back in.")
                self.preview.status = f"The lights box on {self.port} stopped taking data: unplug it and plug it back in"
            return
        if self.failing >= STALL_FRAMES:
            print(f"The ENTTEC box on {self.port} is taking data again.")
        self.failing = 0

    def close(self) -> None:
        self.inner.close()


class Quit(KeyboardInterrupt):
    pass


def live_state(show: Show) -> dict:
    """What the window's buttons and beat light show (1.7.0, his recording 1:28 and 1:45): each
    toggle's on/off state, and the beat as (beat, BPM, at) so the light keeps time between polls."""
    ov, f = show.looks.overrides, show.last_frame
    return {"blackout": ov.blackout, "strobe": ov.strobe, "hold": ov.hold_loop,
            "color": ov.color_hold is not None, "autoloops": ov.autoloop_override,
            "master": round(ov.master, 2), "bpm": round(f.bpm if f else show.clock.bpm, 2),
            "beat": round(f.beat, 3) if f else 0.0, "playing": bool(f and f.playing), "at": time.time(),
            "scene": ov.scene, "offset_ms": round(show.offset_ms),
            # beats from Mixxx in the last 3 s: the setup guide's "Hear Mixxx" step (1.21)
            "mixxx_heard": bool(show.state.last_message) and time.perf_counter() - show.state.last_message < 3.0,
            # the cue timeline's song (Show.timeline, Llano PM #23787): None when nothing with a grid plays
            "timeline": show.timeline() if hasattr(show, "timeline") else None}


def run_with_preview(show: Show, inner, mode: str, opts, feed=None, page: str = "") -> int:
    shared = getattr(opts, "preview", None)  # the desktop window's server, kept between runs
    if shared:
        preview = shared
        preview.begin(mode, show.set_venue)
    else:
        preview = Preview(mode, LayoutStore(), on_layout=show.set_venue)
    gui = shared is not None
    show.set_venue(preview.layout)
    st = getattr(opts, "studio", None)   # the launch's Light studio: what he holds carries from run to run
    if st is not None:
        show.studio = st
        with st.lock:
            st.layout = show.looks.venue
    output = TeeOutput(inner, preview, picture=getattr(show, "picture_slots", None))
    print(f"Room layout: {preview.layout.label} (change it in the Show Designer)")
    if not gui:
        print(f"Light preview: {preview.url}{page}")
        if not opts.no_browser:
            webbrowser.open(preview.url + page)
        print("Keys work in this window or the preview: b blackout, s strobe, space tap tempo, "
              "a autoloops, n/p next/prev look, h hold, c color, +/- brightness, [ ] timing, 0 timing reset, q quit.\n")
    last = [0.0]
    width = max(40, shutil.get_terminal_size((100, 20)).columns - 1)

    def tick(now: float) -> None:
        if feed:
            feed(now)
        pressed = not preview.keys.empty()
        while not preview.keys.empty():
            if not gl.handle_key(preview.keys.get(), show):
                raise Quit
        if pressed:  # a button's new state shows on the next poll, not a quarter second later
            preview.live = live_state(show)
        if now - last[0] > 0.25:
            last[0] = now
            preview.live = live_state(show)
            preview.status = show.looks.mode.replace("line-up: ", "Lining up ") if mode.startswith("Line up") \
                else show.status(now).replace("unknown track", "demo song") \
                if "pretend song" in mode else show.status(now).replace("deck 1: ", "Playing ") \
                if mode.startswith("Demo:") else show.status(now)
            if not gui:
                print("\r" + preview.status[:width].ljust(width), end="", flush=True)

    try:
        rc = gl._run_loop(show, output, seconds=opts.seconds, feed=tick, view=False, read_keys=not gui)
    finally:
        preview.end() if gui else preview.close()
    print(f"Frames rendered: {preview.frames}; preview refreshes served: {preview.sent_frames}.")
    return rc


# --- modes ------------------------------------------------------------------------------

def mode_demo(opts) -> int:
    show = Show(analyze=False)
    song = demo_songs.find(getattr(opts, "song", "") or "")
    # "Also on the lights" (1.7.0, his recording 7:00): the window plays the song and the real
    # lights follow it, the way to see and hear a show with no Mixxx and no Spotify.
    inner = _lights_out() if getattr(opts, "lights", False) else NullOutput()
    where = _where(inner) if getattr(opts, "lights", False) else "nothing plugged in"
    if song:
        print(f"DEMO: {song.title} by {song.artist} ({song.feel.lower()}, {song.bpm:.0f} BPM). The lights follow")
        print("its beat and its sections: " + ", ".join(s["kind"] for s in song.sections) + ".")
        print(song.credit + f" ({song.license_url})")
        return run_with_preview(show, inner, f"Demo: {song.title}, {where}", opts,
                                feed=demo_songs.SongFeed(show, song, getattr(opts, "song_clock", None)))
    print("DEMO: a pretend 128 BPM song runs through intro, build, drop, breakdown, build, drop, outro.")
    print("No Mixxx and no lights needed. A full pass takes about 2 minutes 15 seconds.")
    return run_with_preview(show, inner, f"Demo: pretend song, {where}", opts,
                            feed=gl.FakeMixxx(show, opts.bpm))


def mode_designer(opts) -> int:
    show = Show(analyze=False)
    print("SHOW DESIGNER: pick a room layout or drag the lights where they'll stand, and watch")
    print("the pretend song play in the room. Save a layout and the real show aims from it.")
    return run_with_preview(show, NullOutput(), "Show Designer: pretend song, nothing plugged in", opts,
                            feed=gl.FakeMixxx(show, opts.bpm), page="#designer")


def mode_show(opts) -> int:
    """A saved show front to back: the Shows page plays each song (or a silent clock for a song not
    on this laptop) and the lights follow its sections with the look the show gives it."""
    songs = getattr(opts, "show_songs", None)
    if songs is None:   # from the command line: the saved show by name
        got = shows.load(getattr(opts, "show", "") or "", MixxxLibrary(), ScriptCache(default_cache_dir()))
        if got is None:
            print(f"No saved show called '{getattr(opts, 'show', '')}'. Saved: "
                  + (", ".join(x["name"] for x in shows.list_public()) or "none yet"))
            return 2
        songs = shows.from_public(got["songs"])
    if not songs:
        print("That show has no songs.")
        return 2
    inner = _lights_out() if getattr(opts, "lights", False) else NullOutput()
    where = _where(inner) if getattr(opts, "lights", False) else "nothing plugged in"
    title = getattr(opts, "show_title", "") or getattr(opts, "show", "") or "show"
    print(f"SHOW: {title}, {len(songs)} songs. " + "; ".join(f"{i + 1}. {s.title} ({s.look or 'house'})"
                                                             for i, s in enumerate(songs)))
    show = Show(analyze=False)
    shows.follow(songs, getattr(opts, "show_own", None), getattr(opts, "show_moods", None))
    opts.show_feed = shows.ShowFeed(show, songs, getattr(opts, "song_clock", None))
    try:
        return run_with_preview(show, inner, f"Show: {title}, {where}", opts, feed=opts.show_feed)
    finally:
        show_settings.set_show_looks(None)


def _live_show(opts) -> Show:
    library = MixxxLibrary()
    if not library.available():
        print(f"Note: Mixxx's music library was not found at {library.path}, so song names and "
              "song sections are off for Mixxx (the lights still follow the beat).")
    return Show(library, ScriptCache(default_cache_dir()))


def _open_midi(on_message):
    try:
        midi = MidiInput(on_message, DEFAULT_PORT_HINT)
    except ImportError:
        print("The MIDI library is missing from this install, so Mixxx can't drive the lights.")
        return None
    except RuntimeError as e:
        print(f"\nNot hearing Mixxx: {e}")
        print("That's fine for Spotify or YouTube Music. For Mixxx: loopMIDI running with a port named "
              "exactly 'Llano Mixxx', and in Mixxx Preferences > Controllers the 'Llano Mixxx' "
              "controller enabled with the 'Llano Light Link' mapping.")
        return None
    print(f"Listening to Mixxx on '{midi.port_name}'.")
    return midi


class SharedInputs:
    """What a live show listens to, opened ONCE per app run and lent to each show (1.20.1, his 11-13
    10:04 crash): 1.20.0 opened the Mixxx MIDI port, the speaker capture (WASAPI) and Windows' now
    playing (WinRT) for every show and closed them at Stop. His second live show of a run, started
    straight from Scenes, crashed inside that setup (the first one of the run was fine). Kept open,
    a show's start and Stop never create or destroy those native objects; only the first show does."""

    def __init__(self):
        self.lock = threading.Lock()
        self.watch: "MixxxWatch | None" = None
        self.capture: "LoopbackCapture | None" = None
        self.media: "MediaSessions | None" = None
        self.midi = None
        self.target = None   # the playing show's MIDI handler; None between shows (messages dropped)

    def start(self) -> "SharedInputs":
        with self.lock:
            if self.watch is None:
                self.watch = MixxxWatch().start()
                self.capture = LoopbackCapture().start()
                self.media = MediaSessions().start()
        return self

    def _deliver(self, msg) -> None:
        t = self.target
        if t is not None:
            t(msg)

    def open_midi(self):
        """The Mixxx link: the one already open while its port is still there, else a new try (Mixxx
        or loopMIDI may have been set up since the last show)."""
        with self.lock:
            if self.midi is not None and not self.midi.still_there():
                print(f"The MIDI port '{self.midi.port_name}' is gone; opening it again.")
                bounded("the old Mixxx MIDI link", self.midi.close)
                self.midi = None
            if self.midi is None:
                self.midi = _open_midi(self._deliver)
            else:
                print(f"Listening to Mixxx on '{self.midi.port_name}'.")
            return self.midi


_inputs = SharedInputs()


class LiveSources:
    """Everything a live show listens to: Mixxx over MIDI when it is set up, plus what the
    laptop plays (Spotify, YouTube Music) and the song name Windows shows for it. Who gets
    the lights when is SystemFeed's call (system_audio.py). The listeners themselves are the
    app's (SharedInputs); a show borrows them and gives them back at Stop."""

    def __init__(self, show: Show, opts, inputs: "SharedInputs | None" = None):
        self.inputs = (inputs or _inputs).start()
        self.midi, self.preview = None, None
        self.watch, self.capture, self.media = self.inputs.watch, self.inputs.capture, self.inputs.media
        self.feed = SystemFeed(show, self.capture, self.media, show.library, watch=self.watch)

        def from_mixxx(msg) -> None:
            self.feed.saw_mixxx()
            show.on_midi(msg)

        self.inputs.target = from_mixxx
        try:
            self.midi = self.inputs.open_midi()
        except BaseException:
            self.close()
            raise
        self.feed.mixxx_link = self.midi is not None
        self.preview = getattr(opts, "preview", None)
        if self.preview is not None:
            self.preview.feed = self.feed  # llano.app/lights reads what is playing from here
        if self.feed.use_audio:
            print("Also following what this laptop plays: start a song in Spotify or YouTube Music.")
        else:
            print("Spotify / YouTube Music following is off (LLANO_LIGHTS_SYSTEM_AUDIO=0): Mixxx only.")

    def close(self) -> None:
        """Give the listeners back: nothing native is closed here (see SharedInputs)."""
        if self.preview is not None:
            self.preview.feed = None
        self.inputs.target = None
        self.capture.want.clear()   # the speaker stream closes until the next show wants it


CLOSE_WAIT_S = 3.0


def bounded(what: str, fn, seconds: float = CLOSE_WAIT_S) -> bool:
    """Run a close that a driver could hang (1.12.4, his 11-08 hang after a live show) on its
    own thread and wait at most `seconds`; past that it is left behind so the app keeps
    answering. True when it finished."""
    t = threading.Thread(target=fn, name=f"close {what}", daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        print(f"Closing {what} didn't finish within {seconds:.0f} s; left it behind so Llano Lights keeps answering.")
        return False
    return True


def mode_preview(opts) -> int:
    show = _live_show(opts)
    sources = LiveSources(show, opts)
    print("PREVIEW: nothing is sent to any lights.")
    try:
        return run_with_preview(show, NullOutput(), "Music, no lights plugged in", opts, feed=sources.feed)
    finally:
        sources.close()


def _lights_out() -> PluggableOutput:
    """The lights for a run, never a refusal (his ask, 2026-11-13: everything opens and works with no
    USB adapter, and the lights pick up on their own when it is plugged in). Looks for the box through
    _enttec_port, the same scan the window's dots use; LLANO_LIGHTS_OUTPUT picks another output
    (Open DMX, Art-Net, sACN: dmx_outputs.py, Llano BL #12136)."""
    return dmx_outputs.pluggable(lambda: _enttec_port())


def _where(out) -> str:
    """Where a run's frames go, for the status line and the log."""
    return f"lights on {out.port}" if out.connected else LIGHTS_WAIT


def _open_enttec():
    """The lights box for a probe: the ENTTEC Pro, or LLANO_LIGHTS_OUTPUT's box or node (dmx_outputs)."""
    try:
        if dmx_outputs.from_env() is not None:
            where = _enttec_port()
            if not where:
                raise RuntimeError(f"No lights box found for {dmx_outputs.ENV}={os.environ.get(dmx_outputs.ENV)}.")
            return dmx_outputs.open_env(where)
        return EnttecPro()
    except RuntimeError as e:
        print(f"\n{e}\nTo try the show without the box, pick 'Music, no lights' instead.")
    except Exception as e:  # port busy (SoundSwitch open), permissions
        print(f"\nCouldn't open the ENTTEC: {e}\nIf SoundSwitch is open, close it first.")
    return None


def mode_live(opts) -> int:
    out = _lights_out()
    show = _live_show(opts)
    sources = LiveSources(show, opts)
    print(f"LIVE: {_where(out)}.")
    try:
        return run_with_preview(show, out, f"Live show, {_where(out)}", opts, feed=sources.feed)
    finally:
        sources.close()


def mode_test(opts) -> int:
    """Each light white for 2 seconds, one after another (his recording, 4:13): on the real lights
    when the ENTTEC box is plugged in, and always in the room picture, so it needs no live show and
    works with nothing plugged in. Stop ends it at once."""
    out = inner = _lights_out()
    preview = getattr(opts, "preview", None)
    sink = TeeOutput(inner, preview) if preview else inner
    print("Each light turns white for 2 seconds, one after another" +
          (f", on the lights ({inner.port})." if out.connected else ". No lights box is plugged in, so watch the room picture."))
    rig = default_rig()
    if preview:
        preview.begin("Test each light", None)
    try:
        tonight = rig.present(rig_public()["counts"]).fixtures   # the rig picker's lights only (1.13.0)
        for i, fx in enumerate(tonight, 1):
            rig.reset()
            gl.light_white(fx)
            line = f"Light {i} of {len(tonight)}: {fx.name} (address {rig_address(rig.fixtures.index(fx), fx):03d}) is white now"
            print(line)
            if preview:
                preview.status = line + ("" if out.connected else " in the picture (no lights box plugged in)")
            end = time.perf_counter() + 2.0
            while time.perf_counter() < end:
                sink.send(rig.render())
                time.sleep(0.025)
                while preview and not preview.keys.empty():
                    if preview.keys.get() == "q":
                        raise Quit
    except Quit:
        print("Test stopped.")
    finally:
        sink.send(bytes(512))
        inner.close()
        if preview:
            preview.end()
    return 0


def _enttec_port():
    """The lights box's serial port, or None (not plugged in, or the port list failed): the ENTTEC Pro,
    or with LLANO_LIGHTS_OUTPUT set its box's port or network target (dmx_outputs.find_env)."""
    with SETUP_LOCK:
        try:
            return dmx_outputs.find_env()
        except Exception:  # noqa: BLE001 -- the window says "not plugged in" either way
            return None


# --- Control a light by hand (1.10.0, his recording 6:09) ------------------------------------
# "pick a light ... turn it on, turn it off, adjust the color, this way or that way, the
# intensity, the strobe ... just to test it". On the lights when the box is plugged in, and
# always in the room picture.

MANUAL_DEFAULT = {"on": False, "color": "#ffffff", "dim": 1.0, "strobe": 0.0, "pan": 0.5, "tilt": 0.5}
# A GigBAR's other lights (1.12.3, his 11-08 report "you missed adding the channels for the other
# lights like the lasers"): derbies, laser, white and UV strobe, and the heads' color wheel and gobo.
GIGBAR_DEFAULT = {"derby": "off", "derby_spin": 0.0, "laser": "off", "laser_strobe": 0.0, "laser_spin": 0.0,
                  "white": 0.0, "uv": 0.0, "flash_speed": 0.5, "head_color": 0, "gobo": 0, "par_uv": 0.0}


def rig_address(i: int, fx) -> int:
    """Where fixture i really starts: the rig block's address (rig.render places it there)."""
    from tools.gigbar_lights.settings_contract import FIXTURES
    return ((show_settings.current().get("rig") or {}).get("addresses") or {}).get(list(FIXTURES)[i], fx.address)


def patch_now(app=None, store=None) -> tuple[list, str]:
    """Every light's address and channel mode from the rig block in force, and where it stands in the
    layout in use (BL #12378): the rows the room picture, Set up, the patch sheet and the run sheet show."""
    try:
        # the window's own layout store first: the room picture draws from it and Save my layout writes it
        store = store or getattr(getattr(app, "preview", None), "store", None) or getattr(app, "layouts", None) or LayoutStore()
        lay = store.current()
    except Exception:  # noqa: BLE001 -- ok: no readable layout only loses the "where it stands" column
        lay = None
    rs = patch_sheet.rows(show_settings.current().get("rig") or {}, lay)
    return rs, (lay.label or lay.name) if lay is not None else ""


def rig_public() -> dict:
    """The rig picker (1.13.0, his 11-08 "I've only got 3 tetras running right now"): how many of
    each light are set up tonight, the saved rigs by name, and the most of each."""
    rig = show_settings.current().get("rig") or {}
    return {"counts": active_counts(rig.get("counts")), "most": dict(KINDS),
            "saved": {n: active_counts(c) for n, c in (rig.get("saved") or {}).items()}}


def present_ids() -> set:
    """The window's light ids (light_list order) set up tonight."""
    r = default_rig()
    on = {id(fx) for fx in r.present(rig_public()["counts"]).fixtures}
    return {i for i, fx in enumerate(r.fixtures) if id(fx) in on}


# A GigBAR Move's 11 parts by name, as you face the bar from the dance floor (1.14.1, his 11-08
# correction "2 moving heads, 2 RGB derbies, 2 RGB+UV pars, 4 white/UV strobes, and a red/green
# laser"). R is the first of each pair on the 35CH map (head 1 is the right one, 1.12.3); the 4
# strobes share one set of channels (ch20-23) in every DMX mode, so they are one part.
GIGBAR_PARTS = (("spot_l", "Spot L"), ("spot_r", "Spot R"), ("derby_l", "Derby L"), ("derby_r", "Derby R"),
                ("par_l", "Par L"), ("par_r", "Par R"), ("strobes", "Strobes"), ("laser", "Laser"))
PART_KEYS = dict(GIGBAR_PARTS)


def light_list() -> list[dict]:
    """The window's light picker: every fixture in address order; aim = it has heads that move;
    a GigBAR also lists its parts by name ("Bar 1: Spot L"), each its own pick."""
    out, bar = [], 0
    for i, fx in enumerate(default_rig().fixtures):
        row = {"id": i, "name": fx.name, "address": rig_address(i, fx), "aim": hasattr(fx, "movers")}
        if row["aim"]:
            bar += 1
            row["parts"] = [{"id": f"{i}:{k}", "part": k, "name": f"Bar {bar}: {n}"} for k, n in GIGBAR_PARTS]
        out.append(row)
    return out


def _rgb(color: str) -> tuple:
    h = str(color or "").lstrip("#")
    try:
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)) if len(h) == 6 else (1.0, 1.0, 1.0)
    except ValueError:
        return (1.0, 1.0, 1.0)


def clean_manual(msg: dict, count: int) -> tuple[list[int], dict]:
    """(which lights, the settings to change) from the panel; raises ValueError on a bad one."""
    which = str(msg.get("light"))
    light, _, part = which.partition(":")   # "3", or "0:spot_l" for one part of a GigBAR (1.14.1)
    ids = list(range(count)) if which == "all" else [int(light)] if light.isdigit() else []
    if not ids or any(not 0 <= i < count for i in ids) or (part and part not in PART_KEYS):
        raise ValueError("pick a light")
    if part:
        ids = [which]
    out = {}
    if "on" in msg:
        out["on"] = msg["on"] is True
    if "color" in msg:
        c = str(msg["color"])
        if len(c) != 7 or c[0] != "#" or any(ch not in "0123456789abcdefABCDEF" for ch in c[1:]):
            raise ValueError("color must look like #ff8800")
        out["color"] = c.lower()
    for k in ("dim", "strobe", "pan", "tilt", "laser_strobe", "white", "uv", "flash_speed", "par_uv"):
        if k in msg:
            out[k] = max(0.0, min(1.0, float(msg[k])))
    for k in ("derby_spin", "laser_spin"):
        if k in msg:
            out[k] = max(-1.0, min(1.0, float(msg[k])))
    for k, names in (("derby", DERBY_COLORS), ("laser", LASER_COLORS)):
        if k in msg:
            if msg[k] not in names:
                raise ValueError(f"{k} must be one of {', '.join(names)}")
            out[k] = msg[k]
    for k in ("head_color", "gobo"):
        if k in msg:
            v = msg[k]
            if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 7:
                raise ValueError(f"{k} must be 0 to 7")
            out[k] = v
    return ids, out


def apply_part(fx, part: str, st: dict) -> None:
    """One part of a GigBAR as the panel set it (1.14.1), over what the whole bar set: on with its
    own settings, or dark. A part turned on with nothing picked lights plainly (white derby, both
    lasers, the white strobe) so On always shows something."""
    from tools.gigbar_lights.rig import Derby, Mover, Par
    side = 0 if part.endswith("_r") else 1
    gb = {**GIGBAR_DEFAULT, **st}
    on, dim, strobe = st.get("on"), st["dim"], st["strobe"]
    if part.startswith("spot"):
        m = fx.movers[side]
        m.__dict__.update(Mover(pan=m.pan, tilt=m.tilt).__dict__)
        if on:
            m.dim, m.strobe, m.pan, m.tilt = dim, strobe, st["pan"], st["tilt"]
            m.color, m.gobo = gb["head_color"], gb["gobo"]
    elif part.startswith("par"):
        p = fx.pars[side]
        p.__dict__.update(Par().__dict__)
        if on:
            p.red, p.green, p.blue = _rgb(st["color"])
            p.uv, p.dim, p.strobe = gb["par_uv"], dim, strobe
    elif part.startswith("derby"):
        d = fx.derbies[side]
        d.__dict__.update(Derby().__dict__)
        if on:
            d.color = gb["derby"] if gb["derby"] != "off" else "white"
            d.rotate, d.strobe = gb["derby_spin"], strobe
    elif part == "strobes":
        fx.strobe_white = fx.strobe_uv = fx.strobe_speed = 0.0
        fx.strobe_program = 0
        if on:
            white, uv = (gb["white"], gb["uv"]) if gb["white"] or gb["uv"] else (1.0, 0.0)
            fx.strobe_white, fx.strobe_uv, fx.strobe_speed = white * dim, uv * dim, gb["flash_speed"]
    elif part == "laser":
        fx.laser, fx.laser_strobe, fx.laser_rotate = "off", 0.0, 0.0
        if on:
            fx.laser = gb["laser"] if gb["laser"] != "off" else "both"
            fx.laser_strobe, fx.laser_rotate = gb["laser_strobe"], gb["laser_spin"]


def apply_manual(rig, lights: dict) -> None:
    """Each fixture as the panel set it: dark, or one color at a brightness, steady or strobing,
    and a GigBAR's two heads aimed by pan (left/right) and tilt (up/down); then each GigBAR part
    set on its own ("0:spot_l") over the whole bar."""
    rig.reset()
    for i, fx in enumerate(rig.fixtures):
        st = lights.get(i)
        if st and st.get("on"):
            apply_whole(fx, st)
        if hasattr(fx, "pars"):   # each part set on its own wins over the whole bar
            for k, _ in GIGBAR_PARTS:
                if lights.get(f"{i}:{k}"):
                    apply_part(fx, k, lights[f"{i}:{k}"])


def apply_whole(fx, st: dict) -> None:
    """A whole fixture as the panel set it: one color at a brightness, steady or strobing; a
    GigBAR's heads aimed, and its derbies, laser and strobes as picked."""
    r, g, b = _rgb(st["color"])
    dim, strobe = st["dim"], st["strobe"]
    if hasattr(fx, "pars"):
        gb = {**GIGBAR_DEFAULT, **st}
        for p in fx.pars:
            p.red, p.green, p.blue, p.dim, p.strobe = r, g, b, dim, strobe
            p.uv = gb["par_uv"]
        for m in fx.movers:
            m.dim, m.strobe, m.pan, m.tilt = dim, strobe, st["pan"], st["tilt"]
            m.color, m.gobo = gb["head_color"], gb["gobo"]
        for d in fx.derbies:
            d.color, d.rotate, d.strobe = gb["derby"], gb["derby_spin"], strobe
        fx.laser, fx.laser_strobe, fx.laser_rotate = gb["laser"], gb["laser_strobe"], gb["laser_spin"]
        fx.strobe_white, fx.strobe_uv = gb["white"] * dim, gb["uv"] * dim
        fx.strobe_speed = gb["flash_speed"]
    else:
        fx.red, fx.green, fx.blue, fx.dim, fx.strobe = r, g, b, dim, strobe

def mode_manual(opts) -> int:
    lights = getattr(opts, "manual", None)
    if lights is None:
        lights = {}
    out = inner = _lights_out()
    preview = getattr(opts, "preview", None)
    sink = TeeOutput(inner, preview) if preview else inner
    where = lambda: (f"on the lights ({out.port}) and in the room picture" if out.connected  # noqa: E731
                     else "in the room picture only (no lights box plugged in)")
    print("Control a light: pick one, turn it on, set its color, brightness, strobe and aim, " + where() + ".")
    rig = default_rig()
    if preview:
        preview.begin("Control a light", None)
    end = time.perf_counter() + opts.seconds if opts.seconds else None
    try:
        while end is None or time.perf_counter() < end:
            apply_manual(rig, dict(lights))
            sink.send(rig.render())
            if preview:
                on = sum(1 for st in list(lights.values()) if st.get("on"))
                preview.status = (f"{on} light{'s' if on != 1 else ''} on, " if on else "Every light off, ") + where()
            time.sleep(0.025)
            while preview and not preview.keys.empty():
                if preview.keys.get() == "q":
                    raise Quit
    except Quit:
        print("Stopped controlling the lights by hand.")
    finally:
        sink.send(bytes(512))
        inner.close()
        if preview:
            preview.end()
    return 0


def mode_lineup(opts) -> int:
    """Line up my lights (1.11.3, his 2:40 PM recording 1:51): at the venue, with no show and no
    demo running, the line-up check drives the lights by itself, on the lights when the box is
    plugged in and in the room picture always. The window sends which bar and spot to aim."""
    show = Show(analyze=False)
    show.looks.overrides.lineup = (0, "center")   # both bars on the middle of the floor until he picks
    inner = _lights_out()
    where = _where(inner)
    print("LINE UP MY LIGHTS: the GigBARs' heads aim at a spot you pick (" + where + ").")
    return run_with_preview(show, inner, f"Line up my lights, {where}", opts, feed=gl.FakeMixxx(show, opts.bpm))


def mode_scenes(opts) -> int:
    """Scenes and moments with no music (1.10.0, his recording 9:30): a steady pretend beat drives
    the scene or moment picked in the window, on the lights when the box is plugged in."""
    show = Show(analyze=False)
    inner = _lights_out()
    where = _where(inner)
    print("SCENES: no music needed; the lights keep a steady pretend beat (" + where + ").")
    return run_with_preview(show, inner, f"Scenes, no music (pretend song beat), {where}", opts,
                            feed=gl.FakeMixxx(show, opts.bpm, loop=True))   # holds until Stop (BL #12093)


def mode_analyze(opts) -> int:
    print("Working out song sections (intro, build, drop...) for the tracks in Mixxx. "
          "This can take a while the first time; tracks done before are skipped.")
    return gl.cmd_analyze(argparse.Namespace(db=None, limit=0, force=False))


# One scan at a time (1.10.0): each click on Check used to start its own thread, all listing MIDI
# ports and serial ports at once (his recording 7:19 and the crash at 8:38).
SETUP_LOCK = threading.RLock()
PREFLIGHT_WAIT_S = 1.5   # a Start click waits this long for a scan, then uses the last reading
STOP_WAIT_S = 8.0   # Stop frees the window after this long even if the run is stuck closing (1.12.4)
STOP_DUMP_S = STOP_WAIT_S + 4   # a run still going this long after Stop leaves every thread's stack in crash.log
_crash_file = None   # crash.log, open for faulthandler (gui)


def arm_stop_dump() -> None:
    """At Stop (1.20.1, his 11-13 freeze): if the run hasn't ended STOP_DUMP_S later, faulthandler
    writes every thread's stack to crash.log from its own C thread, which works even when the whole
    app is frozen holding Python's lock, so the next crash report says where it stuck."""
    if _crash_file is None:
        return
    try:
        faulthandler.dump_traceback_later(STOP_DUMP_S, exit=False, file=_crash_file)
    except (OSError, ValueError, RuntimeError):
        pass


def disarm_stop_dump() -> None:
    try:
        faulthandler.cancel_dump_traceback_later()
    except (OSError, ValueError, RuntimeError):
        pass


def midi_port() -> "str | None":
    """The 'Llano Mixxx' loopMIDI port's name, "" when there is none, None if the list failed."""
    try:
        import rtmidi  # noqa: PLC0415
        m = rtmidi.MidiIn()
        try:
            ports = m.get_ports()
        finally:
            m.delete()
    except Exception:  # noqa: BLE001 -- a missing DLL or a failed list: unknown, not "missing"
        return None
    return next((p for p in ports if DEFAULT_PORT_HINT.lower() in p.lower()), "")


def connections(mixxx_running, wait_s: "float | None" = None) -> "dict | None":
    """What a show leans on, cheap enough to read every few seconds (his recording 7:46): the
    lights box, the loopMIDI port and Mixxx. ok True / False, or None when it can't tell.
    With wait_s, None when another scan holds the lock that long."""
    if not SETUP_LOCK.acquire(timeout=-1 if wait_s is None else wait_s):
        return None
    try:
        port, midi = _enttec_port(), midi_port()
    finally:
        SETUP_LOCK.release()
    return {"enttec": {"ok": bool(port), "detail": dmx_outputs.status(port)},
            "loopmidi": {"ok": None if midi is None else bool(midi),
                         "detail": f"'{midi}' is there" if midi else "couldn't list MIDI ports" if midi is None
                         else "no 'Llano Mixxx' port: open loopMIDI and add it"},
            "mixxx": {"ok": mixxx_running, "detail": "open" if mixxx_running else "not open" if mixxx_running is False
                      else "can't tell"}}


def setup_status() -> list[dict]:
    """What is installed and found, one plain line each; ok None = optional, not there yet."""
    with SETUP_LOCK:
        return _setup_status()


def _setup_status() -> list[dict]:
    items = []
    missing = []
    for mod in ("rtmidi", "serial"):
        try:
            __import__(mod)
        except Exception as e:  # a missing DLL shows up here, not as ImportError
            missing.append(f"{mod} ({e})")
    for mod in ("numpy", "soundfile"):  # only song analysis loads these; don't pay for it at startup
        if importlib.util.find_spec(mod) is None:
            missing.append(mod)
    items.append({"key": "libraries", "label": "App files",
                  "ok": not missing, "detail": "all there" if not missing else
                  "missing: " + ", ".join(missing) + ". Download Llano Lights again."})
    midi = midi_port()
    items.append({"key": "loopmidi", "label": "loopMIDI port", "ok": bool(midi) or None,
                  "detail": f"'{midi}' found" if midi else "couldn't list MIDI ports" if midi is None else
                  "no port named 'Llano Mixxx' yet: open loopMIDI and add it (needed for Mixxx)"})
    have_capture = have_names = True
    try:
        import soundcard  # noqa: F401, PLC0415
    except Exception:  # missing, or a missing DLL
        have_capture = False
    try:
        import winrt.windows.media.control  # noqa: F401, PLC0415
    except Exception:
        have_names = False
    items.append({"key": "system_audio", "label": "Spotify / YouTube Music", "ok": (have_capture and have_names) or None,
                  "detail": "the lights can follow what this laptop plays, and read the song name" if have_capture and have_names
                  else "missing: " + ", ".join(n for n, ok in (("sound capture", have_capture), ("song names", have_names)) if not ok)
                  + ". Download Llano Lights again (Mixxx still works)."})
    lib = MixxxLibrary()
    items.append({"key": "mixxx", "label": "Mixxx music library", "ok": lib.available() or None,
                  "detail": "found" if lib.available() else f"not found at {lib.path} (song sections stay off)"})
    cdir = mixxx_controllers_dir()
    have = all((cdir / f).exists() for f in MAPPING_FILES)
    items.append({"key": "mapping", "label": "Mixxx mapping", "ok": have or None,
                  "detail": "in place" if have else "not copied yet: run Setup again"})
    port = _enttec_port()
    items.append({"key": "enttec", "label": "ENTTEC lights box", "ok": bool(port) or None,
                  "detail": dmx_outputs.status(port) if port else "not plugged in (fine for the demo and the preview)"})
    return items


def mode_check(opts) -> int:
    print(f"Llano Lights {label()}, Python {sys.version.split()[0]} ({sys.executable})")
    items = setup_status()
    for it in items:
        mark = "ok" if it["ok"] else ("MISSING" if it["ok"] is False else "--")
        print(f"  [{mark}]   {it['label']}: {it['detail']}")
    print("\n[ok] = ready, -- = not set up yet or not plugged in.")
    return 1 if any(it["ok"] is False for it in items) else 0


def mode_probe(opts) -> int:
    """A Llano session holds a few DMX channels to check a fix on the real lights (probe.py, 1.14.0).
    Started by the app itself when a probe arrives and nothing else runs: everything dark except
    the probed channels, until the probe lapses, Llano stops it, or he starts anything else."""
    out = _open_enttec()
    if out is None:
        probes.note = "refused: the lights box isn't plugged in (or another program has it)"
        probes.clear()
        return 2
    preview = getattr(opts, "preview", None)
    sink = TeeOutput(out, preview) if preview else out
    if preview:
        preview.begin("Llano is testing a light", None)
    try:
        while probes.active():
            if preview:
                held = probes.active()
                preview.status = (f"A Llano session is checking {len(held)} channel{'s' if len(held) != 1 else ''} "
                                  f"on the lights ({int(probes.left())} s left)")
            sink.send(bytes(512))
            time.sleep(0.025)
            if preview and not preview.keys.empty() and preview.keys.get() == "q":
                probes.clear()
                break
    finally:
        out.send(bytes(512))
        out.close()
    return 0


MODES = {
    "demo": ("Demo: a song played here, no Mixxx (on the lights if you choose)", mode_demo),
    "preview": ("Music, no lights plugged in (Mixxx, Spotify or YouTube Music; watch the preview)", mode_preview),
    "live": ("Live show: lights follow Mixxx, Spotify or YouTube Music", mode_live),
    "test": ("Test each light (on the lights, and in the room picture)", mode_test),
    "analyze": ("Find song sections in my Mixxx music", mode_analyze),
    "check": ("Check my setup", mode_check),
    "designer": ("Show Designer: place the lights and watch the room", mode_designer),
    "manual": ("Control a light by hand (on the lights, and in the room picture)", mode_manual),
    "scenes": ("Scenes and moments, no music", mode_scenes),
    "lineup": ("Line up my lights (on the lights, and in the room picture)", mode_lineup),
    "show": ("Play a saved show here, song by song (Shows)", mode_show),
    "probe": ("A Llano session is testing a light", mode_probe),
}


def menu(opts) -> int:
    keys = [k for k in MODES if k != "probe"]
    while True:
        print("\n=== Llano Lights ===")
        for i, k in enumerate(keys, 1):
            print(f"  {i}. {MODES[k][0]}")
        print("  Q. Quit")
        choice = input("Type a number and press Enter: ").strip().lower()
        if choice in ("q", "quit", "exit"):
            return 0
        if choice.isdigit() and 1 <= int(choice) <= len(keys):
            try:
                MODES[keys[int(choice) - 1]][1](opts)
            except KeyboardInterrupt:
                print()
            except Exception as e:  # keep the menu alive; show what broke in plain words
                print(f"\nSomething went wrong: {type(e).__name__}: {e}")
            input("\nPress Enter to go back to the menu.")


# --- the desktop window ------------------------------------------------------------------

SHORT = {"live": "Live show", "preview": "Music, no lights", "demo": "Demo", "designer": "Show Designer",
         "test": "Test each light", "analyze": "Finding song sections", "check": "Checking the setup",
         "manual": "Control a light", "scenes": "Scenes, no music", "show": "Show",
         "lineup": "Line up my lights", "probe": "Llano test"}  # the phone's header
SHOW_MODES = {"demo", "preview", "live", "designer", "scenes", "show"}  # shows: the keys drive them
STOP_BY_KEY = SHOW_MODES | {"test", "manual", "lineup", "probe"}
HIDDEN_MODES = {"probe"}   # the app starts it for a Llano session; never a button                  # these stop on q; the rest are interrupted
# studio commands that light something: with nothing running they start Scenes (no music) first
STUDIO_LIGHTS = {"look", "next", "goto", "find", "touch"}
MOMENT_S = 6 * 3600   # a moment picked in the window holds until Back to the show, Stop, or this
# No adapter never locks him out (his ask, 2026-11-13): the run starts in the room picture, says so
# calmly, and the lights pick up by themselves when the box is plugged in (enttec.PluggableOutput).
LIGHTS_NOTE = ("Lights not connected. Everything still runs in the room picture, and the lights pick up "
               "by themselves when you plug in the USB lights box.")
LIGHTS_WAIT = "lights not connected yet, they pick up when you plug in the box"
LIGHTS_GONE = "Lights not connected: the show keeps going in the room picture; plug the box back in and the lights pick up"


class LogBuffer:
    """Stands in for stdout/stderr in the window (pythonw has neither): keeps the last lines
    for the log panel and appends them to llano-lights.log in his profile."""

    def __init__(self, path: Path, keep: int = 400, echo=None):
        self.echo = echo  # the console, when there is one
        self.lines: "collections.deque[str]" = collections.deque(maxlen=keep)
        self.lock = threading.Lock()
        self.part = ""
        self.path = path
        try:
            if path.exists() and path.stat().st_size > 1_000_000:
                path.replace(path.with_suffix(".old.log"))
            self.file = open(path, "a", encoding="utf-8", buffering=1)
        except OSError:
            self.file = None

    def write(self, text: str) -> int:
        if self.echo:
            try:
                self.echo.write(text)
                self.echo.flush()
            except Exception:
                pass
        with self.lock:
            self.part += text
            *done, self.part = self.part.split("\n")
            for line in done:
                line = line.rsplit("\r", 1)[-1].rstrip()
                if line:
                    stamped = time.strftime("%H:%M:%S ") + line
                    self.lines.append(stamped)
                    if self.file:
                        self.file.write(time.strftime("%Y-%m-%d ") + stamped + "\n")
        return len(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False

    def tail(self, n: int = 200) -> list[str]:
        with self.lock:
            return list(self.lines)[-n:]


class App:
    """One mode at a time on a worker thread, the setup checks, and the update offer."""

    def __init__(self, opts, log: LogBuffer):
        self.opts, self.log = opts, log
        self.preview: "Preview | None" = None
        self.running: "str | None" = None
        self.runner: "threading.Thread | None" = None
        self.last_run = ""  # plain line on how the last mode ended
        self.setup: list[dict] = []
        self.offer: "updater.Offer | None" = None
        self.update_note = "checking for updates"
        # checking, current, offered, downloading, ready (downloaded, waits for Install now), restarting, failed
        self.update_state = "checking"
        self.staged: "tuple | None" = None   # (offer, swap command) of a downloaded update (Llano BL #12377)
        self.test_note = ""             # the test channel's last word (1.14.0): "Test build 7 ready", ...
        self.test_offer: "updater.Offer | None" = None   # the newest test build, offered with an Update button
        self.test_busy = False          # one test-feed check at a time
        self.progress = 0.0
        self.update_later = ""          # the offered version he said Later to (the banner hides)
        self.test_later = ""            # the test build whose banner he closed (BL #12145), kept in window.json
        # a failed update comes back here with the swap's reason (BL #11612), shown and sent to Llano
        self.update_log, self.update_why = updater.last_swap() if opts.update_failed else ([], "")
        self.notice = ("Updated to Llano Lights " + VERSION) if opts.updated else \
            ("The update didn't finish, so this is still Llano Lights " + VERSION +
             (": " + self.update_why if self.update_why else "") + ". Update now tries again.") if opts.update_failed else ""
        self.last_request = time.monotonic()
        self.page_seen = False   # the first window request ends the startup timing lines
        self.launch = secrets.token_hex(6)  # a window from an earlier run sees a new one and closes itself
        self.warning: "dict | None" = None  # a heads-up he clears with OK (his recording, 8:03)
        self.conn: dict = {}
        self.setup_at, self.setup_busy = 0.0, False
        self.manual: dict = {}   # Control a light: fixture index -> its settings
        self.lights_list = light_list()
        self.moment = ""         # a wedding moment picked in the window (memory only, like a draft)
        # The Light studio (1.20.0): one for the whole launch, handed to every run, with tonight's
        # list of the night. It is loaded once the settings are (reload_night, below): the night can
        # come from a saved show (Llano BL #12387), so the plain order stands in until then.
        self.studio = studio_mod.Studio(path=studio_mod.default_path())
        self.studio.night = tonight_mod.Tonight.plain()
        self.night_sig = None   # what the night was last loaded from (Tonight.signature)
        self.keep_studio = self.switching = False
        self.studio_refused: "dict | None" = None   # the last command from llano.app the studio refused
        self.crash: "dict | None" = None   # the previous run's last lines, when it never closed
        self.doctor: "dict | None" = None  # the last Light doctor run, sent to Llano with the status
        self.songs = demo_songs.load()
        self.song = ""  # the demo song playing, "" for the pretend song or another mode
        self.song_clock = demo_songs.SongClock()
        self.lights = False  # the demo also plays on the real lights
        self.show_title = ""  # the saved show playing (Shows page), "" for none
        self.show_opts = None  # that run's options: its song list is the one the lights play
        self.live_tags = ("", {})  # (name, shows.tag_index) of the show the Live show follows (BL #12341)
        # Start with Mixxx (1.7.0, his recording 5:44): opening Mixxx starts the live show.
        self.prefs_file = app_data_dir() / "window.json"
        self.test_later = str(self._prefs().get("test_hidden") or "")   # closed stays closed for that build
        self.auto_live = self._prefs().get("auto_live") is True
        self.mixxx = MixxxWatch()
        # Local mode (1.8.0): the phone drives the show over the room's Wi-Fi, no internet.
        self.local = local_mode.LocalServer(local_mode.LocalKey(), self._local_state, self._local_send, page=REMOTE_HTML,
                                            stop=self._local_stop, studio=self.studio_post, go=self.switch_show,
                                            settings=self._local_settings, console=STUDIO_JS)
        self.run_started = 0.0  # time.monotonic() when the current run began (a Stop from Llano older than it is ignored)
        self.local_on = self._prefs().get("local") is not False
        self.hotspot_on, self.hotspot_note = False, ""
        self.hotspot_net = {"ssid": hotspot.SSID, "password": ""}   # the network a phone joins, once one is on
        self.hotspot_settings = False   # Windows refused and its own hotspot screen was opened for him
        self.hotspot_starting, self.hotspot_lock = False, threading.Lock()   # one start at a time (BL #12109)
        self.stopping = False
        self.quit = threading.Event()
        self.lock = threading.Lock()
        # Show settings (palettes, strobe, drops, looks, layout) and the Llano link
        # (llano_sync.py): the show reads the settings every frame; the link only moves
        # them to and from llano.app when it is reachable.
        self.settings_file = show_settings.SettingsFile()
        # each saved show's wedding-night plan (folder, moment times, unplaced songs), kept here on the laptop:
        # the page's localStorage is per port, and a restart can land on another (Llano BL #12426)
        self.night_plans = night_plans.NightPlans(self.settings_file.path.parent / "night_plans.json")
        self.points = wedding_night.PointsCache(self.settings_file.path.parent / "song_points.json")
        self.point_files: dict = {}          # song key -> its file, as the points action found it
        self._point_index = None             # (folder, when, index_folder) for the points action
        self.layouts = LayoutStore()
        show_settings.set_current(self._with_local_layouts(self.settings_file.load()))
        self.reload_night()   # tonight's list: a built night, else the saved show's own night, else the plain order
        self.link = llano_sync.LlanoLink(self.settings_file, version=VERSION, on_doc=self._settings_from_llano,
                                         status=self._sync_status, catalog=self._sync_catalog,
                                         universe=lambda: self.preview.universe if self.preview else b"",
                                         sent=self._status_sent, update=self._test_build,
                                         song_playing=self.song_playing, stop=self._llano_stop,
                                         studio=self._llano_studio, scene=self._llano_scene)
        probes.song_playing = self.song_playing
        # Get my songs (Llano BL #12342): the Drive song folder's copy on this laptop, one get at a time
        self.songs_lock = threading.Lock()
        self.songs_get: dict = {"state": "idle", "seq": 0}

    def touch(self) -> None:
        if not self.page_seen:
            self.page_seen = True
            startup_mark("the window asked for its first state")
        self.last_request = time.monotonic()

    def _prefs(self) -> dict:
        try:
            d = json.loads(self.prefs_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # ok: none saved yet = the defaults
            return {}
        return d if isinstance(d, dict) else {}

    def set_auto_live(self, on: bool) -> None:
        self.auto_live = on
        try:
            self.prefs_file.write_text(json.dumps({**self._prefs(), "auto_live": on}), encoding="utf-8")
        except OSError as e:
            print(f"Couldn't save the Start with Mixxx choice: {e}")

    def _local_state(self) -> dict:
        """What the phone draws over Wi-Fi: the studio's one state shape (studio_state), with the
        room's light as a phone draws it, plus what the phone app from before 1.20 reads."""
        st = self.studio_state(glow=True)
        return {**st, "motion": self._motion(),
                "update": {**st["update"], "offer": self.offer.version if self.offer else ""}}

    def _local_settings(self, ops: "list | None") -> tuple[int, dict]:
        """The saved settings over Wi-Fi (his rule, 2026-11-12: settings must work with no internet):
        None reads them; a list of ops changes them the way a change in this window does: in force
        now, saved, and sent to Llano when it is reachable again."""
        if ops is None:
            return 200, {"settings": show_settings.current(), "schema": settings_contract.SCHEMA}
        if not ops:
            return 400, {"error": "nothing to change"}
        try:
            new = self.link.local_change(ops)
        except settings_contract.ContractError as e:
            return 400, {"error": str(e)}
        return 200, {"ok": True, "settings": new}

    def _motion(self) -> "dict | None":
        """What the heads were sent lately (his 11-09 "choppy" report): the frames a second really
        going out, and the last frames' pan/tilt bytes stamped in ms, so Llano can see on this
        laptop whether a move ticks or glides without asking him for a video."""
        trail = list(self.preview.trail) if self.preview is not None and self.running else []
        if len(trail) < 2:
            return None
        span = (trail[-1][0] - trail[0][0]) / 1000.0
        return {"hz": round((len(trail) - 1) / span, 1) if span > 0 else None,
                "trail": [row[:1 + len(HEAD_BYTES)] for row in trail]}   # the bytes sent, not the picture's columns

    def _local_send(self, item: str) -> bool:
        if self.running not in SHOW_MODES or self.preview is None:
            return False
        self.preview.keys.put(item)
        return True

    def _local_stop(self) -> dict:
        """Stop from his phone over the room Wi-Fi (1.15.0, Llano BL #11606): the window's own Stop."""
        print("Stop from the phone over Wi-Fi")
        return self.stop()[1]

    def _llano_stop(self, age_s: float) -> None:
        """Stop from llano.app or the Conductor (1.15.0, Llano BL #11606). A press older than the run
        playing now was meant for an earlier one (this laptop was offline, or just launched): ignored."""
        with self.lock:
            mode, started = self.running, self.run_started
        if not mode:
            return
        if started > time.monotonic() - age_s:
            print("Llano's Stop was pressed before this show started; it keeps playing")
            return
        print("Stop from Llano")
        self.stop()

    def _llano_studio(self, cmd: dict) -> tuple[int, dict]:
        """A studio command pressed on llano.app over the internet (1.20.0): done the way a press in
        this window is. One the studio refuses is kept, so the phone's screen can say why. "go" is
        the Live screen's Live show / No lights button, which is the app's to run, not the studio's."""
        if cmd.get("op") == "go":
            code, body = self.switch_show(str(cmd.get("mode") or ""))
        else:
            code, body = self.studio_post(cmd)
        if code != 200:
            self.studio_refused = {"n": self.link.studio_seen, "error": str((body or {}).get("error") or "The laptop refused that."),
                                   "at": time.time()}
        return code, body

    def _llano_scene(self, name: "str | None") -> bool:
        """A scene pad from an older Llano page or the Conductor. With the studio as the front page
        it is the studio's own (a held look, a held white-out, blackout), so the strip shows it and
        the newest press wins everywhere; False = the classic scene pad takes it."""
        st = self.studio
        if not st.live:
            return False
        if name == "whiteout":
            cmds = [{"op": "hit", "name": "whiteout", "on": True}]
        elif name == "blackout":
            cmds = [{"op": "blackout", "on": True}]
        elif name:
            cmds = [{"op": "hit", "name": "whiteout", "on": False}, {"op": "look", "key": "scene:" + name}]
        else:   # back to the show: only what a scene pad put there (a moment or a look he holds stays)
            cmds = [{"op": "hit", "name": "whiteout", "on": False}, {"op": "blackout", "on": False}]
            if st.look and st.look["key"].startswith("scene:"):
                cmds.append({"op": "release"})
        if not name and not self.running:
            return True   # nothing runs: nothing to hand back
        for cmd in cmds:
            self.studio_post(cmd)
        show_settings.clear_scene()
        return True

    def set_local(self, on: bool) -> None:
        self.local_on = on
        try:
            self.prefs_file.write_text(json.dumps({**self._prefs(), "local": on}), encoding="utf-8")
        except OSError as e:
            print(f"Couldn't save the Phone control choice: {e}")
        if on and local_mode.enabled():
            if self.local.start():
                print("Phone control on this Wi-Fi: " + (", ".join(self.local.public()["urls"]) or "no local network yet"))
            else:
                print("Phone control couldn't start: ports 8790-8799 are all in use.")
        else:
            self.local.stop()

    def request_hotspot(self) -> tuple[int, dict]:
        """The window's "Start hotspot": answers at once, Windows works on it in the background.
        A second press while one is starting (or once it is on) starts nothing more."""
        with self.hotspot_lock:
            if self.hotspot_starting or self.hotspot_on:
                return 200, {"ok": True, "starting": self.hotspot_starting, "on": self.hotspot_on}
            self.hotspot_starting, self.hotspot_note = True, "Starting the hotspot..."
        print("Starting the laptop's hotspot...")
        threading.Thread(target=self.start_hotspot, name="hotspot", daemon=True).start()
        return 200, {"ok": True, "starting": True, "on": False}

    def start_hotspot(self) -> None:
        try:
            ok, why = hotspot.start()
        except Exception as e:  # noqa: BLE001 -- hotspot.start already never raises; belt and braces
            ok, why = False, f"Windows refused: {e}"
        opened = False
        if not ok:   # the fallback he asked for (2026-11-13): Windows' own hotspot screen, opened for him
            try:
                opened = hotspot.open_settings()
            except Exception:  # noqa: BLE001 -- ok: the reason still shows; the button offers the screen again
                opened = False
            if opened:
                why += " Windows' own hotspot screen is open: turn on Mobile hotspot there, and its name and password show here."
        with self.hotspot_lock:
            self.hotspot_on, self.hotspot_note, self.hotspot_starting = ok, why, False
            self.hotspot_settings = opened
            if ok:
                self.hotspot_net = {"ssid": hotspot.SSID, "password": hotspot.password()}
        print(f"The laptop's hotspot '{hotspot.SSID}' is on." if ok else f"The laptop's hotspot didn't start: {why}")

    def open_hotspot_settings(self) -> tuple[int, dict]:
        """The window's "Open Windows hotspot settings", shown after Windows refused the start."""
        if not hotspot.open_settings():
            return 400, {"error": "Windows' hotspot settings couldn't be opened from here. Open Settings, Network & internet, Mobile hotspot."}
        self.hotspot_settings = True
        return 200, {"ok": True}

    def check_hotspot(self) -> None:
        """After a refused start, a hotspot he turned on in Windows' own screen is noticed, with the
        name and password Windows gave it, so the window shows its join code like one this app started."""
        if self.hotspot_on or self.hotspot_starting or not self.hotspot_note:
            return
        st = hotspot.status()
        if not st.get("on"):
            return
        with self.hotspot_lock:
            if self.hotspot_starting:
                return
            self.hotspot_on, self.hotspot_note, self.hotspot_settings = True, "", False
            self.hotspot_net = {"ssid": str(st.get("ssid") or hotspot.SSID), "password": str(st.get("password") or "")}
        print(f"The laptop's hotspot '{self.hotspot_net['ssid']}' is on (turned on in Windows).")

    def hotspot_public(self) -> dict:
        return {"ssid": self.hotspot_net["ssid"], "on": self.hotspot_on, "starting": self.hotspot_starting,
                "note": self.hotspot_note, "settings": self.hotspot_settings}

    def local_public(self) -> dict:
        out = self.local.public(with_key=True)
        net = self.hotspot_net
        out.update(enabled=local_mode.enabled(), pref=self.local_on, hotspot={
            **self.hotspot_public(),
            "password": net["password"] if self.hotspot_on else "",
            "qr": hotspot.wifi_qr_text(net["ssid"], net["password"]) if self.hotspot_on and net["password"] else ""})
        return out

    def watch_mixxx(self, every_s: float = 1.0) -> None:
        """Start with Mixxx: Mixxx opening (or already open when this app starts) starts the live
        show once. Stop keeps it stopped until Mixxx is opened again."""
        was = False
        while not self.quit.is_set():
            now = self.mixxx.running
            if now and not was and self.auto_live and not self.running and self.update_state != "restarting":
                print("Mixxx is open: starting the live show (Start with Mixxx is on).")
                self.run("live")
            if now is not None:
                was = now
            self.quit.wait(every_s)

    def state(self) -> dict:
        offer = self.offer
        return {"product": updater.PRODUCT, "version": VERSION, "built": BUILT_CT, "root": str(updater.install_root()),
                "channel": CHANNEL, "build": BUILD, "test_update": self.test_note,
                "test_offer": {"version": self.test_offer.version, "build": self.test_offer.build,
                               "notes": self.test_offer.notes, "built": self.test_offer.built,
                               # Later hides this test build's banner until a newer one or the next launch
                               "later": self.test_later == self.test_offer.version}
                if self.test_offer else None,
                "can_go_back": CHANNEL == "test" and updater.stable_copy() is not None,
                "running": self.running,
                "songs": [s.public() for s in self.songs], "song": self.song if self.running == "demo" else "",
                "running_label": MODES[self.running][0] if self.running else "",
                "show": self.running in SHOW_MODES, "status": self.preview.status if self.running else "",
                "live": self.preview.live if self.running in SHOW_MODES else None,
                "lights": self.lights and self.running in ("demo", "show"),
                "show_title": self.show_title if self.running == "show" else "",
                "auto_live": self.auto_live, "mixxx": self.mixxx.running,
                "local": self.local_public(),
                "last_run": self.last_run, "setup": self.setup, "notice": self.notice,
                "launch": self.launch, "warning": self.warning, "conn": self.conn,
                "setup_at": self.setup_at, "setup_busy": self.setup_busy,
                "lights_list": [{**l, "present": l["id"] in on} for on in (present_ids(),) for l in light_list()],   # addresses from the rig block, live
                "rig": rig_public(), "manual": {str(k): v for k, v in dict(self.manual).items()},
                "moments": [{"key": m["key"], "name": m["name"], "kind": m["kind"], "note": m["note"]}
                            for m in moments.MOMENTS],
                "moment": self.moment_now(),
                "studio_on": self.studio.live, "studio": self.studio.public(),
                "studio_catalog": self.studio.catalog(),
                "update": {"state": self.update_state, "note": self.update_note,
                           "progress": round(self.progress, 3),
                           "version": offer.version if offer else "", "notes": offer.notes if offer else "",
                           "built": offer.built if offer else "",
                           # Later hides this offer's banner until the next launch or a newer version
                           "later": bool(offer and self.update_later == offer.version)},
                "modes": [{"key": k, "label": v[0]} for k, v in MODES.items() if k not in HIDDEN_MODES],
                "llano": self.link.public(),
                "log": self.log.tail()}

    def post(self, action: str, msg: dict) -> tuple[int, dict]:
        if action == "run":
            if str(msg.get("mode") or "") in HIDDEN_MODES:
                return 400, {"error": "unknown mode"}
            return self.run(str(msg.get("mode") or ""), str(msg.get("song") or ""), msg.get("lights") is True)
        if action == "test-update":
            return self.start_test_update()
        if action == "go-back":
            return self.go_back_to_stable()
        if action == "local":
            self.set_local(msg.get("on") is True)
            return 200, {"ok": True}
        if action == "local-key":   # old phones stop working; scan the new code
            self.local.key.rotate()
            return 200, {"ok": True}
        if action == "hotspot":
            return self.request_hotspot()
        if action == "hotspot-settings":
            return self.open_hotspot_settings()
        if action == "auto-live":
            self.set_auto_live(msg.get("on") is True)
            return 200, {"ok": True, "auto_live": self.auto_live}
        if action.startswith("shows-"):   # the Shows page (1.11.0)
            return self.shows_post(action[6:], msg)
        if action == "demo-clock":  # the window's player: where the demo song is
            try:
                self.song_clock.report(str(msg.get("song") or ""), float(msg.get("t") or 0), bool(msg.get("playing")))
            except (TypeError, ValueError):
                return 400, {"error": "bad position"}
            return 200, {"ok": True}
        if action == "stop":
            return self.stop()
        if action == "warning-ok":
            self.warning = None
            return 200, {"ok": True}
        if action == "manual":
            return self.set_manual(msg)
        if action == "rig":
            return self.set_rig(msg)
        if action == "manual-off":
            self.manual.clear()
            return 200, {"ok": True}
        if action == "scene":
            return self.pick_scene(str(msg.get("name") or ""))
        if action == "moment":
            return self.pick_moment(str(msg.get("key") or ""))
        if action == "studio":
            return self.studio_post(msg)
        if action == "settings":   # the Live screen's Saved panel: the same checked ops Llano sends
            return self._local_settings(msg.get("ops") if isinstance(msg.get("ops"), list) else [])
        if action == "studio-peek":
            return self.studio_peek(str(msg.get("key") or "")[:80])
        if action == "studio-go":
            return self.switch_show(str(msg.get("mode") or ""))
        if action == "update":
            return self.start_update()
        if action == "install-update":   # a downloaded update's Install now (Llano BL #12377)
            return self.install_update()
        if action == "update-later":   # the banner's Later (BL #11612): Update now stays by the version
            self.update_later = self.offer.version if self.offer else ""
            return 200, {"ok": True}
        if action == "guide-confirm":   # the setup guide: a step only he can see worked (1.21)
            return self.guide_confirm(str(msg.get("key") or ""), msg.get("ok") is not False)
        if action == "guide-later":     # Not now: launches open on the Live screen again
            self._set_prefs(guide_later=True)
            return 200, {"ok": True}
        if action == "test-hide":   # the test banner's X (Llano BL #12145): never nag a test build
            return self.hide_test_banner()
        if action == "check":
            self.setup_busy = True   # the window says "Checking..." until the scan lands
            threading.Thread(target=self.refresh_setup, daemon=True).start()
            if self.update_state in ("current", "unreachable", "failed"):
                threading.Thread(target=self.check_update, daemon=True).start()
            return 200, {"ok": True}
        if action == "check-update":  # the window's Check for updates button
            with self.lock:
                if self.update_state in ("checking", "downloading", "ready", "restarting"):
                    return 200, {"ok": True}
                self.update_state = "checking"
            threading.Thread(target=self.check_update, daemon=True).start()
            return 200, {"ok": True}
        if action == "quit":
            self.stop()
            self.quit.set()
            return 200, {"ok": True}
        if action == "dismiss":
            self.notice = ""
            return 200, {"ok": True}
        if action == "llano-landed-ok":   # the "changes from Llano landed" banner's OK (Llano BL #12370)
            return 200, self.link.landed_ok()
        if action == "llano-link":
            try:
                return 200, self.link.link(str(msg.get("code") or ""), str(msg.get("name") or ""))
            except llano_sync.LinkError as e:
                return 400, {"error": str(e)}
        if action == "llano-unlink":
            self.local.key.rotate()   # the key Llano handed to his phone stops working too
            return 200, self.link.unlink()
        return 404, {"error": "unknown action"}

    # Shows (1.11.0): a playlist designed into a whole show, saved by name
    def shows_post(self, action: str, msg: dict) -> tuple[int, dict]:
        lib, cache = MixxxLibrary(), ScriptCache(default_cache_dir())
        doc = show_settings.current()

        def matched(items: list, index=None) -> list:
            index = index or shows.LibraryIndex(lib)
            out = []
            for it in items:
                song = shows.ShowSong(it["artist"], it["title"], secs=float(it.get("secs") or 0),
                                      bpm=float(it.get("bpm") or 0), part=it.get("part") or "",
                                      moment=it.get("moment") if it.get("moment") in settings_contract.SHOW_MOMENTS else "",
                                      camelot=str(it.get("camelot") or ""), year=int(it.get("year") or 0),
                                      trouble=it.get("trouble") if it.get("trouble") in shows.TROUBLES else "")
                lt = index.find(song.artist, song.title)
                if lt:
                    song.track_id, song.secs, song.bpm = lt.track_id, lt.secs or song.secs, lt.bpm or song.bpm
                    song.playable = bool(lt.location and lt.location.is_file())
                    song.trouble = "" if song.secs > 0 else song.trouble
                out.append(song.public())
            return out

        def folder_songs(path) -> list:
            """The show's folder read again (song_folder.read_folder), for fill: [] when the page knows
            no folder, or it is gone (a show opens whole either way, with what it has)."""
            path = folder_picker.clean(path)
            if not path:
                return []
            try:
                return song_folder.read_folder_all(path)[1]
            except Exception as e:  # noqa: BLE001 -- ok: opening his show must never fail on its folder (a
                # drive unplugged, a folder moved, one file no reader expected): it opens with what it has
                print(f"Shows: the show's folder could not be read again ({type(e).__name__}: {e})")
                return []

        def folder_gone(path) -> list:
            """A needs line when the show's folder can't be found on this laptop (moved, renamed, a drive
            unplugged): said in words, never a box that quietly reads nothing (BL #12426)."""
            path = folder_picker.clean(path)
            try:
                gone = bool(path) and not Path(path).is_dir()
            except (OSError, ValueError):
                gone = True
            return [{"kind": "folder", "text": f"The song folder {path} can't be found on this laptop (moved or renamed?): "
                                               "press Browse in step 2 and choose where it is now."}] if gone else []

        def moments_of(m) -> "dict | None":
            return m if isinstance(m, dict) else None

        def unplaced_of(m) -> list:
            return [str(x)[:200] for x in m[:200]] if isinstance(m, list) else []

        def with_tags(songs: list) -> list:
            """Each library song's key and year from Mixxx, where the page doesn't have them yet."""
            got = shows.tags(lib, [s.track_id for s in songs if s.track_id and not (s.camelot and s.year)])
            for s in songs:
                key, year = got.get(s.track_id, ("", 0))
                s.camelot, s.year = s.camelot or key, s.year or year
            return songs

        try:
            if action.startswith("drive-") or action in ("pick-file", "add-file"):   # Get my songs, Add a song (BL #12342)
                return self.drive_post(action, msg, matched)
            if action == "design-with-llano":   # Llano designs it on llano.app/lights; the show syncs back here
                webbrowser.open("https://llano.app/lights")
                return 200, {"ok": True}
            if action == "home":
                return 200, {"shows": shows.list_public(doc), "mixxx": lib.available(),
                             "most": settings_contract.MAX_SHOW_SONGS,
                             "live_show": self._prefs().get("live_show") or "",
                             "lists": shows.lists(lib),
                             "looks": [{"name": n, "note": v.get("note", ""), "builtin": True}
                                       for n, v in settings_contract.BUILTIN_LOOKS.items()] +
                                      [{"name": n, "note": v.get("note", ""), "builtin": False} for n, v in doc["styles"].items()]}
            if action == "open":   # filled as it opens (BL #11473): a blank look, part or length from the folder
                name = str(msg.get("name") or "")
                # its night plan as this laptop kept it (BL #12426); the page's own copy only when the app has
                # none yet (a plan kept before BL #12426), and then the app keeps it; one he cleared stays cleared
                plan = self.night_plans.get(name) if name in shows.saved_shows(doc) else None
                if plan is None:
                    page = night_plans.clean({"folder": msg.get("folder"), "moments": msg.get("moments"),
                                              "keep": msg.get("keep"), "times": msg.get("times"),
                                              "unplaced": msg.get("unplaced")})
                    if not night_plans.empty(page):
                        plan = page
                        if name in shows.saved_shows(doc):
                            try:
                                self.night_plans.put(name, plan)
                            except OSError as e:  # ok: the show opens with the window's plan; it is kept next time
                                print(f"Shows: the night plan could not be kept ({type(e).__name__}: {e})")
                plan = plan or night_plans.clean({})
                got = shows.load(name, lib, cache, found=folder_songs(plan["folder"]),
                                 filed=doc["songs"], styles=doc["styles"])
                if not got:
                    return 404, {"error": "no saved show by that name"}
                got["needs"] = folder_gone(plan["folder"]) + shows.needs(
                    shows.from_public(got["songs"]), moments_of(plan["moments"] or None), unplaced_of(plan.get("unplaced")))
                got["night"] = plan
                return 200, got
            if action == "night-remember":   # step 2 changed: the app keeps this show's plan (BL #12426)
                name = str(msg.get("name") or "")
                if name not in shows.saved_shows(doc):
                    return 404, {"error": "save the show first"}
                kept = self.night_plans.put(name, msg.get("plan"))
                if kept is None:
                    return 400, {"error": "that is not a night plan"}
                return 200, {"ok": True}
            if action == "from-mixxx":
                kind, list_id = str(msg.get("kind") or ""), int(msg.get("id") or 0)
                tracks = shows.list_tracks(lib, kind, list_id)
                name = next((x["name"] for x in shows.lists(lib) if x["kind"] == kind and x["id"] == list_id), "")
                part = shows.part_from_name(name)   # a "Cocktail Hour" playlist fills cocktail hour
                return 200, {"songs": [{**t.song().public(), "part": part} for t in tracks], "part": part}
            if action == "pick-folder":   # Browse: Windows' own folder picker hands back the path (BL #12132)
                path, err = folder_picker.pick(str(msg.get("title") or "Choose the folder your songs are in"),
                                               str(msg.get("start") or ""))
                if err:
                    return (409 if "already open" in err else 501), {"error": err}
                return 200, {"path": path}   # "" = he pressed Cancel
            if action == "folder":   # a folder of songs on this laptop (his Drive wedding folder)
                try:
                    name, items, left_out = song_folder.read_folder_all(folder_picker.clean(msg.get("path")))
                except FileNotFoundError as e:
                    return 400, {"error": f"{e}: paste the folder's full path, like C:\\Users\\you\\Music\\Wedding"}
                if not items:
                    return 400, {"error": "no songs in that folder (mp3, flac, wav, m4a, ogg)"}
                # A Moments-folder song no dance is known for, or a second song for a dance that has one, is
                # never left out (BL #11473): it comes in as a Dancing song with no moment, it is named in
                # `unplaced`, and the needs list asks him to pick its moment in step 2. Picked there, it plays
                # at that moment only (wedding_night.arrange); never picked, it plays in the dancing.
                unplaced = [" - ".join(x for x in (it["artist"], it["title"]) if x) for it in items if it.get("moment") == "?"]
                for it in items:
                    if it.get("moment") == "?":
                        it["moment"], it["part"] = "", "dancing"
                # one song in two folders is one song in the show, from the first folder, and he is told
                seen, twins, kept = set(), [], []
                for it in items:
                    k = shows.song_key(it["artist"], it["title"])   # never "" for a name: non-Latin names stay apart
                    if k and k in seen:
                        first = next(x for x in kept if shows.song_key(x["artist"], x["title"]) == k)
                        where = shows.PART_TITLES.get(first.get("part"), "the show with no part yet")
                        twins.append(f"{shows._label(shows.ShowSong(it['artist'], it['title']))} is in two folders, so it is "
                                     f"in the show once, in {where}. If it belongs elsewhere, pick its part in its row.")
                        continue
                    seen.add(k)
                    kept.append(it)
                # songs already in the show with no part take theirs from the folder (BL #12338); a part he
                # chose is never undone by adding the folder again (the lead's review, BL #11473)
                have = msg.get("have") if isinstance(msg.get("have"), list) else []
                have = have[:settings_contract.MAX_SHOW_SONGS]
                placed = [x for x in song_folder.place_from_folder(have, kept)
                          if isinstance(have[x["i"]], dict) and not have[x["i"]].get("part") and not have[x["i"]].get("moment")]
                # and songs already in the show with no length take it from this same read of the folder
                by = {}
                for it in kept:
                    k = shows.song_key(it["artist"], it["title"])
                    if k:
                        by.setdefault(k, it)
                lengths = []
                for i, h in enumerate(have):
                    f = by.get(shows.song_key(str(h.get("artist") or ""), str(h.get("title") or ""))) if isinstance(h, dict) else None
                    if f and not (isinstance(h.get("secs"), (int, float)) and h["secs"] > 0) and (f["secs"] > 0 or f["trouble"]):
                        lengths.append({"i": i, "secs": f["secs"], "trouble": f["trouble"]})
                songs = matched(kept)
                return 200, {"title": name, "songs": songs, "lengths": lengths,
                             "placed": placed,
                             "unplaced": unplaced, "twins": twins, "left_out": left_out,
                             "most": settings_contract.MAX_SHOW_SONGS,
                             "needs": shows.needs(shows.from_public(songs), None, unplaced)}
            if action == "fill":   # the one guarantee (BL #11473): a look, a part, a tag, a length for every song
                songs = shows.from_public(msg.get("songs"))
                done = shows.fill(songs, found=folder_songs(msg.get("folder")), filed=doc["songs"], styles=doc["styles"],
                                  own=shows.own_looks(msg.get("looks")))
                return 200, {"songs": [s.public() for s in songs], "fixed": done["fixed"], "lengths": done["lengths"],
                             "timeline": shows.timeline(songs),
                             "needs": shows.needs(songs, moments_of(msg.get("moments")), unplaced_of(msg.get("unplaced")))}
            if action == "needs":   # what only he can settle, for the panel at the top of Review; changes nothing
                return 200, {"needs": folder_gone(msg.get("folder")) + shows.needs(
                    shows.from_public(msg.get("songs")), moments_of(msg.get("moments")), unplaced_of(msg.get("unplaced")))}
            if action in ("arrange", "evaluate", "ask"):   # the set arranger (1.18.0)
                songs = with_tags(shows.from_public(msg.get("songs")))
                event = str(msg.get("event") or "wedding")
                if not songs:
                    return 400, {"error": "add some songs first"}
                if action == "ask":
                    reply = set_arranger.discuss(str(msg.get("text") or ""), songs, event)
                    placed = (set_arranger.arrange(songs, event) if reply.rearrange
                              else set_arranger.evaluate(reply.songs or songs, event))
                    return 200, {**set_arranger.public(placed, event), "answer": reply.answer,
                                 "changed": reply.changed or reply.rearrange, "focus": reply.focus}
                placed = set_arranger.arrange(songs, event) if action == "arrange" else set_arranger.evaluate(songs, event)
                return 200, set_arranger.public(placed, event)
            if action == "search":
                return 200, {"songs": [t.song().public() for t in shows.search(lib, str(msg.get("q") or ""))]}
            if action == "paste":
                # A line that is not a song ("not a song", "----") is left out and named (Llano BL #11473);
                # a bare title is a song when his Mixxx library has it.
                index = shows.LibraryIndex(lib)
                items, left = shows.parse_pasted(str(msg.get("text") or ""),
                                                 known=lambda t: index.find("", t) is not None)
                if not items:
                    if left:
                        shown = ", ".join(left[:5]) + (f" and {len(left) - 5} more" if len(left) > 5 else "")
                        return 400, {"error": f"None of those lines looked like a song: {shown}. Type each one as "
                                              "Title by Artist, one per line.", "left_out": left}
                    return 400, {"error": "no songs found in that text: one song per line, like Artist - Title"}
                return 200, {"songs": matched(items, index), "left_out": left}
            if action == "spotify":
                name, items = shows.spotify_playlist(str(msg.get("url") or ""))
                return 200, {"title": name, "songs": matched(items)}
            if action == "analyze":   # one song at a time, so the page shows progress
                songs = shows.from_public([msg.get("song")])
                if not songs:
                    return 400, {"error": "no song"}
                return 200, {"song": shows.analyze(songs[0], lib, cache).public()}
            if action == "points":   # Review's Starts at and Ends at (PM #23751), one song at a time like analyze
                return 200, self.song_points(msg, lib)
            if action == "moods":   # Set the mood (BL #12340): Llano's suggestion and the choices
                return 200, {"suggested": settings_contract.moods(None), "swatches": settings_contract.MOOD_SWATCHES,
                             "every": list(settings_contract.MOOD_EVERY)}
            if action == "design":
                songs = shows.design(shows.from_public(msg.get("songs")), doc["songs"], doc["styles"],
                                     keep=msg.get("keep") is True)
                return 200, {"songs": [s.public() for s in songs], "timeline": shows.timeline(songs)}
            if action == "save":
                songs = shows.from_public(msg.get("songs"))
                # Save pressed while songs are still being read, or after a design that failed, never stores
                # a blank look (BL #11473): the show is filled here, on the app's side, before it is kept.
                filled = shows.fill(songs, filed=doc["songs"], styles=doc["styles"], own=shows.own_looks(msg.get("looks")))
                name, ops = shows.save_ops(str(msg.get("title") or ""), [s.saved() for s in songs],
                                           str(msg.get("note") or ""), str(msg.get("name") or ""), msg.get("looks"),
                                           msg.get("moods"))
                self.link.local_change(ops)
                if self.running in ("live", "preview") and self._prefs().get("live_show") == name:
                    self.live_show_looks()   # the Live show follows this show: its new looks apply now
                return 200, {"ok": True, "name": name, "shows": shows.list_public(), "fixed": filled["fixed"],
                             "songs": [s.saved() for s in songs]}
            if action == "delete":
                name = str(msg.get("name") or "")
                if name not in shows.saved_shows():
                    return 404, {"error": "no saved show by that name"}
                self.link.local_change([{"path": f"shows.{name}", "value": None}])
                try:
                    self.night_plans.drop(name)
                except OSError as e:  # ok: the show is deleted; a plan left behind is never shown for another show
                    print(f"Shows: the night plan could not be forgotten ({type(e).__name__}: {e})")
                return 200, {"ok": True, "shows": shows.list_public()}
            if action == "play":
                songs = shows.from_public(msg.get("songs"))
                opts = self.show_opts
                if self.running == "show" and opts is not None and songs:
                    # Edited while it plays: the running show takes the page's list as it is now, so
                    # the song the page reports by number is the one the lights play.
                    opts.show_songs[:] = songs
                    opts.show_own = shows.own_looks(msg.get("looks"))
                    opts.show_moods = msg.get("moods") if isinstance(msg.get("moods"), dict) else None
                    shows.follow(songs, opts.show_own, opts.show_moods)
                    if getattr(opts, "show_feed", None) is not None:
                        opts.show_feed.index = -1   # start the reported song again, with its new look
                    self.show_title = str(msg.get("title") or "")[:80] or self.show_title
                    return 200, {"ok": True, "updated": True}
                return self.run("show", lights=msg.get("lights") is True, show_songs=songs,
                                show_title=str(msg.get("title") or "")[:80] or "this show",
                                show_own=shows.own_looks(msg.get("looks")), show_moods=msg.get("moods"))
            if action == "live":   # the saved show the Live show follows; "" for none
                name = str(msg.get("name") or "")
                if name and name not in shows.saved_shows():
                    return 400, {"error": "save the show first"}
                self.prefs_file.write_text(json.dumps({**self._prefs(), "live_show": name}), encoding="utf-8")
                note = "" if self.running not in ("live", "preview") else " It starts with the next Live show."
                return 200, {"ok": True, "live_show": name, "note": note}
            if action == "night-home":    # the wedding night panel (1.19.0): the moments, the last build
                return 200, {"moments": [{"key": k, "name": v[0], "say": v[2], "song": v[3], "hold": v[4]}
                                         for k, v in run_of_show.MOMENTS.items()],
                             # step 2 offers only the moments in the night's order: the build plays DEFAULT_ORDER, so
                             # a box for any other moment would do nothing (Llano BL #11473); OPTIONAL starts unticked
                             "order": list(run_of_show.DEFAULT_ORDER), "optional": list(run_of_show.OPTIONAL),
                             "night": self.night_public(),
                             "transition_s": wedding_night.sc.TRANSITION_S}
            if action == "night-build":
                return self.night_start(msg, lib)
            if action == "night-status":
                return 200, self.night_public()
            if action == "night-check":   # Mixxx's Auto DJ settings, read only
                return 200, wedding_night.check_mixxx()
            if action == "night-load-mixxx":   # Load Mixxx (BL #12343): the built night into Mixxx, then open it
                return self.night_load_mixxx()
            if action == "night-open":    # the folder, or the run sheet, in Windows' own viewer
                # this launch's build, else the last night built on this laptop: the run sheet must be
                # findable after the app was closed and opened again (his 2026-11-13 "I can't find it")
                built = str((self.night or {}).get("folder") or (self._last_night() or {}).get("folder") or "")
                target = Path(built) / wedding_night.SHEET_NAME if msg.get("what") == "sheet" else Path(built)
                if not built or not target.exists():      # no build yet: never the app's own folder
                    return 404, {"error": "build the night first"}
                try:
                    os.startfile(str(target))   # noqa: S606 -- his own folder, built by this app
                except (AttributeError, OSError):
                    webbrowser.open(target.as_uri())
                return 200, {"ok": True, "path": str(target)}
            if action == "mixxx-playlist":   # the show's order as a playlist file Mixxx imports
                songs = shows.from_public(msg.get("songs"))
                folder = Path.home() / "Music" / "Llano Lights shows"
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / (shows.slug(str(msg.get("title") or "show")) + ".m3u8")
                path.write_text(shows.m3u(songs, lib), encoding="utf-8")
                return 200, {"ok": True, "path": str(path)}
        except (settings_contract.ContractError, shows.SpotifyError) as e:
            return 400, {"error": str(e)}
        except OSError as e:
            return 500, {"error": f"couldn't write that file: {e}"}
        return 404, {"error": "unknown action"}

    # The wedding night (1.19.0): the show's songs and the night's moments built into one folder he
    # plays from (cut files, holds, numbered playlists, the run sheet). It takes a few minutes, so it
    # runs on its own thread and the page asks how far it is.
    night: "dict | None" = None
    night_lock = threading.Lock()     # one build at a time: a second press is answered, never started

    def _last_night(self) -> "dict | None":
        """The newest night built on this laptop (Music, Llano Lights shows, <show>-night) that has
        its run sheet: where the sheet is when this launch has built nothing."""
        root = Path.home() / "Music" / wedding_night.OUT_PARENT
        try:
            found = [d for d in root.glob("*-night") if (d / wedding_night.SHEET_NAME).is_file()]
            if not found:
                return None
            d = max(found, key=lambda p: (p / wedding_night.SHEET_NAME).stat().st_mtime)
            return {"folder": str(d), "sheet": str(d / wedding_night.SHEET_NAME)}
        except OSError:  # ok: a Music folder that can't be read has no last night to offer
            return None

    # --- Get my songs and Add a song from this laptop (Llano BL #12342) ------------------------------------

    # --- Starts at and Ends at (Llano PM #23751) -------------------------------------------------------------
    # Review shows where each song's cut for the night starts and ends, read from his own file: a dance song
    # starts where the dancing starts and leaves where it stops; he plays it from there and nudges it.

    def _point_file(self, song: dict, folder, lib) -> "Path | None":
        """The song's own file: in the song folder the page names (as Build the night reads it), else in his
        Mixxx library, never a cut of an earlier night."""
        k = wedding_night.key_of(song)
        folder = folder_picker.clean(folder)
        if folder:
            now = time.monotonic()
            got = self._point_index
            if not got or got[0] != folder or now - got[1] > 30:
                got = (folder, now, wedding_night.index_folder(folder))
                self._point_index = got
            if k in got[2]:
                return Path(got[2][k])
        lt = shows.LibraryIndex(lib).find(song.get("artist", ""), song.get("title", ""))
        where = Path(lt.location) if lt and lt.location else None
        if where and where.is_file() and wedding_night.OUT_PARENT.casefold() not in (p.casefold() for p in where.parts):
            return where
        return None

    def song_points(self, msg: dict, lib) -> dict:
        songs = shows.from_public([msg.get("song")])
        if not songs:
            return {"points": None, "why": "no song"}
        s = songs[0].public()
        part = "moment" if s.get("moment") else s.get("part")
        if part not in (*settings_contract.SHOW_PARTS, "moment"):
            return {"points": None, "why": "Pick its part of the night first."}
        path = self._point_file(s, msg.get("folder"), lib)
        if path is None:
            return {"points": None, "why": "Its file is not in the song folder, so Llano can't read where it starts."}
        try:
            pts = self.points.get(s, part, path, opens=msg.get("opens") is True)   # a set's first song (PM #23864)
        except wedding_night.sc.CannotCut as e:
            return {"points": None, "why": "It plays whole: " + ("a kind of file this laptop can't cut." if e.why == "type"
                                                                 else "too long to cut here.")}
        except wedding_night.sc.DamagedFile as e:
            return {"points": None, "why": str(e)}
        except Exception as e:  # noqa: BLE001 -- ok: one unreadable song leaves its row blank, never the page
            print(f"Song points: {type(e).__name__}: {e}")
            return {"points": None, "why": "Llano couldn't read this file."}
        self.point_files[pts["key"]] = path
        return {"points": {**pts, "audio": "/song-audio/" + urllib.parse.quote(pts["key"])}}

    def _songs_dir(self) -> Path:
        return self.settings_file.path.parent

    def drive_public(self) -> dict:
        return dict(self.songs_get)

    def drive_start(self, why: str) -> dict:
        """Bring the connected Drive folder's songs to this laptop, in the background. `why` is
        "button", "connect" or "open"; an open with nothing connected, or no link, does nothing."""
        con = drive_songs.read_connected(self._songs_dir())
        if not con or not self.link.linked:
            return self.drive_public()
        with self.songs_lock:
            if self.songs_get.get("state") == "getting":
                return self.drive_public()
            seq = int(self.songs_get.get("seq") or 0) + 1
            self.songs_get = {"state": "getting", "why": why, "seq": seq, "what": "Asking Llano what is in your Drive folder",
                              "i": 0, "n": 0}

        def progress(what: str, i: int, n: int) -> None:
            self.songs_get = {**self.songs_get, "what": what, "i": i, "n": n}

        def work() -> None:
            try:
                got = drive_songs.get_songs(self.link, con, con["root"], on_progress=progress)
                self.songs_get = {"state": "done", "why": why, "seq": seq, "at": time.strftime("%H:%M"), **got}
            except Exception as e:  # noqa: BLE001 -- the page must hear that it failed, and why
                print(f"Get my songs failed: {type(e).__name__}: {e}")
                self.songs_get = {"state": "failed", "why": why, "seq": seq, "error": str(e)[:300]}

        threading.Thread(target=work, name="get-my-songs", daemon=True).start()
        return self.drive_public()

    def drive_post(self, action: str, msg: dict, matched) -> tuple[int, dict]:
        sd = self._songs_dir()
        con = drive_songs.read_connected(sd)
        if action == "drive-home":
            return 200, {"connected": con, "linked": self.link.linked, "get": self.drive_public(),
                         "last": drive_songs.last_get(con.get("root")) if con else {},
                         "parts": [[k, v] for k, v in (("cocktail", "Cocktail hour"), ("dinner", "Dinner"), ("dancing", "Dancing"))],
                         "moments": list(settings_contract.SHOW_MOMENTS)}
        if action == "drive-connect":   # Connect my Drive folder: one of the folders Llano connected for him
            try:
                folders = self.link.drive_folders()
            except llano_sync.LinkError as e:
                return 409, {"error": str(e)}
            if not folders:
                return 404, {"error": "Llano has no Drive song folder for you yet. Send Llano the folder's Drive link "
                                      "and ask it to connect it, then press Connect again."}
            want = str(msg.get("id") or "")
            pick = next((f for f in folders if f["id"] == want), None) if want else (folders[0] if len(folders) == 1 else None)
            if pick is None:
                return 200, {"pick": folders}
            con = drive_songs.connect(sd, pick)
            return 200, {"connected": con, "get": self.drive_start("connect")}
        if action == "drive-disconnect":   # the copy on this laptop stays; Get my songs stops
            drive_songs.disconnect(sd)
            return 200, {"connected": {}}
        if action == "drive-get":
            if not con:
                return 409, {"error": "Connect your Drive folder first."}
            if not self.link.linked:
                return 409, {"error": "Link this laptop to Llano first (Set up, Llano link)."}
            return 200, {"get": self.drive_start("button")}
        if action == "drive-status":
            return 200, {"get": self.drive_public(), "connected": con}
        if action == "drive-read":   # the copy, read as the show takes it in
            root = con.get("root") if con else ""
            if not root or not Path(root).is_dir():
                return 409, {"error": "Press Get my songs first."}
            name, items, left_out = song_folder.read_folder_all(root)
            # A subfolder that names no part (his "Extra") stays out of the night: it is named, not filed as Dancing.
            aside = [it for it in items if not it.get("part") and not it.get("moment") and Path(it["file"]).parent != Path(root)]
            items = [it for it in items if it not in aside]
            unplaced = [" - ".join(x for x in (it["artist"], it["title"]) if x) for it in items if it.get("moment") == "?"]
            have = msg.get("have") if isinstance(msg.get("have"), list) else []
            place = getattr(song_folder, "place_from_folder", None)   # BL #12338: songs in the show follow their folder
            return 200, {"title": con.get("name") or name, "folder": root,
                         "songs": matched([it for it in items if it.get("moment") != "?"]),
                         "placed": place(have[:settings_contract.MAX_SHOW_SONGS], items) if place else [],
                         "aside": [" - ".join(x for x in (it["artist"], it["title"]) if x) + f" ({Path(it['file']).parent.name})"
                                   for it in aside],
                         "unplaced": unplaced, "left_out": left_out, "most": settings_contract.MAX_SHOW_SONGS}
        if action == "pick-file":
            path, err = folder_picker.pick_file("Choose the song to add", str(msg.get("start") or ""))
            if err:
                return (409 if "already open" in err else 501), {"error": err}
            return 200, {"path": path}
        if action == "add-file":   # Add a song from this laptop: into the show's song folder, in its part
            root = folder_picker.clean(msg.get("folder")) or (con.get("root") if con else "") or \
                str(Path.home() / "Music" / drive_songs.PARENT / "My songs")
            try:
                song = drive_songs.add_file(folder_picker.clean(msg.get("path")), root, str(msg.get("part") or ""),
                                            str(msg.get("moment") or ""))
            except drive_songs.SongsError as e:
                return 400, {"error": str(e)}
            except OSError as e:
                return 400, {"error": f"the song could not be copied ({e.strerror or type(e).__name__})"}
            got = matched([song])[0]
            return 200, {"song": {**got, "part": song["part"], "moment": song["moment"]}, "folder": root,
                         "file": song["file"]}
        return 404, {"error": "no such action"}

    def night_public(self) -> dict:
        n = self.night or {}
        if n:
            out = {k: n.get(k) for k in ("state", "what", "i", "n", "folder", "error", "report", "notes")}
            if n.get("state") == "done" and n.get("folder"):
                out["sheet"] = str(Path(str(n["folder"])) / wedding_night.SHEET_NAME)
            return out
        last = self._last_night()
        return {"state": "idle", "last": last} if last else {"state": "idle"}

    def night_load_mixxx(self) -> tuple[int, dict]:
        """The built night (this launch's, else the last one built on this laptop) into Mixxx's library:
        its songs, the numbered playlists, playlist 1 in the Auto DJ queue, Auto DJ set to Full Track,
        then Mixxx opens. Refused, with nothing written, while Mixxx runs or on a library it doesn't know."""
        n = self.night or {}
        if n.get("state") == "building":
            return 409, {"error": "The night is still building. Load Mixxx when it says it is done."}
        built = str(n.get("folder") or "") if n.get("state") == "done" else str((self._last_night() or {}).get("folder") or "")
        if not built:
            return 404, {"error": "Build the night first, then press Load Mixxx."}
        try:
            return 200, mixxx_load.load(built)
        except mixxx_load.LoadRefused as e:
            return 409, {"error": str(e)}
        except sqlite3.Error as e:
            print(f"Load Mixxx failed: {type(e).__name__}: {e}")
            return 500, {"error": "Mixxx's library couldn't be written, so nothing was changed in it. "
                                  "Import the playlists by hand (the steps below)."}

    def night_start(self, msg: dict, lib) -> tuple[int, dict]:
        songs = [s.public() for s in shows.from_public(msg.get("songs"))]
        if not songs:
            return 400, {"error": "add the songs first"}
        need = wedding_night.needs_part(songs)   # never built as Dancing by default (BL #12338)
        if need:
            return 400, {"error": wedding_night.needs_part_words(need), "needs_part": need}
        title = str(msg.get("title") or "").strip()[:80] or "Wedding"
        out = Path.home() / "Music" / wedding_night.OUT_PARENT / (shows.slug(title) + "-night")
        with self.night_lock:
            if (self.night or {}).get("state") == "building":
                return 409, {"error": "the night is still building; it says when it is done"}
            was = self.night
            # said before the folder is read: finding the files can take a while, and a second press
            # in that time must find a build already under way
            self.night = {"state": "building", "what": "Finding the songs", "i": 0, "n": 0, "folder": str(out)}
        try:
            plan = self._night_plan(msg, lib, songs, out)
        except Exception:
            self.night = was
            raise
        if not plan["files"]:
            self.night = was
            return 400, {"error": "none of the songs' files were found: paste the songs' folder in the box, "
                                  "like C:\\Users\\you\\Music\\Wedding"}
        keep, notes = plan["keep"], []

        def progress(what: str, i: int, n: int) -> None:
            self.night.update(what=what, i=i, n=n)

        def file_looks(report: dict) -> None:
            # the moments' looks, as soon as the night is whole: before the preview and the backups,
            # and a failure here is a note on a finished night, never a failed one
            try:
                ops, said = wedding_night.looks_ops(report, show_settings.current())
                notes.extend(said)
                if ops:
                    self.link.local_change(ops)
            except Exception as e:  # noqa: BLE001 -- ok: the music is built; the note says what to do
                print(f"Wedding night looks not saved: {type(e).__name__}: {e}")
                notes.append("The lights' looks for the moments could not be saved. The music is built. "
                             "Build again to save them.")

        def work() -> None:
            try:
                report = wedding_night.build(out, plan["songs"], plan["files"], title=title,
                                             moment_songs=plan["moment_songs"], times=plan["times"], skip=plan["skip"],
                                             extras=msg.get("extras") is not False, keep_whole=keep,
                                             moods=msg.get("moods") if isinstance(msg.get("moods"), dict) else None,
                                             on_progress=progress, on_built=file_looks, patch=patch_now(self)[0])
                self.night = {"state": "done", "folder": str(out), "notes": notes,
                              "report": {**{k: report[k] for k in ("title", "built", "seconds", "playlists", "checks",
                                                                    "damaged", "missing", "handoffs", "backups", "level_lufs")},
                                         # what the build changed in a song, for him to look over
                                         "changed": [{k: c[k] for k in ("key", "artist", "title", "kind", "why",
                                                                        "cut_start_s", "cut_end_s")}
                                                     for c in report["cuts"] if c["kind"] != "whole" or c["key"] in keep],
                                         "kept": sorted(keep)}}
                print(f"Wedding night built in {report['seconds']:.0f} s: {out}")
                self.reload_night(force=True)   # the Live screen's Tonight list is this night now
            except Exception as e:  # noqa: BLE001 -- the page must hear that it failed, and what to do
                # his words on the page (Mixxx has a song open, the disk is full ...); the technical ones in the log
                self.night = {"state": "failed", "folder": str(out),
                              "error": night_failure_words(e, str((self.night or {}).get("what") or ""))}
                print(f"Wedding night build failed: {type(e).__name__}: {e}")

        try:
            threading.Thread(target=work, name="wedding-night", daemon=True).start()
        except Exception:
            self.night = was            # never left saying "building" with nothing building
            raise
        return 200, {"ok": True, **self.night_public()}

    def _night_plan(self, msg: dict, lib, songs: list, out: Path) -> dict:
        """What the panel asked for, as wedding_night.build takes it: the songs' files, the moments
        that are on, their songs and times."""
        folder = folder_picker.clean(msg.get("folder"))
        files = wedding_night.index_folder(folder, exclude=[out]) if folder else {}
        index = shows.LibraryIndex(lib)

        def locate(song: dict) -> None:   # a song not in the folder may still be in the Mixxx library
            k = wedding_night.key_of(song)
            if k not in files:
                lt = index.find(song.get("artist", ""), song.get("title", ""))
                where = Path(lt.location) if lt and lt.location else None
                # never a cut of an earlier night: Mixxx has scanned that folder too
                if where and where.is_file() and wedding_night.OUT_PARENT.casefold() not in (p.casefold() for p in where.parts):
                    files[k] = where

        moments_in = msg.get("moments") if isinstance(msg.get("moments"), dict) else {}
        skip, times, moment_songs = set(), {}, {}
        for key in run_of_show.MOMENTS:
            m = moments_in.get(key) if isinstance(moments_in.get(key), dict) else {}
            if m.get("on") is False or (m.get("on") is None and key in run_of_show.OPTIONAL):
                skip.add(key)
                continue
            if str(m.get("at") or "").strip():
                times[key] = str(m["at"]).strip()[:12]
            name = str(m.get("song") or "").strip()[:200]
            if name:
                artist, _, song_title = name.partition(" - ")
                typed = ({"artist": artist.strip(), "title": song_title.strip()} if song_title
                         else {"artist": "", "title": artist.strip()})
                if not typed["artist"]:   # a title alone: it is the show's song of that title, not a second song
                    same = [s for s in songs if s.get("title", "").strip().casefold() == typed["title"].casefold()]
                    if len(same) == 1:
                        typed = {"artist": same[0].get("artist", ""), "title": same[0].get("title", "")}
                moment_songs[key] = typed
        for part in settings_contract.SHOW_PARTS:
            at = str((msg.get("times") or {}).get(part) or "").strip()
            if at:
                times[part] = at[:12]
        if not moment_songs.get("close"):
            skip.add("close")
        for s in songs + list(moment_songs.values()):
            locate(s)
        # songs whose soft intro he wants kept (a dancing cut otherwise starts where the band comes in)
        keep = {str(k)[:120] for k in (msg.get("keep") if isinstance(msg.get("keep"), list) else [])[:200]}
        return {"songs": songs, "files": files, "skip": skip, "times": times, "moment_songs": moment_songs, "keep": keep}

    # modes
    def run(self, mode: str, song: str = "", lights: bool = False, show_songs=None, show_title: str = "",
            show_own=None, show_moods=None) -> tuple[int, dict]:
        if mode not in MODES:
            return 400, {"error": "unknown mode"}
        if lights and mode not in ("demo", "show"):
            return 400, {"error": "only the demo and a show play on the lights from here"}
        if mode == "show" and not show_songs:
            return 400, {"error": "open a show on the Shows page and press Play"}
        if song and (mode != "demo" or song not in {s.id for s in self.songs}):
            return 400, {"error": "unknown demo song"}
        if mode != "probe":   # anything he starts ends a session's probe, at once
            probes.clear()
        if self.running == "probe" and mode != "probe":
            self.preview.keys.put("q")
            runner = self.runner
            if runner:
                runner.join(3)
        if not self.running:
            warned = self.preflight(mode, lights)
            if warned:
                return warned
        with self.lock:
            if self.running:
                return 409, {"error": f"'{MODES[self.running][0]}' is running; stop it first"}
            if self.update_state == "restarting":   # a download never blocks the show (Llano BL #12377)
                return 409, {"error": "Llano Lights is restarting into the update; it is back in about a minute"}
            self.running, self.stopping = mode, False
            self.run_started = time.monotonic()
            opts = argparse.Namespace(**vars(self.opts))
            opts.no_browser, opts.preview = True, self.preview
            opts.song, opts.song_clock, self.song = song, self.song_clock, song
            opts.lights, self.lights = lights, lights
            opts.manual = self.manual
            opts.studio = self.studio
            opts.show_songs, opts.show_title, self.show_title = show_songs, show_title, show_title
            opts.show_own = show_own or {}
            opts.show_moods = show_moods if isinstance(show_moods, dict) else None
            self.show_opts = opts if mode == "show" else None
            self.runner = threading.Thread(target=self._run, args=(mode, opts), daemon=True)
            self.runner.start()
        return 200, {"ok": True}

    def preflight(self, mode: str, lights: bool) -> "tuple[int, dict] | None":
        """Before a show starts, say what isn't connected (his recording 4:42 and 8:03): a show
        that needs the lights box refuses with why; anything else is a heads-up he clears."""
        if mode not in ("live", "preview", "demo", "test", "show"):
            return None
        conn = connections(self.mixxx.running, PREFLIGHT_WAIT_S) or self.conn
        if not conn:   # no reading yet and a scan is busy: start, and let the dots catch up
            return None
        self.conn = conn
        no_box = (mode == "live" or (mode in ("demo", "show") and lights)) and not conn["enttec"]["ok"]
        gaps = []
        if mode == "test" and not conn["enttec"]["ok"]:
            gaps.append("the ENTTEC lights box isn't plugged in, so the test runs in the room picture only")
        if mode in ("live", "preview"):
            if conn["loopmidi"]["ok"] is False:
                gaps.append("loopMIDI has no 'Llano Mixxx' port, so Mixxx can't drive the lights (open loopMIDI and add it)")
            if conn["mixxx"]["ok"] is False:
                gaps.append("Mixxx isn't open")
        text = " ".join(t for t in (
            LIGHTS_NOTE if no_box else "",
            ("Heads up: " + "; ".join(gaps) + "." + (" Spotify and YouTube Music still work." if mode in ("live", "preview")
                                                      and conn["loopmidi"]["ok"] is False else "")) if gaps else "") if t)
        self.warning = {"level": "warn", "text": text, "lights": no_box} if text else None
        return None

    def lights_changed(self, port: str) -> None:
        """The run's lights box came (port) or went (""): the dot follows at once, and the calm note
        clears itself once the lights are on (or comes back when they go)."""
        self.conn = {**(self.conn or {}), "enttec": {"ok": bool(port),
                                                     "detail": f"plugged in on {port}" if port else "not plugged in"}}
        if port and self.warning and self.warning.get("lights"):
            self.warning = None
        elif not port and self.running and not self.warning:
            self.warning = {"level": "warn", "text": LIGHTS_NOTE, "lights": True}

    def set_manual(self, msg: dict) -> tuple[int, dict]:
        try:
            ids, change = clean_manual(msg, len(self.lights_list))
        except (ValueError, TypeError) as e:
            return 400, {"error": str(e)}
        if self.running and self.running != "manual":
            return 409, {"error": f"Stop '{SHORT.get(self.running, self.running)}' first, then control a light by hand."}
        for i in ids:
            self.manual[i] = {**MANUAL_DEFAULT, **self.manual.get(i, {}), **change}
        if not self.running:
            code, body = self.run("manual")
            if code == 409 and self.running == "manual":   # two quick slider moves: the first started it
                return 200, {"ok": True}
            return code, body
        return 200, {"ok": True}

    def pick_scene(self, name: str) -> tuple[int, dict]:
        """A scene pad: over the show that runs, or with no music when nothing runs (1.10.0)."""
        if name and name not in settings_contract.SCENES:
            return 400, {"error": "no such scene"}
        if self.running and self.running not in SHOW_MODES:
            return 409, {"error": f"Stop '{SHORT.get(self.running, self.running)}' first, then pick a scene."}
        if not self.running:
            if not name:
                return 200, {"ok": True}
            code, body = self.run("scenes")
            if code != 200:
                return code, body
        self.preview.keys.put("scene:" + name)
        return 200, {"ok": True}

    def set_rig(self, msg: dict) -> tuple[int, dict]:
        """The rig picker (1.13.0): {"counts": {bars, tetras, sticks}} sets tonight's lights,
        {"save": name} keeps tonight's as a named rig, {"use": name} picks one, {"delete": name}
        drops one. A settings change like any other, so llano.app/lights shows it too."""
        rig = rig_public()
        if isinstance(msg.get("counts"), dict):
            counts = {**rig["counts"]}
            for kind, most in KINDS:
                v = msg["counts"].get(kind, counts[kind])
                if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= most:
                    return 400, {"error": f"{kind} must be 0 to {most}"}
                counts[kind] = v
            ops = [{"path": f"rig.counts.{k}", "value": v} for k, v in counts.items()]
        elif msg.get("save") is not None:
            raw = str(msg.get("save") or "")
            name = venue_slug(raw) if any(c.isalnum() for c in raw) else ""   # slug("!!") is "my-layout"
            if not settings_contract.good_name(name):
                return 400, {"error": "Name the rig with letters and numbers, like small gig"}
            if name not in rig["saved"] and len(rig["saved"]) >= settings_contract.MAX_SAVED_RIGS:
                return 400, {"error": f"Up to {settings_contract.MAX_SAVED_RIGS} saved rigs: delete one first"}
            ops = [{"path": f"rig.saved.{name}", "value": rig["counts"]}]
        elif msg.get("use") is not None or msg.get("delete") is not None:
            name = str(msg.get("use") or msg.get("delete") or "")
            if name not in rig["saved"]:
                return 404, {"error": "No saved rig by that name"}
            ops = ([{"path": f"rig.counts.{k}", "value": v} for k, v in rig["saved"][name].items()]
                   if msg.get("use") is not None else [{"path": f"rig.saved.{name}", "value": None}])
        else:
            return 400, {"error": "Say counts, save, use or delete"}
        try:
            self.link.local_change(ops)
        except settings_contract.ContractError as e:
            return 400, {"error": str(e)}
        return 200, {"ok": True, "rig": rig_public()}

    def lineup(self, bar: str, spot: str) -> tuple[int, dict]:
        """The line-up page (1.11.3): over the show that runs, or on its own when nothing runs
        (his 2:40 PM recording 1:51, "without having to go run the demo"); bar "" = done, which
        ends a line-up that started itself and leaves a show running."""
        if self.running and self.running not in SHOW_MODES | {"lineup"}:
            return 409, {"error": f"Stop '{SHORT.get(self.running, self.running)}' first, then line up the lights."}
        if bar.isdigit() and int(bar) > rig_public()["counts"]["bars"]:
            return 409, {"error": f"GigBAR {bar} isn't in tonight's rig. Add it under Tonight's lights."}
        if not bar:
            if self.running == "lineup":
                return self.stop()
            if self.running:
                self.preview.keys.put("lineup:")
            return 200, {"ok": True}
        if not self.running:
            code, body = self.run("lineup")
            if code != 200:
                return code, body
        self.preview.keys.put(f"lineup:{bar}:{spot}")
        return 200, {"ok": True}

    def setup_lights(self, on: bool, whole: bool = False) -> tuple[int, dict]:
        """The line-up page's Lights on switch (1.12.3, his 11-08 report "how do i turn the lights
        on"): every GigBAR head a white spot at full, or dark. Lights on with nothing running starts
        the line-up run, so it works with no show or demo."""
        if self.running and self.running not in SHOW_MODES | {"lineup"}:
            return 409, {"error": f"Stop '{SHORT.get(self.running, self.running)}' first, then turn the lights on."}
        if on and not self.running:
            code, body = self.run("lineup")
            if code != 200:
                return code, body
        if self.running:
            self.preview.keys.put(("lights:2" if whole else "lights:1") if on else "lights:0")
        return 200, {"ok": True, "on": on, "whole": on and whole}

    def calibrate(self, key: str) -> tuple[int, dict]:
        """One head by raw pan/tilt (1.12.1), on the line-up run when nothing else runs."""
        if self.running and self.running not in SHOW_MODES | {"lineup"}:
            return 409, {"error": f"Stop '{SHORT.get(self.running, self.running)}' first, then calibrate."}
        if key != "cal:" and int(key.split(":")[1]) > rig_public()["counts"]["bars"]:
            return 409, {"error": f"GigBAR {key.split(':')[1]} isn't in tonight's rig. Add it under Tonight's lights."}
        if key != "cal:" and not self.running:
            code, body = self.run("lineup")
            if code != 200:
                return code, body
        if self.running:
            self.preview.keys.put(key)
        return 200, {"ok": True}

    def aim(self, key: str) -> tuple[int, dict]:
        """Line up my lights, one spot (1.16.0): the heads he lines up, on the line-up run when nothing
        else runs. Over a running show it plays until he leaves the line-up, then the show comes back."""
        if self.running and self.running not in SHOW_MODES | {"lineup"}:
            return 409, {"error": f"Stop '{SHORT.get(self.running, self.running)}' first, then line up the lights."}
        if key != "aim:":
            aim = gl.parse_aim(key[4:])
            if any(b > rig_public()["counts"]["bars"] for b, _ in aim["poses"]):
                return 409, {"error": "That GigBAR isn't in tonight's rig. Add it under Tonight's lights."}
            if not self.running:
                code, body = self.run("lineup")
                if code != 200:
                    return code, body
        if self.running:
            self.preview.keys.put(key)
        return 200, {"ok": True}

    def moment_now(self) -> str:
        """The wedding moment playing now, as the window lights its button and enables Back to the
        show. On the Live screen a moment is the studio's held look, whichever screen held it (a
        pad there or the phone); in the classic window it is the play that holds its label, and a
        draft Llano sent since replaced it."""
        if self.studio.live:
            key = str((self.studio.look or {}).get("key") or "")
            return key[len("moment:"):] if key.startswith("moment:") and key[len("moment:"):] in moments.KEYS else ""
        return self.moment if show_settings.play_label() else ""

    def pick_moment(self, key: str) -> tuple[int, dict]:
        """A wedding moment, the same ones as the phone (1.10.0, his recording 11:12): it plays
        instead of the saved show until Back to the show or Stop; "" = back to the show."""
        if key and key not in moments.KEYS:
            return 400, {"error": "no such moment"}
        if self.studio.live:   # the Live screen is the front page: a moment is a held look there
            code, body = self.studio_post({"op": "look", "key": "moment:" + key} if key else {"op": "release"})
            if code == 200:
                self.moment = key
            return code, ({"ok": True} if code == 200 else body)
        if not key:
            if show_settings.play_label():   # never a draft Llano sent since
                show_settings.clear_play()
            self.moment = ""
            return 200, {"ok": True}
        if self.running and self.running not in SHOW_MODES:
            return 409, {"error": f"Stop '{SHORT.get(self.running, self.running)}' first, then pick a moment."}
        name = next(m["name"] for m in moments.MOMENTS if m["key"] == key)
        if not self.running:   # start first: a refused start leaves no moment behind for the next show
            code, body = self.run("scenes")
            if code != 200:
                return code, body
        show_settings.set_play(moments.style(key), time.time() + MOMENT_S, label=name)
        self.moment = key
        print(f"Moment: {name}")
        self.preview.keys.put("scene:")   # a moment is a whole show: a scene pad over it would hide it
        return 200, {"ok": True}

    # The Light studio (1.20.0): every screen sends the same commands (studio.Studio.command).
    def studio_post(self, msg: dict) -> tuple[int, dict]:
        """One command from a screen. A press that lights something with nothing running starts
        Scenes (no music) first, the way a scene pad does; a refused command leaves nothing running."""
        try:
            if len(json.dumps(msg)) > studio_mod.MAX_CMD_BYTES:
                return 400, {"error": "that command is too long"}
        except (TypeError, ValueError):
            return 400, {"error": "not a command"}
        op = str(msg.get("op") or "")
        if op == "song_tag":   # Hype, Dance or Slow for the Dancing song playing now (BL #12341)
            return self.retag_live(msg)
        if op in ("tap", "timing"):   # the beat's own keys: tap tempo, and the lights earlier or later
            d = msg.get("d")
            # the Live screen sends d -1 for Earlier and 1 for Later; "[" is the lights earlier (+offset_ms,
            # "ms early" on the main screen), "]" later. It was the other way round (Llano BL #11473).
            key = "t" if op == "tap" else {-1: "[", 1: "]", 0: "0"}.get(d) if isinstance(d, int) and not isinstance(d, bool) else None
            if key is None:
                return 400, {"error": "timing is later, earlier or reset"}
            if not self._local_send(key):
                return 409, {"error": "Nothing is running: start the lights first."}
            return 200, {"ok": True}
        lights = op in STUDIO_LIGHTS or (op in ("hit", "spots") and msg.get("on") is True)
        if lights and self.running and self.running not in SHOW_MODES:
            return 409, {"error": f"Stop '{SHORT.get(self.running, self.running)}' first."}
        if lights and self.switching:   # between the old run and the live show: a press here would start Scenes under it
            return 409, {"error": "The live show is starting. Press that again in a moment."}
        started = False
        if lights and not self.running:
            code, body = self.run("scenes")
            if code != 200 and self.running not in SHOW_MODES:   # two quick presses: the first started it
                return code, body
            started = code == 200
        st = self.studio
        with st.lock:
            if self.preview is not None:
                st.venue = self.preview.layout.name   # with nothing running, his places and view are this venue's
            if st.layout is None and self.preview is not None and self.running in SHOW_MODES:
                st.layout = self.preview.layout   # spots start on this floor, before the first frame
        try:
            out = st.command(msg)
        except studio_mod.CommandError as e:
            if started:   # (outside the studio's lock: Stop takes the app's, and a run's end takes both)
                self.stop()
            return 400, {"error": str(e)}
        except Exception as e:  # noqa: BLE001 -- a command shaped in a way no check foresaw: refused, and nothing it started is left running
            if started:
                self.stop()
            print(f"Light studio: refused a malformed command ({type(e).__name__}: {e}): {str(msg)[:200]}")
            return 400, {"error": "The lights couldn't read that command."}
        return 200, {"ok": True, **out, "studio": st.public()}

    def stage_now(self) -> dict:
        """The spots, places and view for the stage picture (it asks many times a second)."""
        if self.preview is not None:
            self.studio.venue = self.preview.layout.name
        return self.studio.stage()

    def studio_peek(self, key: str) -> tuple[int, dict]:
        """Look before you press: the pad plays in the room picture only ("" ends it). The lights
        keep doing what they are doing (studio_peek.py)."""
        p = self.preview
        if not key:
            p.peek = None
            return 200, {"ok": True}
        cur = p.peek
        if cur is not None and cur.key == key and not cur.over():
            cur.renew()
            return 200, {"ok": True, "name": cur.name}
        try:
            p.peek = studio_peek.Peek(self.studio, key, p.layout, bpm=float((p.live or {}).get("bpm") or 0))
        except studio_mod.CommandError as e:
            return 400, {"error": str(e)}
        return 200, {"ok": True, "name": p.peek.name}

    def switch_show(self, mode: str) -> tuple[int, dict]:
        """Start the live show (or Music, no lights) from the Live screen. Over Scenes, which a pad
        starts by itself, it swaps the run and keeps what he holds: the look, the spots, all of it."""
        if mode not in ("live", "preview"):
            return 400, {"error": "start the live show, or music with no lights"}
        if self.running == mode:
            return 200, {"ok": True}
        if self.running and self.running not in SHOW_MODES:
            return 409, {"error": f"Stop '{SHORT.get(self.running, self.running)}' first."}
        if self.running:
            warned = self.preflight(mode, False)   # before the swap: a refused start leaves the lights as they are
            if warned:
                return warned
            self.keep_studio = self.switching = True
            try:
                runner = self.runner
                self.stop()
                if runner:
                    runner.join(STOP_WAIT_S - 1)
                if runner and runner.is_alive():
                    # The old run is still closing: never start a second show on the same studio
                    # beside it (two loops would steer the same spots). He presses again once it is down.
                    return 409, {"error": "The lights are still stopping. Press that again in a moment."}
                code, body = self.run(mode)
                if code != 200:   # nothing runs now: what he held must not read as still held over dark lights
                    with self.studio.lock:
                        self.studio.reset()
                        self.studio.rev += 1
            finally:
                self.keep_studio = self.switching = False
            return code, body
        return self.run(mode)

    def studio_state(self, glow: bool = False) -> dict:
        """What every studio screen draws from, in one shape (this window, the phone over Wi-Fi, and
        through Llano): the layers, the pads, what runs and what it is connected to. `glow` adds the
        room's light as a phone draws it (stage_glow.py); this window has the room picture itself."""
        p = self.preview
        if p is not None:
            self.studio.venue = p.layout.name
        st = self.studio.public()
        if p is not None and st["spots"]["plan"] is None:   # nothing running: the floor still shows
            st["spots"]["plan"] = self.studio._plan(p.layout)
        counts = rig_public()["counts"]
        feed = getattr(p, "feed", None) if (p and self.running) else None
        try:
            playing = feed.public() if feed is not None else None
        except Exception:  # noqa: BLE001 -- ok: the strip says nothing about the song rather than failing the screen
            playing = None
        return {"song_tag": self.song_tag(playing), "on": self.studio.live, "version": VERSION, "built": BUILT_CT, "launch": self.launch,
                "studio": st, "catalog": self.studio.catalog(), "now": time.time(),
                **({"glow": stage_glow.scene(p.universe, p.layout, counts)} if glow and p is not None else {}),
                "running": self.running or "", "running_label": SHORT.get(self.running, "") if self.running else "",
                "show": self.running in SHOW_MODES, "status": p.status if (p and self.running) else "",
                "live": p.live if (p and self.running in SHOW_MODES) else None,
                "now_playing": playing, "conn": self.conn, "warning": self.warning, "refused": self.studio_refused,
                "last_run": self.last_run, "phone": self.local.server is not None,
                "update": {"state": self.update_state, "version": self.offer.version if self.offer else "",
                           "notes": self.offer.notes if self.offer else "", "progress": round(self.progress, 3),
                           "later": bool(self.offer and self.update_later == self.offer.version)},
                "llano": self.llano_notice()}

    def llano_notice(self) -> dict:
        """What the Live screen says about Llano (Llano BL #12370): the change this laptop holds, and the
        changes that just landed until he presses OK. Never fails the screen."""
        try:
            pub = self.link.public()
        except Exception:  # noqa: BLE001 -- ok: the screen draws without the notice rather than failing
            return {}
        landed = pub.get("landed") or {}
        return {"linked": pub["linked"], "online": pub["online"], "rev": pub["rev"], "pending": pub["pending"],
                "landed": landed if landed.get("changes") and not landed.get("seen") else None}

    def song_tag(self, playing) -> "dict | None":
        """The playing song's part of the night and energy tag, from the show the Live show follows
        ("Dancing · Hype" beside the song on the Live screen), or None."""
        name, index = self.live_tags
        if not (name and index and isinstance(playing, dict)) or self.running not in ("live", "preview"):
            return None
        hit = shows.tag_of(index, str(playing.get("artist") or ""), str(playing.get("title") or ""))
        if not hit:
            return None
        i, part, tag = hit
        return {"i": i, "part": part, "part_title": shows.PART_TITLES.get(part, ""), "tag": tag,
                "tag_title": shows.TAG_TITLES.get(tag, ""), "can_tag": part == "dancing"}

    def retag_live(self, msg: dict) -> tuple[int, dict]:
        """The Live screen's tap on a Dancing song's tag: saved into the show it follows, and its look
        plays at once."""
        name = self.live_tags[0]
        sh = shows.saved_shows().get(name) if name else None
        i = msg.get("i")
        if sh is None or not isinstance(i, int) or isinstance(i, bool):
            return 409, {"error": "The Live show isn't following a saved show, so there is no song to tag."}
        if not (0 <= i < len(sh["songs"])) or sh["songs"][i].get("part") != "dancing":
            return 400, {"error": "Only a Dancing song takes Hype, Dance or Slow."}
        try:
            self.link.local_change(shows.retag_ops(name, sh, i, str(msg.get("tag") or "")))
        except settings_contract.ContractError as e:
            return 400, {"error": str(e)}
        self.live_show_looks()   # its new look applies now
        return 200, {"ok": True}

    def reload_night(self, force: bool = False) -> bool:
        """Tonight's list again when what it is made from changed: a night built (or rebuilt) on this
        laptop, or a saved show changed here or by Llano (Llano BL #12387: the AJ Wedding order and
        two new songs, set by Llano, never reached the Live screen, which read only a built night).
        Where Mixxx is in the night carries over while the steps are the same."""
        doc, prefer = show_settings.current(), self._prefs().get("live_show") or ""
        sig = tonight_mod.Tonight.signature(doc=doc, prefer=prefer)
        if not force and sig == self.night_sig:
            return False
        self.night_sig = sig
        night = tonight_mod.Tonight.load(doc=doc, prefer=prefer)   # outside the studio's lock: every frame takes it
        with self.studio.lock:
            old = self.studio.night
            if old is not None and night.same_steps(old) and old.source == night.source:
                night.at, night.ahead = old.at, old.ahead
            elif old is not None and old.ahead is not None:
                old._let_go(self.studio)   # a step he ran ahead to is not in the new list
            self.studio.night = night
            self.studio.rev += 1
        night.tell_lights()   # its soft and still songs and its moods (show_settings)
        print(f"Tonight: {len(night.steps)} steps from " + {"built": f"the night built as {night.title}",
              "show": f"the show {night.title}"}.get(night.source, "the usual wedding order"))
        return True

    def watch_night(self, every_s: float = 2.0) -> None:
        """Keeps tonight's list current: a show Llano changes reaches the Live screen in seconds."""
        while not self.quit.is_set():
            try:
                self.reload_night()
            except Exception as e:  # noqa: BLE001 -- ok: the list keeps the last night; the next look tries again
                print(f"Tonight could not be reloaded: {type(e).__name__}: {e}")
            self.quit.wait(every_s)

    def watch_probe(self, every_s: float = 0.2) -> None:
        """A probe from a Llano session with nothing running: run the probe's own output loop."""
        while not self.quit.is_set():
            if probes.active() and not self.running and self.update_state not in ("downloading", "restarting"):
                code, out = self.run("probe")
                if code != 200:
                    probes.note = f"refused: {out.get('error') or 'could not start'}"
                    probes.clear()
            self.quit.wait(every_s)

    def watch_connections(self, every_s: float = 4.0) -> None:
        """Keeps the header's lights box / loopMIDI / Mixxx dots current while a window looks."""
        while not self.quit.is_set():
            if time.monotonic() - self.last_request < 15:
                try:
                    self.conn = connections(self.mixxx.running)
                    if self.warning and self.warning.get("lights") and self.conn["enttec"]["ok"]:
                        self.warning = None   # the box is in: the calm note goes by itself
                except Exception as e:  # noqa: BLE001 -- a failed read leaves the last one shown
                    print(f"connection check failed: {e}")
                try:
                    self.check_hotspot()   # only asks Windows after a refused start (it returns at once otherwise)
                except Exception as e:  # noqa: BLE001 -- ok: the hotspot line keeps what it said
                    print(f"hotspot check failed: {e}")
            self.quit.wait(every_s)

    def live_show_looks(self) -> bool:
        """The saved show the Live show follows (Shows page): while Mixxx, Spotify or YouTube Music
        plays one of its songs, the lights play that song's look from the show."""
        sh = shows.saved_shows().get(self._prefs().get("live_show") or "")
        if sh is None:
            return False
        songs = shows.from_public(sh["songs"])
        shows.follow(songs, sh.get("looks"), sh.get("moods"))
        self.live_tags = (self._prefs().get("live_show") or "", shows.tag_index(songs))
        print(f"Following the show '{sh['title'] or self._prefs().get('live_show')}': each of its songs plays its look.")
        return True

    def _run(self, mode: str, opts) -> None:
        print(f"--- {MODES[mode][0]} ---")
        following = False
        try:
            following = mode in ("live", "preview") and self.live_show_looks()
            rc = MODES[mode][1](opts)
            # A check that finds something missing ran fine: say what it found (his recording, 7:24).
            self.last_run = f"{MODES[mode][0]}: " + ("stopped" if self.stopping else "finished" if not rc
                                                     else "found something to fix; it is marked under Your setup" if mode == "check"
                                                     else "didn't start; the log below says why")
        except KeyboardInterrupt:
            self.last_run = f"{MODES[mode][0]}: stopped"
        except Exception as e:
            traceback.print_exc()
            self.last_run = f"{MODES[mode][0]}: something went wrong ({type(e).__name__}: {e})"
        finally:
            disarm_stop_dump()   # it ended: no stack dump needed
            with self.lock:   # run() takes it too: nothing new starts until this run is cleared away
                if self.runner is not threading.current_thread():   # Stop gave up on this run (1.12.4)
                    print(f"{MODES[mode][0]}: the run that didn't stop has now finished.")
                    return
                self.running = None  # first: a late Stop interrupt below must not leave it set
                if show_settings.play_label():   # Stop ends a moment too; the next show starts as saved
                    show_settings.clear_play()
                self.moment = ""
                with self.studio.lock:   # and what he held in the studio; brightness, pins, pads and marks stay
                    if not self.keep_studio:   # (kept across a swap to the live show: switch_show)
                        self.studio.reset()
                    self.studio.layout = None
                    self.studio.rev += 1
                if following or mode == "show":
                    show_settings.set_show_looks(None)
                self.live_tags = ("", {})
                while not self.preview.keys.empty():  # a Stop that came before the show began
                    self.preview.keys.get()
            print(self.last_run)
            self.refresh_setup()

    def stop(self) -> tuple[int, dict]:
        with self.lock:
            mode, runner = self.running, self.runner
        if not mode or not runner or not runner.is_alive():
            return 200, {"ok": True, "note": "nothing was running"}
        if mode == "check":
            return 200, {"ok": True, "note": "the check finishes in a moment"}
        self.stopping = True
        arm_stop_dump()
        threading.Thread(target=self._stop_watch, args=(mode, runner), daemon=True).start()
        if mode in STOP_BY_KEY:
            self.preview.keys.put("q")
        elif runner.ident and runner.is_alive() and self.running == mode:  # analyze
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(runner.ident),
                                                       ctypes.py_object(KeyboardInterrupt))
        return 200, {"ok": True}

    def _stop_watch(self, mode: str, runner: threading.Thread) -> None:
        """Stop always frees the window (1.12.4, his 11-08 report "Stop stopped responding"): a run
        still going STOP_WAIT_S after Stop is left behind, and the window is ready for the next."""
        runner.join(STOP_WAIT_S)
        if not runner.is_alive():
            return
        with self.lock:
            if self.runner is not runner:
                return
            self.runner, self.running = None, None
            self.last_run = f"{MODES[mode][0]}: stopped (it didn't finish closing; restart Llano Lights if the lights box says it is busy)"
            while not self.preview.keys.empty():
                self.preview.keys.get()
        self.preview.end()
        print(self.last_run)

    # The setup guide (1.21, Llano PM #23415): setup_guide.steps() over what this window knows.
    def _set_prefs(self, **kv) -> None:
        try:
            self.prefs_file.write_text(json.dumps({**self._prefs(), **kv}), encoding="utf-8")
        except OSError as e:
            print(f"Couldn't save a setting: {e}")

    def guide_facts(self) -> dict:
        items = {i.get("key"): i for i in (self.setup or [])}
        conn = self.conn or {}
        prefs = self._prefs()
        live = self.preview.live if (self.preview is not None and self.running in SHOW_MODES) else None
        heard_now = bool(live and live.get("mixxx_heard"))
        if heard_now and not prefs.get("guide_heard"):
            self._set_prefs(guide_heard=True)
            prefs["guide_heard"] = True
        box = conn.get("enttec") or items.get("enttec") or {}
        midi = conn.get("loopmidi") or items.get("loopmidi") or {}
        lib = items.get("libraries") or {}
        try:
            n_songs = sum(1 for s in shows.list_public() if s.get("songs"))
        except Exception as e:  # noqa: BLE001 -- a settings file that won't read: no show yet, said plainly
            print(f"setup guide: couldn't read the saved shows: {e}")
            n_songs = 0
        night = self.night if (self.night or {}).get("state") == "done" else self._last_night()
        try:
            autodj = wedding_night.check_mixxx()
            autodj = autodj if autodj.get("found") else None
        except Exception as e:  # noqa: BLE001 -- Mixxx's settings unreadable: unknown, not wrong
            print(f"setup guide: couldn't read Mixxx's Auto DJ settings: {e}")
            autodj = None
        port = str(box.get("detail") or "")
        return {"app_ok": lib.get("ok") is not False, "app_detail": lib.get("detail", ""),
                "mapping": (items.get("mapping") or {}).get("ok") is not False if items else True,
                "box": bool(box.get("ok")), "box_port": port[len("plugged in on "):] if port.startswith("plugged in on ") else "",
                "lights_confirmed": bool(prefs.get("guide_lights")),
                "lined_up": self.preview is not None and setup_guide.lined_up(self.preview.layout),
                "midi": midi.get("ok"), "heard_now": heard_now, "heard_ever": bool(prefs.get("guide_heard")),
                "listening": self.running in ("preview", "live"),
                "shows_with_songs": n_songs, "night": night, "autodj": autodj}

    def guide_public(self) -> dict:
        items = setup_guide.steps(self.guide_facts())
        return {"steps": items, **setup_guide.summary(items), "running": self.running,
                "running_label": SHORT.get(self.running, "") if self.running else "",
                "setup_busy": self.setup_busy, "version": VERSION}

    def guide_confirm(self, key: str, ok: bool) -> tuple[int, dict]:
        if key not in setup_guide.CONFIRMABLE:
            return 400, {"error": "that step checks itself"}
        self._set_prefs(**{f"guide_{key}": ok})
        return 200, {"ok": True}

    def guide_first(self) -> bool:
        """Open on the setup guide? Only until he finishes it or presses Not now, and never when
        LLANO_LIGHTS_GUIDE=0. A failure reading the steps opens the usual front page."""
        if os.environ.get("LLANO_LIGHTS_GUIDE", "1") == "0":
            return False
        if getattr(self, "guide_opened", False):   # once per launch: ← Live must reach the Live screen
            return False
        prefs = self._prefs()
        if prefs.get("guide_later") or prefs.get("guide_done"):
            return False
        try:
            done = setup_guide.summary(setup_guide.steps(self.guide_facts()))["complete"]
        except Exception as e:  # noqa: BLE001 -- never let the guide keep him off the Live screen
            print(f"setup guide: {e}")
            return False
        if done:
            self._set_prefs(guide_done=True)
        self.guide_opened = not done
        return not done

    def refresh_setup(self) -> None:
        self.setup_busy = True
        try:
            self.setup = setup_status()
            self.setup_at = time.time()
        except Exception as e:
            print(f"setup check failed: {e}")
        finally:
            self.setup_busy = False

    # updates
    def check_update(self) -> None:
        self.update_state, self.update_note = "checking", "checking for updates"
        offer, note = updater.check()
        self.offer, self.update_note = offer, note
        # "unreachable": offline, or an answer that isn't our signed update file (a sign-in page)
        self.update_state = "offered" if offer else "current" if note.endswith("is the newest version") \
            else "unreachable"
        print(f"Updates: {note}")

    def start_update(self) -> tuple[int, dict]:
        with self.lock:
            if self.show_busy():
                return 409, {"error": "Stop the show first, then update."}
            if not self.offer or self.update_state != "offered":
                return 400, {"error": "there is no update to install"}
            if not updater.is_installed():
                return 400, {"error": "this copy isn't an installed Llano Lights folder"}
            self.update_state, self.progress = "downloading", 0.0
        threading.Thread(target=self._update, args=(self.offer,), daemon=True).start()
        return 200, {"ok": True}

    def show_busy(self) -> bool:
        """Something he runs is on (a show, scenes, the designer, a check): no restart may cut into it.
        A Llano probe is not his: an update may end it."""
        return bool(self.running) and self.running != "probe"

    def _update(self, offer) -> None:
        """Download and unpack in the background, then restart only with nothing running (Llano BL
        #12377, his 11-14 report: he pressed Update while running the show, the app stopped answering
        his presses for the whole download, and the restart left a window on a dead 127.0.0.1 page).
        The show keeps working during the download; an update that finishes while something runs waits
        as "ready" until he presses Install now with the show stopped."""
        def progress(done: int, total: int) -> None:
            self.progress = done / total if total else 0.0
        try:
            print(f"Downloading Llano Lights {offer.version}")
            cmd = updater.prepare(offer, progress=progress)
        except Exception as e:  # UpdateError or anything else: keep running this version
            self.update_state, self.update_note = "failed", f"the update didn't install: {e}"
            print(self.update_note)
            return
        with self.lock:
            self.staged = (offer, cmd)
            if self.show_busy():
                self.update_state = "ready"
                self.update_note = (f"Llano Lights {offer.version} is downloaded. It installs when you press "
                                    "Install now with the show stopped; nothing restarts during a show")
                print(self.update_note)
                return
            if getattr(self.preview, "tried", False):   # an unsaved room would be lost in the restart (PM #23745)
                self.update_state = "ready"
                self.update_note = (f"Llano Lights {offer.version} is downloaded. Your room has changes you haven't saved: "
                                    "press Save my layout (or Reset) in the Show Designer, then Install now")
                print(self.update_note)
                return
            self.update_state = "restarting"   # run() refuses from here: nothing new starts under the swap
        self._swap(offer, cmd)

    def install_update(self) -> tuple[int, dict]:
        """Install now on a downloaded update (state "ready"): only with nothing running."""
        with self.lock:
            if self.update_state != "ready" or not self.staged:
                return 400, {"error": "there is no downloaded update to install"}
            if self.show_busy():
                return 409, {"error": "Stop the show first, then install the update."}
            if getattr(self.preview, "tried", False):
                # the 11-14 video (after an update the lights moved back): the restart dropped
                # a room he had changed and not saved (PM #23745). The update waits for him to keep it or throw it away.
                return 409, {"error": "Your room has changes you haven't saved. In the Show Designer press Save my layout "
                                      "(or Reset to throw them away), then press Update again."}
            self.update_state = "restarting"
            offer, cmd = self.staged
        threading.Thread(target=self._swap, args=(offer, cmd), name="update-install", daemon=True).start()
        return 200, {"ok": True}

    def _swap(self, offer, cmd) -> None:
        self.update_note = f"restarting into Llano Lights {offer.version}"
        try:
            updater.launch_swap(cmd)  # waits until the installer is alive; it then waits for us to exit
        except Exception as e:  # noqa: BLE001 -- nothing changed: keep running this version
            self.update_state, self.update_note = "failed", f"the update didn't install: {e}"
            print(self.update_note)
            return
        print(self.update_note)
        self.quit.set()

    # the test channel (1.14.0): Llano publishes a test build on every merge; he installs it with a
    # click (Update), and Go back to stable puts the stable copy kept on disk back, no internet needed
    def song_playing(self) -> bool:
        """A song is playing, or he is in the middle of something a probe must not cut into."""
        mode = self.running
        if not mode:
            return False
        if mode in ("live", "preview"):
            feed = getattr(self.preview, "feed", None)
            return bool(feed is not None and feed.playing)
        return mode != "probe"

    def _test_build(self, info: dict) -> None:
        """Llano's pull named the test channel's newest build: offer it when it is newer."""
        if info.get("channel") != "test" or self.test_busy:
            return
        version = str(info.get("version") or "")
        try:
            newer = updater.is_newer(version, VERSION)
        except updater.UpdateError:
            return
        if not newer or (self.test_offer and self.test_offer.version == version):
            return
        self.test_busy = True
        threading.Thread(target=self._fetch_test_offer, args=(version,), name="test-channel", daemon=True).start()

    def _fetch_test_offer(self, version: str) -> None:
        try:
            offer, note = updater.check(updater.test_url())
            if offer is None or offer.channel != "test":
                self.test_note = f"test build {version} isn't ready yet: {note}"
                return
            self.test_offer, self.test_note = offer, f"Test build {offer.build} ready"
            print(f"Test channel: test build {offer.build} ({offer.version}) is ready; Update installs it")
        finally:
            self.test_busy = False

    def hide_test_banner(self) -> tuple[int, dict]:
        """His X on the green test build banner (Llano BL #12145): hidden for that build only, across
        launches; a newer test build shows its banner again, and the small Update by Check for updates
        stays so he can still install this one. Nothing is ever forced or nagged."""
        self.test_later = self.test_offer.version if self.test_offer else ""
        try:
            self.prefs_file.write_text(json.dumps({**self._prefs(), "test_hidden": self.test_later}), encoding="utf-8")
        except OSError as e:
            print(f"Couldn't save the hidden test build: {e}")   # still hidden until the next launch
        return 200, {"ok": True}

    def start_test_update(self) -> tuple[int, dict]:
        with self.lock:
            if self.show_busy():
                return 409, {"error": "Stop the show first, then update."}
            if not self.test_offer:
                return 400, {"error": "there is no test build to install"}
            if not updater.is_installed():
                return 400, {"error": "this copy isn't an installed Llano Lights folder"}
            if self.update_state in ("downloading", "ready", "restarting"):
                return 409, {"error": "an update is being installed"}
            self.update_state, self.progress = "downloading", 0.0
            self.offer = self.test_offer
        threading.Thread(target=self._update, args=(self.test_offer,), daemon=True).start()
        return 200, {"ok": True}

    def go_back_to_stable(self) -> tuple[int, dict]:
        """Put the stable copy kept on disk back (no download). It restarts the app, so never during a
        show (Llano BL #12377): Stop first, then Go back."""
        with self.lock:
            if self.update_state in ("downloading", "ready", "restarting"):
                return 409, {"error": "an update is being installed"}
            if self.show_busy():
                return 409, {"error": "Stop the show first, then go back to stable."}
            if updater.stable_copy() is None:
                return 400, {"error": "there is no stable copy on this laptop to go back to"}
            self.update_state = "restarting"
            self.update_note = "going back to the stable copy"
            if self.running:
                self.stopping = True
                self.preview.keys.put("q")
        try:
            if self.runner:
                self.runner.join(5)
            updater.launch_swap(updater.stage_rollback())
        except Exception as e:  # noqa: BLE001 -- nothing changed; this copy keeps running
            self.update_state, self.update_note = "failed", f"couldn't go back to stable: {e}"
            print(self.update_note)
            return 500, {"error": self.update_note}
        print(self.update_note)
        self.quit.set()
        return 200, {"ok": True}

    # settings + the Llano link
    def _with_local_layouts(self, doc: dict) -> dict:
        """The settings document plus his saved layouts and the one in use, from the layout files."""
        doc = dict(doc)
        doc["layouts"] = {"in_use": self.layouts.current_name(),
                          "saved": {n: lay.to_dict() for n, lay in self.layouts.saved().items()}}
        return show_settings.set_current(doc)

    def layout_changed(self, lay: Layout, saved: bool, use: bool = True) -> None:
        """Show Designer: a layout saved or picked here goes to Llano too. `use=False` (a venue renamed
        under My venues, BL #12380) sends the venue without changing which one the show aims from."""
        if not settings_contract.good_name(lay.name):
            print(f"Layout {lay.name!r} stays on this laptop: Llano takes names of letters, numbers and dashes")
            return
        ops = [{"path": "layouts.in_use", "value": lay.name}] if use else []
        if saved:
            ops.insert(0, {"path": f"layouts.saved.{lay.name}", "value": lay.to_dict()})
        self._send_layout_ops(ops)

    def layout_removed(self, name: str) -> None:
        """My venues (BL #12380): a venue deleted here comes off llano.app/lights too."""
        if settings_contract.good_name(name):
            self._send_layout_ops([{"path": f"layouts.saved.{name}", "value": None}])

    def _send_layout_ops(self, ops: list) -> None:
        if not ops:
            return
        try:
            self.link.local_change(ops)
        except Exception as e:  # noqa: BLE001 -- the layout file is saved; only the sync copy failed
            print(f"Couldn't queue the layout for Llano: {e}")

    def _settings_from_llano(self, new: dict, old: dict) -> None:
        """Llano changed the settings: the show already reads the new ones; layouts need files."""
        store = self.layouts
        mine = store.saved()
        changed = set()
        for name, data in new["layouts"]["saved"].items():
            try:
                lay = Layout.from_dict({**data, "name": name})
            except ValueError as e:
                print(f"Layout {name} from Llano skipped: {e}")
                continue
            lay.name, lay.preset = name, False
            if name in mine and mine[name].to_dict() == lay.to_dict():
                continue
            try:
                store.dir.mkdir(parents=True, exist_ok=True)
                dest = store.dir / f"{name}.json"
                if name in mine and has_lineup(mine[name]) and not has_lineup(lay):
                    # Llano's copy has no line-up where his had one (PM #23745): keep his as the last good line-up,
                    # so Bring back my line-up puts it back; Clear line-up on the phone also arrives this way.
                    store.remember_lineup(mine[name])
                    print(f"Layout {name} from Llano has no line-up; kept yours for Bring back my line-up")
                if name in mine and dest.is_file():
                    # A different copy of this layout lives here: keep it beside the new one.
                    dest.replace(store.dir / f"{name}.json.replaced")
                    print(f"Layout {name} replaced from Llano; kept your old copy as {name}.json.replaced")
                tmp = store.dir / f"{name}.json.tmp"
                tmp.write_text(json.dumps(lay.to_dict(), indent=1), encoding="utf-8")
                tmp.replace(dest)
                changed.add(name)
            except OSError as e:  # one layout that won't write never stops the others
                print(f"Layout {name} from Llano couldn't be saved: {e}")
        for name in set(old["layouts"]["saved"]) - set(new["layouts"]["saved"]):
            f = store.dir / f"{name}.json"
            try:
                if f.is_file():  # removed in Llano: set aside, never deleted
                    f.replace(store.dir / f"{name}.json.removed")
            except OSError as e:
                print(f"Layout {name} couldn't be set aside: {e}")
        want = new["layouts"]["in_use"]
        # The layout in use changed on his phone (Light positions, BL #11766): the show re-aims from it now.
        if want and want == store.current_name() and want in changed and getattr(self.preview, "tried", False):
            # He is mid line-up (or trying a layout) on the laptop: his unsaved work wins; the phone's copy
            # is saved and the show picks it up when he saves or leaves.
            print(f"Layout {want} changed in Llano while you were lining up; kept your line-up on screen")
        elif want and (want != store.current_name() or want in changed) and want in store.all():
            lay = store.use(want)
            if self.preview:
                self.preview.layout = lay
                if self.preview.on_layout:
                    self.preview.on_layout(lay)
            print(f"Room layout from Llano: {lay.label}")

    def _status_sent(self, status: dict, reply: dict) -> None:
        """Llano keeps the crash report: stop sending it from crash-report.txt on later launches."""
        if reply.get("crash_kept") and status.get("last_crash") and self.crash is status.get("last_crash"):
            mark_crash_sent(app_data_dir(), self.crash)

    def _sync_status(self, watch: bool) -> dict:
        p = self.preview
        out = {"mode": self.running or "", "mode_label": MODES[self.running][0] if self.running else "",
               "status": p.status if (p and self.running) else "stopped", "version": VERSION,
               "channel": CHANNEL, "build": BUILD, "test_update": self.test_note, "probe": probes.public(),
               # on Llano's clock (epoch s), 0 = no draft playing
               "draft_until": int(show_settings.play_until() + self.link.clock_skew)
               if show_settings.play_until() and not show_settings.play_label() else 0}
        if self.moment_now():
            out["moment"] = self.moment_now()
        if self.studio.live:   # the Light studio, in the one shape every screen draws (1.20.0)
            out["studio"] = self.studio_state(glow=True)
        if self.crash:   # the last run's end, so Llano sees a crash without asking him for the log
            out["last_crash"] = self.crash
        if self.doctor:  # the last Light doctor run (BL #11615): what it drove, where he tapped, the fit
            out["light_doctor"] = self.doctor
        feed = getattr(p, "feed", None) if (p and self.running) else None
        if feed is not None:
            out["now_playing"] = feed.public()
        # Local mode: where his paired phone can reach this laptop when the internet drops.
        if self.local.server is not None:
            out["local"] = self.local.public(with_key=True)
        if self.hotspot_on or self.hotspot_starting or self.hotspot_note:
            out["hotspot"] = self.hotspot_public()   # what Windows said, so Llano can read it (BL #12109)
        if p is not None:
            out["layout_name"] = p.layout.name
            if watch:
                out["layout"] = p.layout.to_dict()
        return out

    def _sync_catalog(self) -> dict:
        return {"version": VERSION, "layouts": {n: lay.to_dict() for n, lay in presets(rig_numbering()).items()}}

    def startup(self) -> None:
        self.link.start()
        self.drive_start("open")   # Get my songs on app open (BL #12342): download only, the show changes on his press
        if self.local_on:
            self.set_local(True)
        self.mixxx.start()
        threading.Thread(target=self.watch_mixxx, name="start-with-mixxx", daemon=True).start()
        threading.Thread(target=self.watch_connections, name="connections", daemon=True).start()
        threading.Thread(target=self.watch_probe, name="llano-probe", daemon=True).start()
        threading.Thread(target=self.watch_night, name="tonight", daemon=True).start()
        if updater.is_installed():
            if not getattr(self.opts, "ready_file", None):   # just swapped in: the swap still owns the old copy
                updater.clean_leftovers()
            refresh_mapping()
            try:
                if windows_apps.register(updater.install_root(), VERSION):
                    print("Listed in Windows Settings > Apps, with Uninstall")
            except (OSError, TypeError, ValueError) as e:
                print(f"Couldn't list Llano Lights in Windows Settings > Apps: {e}")
            try:   # the "not running" screen's Start Llano Lights button (Llano BL #12377)
                if windows_apps.register_start_link(updater.install_root()):
                    print("The window's Start Llano Lights button is set up")
            except (OSError, TypeError, ValueError) as e:
                print(f"Couldn't set up the Start Llano Lights button: {e}")
        self.refresh_setup()
        self.check_update()
        threading.Thread(target=self.watch_updates, name="update-check", daemon=True).start()

    def watch_updates(self, every_s: float = UPDATE_RECHECK_S) -> None:
        """Ask the update server again every half hour while the app stays open (his 11-09 report:
        the laptop sat on 1.15.0.3 all day while 1.16.1 was out, because the app asked once, when
        it opened, and the heads kept the old stepping). Never mid-download, and never a second
        check while one is running; a found offer just waits for his Update."""
        while not self.quit.wait(every_s):
            if self.update_state in ("current", "unreachable", "failed"):
                self.check_update()


def refresh_mapping() -> None:
    """A new build may carry a new Mixxx mapping: copy it over the old one."""
    src = updater.install_root() / "Mixxx mapping"
    cdir = mixxx_controllers_dir()
    if not (src.is_dir() and cdir.is_dir()):
        return
    for f in MAPPING_FILES:
        try:
            if (src / f).is_file() and (not (cdir / f).exists() or (cdir / f).read_bytes() != (src / f).read_bytes()):
                shutil.copyfile(src / f, cdir / f)
                print(f"Updated the Mixxx mapping file {f}")
        except OSError as e:
            print(f"Couldn't update the Mixxx mapping file {f}: {e}")


NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # a system proxy must not see 127.0.0.1


def running_instance() -> "tuple[str, dict] | None":
    """(URL, its /api/app state) of a Llano Lights window server already running here, if any.

    All the ports at once (1.11.4, his 2:40 PM recording 0:14: slow to open): Windows retries a
    connection to a closed local port instead of refusing it, so each free port used its whole
    0.5 s timeout, one after another, about 10 s on every launch before the window opened."""
    def probe(port: int) -> "tuple[str, dict] | None":
        url = f"http://127.0.0.1:{port}/"
        try:
            with NO_PROXY.open(url + "api/app", timeout=0.5) as r:
                info = json.load(r)
            return (url, info) if info.get("product") == updater.PRODUCT else None
        except Exception:
            return None
    found: list = [None] * len(PORTS)
    def one(i: int, port: int) -> None:
        found[i] = probe(port)
    threads = [threading.Thread(target=one, args=(i, port), daemon=True) for i, port in enumerate(PORTS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(2.0)
    return next((f for f in found if f), None)   # the lowest port, as when they ran in turn


def same_copy(info: dict) -> bool:
    """Is the running window this very build? 1.2.1 and older don't say their folder, so
    for them only the version can tell; any other version is another copy."""
    if info.get("version") != VERSION:
        return False
    root = info.get("root")
    return not root or os.path.normcase(os.path.normpath(root)) == \
        os.path.normcase(os.path.normpath(str(updater.install_root())))


def close_other(url: str, wait_s: float = 10.0) -> bool:
    """Ask another copy's window server to quit (every version since 1.1.0 takes /api/quit with
    the token baked into its page) and wait for it to stop answering."""
    try:
        with NO_PROXY.open(url, timeout=2) as r:
            page = r.read().decode("utf-8", "replace")
        token = page.split('name="llano-token" content="', 1)[1].split('"', 1)[0]
        req = urllib.request.Request(url + "api/quit", data=b"{}", method="POST",
                                     headers={"X-Llano-Token": token, "Content-Type": "application/json"})
        NO_PROXY.open(req, timeout=3).close()
    except Exception as e:
        print(f"Couldn't ask the other copy to close: {e}")
        return False
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        try:
            NO_PROXY.open(url + "api/app", timeout=0.5).close()
        except Exception:
            return True
        time.sleep(0.3)
    return False


# One copy at a time (1.8.0): he had two 1.7.0 windows open on one laptop, both able to drive the
# ENTTEC box and the MIDI port. The lock is taken before anything else so two quick launches can't
# both get past the probe, and a second launch brings the open window forward instead of opening
# another. Process exit releases it, so the update swap's new copy gets it once the old one is gone.
INSTANCE_LOCK = "Local\\LlanoLightsWindow"
INSTANCE_WAIT_S = 20.0
_instance_handle = None


def take_instance_lock() -> bool:
    """True if this process now holds the one-copy lock (kept until it exits)."""
    global _instance_handle
    if _instance_handle is not None:
        return True
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.CreateMutexW.restype = ctypes.c_void_p
        h = k32.CreateMutexW(None, False, INSTANCE_LOCK)
        if not h:
            return True  # can't make the lock at all: never refuse to open over it
        if k32.WaitForSingleObject(ctypes.c_void_p(h), 0) in (0, 0x80):  # owned, or abandoned by a crash
            _instance_handle = h
            return True
        k32.CloseHandle(ctypes.c_void_p(h))
        return False
    import fcntl
    try:
        f = open(app_data_dir() / "window.lock", "a")
    except OSError:
        return True
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    _instance_handle = f
    return True


def focus_window() -> bool:
    """Bring an open Llano Lights window to the front (restoring it if minimised). The window's
    title is the page's ("Llano Lights 1.8.0 (built ...)"); Edge's own browser windows end in
    "Edge", so a tab with that name isn't mistaken for it."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        if u32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(hwnd, buf, 256)
            if is_app_window_title(buf.value):
                found.append(hwnd)
                return False
        return True

    u32.EnumWindows(each, 0)
    if not found:
        return False
    if u32.IsIconic(found[0]):
        u32.ShowWindow(found[0], 9)  # SW_RESTORE
    u32.SetForegroundWindow(found[0])
    return True


def is_app_window_title(title: str, version: str = "") -> bool:
    """The app window's title is exactly the page's, "Llano Lights 1.10.0 (built ...)". A browser
    tab with that page (or llano.app/lights) adds " - Google Chrome", " - Microsoft Edge" or more,
    so it never matches. With `version`, only that build's window."""
    m = APP_TITLE.match(title)
    return bool(m) and (not version or m.group(1) in (None, version))   # bare = the page before its script ran


# A test-channel build is VERSION.<build> ("1.19.3.24", version.py): four numbers. Matching only three
# left a test copy's window unfindable, so opening the app again opened another window and an update
# never closed the old one (Llano BL #12140, several copies on his test-channel laptop).
# A page after the app title (" · Shows", " · Set up guide", the " · not running" screen of sw.js) is
# still the app window (Llano BL #12377: the Shows page's window stayed open on a dead engine after an
# update, because its title wasn't the app's). Edge's own windows end " - Microsoft Edge", never this.
APP_TITLE = __import__("re").compile(
    r"^Llano Lights(?: (\d+\.\d+\.\d+(?:\.\d+)?)(?: \(built [^)]*\))?)?(?: \u00b7 [^-\u00b7]+)?$")


def window_title() -> str:
    """The app window's title, "Llano Lights 1.25.0 (built ...)"; every page the window shows starts
    with it (the Shows page adds " · Shows"), so APP_TITLE finds the window whatever page it is on."""
    return f"Llano Lights {VERSION}" + (f" (built {BUILT_CT})" if BUILT_CT else "")


def close_app_windows(version: "str | None" = None) -> int:
    """Ask every open Llano Lights window to close, the way its X button does (1.10.0, his
    recording 0:07): after an update the old window goes by itself and the new one opens. Edge
    often hands the window to a process of its own, so the one we started can't be relied on.
    `version` "" closes every copy's window: a starting copy closes the ones left on a dead engine
    (Llano BL #12377); by default only this build's."""
    version = VERSION if version is None else version
    if sys.platform != "win32":
        return 0
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        buf, cls = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(64)
        u32.GetWindowTextW(hwnd, buf, 256)
        u32.GetClassNameW(hwnd, cls, 64)
        # Edge's own window class, and only THIS build's window: a second copy's stays open
        if u32.IsWindowVisible(hwnd) and cls.value == "Chrome_WidgetWin_1" and is_app_window_title(buf.value, version):
            found.append(hwnd)
        return True

    u32.EnumWindows(each, 0)
    for hwnd in found:
        u32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    return len(found)


# The run marker (1.10.0, his recording 8:38): written once this copy serves the window and
# removed on a clean close, so the next launch knows the last run crashed or was killed and
# keeps what it was doing (the log since it started, and faulthandler's crash.log) for Llano.
RUN_MARKER = "running.json"
CRASH_LINES = 80
CRASH_BYTES = 8 * 1024


def frozen_pid(base: Path) -> int:
    """The process id the run marker names when it is another copy, else 0."""
    try:
        info = json.loads((base / RUN_MARKER).read_text(encoding="utf-8"))
        pid = int(info.get("pid") or 0) if isinstance(info, dict) else 0
    except (OSError, ValueError, TypeError):
        return 0
    return pid if pid > 0 and pid != os.getpid() else 0


def end_frozen_copy(base: Path) -> bool:
    """End a copy that holds the window lock but hasn't answered for INSTANCE_WAIT_S (1.20.1, his
    11-13 freeze): left running it keeps the ENTTEC's COM port, so the new copy's lights stay dark.
    Only the process the run marker names, and only when it is a Python (this app's runtime), so a
    reused process id is never touched. Its run marker and crash.log stay for the crash report."""
    pid = frozen_pid(base)
    if not pid or sys.platform != "win32":
        return False
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = ctypes.c_void_p
    h = k32.OpenProcess(0x0001 | 0x1000, False, pid)   # PROCESS_TERMINATE | QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        buf, n = ctypes.create_unicode_buffer(1024), ctypes.c_ulong(1024)
        if not k32.QueryFullProcessImageNameW(ctypes.c_void_p(h), 0, buf, ctypes.byref(n)):
            return False
        if Path(buf.value).name.lower() not in {"python.exe", "pythonw.exe", Path(sys.executable).name.lower()}:
            return False
        if not k32.TerminateProcess(ctypes.c_void_p(h), 3):
            return False
        k32.WaitForSingleObject(ctypes.c_void_p(h), 5000)
        return True
    finally:
        k32.CloseHandle(ctypes.c_void_p(h))


def mark_running(base: Path) -> None:
    try:
        (base / RUN_MARKER).write_text(json.dumps({"pid": os.getpid(), "version": VERSION,
                                                   "started": time.strftime("%Y-%m-%d %H:%M:%S")}), encoding="utf-8")
    except OSError as e:
        print(f"Couldn't write the run marker: {e}")


def clear_running(base: Path) -> None:
    try:
        (base / RUN_MARKER).unlink()
    except OSError:
        pass  # ok: already gone


def last_crash(base: Path, log_name: str = "llano-lights.log") -> "dict | None":
    """The previous run's last lines when it never closed cleanly, else None. Call before this
    run writes its marker. Saved beside the log as crash-report.txt too."""
    try:
        info = json.loads((base / RUN_MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return backfill_crash(base, log_name)
    started = str(info.get("started") or "") if isinstance(info, dict) else ""
    lines: list[str] = []
    for name in (log_name.replace(".log", ".old.log"), log_name):   # a run can straddle the rotation
        try:
            with open(base / name, "rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 400_000))
                lines += f.read().decode("utf-8", "replace").splitlines()
        except OSError:
            continue
    lines = [ln for ln in lines if ln[:19] >= started][-CRASH_LINES:] if started else lines[-CRASH_LINES:]
    fault = ""
    try:
        cf = base / "crash.log"
        if cf.stat().st_mtime >= time.mktime(time.strptime(started, "%Y-%m-%d %H:%M:%S")):
            fault = fault_excerpt(cf.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError, OverflowError):
        pass
    return _report(base, str(info.get("version") or "?"), started, lines, fault)


BACKFILL_FLAG = "crash-backfill.done"


def backfill_crash(base: Path, log_name: str = "llano-lights.log") -> "dict | None":
    """Once, on the first run that writes run markers: the builds before 1.10.0 wrote none, so a
    crash they had (his recording, 8:38) shows in the log as a window server that started and was
    followed by another one with no "Llano Lights closed" between them. Report the latest one."""
    if (base / BACKFILL_FLAG).exists():
        return None
    try:
        (base / BACKFILL_FLAG).write_text(VERSION, encoding="utf-8")
    except OSError:
        return None
    lines = []
    for name in (log_name.replace(".log", ".old.log"), log_name):   # this launch may just have rotated it
        try:
            with open(base / name, "rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 1_000_000))
                lines += f.read().decode("utf-8", "replace").splitlines()
        except OSError:
            continue
    servers = [i for i, ln in enumerate(lines) if " Window server at " in ln]
    for a, b in reversed(list(zip(servers, servers[1:]))):
        if not any(ln.endswith("Llano Lights closed") for ln in lines[a:b]):
            run = lines[a:b]
            begin = max((i for i, ln in enumerate(lines[:a]) if " starting from " in ln), default=a)
            version = lines[begin].split("Llano Lights ", 1)[-1].split(",", 1)[0].split(" ", 1)[0] if begin < a else "?"
            ended = next((i for i in range(b - 1, a - 1, -1) if " starting from " in lines[i]), b)
            return _report(base, version, lines[begin][:19], lines[begin:a] + run[:ended - a][-CRASH_LINES:], "")
    return None


FAULT_CHARS = 4000


def fault_excerpt(text: str, limit: int = FAULT_CHARS) -> str:
    """crash.log cut to fit the report, keeping its HEAD (1.20.1, his 11-13 10:04 crash): faulthandler
    writes the fault ("Windows fatal exception: access violation") and the crashing thread first,
    then every idle thread; keeping only the tail lost exactly the part that names the cause."""
    if len(text) <= limit:
        return text
    cut = "\n... (more threads cut) ...\n"
    head = limit * 3 // 4
    return text[:head] + cut + text[-(limit - head - len(cut)):]


def _trimmed(version: str, started: str, lines: list, fault: str) -> dict:
    report = {"version": version, "started": started, "lines": lines[-CRASH_LINES:], "fault": fault}
    while len(json.dumps(report)) > CRASH_BYTES and report["lines"]:
        report["lines"] = report["lines"][1:]
    return report


SENT_FLAG = "crash-report.sent"
REPORT_HEAD = re.compile(r"^Llano Lights (\S+), started (.*), never closed cleanly$")


def pending_crash(base: Path) -> "dict | None":
    """The crash in crash-report.txt when Llano hasn't said it keeps it (PM #22370). The app
    sends a crash only during the run after it, so a later clean launch lost the 1.5.0 report
    of 2026-11-07 before Llano saved it; this sends it again until Llano answers crash_kept."""
    try:
        text = (base / "crash-report.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    head, _, body = text.partition("\n\n")
    m = REPORT_HEAD.match(head.strip())
    if not m:
        return None
    try:
        if (base / SENT_FLAG).read_text(encoding="utf-8").strip() == _crash_key(m.group(1), m.group(2)):
            return None
    except OSError:
        pass   # ok: never sent
    body, _, fault = body.partition("\n\n--- crash.log ---\n")
    return _trimmed(m.group(1), m.group(2), body.splitlines(), fault)


def _crash_key(version, started) -> str:
    return f"{version} {started}"


def mark_crash_sent(base: Path, crash: dict) -> None:
    try:
        (base / SENT_FLAG).write_text(_crash_key(crash.get("version"), crash.get("started")), encoding="utf-8")
    except OSError as e:
        print(f"Couldn't note that Llano has the crash report: {e}")


def _report(base: Path, version: str, started: str, lines: list, fault: str) -> dict:
    report = _trimmed(version, started, lines, fault)
    try:
        (base / "crash-report.txt").write_text(
            f"Llano Lights {version}, started {started}, never closed cleanly\n\n" +
            "\n".join(lines) + ("\n\n--- crash.log ---\n" + fault if fault else ""), encoding="utf-8")
    except OSError:
        pass
    return report


def show_running(url: str, opts) -> None:
    print(f"Already running at {url}; bringing up its window")
    if not opts.no_window and not focus_window():
        open_window(url)  # its window was closed (it runs on for a show or the browser): open one


def find_edge() -> "Path | None":
    for env in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            exe = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if exe.is_file():
                return exe
    return None


# Edge signs a fresh profile into the PC's Microsoft account on its own and syncs it, so
# 1.1.0 to 1.2.0's window profile pulled in the owner's extensions, each opening its
# welcome page in a new Edge window. The window runs with no extensions and no sync, in a
# new profile that also says no to sign-in; the old one is deleted.
WINDOW_PROFILE = "edge-window"
OLD_WINDOW_PROFILES = ("window",)
EDGE_FLAGS = ("--no-first-run", "--no-default-browser-check", "--disable-extensions",
              "--disable-sync", "--disable-background-mode", "--hide-crash-restore-bubble",
              "--window-size=1320,880")
WINDOW_PREFS = {
    "signin": {"allowed": False, "allowed_on_next_startup": False},
    "sync": {"requested": False},
    "browser": {"has_seen_welcome_page": True},
    "session": {"restore_on_startup": 5},  # a new tab page, never the last session's windows
}
REOPEN_LIMIT = 3  # windows opened again within REOPEN_WINDOW seconds before it stops trying
REOPEN_WINDOW = 600


def window_profile() -> Path:
    """The window's own Edge profile, set up before Edge first sees it."""
    base = app_data_dir()
    for old in OLD_WINDOW_PROFILES:
        if (base / old).is_dir():
            shutil.rmtree(base / old, ignore_errors=True)  # holds the synced extensions
    profile = base / WINDOW_PROFILE
    prefs = profile / "Default" / "Preferences"
    if not prefs.exists():
        try:
            prefs.parent.mkdir(parents=True, exist_ok=True)
            prefs.write_text(json.dumps(WINDOW_PREFS))
        except OSError as e:
            print(f"Couldn't set up the window's Edge profile: {e}")
    else:
        mark_clean_exit(prefs)
    return profile


def mark_clean_exit(prefs: Path) -> None:
    """A window that was closed hard (an update, a crash) leaves Edge thinking it crashed, and the
    next window then brings the old one back beside it: two windows (his recording, 9:11). Say the
    last run ended cleanly before Edge reads the profile."""
    try:
        d = json.loads(prefs.read_text(encoding="utf-8"))
        prof = d.setdefault("profile", {}) if isinstance(d, dict) else None
        if not isinstance(prof, dict) or (prof.get("exit_type") == "Normal" and prof.get("exited_cleanly") is True):
            return
        prof["exit_type"], prof["exited_cleanly"] = "Normal", True
        prefs.write_text(json.dumps(d), encoding="utf-8")
    except (OSError, ValueError):
        pass  # ok: at worst Edge offers to restore the old window


def edge_command(edge: Path, url: str, profile: Path) -> list[str]:
    return [str(edge), f"--app={url}", f"--user-data-dir={profile}", *EDGE_FLAGS]


def open_window(url: str) -> "subprocess.Popen | None":
    """An app window (no tabs, no address bar) in Edge, which every Windows 10/11 has;
    otherwise the default browser. Returns the Edge process to watch, if there is one."""
    edge = find_edge() if sys.platform == "win32" else None
    if edge:
        try:
            return subprocess.Popen(edge_command(edge, url, window_profile()), cwd=str(app_data_dir()))
        except OSError as e:
            print(f"Couldn't open Edge ({e}); using the default browser")
    webbrowser.open(url)
    return None


def close_stale_windows(wait_s: float = 2.0) -> int:
    """Close every Llano Lights window already open before this copy opens its own (Llano BL #12377).
    This copy holds the one-copy lock and has closed any other copy, so a window still open is on a
    dead engine: an old version's window after an update, or the "not running" screen."""
    try:
        n = close_app_windows("")
    except Exception as e:   # noqa: BLE001 -- never stop the window opening over this
        print(f"Couldn't close the old windows: {e}")
        return 0
    if n:
        print(f"Closed {n} window(s) left on a closed Llano Lights")
        deadline = time.monotonic() + wait_s   # let Edge let go of them before it gets the new one
        while time.monotonic() < deadline and app_windows_open():
            time.sleep(0.1)
    return n


def app_windows_open() -> bool:
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        buf = ctypes.create_unicode_buffer(256)
        u32.GetWindowTextW(hwnd, buf, 256)
        if u32.IsWindowVisible(hwnd) and is_app_window_title(buf.value):
            found.append(hwnd)
            return False
        return True

    u32.EnumWindows(each, 0)
    return bool(found)


def startup_mark(step: str) -> None:
    """One log line per launch step with the seconds since launch (1.11.4, his 2:40 PM recording
    0:14: slow to open), so the next slow open shows where the time went."""
    print(f"Startup: {step} at {time.monotonic() - STARTED:.2f}s")


def gui(opts) -> int:
    log = LogBuffer(app_data_dir() / "llano-lights.log", echo=sys.__stdout__)
    sys.stdout = sys.stderr = log  # pythonw has no console; the window shows the log
    threading.excepthook = lambda a: traceback.print_exception(a.exc_type, a.exc_value, a.exc_traceback, file=log)
    print(f"Llano Lights {label()} starting from {updater.install_root()}")
    startup_mark("code loaded")
    deadline = time.monotonic() + INSTANCE_WAIT_S
    while not take_instance_lock():  # another 1.8.0+ copy holds it: hand over to it, or wait it out
        found = running_instance()
        if found and same_copy(found[1]):
            show_running(found[0], opts)
            return 0
        if found:
            print(f"Llano Lights {found[1].get('version') or '?'} from {found[1].get('root')} is open; closing it")
            close_other(found[0])
        if time.monotonic() > deadline:  # a copy that holds the lock but never answers: don't lock him out
            print("Another copy holds the lock but doesn't answer; opening anyway")
            if end_frozen_copy(app_data_dir()):   # a frozen copy keeps the lights box busy
                print("It was frozen: ended it, so the lights box is free for this one")
                take_instance_lock()
            break
        time.sleep(0.5)
    found = running_instance()
    if found and same_copy(found[1]):
        show_running(found[0], opts)
        return 0
    if found:  # an older copy (1.1.0 unzipped elsewhere, say): it must not stand in for this one
        where = found[1].get("root") or "another folder"
        print(f"Llano Lights {found[1].get('version') or '?'} from {where} is open; closing it so {VERSION} opens")
        if not close_other(found[0]):
            print("It didn't close; this copy opens its own window beside it")
    startup_mark("checked for another copy")
    base = app_data_dir()
    crash = last_crash(base)
    resend = None if crash else pending_crash(base)   # an older report Llano hasn't kept yet
    startup_mark("checked the last run")
    global _crash_file
    try:   # a crash inside Python's C code (MIDI, sound, serial) leaves its stack here
        _crash_file = open(base / "crash.log", "w", encoding="utf-8")
        faulthandler.enable(_crash_file, all_threads=True)
    except OSError:
        pass
    mark_running(base)
    app = App(opts, log)
    if resend:
        app.crash = resend
        print(f"Sending Llano the saved crash report (Llano Lights {resend['version']}, started {resend['started']})")
    if crash:
        app.crash = crash
        print(f"The last run (Llano Lights {crash['version']}, started {crash['started']}) never closed: a crash, or "
              "Windows shut down or ended it with the app open; "
              f"what it was doing is saved in crash-report.txt and goes to Llano when linked")
        if not app.notice:
            app.notice = ("Llano Lights didn't close normally last time (a crash, or Windows shut it down). What it was doing is saved" +
                          (" and sent to Llano so it can be fixed." if app.link.linked else " in crash-report.txt."))
    if opts.update_failed and not crash:   # Llano sees where the update died without asking him
        app.crash = update_report(app.update_log, app.update_why)
        print(f"The update didn't finish ({app.update_why or 'no reason in the log'}); "
              "its log goes to Llano when linked")
    startup_mark("app ready")
    app.preview = Preview("", LayoutStore(), app=app)
    app.preview.status = "stopped"
    url = app.preview.url
    print(f"Window server at {url}")
    startup_mark("window server up")
    if opts.ready_file:  # an update just swapped us in: tell the installer we came up
        try:
            Path(opts.ready_file).write_text(VERSION)
        except OSError as e:
            print(f"couldn't confirm the update to the installer: {e}")
    threading.Thread(target=app.startup, daemon=True).start()
    if not opts.no_window:
        close_stale_windows()
    window = None if opts.no_window else open_window(url)
    startup_mark("window opened" if window else "window handed to the browser")
    opened = time.monotonic()
    reopens: collections.deque = collections.deque()
    browser_only = window is None
    try:
        while not app.quit.wait(0.5):
            if opts.no_window:
                continue
            if window is not None and window.poll() is not None:
                if time.monotonic() - opened <= 5:
                    window, browser_only = None, True  # Edge handed off to another copy of itself
                elif app.running in SHOW_MODES:
                    now = time.monotonic()
                    while reopens and now - reopens[0] > REOPEN_WINDOW:
                        reopens.popleft()
                    if len(reopens) >= REOPEN_LIMIT:  # never a stream of windows
                        print("The window keeps closing; not opening it again (the show keeps running)")
                        window, browser_only = None, True
                    else:
                        reopens.append(now)
                        print("The window closed while the show runs; opening it again (Stop, then close, to quit)")
                        window, opened = open_window(url), now
                        browser_only = window is None
                else:
                    print("The window was closed")
                    break
            if browser_only and app.running is None and app.update_state not in ("downloading", "ready") \
                    and time.monotonic() - app.last_request > 120:
                print("No window has asked for two minutes; closing")
                break
    finally:
        swapping = app.update_state == "restarting"
        if swapping and os.environ.get("LLANO_LIGHTS_TEST_STUCK_EXIT") == "1":
            swapping = False   # the Windows update test plays 1.12.1's hang: the swap must close this copy
            threading.Thread(target=threading.Event().wait, name="stuck on close (test)").start()
        if swapping:   # nothing may keep this copy alive while the swap waits for its files
            threading.Thread(target=exit_hard, args=(EXIT_WAIT_S, "the close took too long"),
                             name="exit for the update", daemon=True).start()
        try:
            app.stop()
            if app.runner:
                app.runner.join(timeout=8)
        except Exception as e:  # noqa: BLE001 -- the rest of the close must still run
            print(f"Stopping the show on close failed: {e}")
        try:
            app.preview.close()
        except Exception as e:  # noqa: BLE001
            print(f"Closing the window server failed: {e}")
        try:
            if not opts.no_window and close_app_windows():   # the new version opens its own window
                for _ in range(20):
                    if window is None or window.poll() is not None:
                        break
                    time.sleep(0.1)
            if window is not None and window.poll() is None:
                window.terminate()
        except Exception as e:  # noqa: BLE001
            print(f"Closing the window failed: {e}")
        clear_running(base)
        print("Llano Lights closed")
        if swapping:
            exit_hard(0, "")
    return 0


# Quitting for an update (BL #11612): his 1.12.1 laptop closed its window and never came back,
# several tries. The swap can only move the install once every program running from it has ended,
# and a close can hang (the MIDI driver close of 1.12.4, a thread that never ends), which kept the
# process, its files and the one-copy lock alive. So a copy quitting for an update ends itself
# after the normal close, or after EXIT_WAIT_S if the close hangs.
EXIT_WAIT_S = 6.0


def exit_hard(after_s: float, why: str) -> None:
    if after_s:
        time.sleep(after_s)
        print(f"Ending this copy for the update: {why}")
    try:
        sys.stdout.flush()
    except Exception:   # noqa: BLE001 -- ok: the exit must happen anyway
        pass
    os._exit(0)


def update_report(lines: list, why: str) -> dict:
    """The failed update's log, shaped like a crash report so Llano keeps it (store._keep_crash)."""
    started = next((ln[:19] for ln in lines if " swap started: " in ln), "") or time.strftime("%Y-%m-%d %H:%M:%S")
    return _trimmed(VERSION, started, list(lines), "update didn't finish: " + (why or "no reason in the log"))


def main(argv=None) -> int:
    enable_windows_colors()
    p = argparse.ArgumentParser(prog="Llano Lights")
    p.add_argument("mode", nargs="?", choices=["gui", "menu"] + list(MODES))
    p.add_argument("--seconds", type=float, default=0.0)
    p.add_argument("--bpm", type=float, default=128.0)
    p.add_argument("--song", default="", choices=[""] + [s.id for s in demo_songs.load()],
                   help="demo with a real song (the window plays its sound)")
    p.add_argument("--show", default="", help="with 'show': the saved show's name")
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--no-window", action="store_true", help="window server only (tests)")
    p.add_argument("--updated", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--update-failed", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--ready-file", help=argparse.SUPPRESS)
    opts = p.parse_args(argv)
    opts.no_window = opts.no_window or os.environ.get("LLANO_LIGHTS_NO_WINDOW") == "1"  # survives the update restart
    if opts.mode in (None, "gui"):
        return gui(opts)
    if opts.mode == "menu":
        return menu(opts)
    return MODES[opts.mode][1](opts)


if __name__ == "__main__":
    if len(sys.argv) == 1:   # the window, also from the Start Llano Lights button, whose folder is Edge's
        os.chdir(HERE)
    sys.exit(main())
