"""The Light studio: the live layers a pro desk gives its operator (1.20.0, Llano PM #23195).

The goal, 2026-11-12: a light studio with the power of a high-end lighting desk and the
ease of use a novice needs. This module is its engine half: state, the ONE command list every screen
sends (the laptop window, the phone over Wi-Fi, the phone over the internet), and what each layer
does to a frame.

Five layers, each on top of the one before it, each staying until he lets it go. Nothing here ends
on a timer:

  the show     the lights follow the music (looks.py, unchanged)
  held look    one look that replaces the show: a simple look (steady, slow pulse, color fade,
               soft glow, house lights), a wedding moment, a scene pad or a pad he saved. Rendered
               by looks.py through its overrides; this module only decides which.
  spots        the moving heads leave the look to light a place on the floor he steers
  touch-ups    lights he changed by hand, or pinned for the night
  hits         white-out, strobe and color burst while held; blackout until pressed again

Over all of them: brightness by zone, speed, and how long a change takes (a crossfade). A studio
nobody has touched changes no byte of any frame (tests/gigbar_lights/test_studio_engine.py), so the
classic window and every show play exactly as before.

Spot steering is by PLACE, in meters on the floor plan (venue.py's room frame), never by motor: the
spot is a point that eases toward where he wants it (an arrow key held, a click, the pointer in
hover follow, a saved mark) under one speed and acceleration limit, and each head is aimed at it
through venue.Layout.aim, which carries Line up my lights' calibration. A GigBAR head takes one
8-bit pan and tilt, about 2.1 and 0.7 degrees a step (glide.py), so the beam itself moves in small
steps however smooth the point is.
"""
from __future__ import annotations

import colorsys
import copy
import json
import math
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

from . import moments, show_settings
from . import settings_contract as contract

# --- the looks he can hold -------------------------------------------------------------------

# tags the pads show: still = nothing moves, fade = a slow change, music = rides the beat,
# move = the heads move, quiet = ignores the music
SIMPLE = {
    "steady": {"name": "Steady", "line": "Every light on in one color. Nothing changes until you change it.",
               "tags": ["still", "quiet"], "color": "#ffd9a3"},
    "pulse": {"name": "Slow pulse", "line": "One color that breathes brighter and softer, about every 6 seconds.",
              "tags": ["fade", "quiet"], "color": "#ffb454"},
    "fade": {"name": "Color fade", "line": "Drifts through your show's colors, one soft change every 20 seconds.",
             "tags": ["fade", "quiet"], "color": ""},
    "glow": {"name": "Soft glow", "line": "Only the wash lights, low, in one color. Heads, derby and laser dark.",
             "tags": ["still", "quiet"], "color": "#c78bff"},
    "house": {"name": "House lights", "line": "Everything bright white, to see by: setup, an emergency, cleanup.",
              "tags": ["still", "quiet"], "color": "#ffffff"},
}
SCENE_PADS = {
    "calm": ("Calm", "Soft and slow, the heads sweeping gently.", ["fade", "move", "music"]),
    "party": ("Party", "Full color on the beat. Derby on, no laser.", ["music", "move"]),
    "hype": ("Hype", "Everything on, the drop look all the time.", ["music", "move"]),
    "party-mode": ("Party mode", "Runs itself: a new high-energy look every 8 bars.", ["music", "move"]),
}
MOMENT_TAGS = {"photo": ["still", "quiet"], "toast": ["still", "quiet"], "dinner": ["fade", "move"],
               "cake": ["fade"], "first-dance": ["move", "fade"], "father-daughter": ["move", "fade"],
               "party": ["music", "move"], "reveal": ["music", "move"], "last-dance": ["music", "move"],
               "entrance": ["music", "move"], "spotlight": ["move"], "two-spotlights": ["move"]}
PAGES = (
    ("simple", "Simple", ["simple:steady", "simple:pulse", "simple:fade", "moment:photo", "simple:glow", "simple:house"]),
    ("wedding", "Wedding", ["moment:entrance", "moment:first-dance", "moment:dinner", "moment:toast", "moment:cake",
                            "moment:father-daughter", "moment:last-dance", "moment:reveal"]),
    ("party", "Party", ["scene:calm", "scene:party", "scene:hype", "scene:party-mode", "moment:party"]),
)
MOTIONS = ("", "still", "slow")          # "" = as the look was designed
ZONES = (("main", "Everything"), ("wash", "Color wash (Tetras and bar pars)"), ("sticks", "Freedom Sticks"),
         ("heads", "Moving heads"), ("fx", "Derby, laser, strobe"))
SPEEDS = (0.5, 1.0, 2.0)
FADES = (0.0, 1.0, 3.0, 8.0)
HITS = ("whiteout", "strobe", "burst")
COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")
MAX_PADS, MAX_MARKS, MAX_NAME = 12, 9, 40
MAX_VENUES, MAX_VENUE_NAME = 40, 80   # venues whose places and view are kept; the newest stay
PIN_S = 18 * 3600                     # a pinned light is for tonight: it is let go this long after
# View from (asked 2026-11-13: from behind the lights in the DJ booth it is hard to look out at the
# room and match where they are): which way the room picture and the steering pad face. From the DJ
# booth looking out at the floor is the default; from the floor facing the booth is the other; a
# quarter turn covers an odd venue. Kept per venue (layout) and per kind of screen, because the
# laptop sits in the booth while the phone walks the floor.
VIEW_FROM, SCREENS, VIEW_DEFAULT = ("booth", "floor"), ("laptop", "phone"), {"from": "booth", "turn": 0}
MAX_CMD_BYTES = 600
# The moving heads, one control on every screen (Llano BL #12339, asked 2026-11-14: the
# heads move on their own in the dances, with a way to stop them or take over). Auto: the
# show moves them (only in the dances, looks.py). Stop heads: dark and still until he resumes. Take
# over: Follow someone or a Spotlight pad steers them instead. Back to auto: all of that let go.
SPOT_LOOKS = ("moment:spotlight", "moment:two-spotlights")
HEADS_DO = ("stop", "resume", "auto")

# --- spotlights --------------------------------------------------------------------------------

PACES = {"slow": 0.3, "walk": 0.9, "fast": 2.4}   # meters a second: about 1, 3 and 8 feet
GOAL_SPEED = 2.4            # a click, a mark or the pointer in hover follow travels at up to this
EASE_IN_S, EASE_OUT_S = 0.25, 0.35   # an arrow key held reaches its speed, and stops, this gently
DARK_JUMP_M = 2.0           # a click or mark farther than this goes dark, moves, then appears
DARK_OUT_S, DARK_IN_S = 0.2, 0.35
FIND_S = 3.0                # Find a light blinks this long


def spot_gate_steps() -> float:
    """How many DMX steps a slowly moving spot lets build up before the head moves (glide.py's
    hold-and-move). Small follows closer; the motor steps either way. LLANO_LIGHTS_SPOT_GATE tunes
    it on the rig without a build."""
    try:
        return max(1.0, min(6.0, float(os.environ.get("LLANO_LIGHTS_SPOT_GATE") or 2.0)))
    except ValueError:
        return 2.0


def enabled() -> bool:
    """The Live screen is the front page: on in a test-channel build until the release turns it on
    for everyone (version.STUDIO), LLANO_LIGHTS_STUDIO=1 forces it, =0 is the kill switch that
    brings the classic window back as the front page."""
    env = (os.environ.get("LLANO_LIGHTS_STUDIO") or "").strip().lower()
    if env in ("0", "off", "false", "no"):
        return False
    if env in ("1", "on", "true", "yes"):
        return True
    from . import version
    return bool(getattr(version, "STUDIO", False)) or version.CHANNEL == "test"


def parse_color(text) -> Optional[tuple]:
    """'#rrggbb' -> (r, g, b) 0..1, else None."""
    if not isinstance(text, str) or not COLOR_RE.fullmatch(text):
        return None
    return tuple(int(text[i:i + 2], 16) / 255 for i in (1, 3, 5))


def hue_sat(rgb: tuple) -> tuple:
    h, s, _v = colorsys.rgb_to_hsv(*rgb)
    return h, s


def full(rgb: tuple) -> tuple:
    """The color at full value (a chip's #7a3d00 lights as its bright orange; the level is brightness's job)."""
    m = max(rgb)
    return tuple(c / m for c in rgb) if m > 0 else (1.0, 1.0, 1.0)


def ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


class CommandError(ValueError):
    """A command this studio refuses; the text is for him."""


class Follower:
    """One spot on the floor: a point that eases toward where he wants it."""

    def __init__(self, x: float, y: float):
        self.x, self.y, self.vx, self.vy = x, y, 0.0, 0.0
        self.goal: Optional[tuple] = None      # (x, y) to travel to, or None
        self.cmd = (0.0, 0.0)                  # the arrow keys held, as a direction (not normalized)
        self.k = 1.0                           # the dark jump's dimmer, 0..1
        self._jump: Optional[tuple] = None     # (phase, t0, x, y)

    def step(self, dt: float, pace: float, bounds: tuple, now: float) -> None:
        dt = max(0.0, min(0.1, dt))
        cx, cy = self.cmd
        n = math.hypot(cx, cy)
        if self._jump:
            self._jump_step(now)
            return
        if n > 0:
            self.goal = None
            wx, wy, top = cx / n * pace, cy / n * pace, pace
        elif self.goal is not None:
            dx, dy = self.goal[0] - self.x, self.goal[1] - self.y
            dist = math.hypot(dx, dy)
            if dist < 0.01 and math.hypot(self.vx, self.vy) < 0.05:
                self.x, self.y, self.vx, self.vy, self.goal = self.goal[0], self.goal[1], 0.0, 0.0, None
                return
            top = GOAL_SPEED
            v = min(top, math.sqrt(2.0 * (top / EASE_OUT_S) * dist))   # the speed that still stops on it
            wx, wy = (dx / dist * v, dy / dist * v) if dist > 0 else (0.0, 0.0)
        else:
            wx = wy = 0.0
            top = max(pace, math.hypot(self.vx, self.vy))
        # ease: speeding up over EASE_IN_S, slowing over EASE_OUT_S
        speeding = math.hypot(wx, wy) > math.hypot(self.vx, self.vy)
        a = top / (EASE_IN_S if speeding else EASE_OUT_S)
        dvx, dvy = wx - self.vx, wy - self.vy
        dv = math.hypot(dvx, dvy)
        if dv > a * dt and dv > 0:
            dvx, dvy = dvx / dv * a * dt, dvy / dv * a * dt
        self.vx += dvx
        self.vy += dvy
        self.x += self.vx * dt
        self.y += self.vy * dt
        x0, y0, x1, y1 = bounds
        if not x0 <= self.x <= x1:
            self.x, self.vx = min(x1, max(x0, self.x)), 0.0
        if not y0 <= self.y <= y1:
            self.y, self.vy = min(y1, max(y0, self.y)), 0.0

    def jump(self, x: float, y: float, now: float) -> None:
        """Go dark, move, appear (a long click or mark): no beam sweeps across the room."""
        self._jump, self.goal, self.cmd = ("out", now, x, y), None, (0.0, 0.0)
        self.vx = self.vy = 0.0

    def _jump_step(self, now: float) -> None:
        phase, t0, x, y = self._jump
        if phase == "out":
            self.k = max(0.0, 1.0 - (now - t0) / DARK_OUT_S)
            if self.k <= 0.0:
                travel = min(1.2, 0.35 + 0.1 * math.hypot(x - self.x, y - self.y))   # the heads' glide there
                self.x, self.y, self._jump = x, y, ("move", now + travel, x, y)
        elif phase == "move":
            self.k = 0.0
            if now >= t0:
                self._jump = ("in", now, x, y)
        else:
            self.k = min(1.0, (now - t0) / DARK_IN_S)
            if self.k >= 1.0:
                self._jump = None

    def moving(self) -> bool:
        return bool(self._jump) or self.goal is not None or self.cmd != (0.0, 0.0) or math.hypot(self.vx, self.vy) > 0.01


def light_name(fid: str) -> str:
    kind, n = contract.FIXTURES[fid], re.sub(r"\D", "", fid)
    return {"gigbar": "GigBAR", "tetra": "Tetra", "stick": "Freedom Stick"}[kind] + " " + n


def _newest(by_venue: dict) -> dict:
    """At most MAX_VENUES venues' places or views, keeping the ones written last (a dict keeps the
    order things were added, and a venue written again is moved to the end by its writer)."""
    return dict(list(by_venue.items())[-MAX_VENUES:])


def default_path() -> Path:
    from .venue import default_dir
    return default_dir() / "studio.json"


class Studio:
    """The live layers and their one command list. One per app launch, shared by every run."""

    def __init__(self, path: Optional[Path] = None, live: Optional[bool] = None):
        self.path = Path(path) if path else None
        self.live = enabled() if live is None else live   # the Live screen is in use: its defaults apply
        # One lock for every screen's commands and the 40 Hz render (Show.render takes it per frame).
        self.lock = threading.RLock()
        self.clock = 0.0            # the render loop's clock (Show.render ticks it): what a blink or a dark jump is timed on
        saved = self._load()
        self.pads: list = saved.get("pads", [])                 # looks he saved: {name, look, color, motion}
        self.marks: dict = saved.get("marks", {})               # layout name -> {mark name: [x, y]}
        # A studio that is off (a stable copy before the release, or LLANO_LIGHTS_STUDIO=0) changes no
        # byte of any frame whatever a test build left in the file: its pins and crossfade are held
        # back, unused, and written back as they were (review 2026-11-13: a 3 s fade saved by a test
        # build melted every song change in the classic window, and a pin there could not be seen).
        self._held_back = {} if self.live else {"pins": saved.get("pins", {}), "pinned": saved.get("pinned", {}),
                                                 "fade_s": saved.get("fade_s")}
        self.pins: dict = saved.get("pins", {}) if self.live else {}   # light id -> {color, dim} | {off: True}
        self.pinned: dict = saved.get("pinned", {}) if self.live else {}   # light id -> when he pinned it (epoch s)
        self.views: dict = saved.get("views", {})               # layout name -> {screen: {from, turn}}
        self.venue = ""             # the layout in use when nothing runs (the app says), for marks and views
        self.masters = {z: 1.0 for z, _ in ZONES}
        self.speed = 1.0
        self.fade_s = float(saved.get("fade_s", 3.0)) if self.live else 0.0
        self.reset()
        # set by the show that runs
        self.layout = None
        self.cfg: Optional[dict] = None
        self.night = None           # tonight.Tonight, when the app has one
        self._levels_last: Optional[list] = None
        self._fade: Optional[tuple] = None     # (from levels, t0)
        self._token: Optional[tuple] = None
        self._t_last: Optional[float] = None
        self._frozen: Optional[list] = None
        self._burst_i = 0
        self.rev = 0                # bumps on every accepted command (the screens poll it)

    def reset(self) -> None:
        """A run ended: what he held is over (like a moment at Stop). Brightness, pins, pads and
        marks stay for the next run."""
        self.look: Optional[dict] = None     # {key, color, motion, since}
        self.color = ""                      # a color for whatever plays ("" = as designed)
        self.motion = ""
        self.blackout = False
        self.frozen = False
        self.heads_stop = False              # Stop heads: dark and still until Resume or Back to auto
        self._heads_aim: Optional[list] = None   # where each head pointed when he stopped them
        self.hits: set = set()
        self.touch: dict = {}
        self.find: Optional[tuple] = None    # (light id, until)
        self.spots = {"on": False, "count": 1, "sel": 0, "dim": 1.0, "room": 0.2, "color": 0, "gobo": 0,
                      "pace": "walk", "dark_jump": True, "hover": False}
        self.followers: list = []
        self.undo: list = []
        self._frozen = None

    # --- saved things -----------------------------------------------------------------------

    def _load(self) -> dict:
        if not self.path:
            return {}
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):   # ok: none saved yet, or a hand-broken file = nothing saved
            return {}
        if not isinstance(d, dict):
            return {}
        out = {}
        # Everything read back is checked the way a command is: the file is his to open, and what
        # it holds reaches the render loop and every screen's page.
        pads = [p for p in d.get("pads") or [] if isinstance(p, dict) and isinstance(p.get("name"), str)
                and ":" not in p["name"] and self.known_look(str(p.get("look") or ""))]
        out["pads"] = [{"name": p["name"][:MAX_NAME], "look": p["look"],
                        "color": p["color"].lower() if parse_color(p.get("color")) else "",
                        "motion": p.get("motion") if p.get("motion") in MOTIONS else ""} for p in pads[:MAX_PADS]]
        marks = {}
        for lay, ms in list((d.get("marks") or {}).items())[:MAX_VENUES]:
            if isinstance(ms, dict):
                good = {str(n)[:MAX_NAME]: [float(v[0]), float(v[1])] for n, v in ms.items()
                        if isinstance(v, list) and len(v) == 2
                        and all(isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c) and abs(c) < 1000 for c in v)}
                marks[str(lay)[:MAX_VENUE_NAME]] = dict(list(good.items())[:MAX_MARKS])
        out["marks"] = marks
        pinned = d.get("pinned") if isinstance(d.get("pinned"), dict) else {}
        pins, when = {}, {}
        for k, v in (d.get("pins") or {}).items():
            st = self._clean_setting(v) if str(k) in contract.FIXTURES else None
            at = pinned.get(k)
            # a pin is for tonight: one from an earlier night is let go, not carried into the next gig
            if st is not None and isinstance(at, (int, float)) and not isinstance(at, bool) and 0 <= time.time() - at < PIN_S:
                pins[str(k)], when[str(k)] = st, float(at)
        out["pins"], out["pinned"] = pins, when
        views = {}
        for lay, by in list((d.get("views") or {}).items())[:MAX_VENUES]:
            if isinstance(by, dict):
                good = {sc: {"from": v["from"], "turn": v["turn"]} for sc, v in by.items()
                        if sc in SCREENS and isinstance(v, dict) and v.get("from") in VIEW_FROM and not isinstance(v.get("turn"), bool) and v.get("turn") in (0, 1, 2, 3)}
                if good:
                    views[str(lay)[:MAX_VENUE_NAME]] = good
        out["views"] = views
        if isinstance(d.get("fade_s"), (int, float)) and 0 <= d["fade_s"] <= 30:
            out["fade_s"] = float(d["fade_s"])
        return out

    def _save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            hb = self._held_back   # a studio that is off writes back the pins and fade it never used
            doc = {"pads": self.pads, "marks": _newest(self.marks), "views": _newest(self.views),
                   "pins": self.pins if self.live else hb.get("pins") or {},
                   "pinned": self.pinned if self.live else hb.get("pinned") or {},
                   "fade_s": self.fade_s if self.live or hb.get("fade_s") is None else hb["fade_s"]}
            tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as e:   # ok: the night goes on with what is in memory; the log says why
            print(f"Light studio: couldn't save pads, marks and pins ({e})")

    # --- the catalog the screens draw ---------------------------------------------------------

    @staticmethod
    def known_look(key: str) -> bool:
        kind, _, name = key.partition(":")
        return (kind == "simple" and name in SIMPLE) or (kind == "moment" and name in moments.KEYS) \
            or (kind == "scene" and name in SCENE_PADS)

    @staticmethod
    def describe(key: str) -> dict:
        kind, _, name = key.partition(":")
        if kind == "simple":
            s = SIMPLE[name]
            return {"key": key, "name": s["name"], "line": s["line"], "tags": s["tags"], "color": s["color"]}
        if kind == "scene":
            n, line, tags = SCENE_PADS[name]
            return {"key": key, "name": n, "line": line, "tags": tags, "color": ""}
        m = next(m for m in moments.MOMENTS if m["key"] == name)
        pal = m["style"]["palettes"][moments.PAL][0]
        rgb = colorsys.hsv_to_rgb(pal[0] % 1.0, 0.75, 1.0)
        return {"key": key, "name": m["name"], "line": m["note"], "tags": MOMENT_TAGS.get(name, []),
                "color": "#%02x%02x%02x" % tuple(round(c * 255) for c in rgb)}

    def catalog(self) -> dict:
        pages = [{"key": k, "name": n, "pads": [self.describe(p) for p in pads]} for k, n, pads in PAGES]
        mine = []
        for p in self.pads:
            d = self.describe(p["look"])
            mine.append({**d, "key": "mine:" + p["name"], "name": p["name"], "line": f"Your saved look, from {d['name']}.",
                         "color": p["color"] or d["color"], "mine": True})
        pages.append({"key": "mine", "name": "Mine", "pads": mine})
        return {"pages": pages, "zones": [{"key": z, "name": n} for z, n in ZONES], "speeds": list(SPEEDS),
                "fades": list(FADES), "motions": list(MOTIONS), "paces": list(PACES), "hits": list(HITS),
                "lights": [{"id": fid, "name": light_name(fid)} for fid in contract.FIXTURES]}

    # --- what the screens show ----------------------------------------------------------------

    def public(self, now: Optional[float] = None) -> dict:
        with self.lock:   # a screen's poll never reads half of a command
            look = None
            if self.look:
                d = self._describe_held(self.look["key"])
                look = {"key": self.look["key"], "name": d["name"], "line": d["line"], "tags": d["tags"],
                        "since": self.look["since"], "night": bool(self.look.get("night"))}
            return {"rev": self.rev, "live": self.live, "look": look, "color": self.color, "motion": self.motion,
                    "blackout": self.blackout, "frozen": self.frozen, "hits": sorted(self.hits),
                    "masters": {k: round(v, 3) for k, v in self.masters.items()}, "speed": self.speed,
                    "fade_s": self.fade_s, "spots": self.stage(), "heads": self.heads_mode(),
                    "touch": dict(self.touch), "pins": dict(self.pins), "can_undo": bool(self.undo),
                    "night": self.night.public() if self.night is not None else None}

    def stage(self) -> dict:
        """The spots as the stage picture draws them: where each is (meters on the floor plan),
        which he steers, the places he saved, and whether they can be trusted to land there."""
        with self.lock:
            return {**self.spots, "ready": self.spots_ready(), "why": self.spots_why(),
                    "at": [[round(f.x, 3), round(f.y, 3)] for f in self.followers],
                    "going": [[round(f.goal[0], 3), round(f.goal[1], 3)] if f.goal else None for f in self.followers],
                    "dark": [f.k < 0.99 for f in self.followers],
                    "marks": [{"name": n, "x": v[0], "y": v[1]} for n, v in self._marks().items()],
                    "size": list(self.layout.room[:2]) if self.layout is not None else None,   # the room, in meters
                    "layout": self._venue(),
                    "views": {sc: dict(self.views.get(self._venue(), {}).get(sc) or VIEW_DEFAULT) for sc in SCREENS},
                    "plan": self._plan()}

    def _plan(self, lay=None) -> Optional[dict]:
        """The floor plan a phone draws to steer on (it has no room picture of its own): the room,
        the dance floor, the booth and where the GigBARs stand, in meters."""
        lay = self.layout if lay is None else lay
        if lay is None:
            return None
        try:
            rect = lambda r: [round(v, 2) for v in (r.x, r.y, r.w, r.d)]   # noqa: E731
            return {"room": [round(v, 2) for v in lay.room[:2]], "floor": rect(lay.floor), "booth": rect(lay.booth),
                    "bars": [[round(lay.spots[b].x, 2), round(lay.spots[b].y, 2)] for b in ("bar1", "bar2")
                             if b in lay.spots and not lay.spots[b].out]}
        except Exception:  # noqa: BLE001 -- ok: a layout that can't say draws no plan; steering by marks still works
            return None

    def _describe_held(self, key: str) -> dict:
        if key.startswith("mine:"):
            pad = next((p for p in self.pads if p["name"] == key[5:]), None)
            if pad:
                return {**self.describe(pad["look"]), "name": pad["name"]}
            return {"name": key[5:], "line": "", "tags": []}
        return self.describe(key)

    # --- commands -----------------------------------------------------------------------------

    def command(self, cmd: dict, now: Optional[float] = None) -> dict:
        """Apply one command from any screen. Raises CommandError with words for him."""
        if not isinstance(cmd, dict):
            raise CommandError("not a command")
        op = str(cmd.get("op") or "")
        fn = getattr(self, "_op_" + op, None) if re.fullmatch(r"[a-z][a-z_]{1,20}", op) else None
        if fn is None:
            raise CommandError("the lights don't know that button; update Llano Lights")
        with self.lock:
            out = fn(cmd, time.time() if now is None else now) or {}
            self.rev += 1
        return out

    def _remember(self) -> None:
        self.undo.append({"look": copy.deepcopy(self.look), "color": self.color, "motion": self.motion,
                          "blackout": self.blackout, "frozen": self.frozen})
        del self.undo[:-20]

    def _resolve(self, key: str) -> tuple:
        """(the look to play, color, motion) for a pad key; a saved pad carries its own color and motion."""
        if key.startswith("mine:"):
            pad = next((p for p in self.pads if p["name"] == key[5:]), None)
            if pad is None:
                raise CommandError("that saved look is gone")
            return pad["look"], pad["color"], pad["motion"]
        if not self.known_look(key):
            raise CommandError("no such look")
        return key, None, None

    def _op_look(self, cmd: dict, now: float) -> None:
        key = str(cmd.get("key") or "")
        base, color, motion = self._resolve(key)
        self._remember()
        self.look = {"key": key, "since": now}
        if base in SPOT_LOOKS:   # a Spotlight pad is taking the heads over: they light again
            self.heads_stop, self._heads_aim = False, None
        if color is not None:
            self.color, self.motion = color, motion
        self.blackout = False
        self.frozen, self._frozen = False, None

    def _op_release(self, cmd: dict, now: float) -> None:
        if self.look or self.frozen:
            self._remember()
        self.look, self.frozen, self._frozen = None, False, None

    def _op_color(self, cmd: dict, now: float) -> None:
        c = cmd.get("color") or ""
        if c and parse_color(c) is None:
            raise CommandError("a color looks like #ff8800")
        self._remember()
        self.color = c.lower() if c else ""

    def _op_motion(self, cmd: dict, now: float) -> None:
        m = cmd.get("motion") or ""
        if m not in MOTIONS:
            raise CommandError("motion is still, slow or as designed")
        self._remember()
        self.motion = m

    def _op_hit(self, cmd: dict, now: float) -> None:
        name = cmd.get("name")
        if name not in HITS:
            raise CommandError("no such button")
        if cmd.get("on") is True:
            if name == "burst" and name not in self.hits:
                self._burst_i += 1
            self.hits.add(name)
        else:
            self.hits.discard(name)

    def _op_blackout(self, cmd: dict, now: float) -> None:
        self._remember()
        self.blackout = (not self.blackout) if cmd.get("on") is None else cmd.get("on") is True

    def _op_freeze(self, cmd: dict, now: float) -> None:
        self._remember()
        self.frozen = (not self.frozen) if cmd.get("on") is None else cmd.get("on") is True
        self._frozen = None

    def _op_master(self, cmd: dict, now: float) -> None:
        zone = cmd.get("zone")
        if not isinstance(zone, str) or zone not in self.masters:
            raise CommandError("no such brightness")
        self.masters[zone] = self._unit(cmd.get("value"))

    def _op_speed(self, cmd: dict, now: float) -> None:
        v = cmd.get("value")
        if v not in SPEEDS:
            raise CommandError("speed is half, normal or double")
        self.speed = float(v)

    def _op_fade(self, cmd: dict, now: float) -> None:
        v = cmd.get("seconds")
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= 30:
            raise CommandError("a change takes 0 to 30 seconds")
        self.fade_s = float(v)
        self._save()

    def _op_undo(self, cmd: dict, now: float) -> None:
        if not self.undo:
            raise CommandError("nothing to undo")
        was = self.undo.pop()
        self.look, self.color, self.motion = was["look"], was["color"], was["motion"]
        self.blackout, self.frozen, self._frozen = was["blackout"], was["frozen"], None

    @staticmethod
    def _unit(v) -> float:
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not -1e9 < v < 1e9:   # (NaN fails it too)
            raise CommandError("that needs a number from 0 to 1")
        return max(0.0, min(1.0, float(v)))

    @staticmethod
    def _clean_setting(v) -> Optional[dict]:
        """A touched or pinned light's setting as read back from the file, or None if it is not one."""
        if not isinstance(v, dict):
            return None
        out = {"color": v["color"].lower() if parse_color(v.get("color")) else "#ffffff"}
        dim = v.get("dim", 1.0)
        if not isinstance(dim, (int, float)) or isinstance(dim, bool) or not 0 <= dim <= 1:
            return None
        out["dim"] = float(dim)
        if v.get("off") is True:
            out["off"] = True
        return out

    # saved pads
    def _op_pad_save(self, cmd: dict, now: float) -> None:
        name = " ".join(str(cmd.get("name") or "").split())[:MAX_NAME]
        if not name or ":" in name:
            raise CommandError("give the look a name")
        if not self.look:
            raise CommandError("hold a look first, then save it")
        base, _, _ = self._resolve(self.look["key"])
        pad = {"name": name, "look": base, "color": self.color, "motion": self.motion}
        same = next((i for i, p in enumerate(self.pads) if p["name"].casefold() == name.casefold()), None)
        if same is None and len(self.pads) >= MAX_PADS:
            raise CommandError(f"up to {MAX_PADS} saved looks: delete one first")
        if same is None:
            self.pads.append(pad)
        else:
            self.pads[same] = pad
        self._save()

    def _op_pad_del(self, cmd: dict, now: float) -> None:
        name = str(cmd.get("name") or "")
        self.pads = [p for p in self.pads if p["name"] != name]
        if self.look and self.look["key"] == "mine:" + name:
            self.look = None
        self._save()

    # spotlights
    def spots_ready(self) -> bool:
        return self.layout is not None and self.spots_why() == ""

    def spots_why(self) -> str:
        """Why the spots can't be trusted to land where the picture shows ("" = they can)."""
        if self.layout is None:
            return "Start the lights first."
        try:
            bad = [f"GigBAR {b} head {m + 1}" for b in (1, 2) for m in (0, 1)
                   if f"bar{b}" in self.layout.spots and not self.layout.spots[f"bar{b}"].out
                   and self.layout.cal(b, m) is None]
        except Exception:  # noqa: BLE001 -- a layout that can't say is treated as not lined up
            bad = ["the moving heads"]
        return ("Not lined up at this venue yet (" + ", ".join(bad) + "): the spot follows the picture's best guess. "
                "Run Line up my lights so it lands where you point.") if bad else ""

    def _bounds(self) -> tuple:
        """Where a spot may go: the venue's head-limits box when it has one (PM #23796), else the room."""
        lim = getattr(self.layout, "limits", None) if self.layout is not None else None
        if lim is not None:
            return lim.x, lim.y, lim.x + lim.w, lim.y + lim.d
        w, d = (self.layout.room[0], self.layout.room[1]) if self.layout is not None else (8.0, 8.0)
        return 0.0, 0.0, w, d

    def _venue(self) -> str:
        return str(self.layout.name if self.layout is not None else self.venue)[:MAX_VENUE_NAME]

    def _marks(self) -> dict:
        return self.marks.get(self._venue(), {})

    def _op_view(self, cmd: dict, now: float) -> None:
        """Which way this kind of screen looks at the room, at this venue."""
        screen = cmd.get("screen")
        if screen not in SCREENS:
            raise CommandError("which screen: the laptop or the phone")
        by = dict(self.views.get(self._venue(), {}))
        view = dict(by.get(screen) or VIEW_DEFAULT)
        if "from" in cmd:
            if cmd["from"] not in VIEW_FROM:
                raise CommandError("view from the DJ booth, or from the floor")
            view["from"], view["turn"] = cmd["from"], 0
        if "turn" in cmd:
            if isinstance(cmd["turn"], bool) or cmd["turn"] not in (0, 1, 2, 3):
                raise CommandError("a quarter turn at a time")
            view["turn"] = cmd["turn"]
        by[screen] = view
        self.views.pop(self._venue(), None)   # written last = kept longest (_newest)
        self.views[self._venue()] = by
        self._save()

    def _start_followers(self) -> None:
        if self.layout is not None:
            fl = self.layout.floor
            cx, cy, off = fl.cx, fl.cy, fl.w / 4
        else:
            cx, cy, off = 4.0, 4.0, 1.0
        self.followers = [Follower(cx, cy)] if self.spots["count"] == 1 else [Follower(cx - off, cy), Follower(cx + off, cy)]

    def _op_spots(self, cmd: dict, now: float) -> None:
        sp = self.spots
        whole = lambda v: isinstance(v, int) and not isinstance(v, bool)   # noqa: E731
        # every field is checked before any is changed: a refused command changes nothing
        if "count" in cmd and not (whole(cmd["count"]) and cmd["count"] in (1, 2)):
            raise CommandError("one spot or two")
        for k in ("dim", "room"):
            if k in cmd:
                self._unit(cmd[k])
        for k in ("color", "gobo"):
            if k in cmd and not (whole(cmd[k]) and 0 <= cmd[k] <= 7):
                raise CommandError(f"{k} is 0 to 7")
        if "pace" in cmd and not (isinstance(cmd["pace"], str) and cmd["pace"] in PACES):
            raise CommandError("steering speed is slow, walk or fast")
        if "sel" in cmd:
            count = cmd.get("count", sp["count"])
            if not (whole(cmd["sel"]) and cmd["sel"] in (0, 1, 2)) or (cmd["sel"] and count == 1):
                raise CommandError("pick spot A, spot B or both")
        if "count" in cmd:
            if cmd["count"] != sp["count"]:
                keep = [(f.x, f.y) for f in self.followers]
                sp["count"], sp["sel"] = cmd["count"], 0
                self._start_followers()
                if keep:   # the first spot stays where it was
                    self.followers[0].x, self.followers[0].y = keep[0]
        on = cmd.get("on")
        if on is True:   # Follow someone is taking the heads over: they light again
            self.heads_stop, self._heads_aim = False, None
        if on is True and not sp["on"]:
            sp["on"] = True
            if len(self.followers) != sp["count"]:
                self._start_followers()
        elif on is False:
            sp["on"], sp["hover"] = False, False
            for f in self.followers:
                f.cmd, f.goal = (0.0, 0.0), None
        for k in ("dim", "room"):
            if k in cmd:
                sp[k] = self._unit(cmd[k])
        for k in ("color", "gobo"):
            if k in cmd:
                sp[k] = cmd[k]
        if "pace" in cmd:
            sp["pace"] = cmd["pace"]
        if "dark_jump" in cmd:
            sp["dark_jump"] = cmd["dark_jump"] is True
        if "hover" in cmd:
            sp["hover"] = cmd["hover"] is True and sp["on"]
            if not sp["hover"]:
                for f in self._selected():   # hover off: the spot holds where it is
                    f.goal = None
        if "sel" in cmd:
            sp["sel"] = cmd["sel"]

    def _selected(self) -> list:
        if not self.followers:
            return []
        if len(self.followers) == 1 or self.spots["sel"] == 0:
            return [self.followers[0]]
        return [self.followers[1]] if self.spots["sel"] == 1 else list(self.followers)

    def _need_spots(self) -> None:
        if not self.spots["on"] or not self.followers:
            raise CommandError("turn the spots on first")

    def _op_spot_key(self, cmd: dict, now: float) -> None:
        """The arrow keys held: a direction (dx, dy each -1, 0 or 1; y grows toward the back of the room)."""
        self._need_spots()
        try:
            dx, dy = float(cmd.get("dx") or 0), float(cmd.get("dy") or 0)
        except (TypeError, ValueError, OverflowError):
            raise CommandError("a direction is left, right, up or down") from None
        if not (math.isfinite(dx) and math.isfinite(dy)):
            raise CommandError("a direction is left, right, up or down")
        d = (max(-1.0, min(1.0, dx)), max(-1.0, min(1.0, dy)))
        if isinstance(cmd.get("pace"), str) and cmd["pace"] in PACES:
            self.spots["pace"] = cmd["pace"]
        for f in self._selected():
            f.cmd = d

    def _op_spot_hold(self, cmd: dict, now: float) -> None:
        """Stop where it is (the pointer left the stage in hover follow, a finger lifted): the spot
        eases to a stop instead of finishing its trip."""
        for f in self._selected():
            f.goal, f.cmd = None, (0.0, 0.0)

    def _point(self, cmd: dict) -> tuple:
        try:
            x, y = float(cmd["x"]), float(cmd["y"])
        except (KeyError, TypeError, ValueError, OverflowError):
            raise CommandError("a place on the floor needs x and y") from None
        if not (math.isfinite(x) and math.isfinite(y)):
            raise CommandError("a place on the floor needs x and y")
        x0, y0, x1, y1 = self._bounds()
        return min(x1, max(x0, x)), min(y1, max(y0, y))

    def _op_spot_goal(self, cmd: dict, now: float) -> None:
        """A click, a drag or the pointer in hover follow: send the selected spot to a place.
        `hover` moves only while hover follow is on; `drag` (a finger held down) never goes dark."""
        self._need_spots()
        x, y = self._point(cmd)
        if cmd.get("hover") is True and not self.spots["hover"]:
            return
        direct = cmd.get("hover") is True or cmd.get("drag") is True
        self._send(x, y, now, direct)

    def _send(self, x: float, y: float, now: float, direct: bool) -> None:
        sel = self._selected()
        both = len(sel) == 2
        for i, f in enumerate(sel):
            tx = x
            if both and i == 1 and self.layout is not None:   # both: the second spot mirrors across the floor
                tx = 2 * self.layout.floor.cx - x
                x0, _, x1, _ = self._bounds()
                tx = min(x1, max(x0, tx))
            far = math.hypot(tx - f.x, y - f.y) > DARK_JUMP_M
            if far and self.spots["dark_jump"] and not direct:
                f.jump(tx, y, self.clock)
            elif not f._jump:
                f.goal, f.cmd = (tx, y), (0.0, 0.0)

    def _op_mark_save(self, cmd: dict, now: float) -> None:
        self._need_spots()
        name = " ".join(str(cmd.get("name") or "").split())[:MAX_NAME]
        if not name:
            raise CommandError("give the place a name, like Cake table")
        lay = self._venue()
        marks = dict(self.marks.get(lay, {}))
        if name not in marks and len(marks) >= MAX_MARKS:
            raise CommandError(f"up to {MAX_MARKS} places: delete one first")
        f = self._selected()[0]
        marks[name] = [round(f.x, 3), round(f.y, 3)]
        self.marks.pop(lay, None)   # written last = kept longest (_newest)
        self.marks[lay] = marks
        self._save()

    def _op_mark_go(self, cmd: dict, now: float) -> None:
        self._need_spots()
        m = self._marks().get(str(cmd.get("name") or ""))
        if m is None:
            raise CommandError("that place is gone")
        self._send(m[0], m[1], now, direct=False)

    def _op_mark_del(self, cmd: dict, now: float) -> None:
        lay = self._venue()
        marks = dict(self.marks.get(lay, {}))
        marks.pop(str(cmd.get("name") or ""), None)
        self.marks[lay] = marks
        self._save()

    # hands on one light
    def _light(self, cmd: dict) -> str:
        fid = str(cmd.get("id") or "")
        if fid not in contract.FIXTURES:
            raise CommandError("pick a light")
        return fid

    def _setting(self, cmd: dict, was: Optional[dict]) -> dict:
        st = dict(was or {"color": "#ffffff", "dim": 1.0})
        if "color" in cmd:
            if parse_color(cmd["color"]) is None:
                raise CommandError("a color looks like #ff8800")
            st["color"] = cmd["color"].lower()
            st.pop("off", None)
        if "dim" in cmd:
            st["dim"] = self._unit(cmd["dim"])
            st.pop("off", None)
        if "off" in cmd:
            if cmd["off"] is True:
                st["off"] = True
            else:
                st.pop("off", None)
        return st

    def _op_touch(self, cmd: dict, now: float) -> None:
        fid = self._light(cmd)
        self.touch[fid] = self._setting(cmd, self.touch.get(fid))

    def _op_give_back(self, cmd: dict, now: float) -> None:
        if cmd.get("id"):
            self.touch.pop(self._light(cmd), None)
        else:
            self.touch.clear()

    def _op_pin(self, cmd: dict, now: float) -> None:
        fid = self._light(cmd)
        self.pins[fid] = self._setting(cmd, self.pins.get(fid) or self.touch.get(fid))
        self.pinned.setdefault(fid, time.time())   # for tonight: let go by itself PIN_S later
        self.touch.pop(fid, None)
        self._save()

    def _op_unpin(self, cmd: dict, now: float) -> None:
        fid = self._light(cmd)
        self.pins.pop(fid, None)
        self.pinned.pop(fid, None)
        self._save()

    def _op_find(self, cmd: dict, now: float) -> None:
        # timed from the first frame that draws it: with nothing running the clock here is stale,
        # and the blink would be over before the lights it starts had sent a frame
        self.find = (self._light(cmd), None)

    # the night
    def _op_heads(self, cmd: dict, now: float) -> None:
        """The moving heads' one control: {"do": "stop" | "resume" | "auto"}."""
        do = cmd.get("do")
        if do not in HEADS_DO:
            raise CommandError("the heads can stop, resume or go back to auto")
        if do == "stop":
            self.heads_stop, self._heads_aim = True, None
            return
        self.heads_stop, self._heads_aim = False, None
        if do == "auto":   # let go of every way he took them over
            self._op_spots({"on": False}, now)
            if self.look and self._resolve_quiet(self.look["key"])[0] in SPOT_LOOKS:
                self._remember()
                self.look = None

    def heads_mode(self) -> dict:
        """What the moving heads are doing, for the screens: "stop", "yours" (Follow someone or a
        Spotlight pad steers them) or "auto" (the show moves them, only in the dances)."""
        if self.heads_stop:
            return {"mode": "stop", "line": "Stopped: dark and still until you resume them."}
        if self.spotting():
            return {"mode": "yours", "line": "Yours: following the spot you steer."}
        if self.look and self._resolve_quiet(self.look["key"])[0] in SPOT_LOOKS:
            return {"mode": "yours", "line": "Yours: the Spotlight pad is moving them."}
        return {"mode": "auto", "line": "Auto: they move by themselves in the dances, gently in the first and parent dances."}

    def _op_next(self, cmd: dict, now: float) -> None:
        self._night().next(self, now)

    def _op_mood(self, cmd: dict, now: float) -> dict:
        """Cocktail hour's or dinner's mood, changed on the Live screen (BL #12340): {"part", "mood"}."""
        return {"mood": self._night().set_mood(str(cmd.get("part") or ""), cmd.get("mood"))}

    def _op_goto(self, cmd: dict, now: float) -> None:
        i = cmd.get("i")
        if not isinstance(i, int) or isinstance(i, bool):
            raise CommandError("pick a step of the night")
        self._night().goto(self, i, now)

    def _op_follow_music(self, cmd: dict, now: float) -> None:
        """Back to wherever Mixxx is in the night (after Next ran ahead of it)."""
        self._night().follow(self)

    def _night(self):
        if self.night is None:
            raise CommandError("no night is loaded")
        return self.night

    # --- what looks.py should play --------------------------------------------------------------

    def held(self) -> tuple:
        """(kind, name, color rgb or None, motion) of the held look, or (None, ...) for the show."""
        rgb = parse_color(self.color) if self.color else None
        if not self.look:
            return None, "", rgb, self.motion
        base, _, _ = self._resolve_quiet(self.look["key"])
        kind, _, name = base.partition(":")
        return kind, name, rgb, self.motion

    def _resolve_quiet(self, key: str) -> tuple:
        try:
            return self._resolve(key)
        except CommandError:   # a saved pad deleted while held: the show comes back
            self.look = None
            return ":", None, None

    def style_for(self, name: str, base_cfg: Optional[dict] = None) -> dict:
        """A wedding moment as the style to play, with his motion and speed applied."""
        st = copy.deepcopy(moments.style(name))
        for sec in st["sections"].values():
            mv = sec["move"]
            if self.motion == "still":
                mv["shape"] = "hold"
                sec.update(pulse=0.0, strobe=0.0, derby=False, laser=False)
            elif self.motion == "slow":
                mv["beats"] = min(64, mv["beats"] * 2)
                sec["pulse"] = sec["pulse"] * 0.4
            if self.speed != 1.0 and self.motion != "still":
                mv["beats"] = int(max(1, min(64, round(mv["beats"] / self.speed))))
                if sec["color_bars"]:
                    sec["color_bars"] = int(max(1, min(32, round(sec["color_bars"] / self.speed))))
        return contract.normalize_style(st)

    # --- the frame --------------------------------------------------------------------------------

    def idle(self) -> bool:
        """Nothing of the studio is on: the frame is the show's own, byte for byte."""
        return (not self.look and not self.color and not self.motion and not self.blackout and not self.frozen
                and not self.heads_stop
                and not self.hits and not self.touch and not self.pins and not self.find
                and not self.spots["on"] and self.speed == 1.0 and self.fade_s <= 0
                and all(v >= 1.0 for v in self.masters.values()) and self._fade is None)

    def token(self, showing: str = "") -> tuple:
        """What a crossfade watches: a change here melts instead of jumping."""
        lk = self.look["key"] if self.look else ""
        return (lk, self.color, self.motion, self.blackout, showing if self.fade_s > 0 else "")

    def post(self, rig, now: float, showing: str = "", mode: str = "") -> None:
        """Everything above the look, on the frame looks.py just made: freeze, the crossfade, spots,
        touch-ups and pins, brightness by zone, the buttons he holds, Find a light."""
        dt = 0.025 if self._t_last is None or now - self._t_last > 0.5 else max(0.0, now - self._t_last)
        self._t_last = now
        if self.frozen:
            if self._frozen is None:
                self._frozen = _snapshot(rig)
            _restore(rig, self._frozen)
        self._crossfade(rig, now, showing)
        dark = self.blackout
        if self.spots["on"] and self.followers:
            self._spots(rig, now, dt, dark)
        if self.heads_stop:
            self._stop_heads(rig)
        if not dark:
            self._hands(rig, self.touch)
            self._hands(rig, self.pins)
        self._zones(rig)
        if not dark:
            self._hits(rig)
            self._find(rig, now)

    def _crossfade(self, rig, now: float, showing: str) -> None:
        levels = _levels(rig)
        tok = self.token(showing)
        if self._token is None:
            self._token = tok
        elif tok != self._token:
            self._token = tok
            if self.blackout:   # dark is at once, the whole room together; coming back fades in
                self._fade = None
            elif self.fade_s > 0 and self._levels_last is not None and len(self._levels_last) == len(levels):
                self._fade = (self._levels_last, now)
        if self._fade is not None:
            src, t0 = self._fade
            k = 1.0 if self.fade_s <= 0 else (now - t0) / self.fade_s
            if k >= 1.0 or len(src) != len(levels):
                self._fade = None
            else:
                k = ease(k)
                levels = [a + (b - a) * k for a, b in zip(src, levels)]
                _set_levels(rig, levels)
        self._levels_last = levels

    def _spots(self, rig, now: float, dt: float, dark: bool) -> None:
        sp = self.spots
        pace = PACES[sp["pace"]]
        bounds = self._bounds()
        for f in self.followers:
            f.step(dt, pace, bounds, now)
        heads = [(b, m, head) for b, bar in enumerate(rig.bars) for m, head in enumerate(bar.movers)]
        two = len(self.followers) == 2
        for i, (b, m, head) in enumerate(heads):
            # one spot: every head; two: one per GigBAR (with a single bar, one head each)
            f = self.followers[(b if len(rig.bars) > 1 else m) % 2] if two else self.followers[0]
            if self.layout is not None:
                try:
                    h = self.layout.heads(b + 1)[m]
                    head.pan, head.tilt = self.layout.aim(b + 1, h, self.layout.spot_target(f.x, f.y, h), m)
                except Exception:  # noqa: BLE001 -- ok: a layout that can't aim leaves the head where the look put it
                    pass
            head.dim = 0.0 if dark else sp["dim"] * f.k * self.masters["main"]
            head.strobe, head.color, head.gobo = 0.0, sp["color"], sp["gobo"]
        room = sp["room"]
        for fx in (*rig.tetras, *rig.sticks):
            fx.dim *= room
        for bar in rig.bars:
            for p in bar.pars:
                p.dim *= room
            bar.strobe_white *= room
            bar.strobe_uv *= room
            if room < 0.5:   # the room steps back: no derby or laser across the spot
                bar.laser, bar.laser_strobe, bar.laser_rotate = "off", 0.0, 0.0
                for d in bar.derbies:
                    d.color, d.rotate, d.strobe = "off", 0.0, 0.0

    def _stop_heads(self, rig) -> None:
        """Stop heads: every moving head dark, held where it pointed when he pressed it."""
        heads = [m for bar in rig.bars for m in bar.movers]
        if self._heads_aim is None or len(self._heads_aim) != len(heads):
            self._heads_aim = [(m.pan, m.tilt) for m in heads]
        for m, (pan, tilt) in zip(heads, self._heads_aim):
            m.pan, m.tilt, m.dim, m.strobe = pan, tilt, 0.0, 0.0

    def spotting(self) -> bool:
        return bool(self.spots["on"] and self.followers)

    @staticmethod
    def _fixture(rig, fid: str):
        kind = contract.FIXTURES[fid]
        n = int(re.sub(r"\D", "", fid)) - 1
        group = rig.bars if kind == "gigbar" else rig.tetras if kind == "tetra" else rig.sticks
        return (kind, group[n]) if n < len(group) else (kind, None)

    def _hands(self, rig, table: dict) -> None:
        for fid, st in table.items():
            kind, fx = self._fixture(rig, fid)
            if fx is None:
                continue
            off = st.get("off") is True
            r, g, b = full(parse_color(st.get("color") or "") or (1.0, 1.0, 1.0))
            dim = 0.0 if off else float(st.get("dim", 1.0))
            targets = fx.pars if kind == "gigbar" else [fx]
            for t in targets:
                t.red, t.green, t.blue, t.dim, t.strobe = r, g, b, dim, 0.0
                if kind == "tetra":
                    t.amber = 0.0
                if kind == "gigbar":
                    t.uv = 0.0

    def _zones(self, rig) -> None:
        m = self.masters
        if m["wash"] < 1.0:
            for t in rig.tetras:
                t.dim *= m["wash"]
            for bar in rig.bars:
                for p in bar.pars:
                    p.dim *= m["wash"]
        if m["sticks"] < 1.0:
            for s in rig.sticks:
                s.dim *= m["sticks"]
        if m["heads"] < 1.0 and not self.spotting():   # a spot has its own brightness
            for bar in rig.bars:
                for h in bar.movers:
                    h.dim *= m["heads"]
        if m["fx"] < 1.0:
            for bar in rig.bars:
                bar.strobe_white *= m["fx"]
                bar.strobe_uv *= m["fx"]
                if m["fx"] <= 0.05:   # derbies and the laser have no dimmer: off is off
                    bar.laser, bar.laser_strobe, bar.laser_rotate, bar.strobe_program = "off", 0.0, 0.0, 0
                    for d in bar.derbies:
                        d.color, d.rotate, d.strobe = "off", 0.0, 0.0
        if m["main"] < 1.0:
            for fx in (*rig.tetras, *rig.sticks):
                fx.dim *= m["main"]
            for bar in rig.bars:
                for p in bar.pars:
                    p.dim *= m["main"]
                if not self.spotting():
                    for h in bar.movers:
                        h.dim *= m["main"]
                bar.strobe_white *= m["main"]
                bar.strobe_uv *= m["main"]
                if m["main"] <= 0.05:
                    bar.laser, bar.laser_strobe, bar.laser_rotate, bar.strobe_program = "off", 0.0, 0.0, 0
                    for d in bar.derbies:
                        d.color, d.rotate, d.strobe = "off", 0.0, 0.0

    def _hits(self, rig) -> None:
        main = self.masters["main"]
        if "burst" in self.hits:
            hues = self._burst_hues()
            r, g, b = colorsys.hsv_to_rgb(hues[self._burst_i % len(hues)], 1.0, 1.0)
            for fx in (*rig.tetras, *rig.sticks):
                fx.red, fx.green, fx.blue, fx.dim, fx.strobe = r, g, b, main, 0.0
            for bar in rig.bars:
                for p in bar.pars:
                    p.red, p.green, p.blue, p.dim, p.strobe = r, g, b, main, 0.0
        if "whiteout" in self.hits:
            for fx in (*rig.tetras, *rig.sticks):
                fx.red = fx.green = fx.blue = 1.0
                fx.dim, fx.strobe = main, 0.0
            for t in rig.tetras:
                t.amber = 0.0
            for bar in rig.bars:
                for p in bar.pars:
                    p.red = p.green = p.blue = 1.0
                    p.dim, p.strobe = main, 0.0
                if not self.spotting():
                    for h in bar.movers:
                        h.dim, h.color, h.gobo = main, 0, 0
                bar.strobe_white, bar.strobe_uv = main, 0.0

    def _burst_hues(self) -> list:
        cfg = self.cfg or show_settings.current()
        try:
            pairs = cfg["palettes"].get(cfg["section_palette"].get("main", "")) or next(iter(cfg["palettes"].values()))
            return [p[0] % 1.0 for p in pairs] or [0.0]
        except Exception:  # noqa: BLE001 -- ok: no palette to read = a plain color wheel
            return [0.0, 0.33, 0.66]

    def _find(self, rig, now: float) -> None:
        if not self.find:
            return
        fid, until = self.find
        if until is None:
            until = now + FIND_S
            self.find = (fid, until)
        if now >= until:
            self.find = None
            return
        kind, fx = self._fixture(rig, fid)
        if fx is None:
            return
        on = 1.0 if int((until - now) * 4) % 2 == 0 else 0.0   # two blinks a second
        for t in (fx.pars if kind == "gigbar" else [fx]):
            t.red = t.green = t.blue = 1.0
            t.dim, t.strobe = on, 0.0
        if kind == "gigbar":
            for h in fx.movers:
                h.dim, h.color, h.gobo = on, 0, 0


# --- frame helpers ---------------------------------------------------------------------------------

def _levels(rig) -> list:
    """Every level a crossfade melts: colors and dimmers. Pan and tilt glide on their own; wheels,
    derbies and the laser are switches."""
    out = []
    for t in rig.tetras:
        out += [t.red, t.green, t.blue, t.amber, t.dim]
    for s in rig.sticks:
        out += [s.red, s.green, s.blue, s.dim]
    for bar in rig.bars:
        for p in bar.pars:
            out += [p.red, p.green, p.blue, p.uv, p.dim]
        for h in bar.movers:
            out.append(h.dim)
    return out


def _set_levels(rig, v: list) -> None:
    it = iter(v)
    for t in rig.tetras:
        t.red, t.green, t.blue, t.amber, t.dim = (next(it) for _ in range(5))
    for s in rig.sticks:
        s.red, s.green, s.blue, s.dim = (next(it) for _ in range(4))
    for bar in rig.bars:
        for p in bar.pars:
            p.red, p.green, p.blue, p.uv, p.dim = (next(it) for _ in range(5))
        for h in bar.movers:
            h.dim = next(it)


def _snapshot(rig) -> list:
    return [copy.deepcopy({k: v for k, v in fx.__dict__.items() if k not in ("name", "address")}) for fx in rig.fixtures]


def _restore(rig, snap: list) -> None:
    for fx, was in zip(rig.fixtures, snap):
        fx.__dict__.update(copy.deepcopy(was))
