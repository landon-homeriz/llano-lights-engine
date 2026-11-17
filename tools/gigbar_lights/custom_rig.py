"""A DJ's own rig, played by role (Llano BL #12524).

The Setup screen saves a rig as the settings' rig.lights: lights from the fixture library, each
(profile, mode, start address, role). This module turns that into a fixture_profiles.ProfileRig and
plays the show on it.

How a look reaches lights it has never heard of: the looks engine keeps rendering every frame onto
the REFERENCE rig (rig.default_rig(), his twelve lights, which nothing sends while a DJ's own rig is
set), and project() reads what that frame asks of each ROLE and sets it on every part of the DJ's rig
playing that role (ProfileRig.by_role):

  wash      the Tetra row's colors, dimmer and strobe (sticks, then the GigBAR pars, when no Tetra
            runs), spread across the DJ's wash lights in patch order, so a chase that walks the Tetras
            walks their pars
  movers    the four GigBAR heads' pan, tilt, dimmer, strobe, wheel color and gobo
  effects   the derbies and lasers: color, strobe, rotation, on or off
  strobes   the GigBARs' white/UV strobe: level and speed

A part gets only the attributes it has. A light with no dimmer channel gets its colors scaled by the
look's dimmer; one with a color wheel and no RGB gets the wheel slot nearest the color; a white-only
light gets the brightness. With rig.lights empty nothing here runs and his twelve lights render
through rig.Rig.render exactly as before (test_fixture_profiles.py pins those frames).
"""
from __future__ import annotations

import json
import logging
import re
import threading
from typing import Optional

from . import fixture_library, fixture_profiles, show_settings
from .rig import DERBY_COLORS, HEAD_WHEEL, Rig

_log = logging.getLogger(__name__)
_LOCK = threading.Lock()
_BUILT: dict = {}

# Color words a wheel band or macro names, as RGB (wheel_slot picks the band nearest a look's color).
COLOR_WORDS = (("light blue", (0.25, 0.8, 1.0)), ("dark blue", (0.1, 0.2, 1.0)), ("congo", (0.3, 0.1, 1.0)),
               ("red", (1, 0, 0)), ("green", (0, 1, 0)), ("blue", (0, 0, 1)), ("yellow", (1, 1, 0)),
               ("amber", (1, 0.6, 0)), ("orange", (1, 0.5, 0)), ("magenta", (1, 0, 1)), ("pink", (1, 0.4, 0.7)),
               ("purple", (0.6, 0.2, 1)), ("violet", (0.6, 0.2, 1)), ("lavender", (0.7, 0.5, 1)),
               ("cyan", (0, 1, 1)), ("turquoise", (0, 0.9, 0.8)), ("lime", (0.6, 1, 0)), ("uv", (0.4, 0, 1)),
               ("white", (1, 1, 1)), ("open", (1, 1, 1)))
DERBY_RGB = {"off": (0, 0, 0), "red": (1, 0, 0), "green": (0, 1, 0), "blue": (0, 0, 1), "yellow": (1, 1, 0),
             "magenta": (1, 0, 1), "cyan": (0, 1, 1), "white": (1, 1, 1), "auto": (1, 1, 1), "auto2": (1, 1, 1)}
LASER_RGB = {"off": (0, 0, 0), "red": (1, 0, 0), "green": (0, 1, 0), "both": (1, 1, 0), "red_flash": (1, 0, 0),
             "green_flash": (0, 1, 0), "alternate": (1, 1, 0)}
assert set(DERBY_RGB) == set(DERBY_COLORS)


def _hex(h: str) -> tuple:
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


HEAD_RGB = tuple(_hex(h) for _n, h in HEAD_WHEEL)


def lights(settings: "dict | None" = None) -> list:
    """The DJ's own rig from the settings (rig.lights); [] = his twelve lights."""
    s = settings if settings is not None else show_settings.current()
    return list((s.get("rig") or {}).get("lights") or [])


class Built:
    """A rig.lights list as a ProfileRig, plus what stops any of it playing (by light, in words)."""

    def __init__(self, entries: list):
        self.entries = entries
        self.problems: list = []
        self.slots: list = []   # per entry: its RigFixture, or None when it can't be read
        fixtures = []
        for i, e in enumerate(entries, 1):
            label = e.get("name") or f"Light {i}"
            try:
                profile = fixture_library.resolve(e["profile"])
                mode = profile.mode(e["mode"])
            except Exception as ex:  # noqa: BLE001 -- ok: a light the library can't read is a problem the
                # Setup screen names, never a frame that fails (every frame would retry it and send nothing)
                msg = ex.args[0] if isinstance(ex, KeyError) and ex.args else ex
                self.problems.append(f"{label}: {msg}")
                self.slots.append(None)
                continue
            fx = fixture_profiles.RigFixture(profile, mode, int(e["address"]), e.get("role") or "wash", label)
            fixtures.append(fx)
            self.slots.append(fx)
        self.rig = fixture_profiles.ProfileRig(fixtures)
        self.problems += self.rig.problems()
        self.parts = {r: self.rig.by_role(r) for r in fixture_profiles.ROLES}
        self.attrs = {(id(fx), el): set(fx.mode.elements().get(el, [])) for r in self.parts.values() for fx, el in r}
        # One frame at a time: the show's 40 Hz thread and a pad preview's Show (studio_peek, on the HTTP
        # thread) share this rig's state, so project and render run under it together.
        self.lock = threading.Lock()


def build(entries: list) -> Built:
    """The rig for these entries, built once per distinct list (a frame is 25 ms)."""
    key = json.dumps(entries, sort_keys=True)
    with _LOCK:
        b = _BUILT.get(key)
        if b is None:
            if len(_BUILT) > 8:
                _BUILT.clear()
            b = _BUILT[key] = Built(entries)
        return b


# --- what each role is asked for, read off the reference rig ----------------------------------

def _wash_sources(ref: Rig) -> list:
    if ref.tetras:
        return [{"red": t.red, "green": t.green, "blue": t.blue, "amber": t.amber, "dim": t.dim, "strobe": t.strobe}
                for t in ref.tetras]
    if ref.sticks:
        return [{"red": s.red, "green": s.green, "blue": s.blue, "dim": s.dim, "strobe": s.strobe} for s in ref.sticks]
    return [{"red": p.red, "green": p.green, "blue": p.blue, "uv": p.uv, "dim": p.dim, "strobe": p.strobe}
            for b in ref.bars for p in b.pars]


def _mover_sources(ref: Rig) -> list:
    out = []
    for b in ref.bars:
        for m in b.movers:
            slot = max(0, min(len(HEAD_RGB) - 1, int(m.color)))
            r, g, bl = HEAD_RGB[slot]
            out.append({"pan": m.pan, "tilt": m.tilt, "dim": m.dim, "strobe": m.strobe, "_gobo": int(m.gobo),
                        "red": r, "green": g, "blue": bl, "_rgb": HEAD_RGB[slot]})
    return out


def _effect_sources(ref: Rig) -> list:
    out = []
    for b in ref.bars:
        for d in b.derbies:
            out.append((DERBY_RGB.get(d.color, (1, 1, 1)), d.color != "off", d.strobe, d.rotate))
        out.append((LASER_RGB.get(b.laser, (1, 1, 0)), b.laser != "off", b.laser_strobe, b.laser_rotate))
    srcs = []
    for rgb, on, strobe, rotate in out:
        srcs.append({"red": rgb[0], "green": rgb[1], "blue": rgb[2], "dim": 1.0 if on else 0.0,
                     "strobe": strobe if on else 0.0, "rotate": rotate if on else 0.0, "_rgb": rgb, "_on": on})
    return srcs


def _strobe_sources(ref: Rig) -> list:
    out = []
    for b in ref.bars:
        prog = max(0, min(10, int(b.strobe_program)))
        white, uv = b.strobe_white, (0.0 if b.strobe_white else b.strobe_uv)
        level = max(white, uv, 1.0 if prog else 0.0)
        on = level > 0
        out.append({"dim": level, "strobe": max(b.strobe_speed, 0.05) if on else 0.0,
                    "red": 1.0 if white or prog else 0.0, "green": 1.0 if white or prog else 0.0,
                    "blue": 1.0 if on else 0.0, "white": level if white or prog else 0.0, "uv": uv,
                    "_rgb": (1, 1, 1) if white or prog else (0.4, 0, 1), "_on": on})
    return out


# --- writing a source onto one part --------------------------------------------------------------

_SLOTS: dict = {}


def wheel_slots(fx, el: str) -> list:
    """[(band index, rgb)] for the color wheel or macro channel of one part: each band whose name holds a
    color word. Cached per profile, mode and part."""
    key = (fx.profile.key, fx.mode.name, el)
    if key not in _SLOTS:
        slots = []
        for ch in fx.mode.channels:
            if ch.element != el:
                continue
            for fn in ch.functions:
                if fn.kind == "choice" and fn.attr == "color":
                    for i, band in enumerate(fn.bands):
                        label = band.label.lower()
                        for word, rgb in COLOR_WORDS:
                            if re.search(rf"\b{word}\b", label) and not re.search(r"\b(and|/|\+|split)\b", label):
                                slots.append((i, rgb))
                                break
                    break
            if slots:
                break
        _SLOTS[key] = slots
    return _SLOTS[key]


def wheel_slot(fx, el: str, rgb: tuple) -> Optional[int]:
    """The band of a part's wheel nearest a color, or None when the part has no named colors."""
    slots = wheel_slots(fx, el)
    if not slots:
        return None
    return min(slots, key=lambda s: sum((a - b) ** 2 for a, b in zip(s[1], rgb)))[0]


_GOBOS: dict = {}
_NOT_A_GOBO = re.compile(r"rotat|shake|scroll|spin|cw\b|ccw|rainbow|effect|random|auto|speed|index|stop")


def gobo_slots(fx, el: str) -> list:
    """The band indexes of a part's gobo wheel that hold one still gobo (open first), leaving out its
    rotation, shake and scroll bands; [] when the gobo channel is not a choice of bands."""
    key = (fx.profile.key, fx.mode.name, el)
    if key not in _GOBOS:
        out = []
        for ch in fx.mode.channels:
            if ch.element != el:
                continue
            fn = next((f for f in ch.functions if f.attr == "gobo"), None)
            if fn is not None:
                if fn.kind == "choice":
                    out = [i for i, b in enumerate(fn.bands) if not _NOT_A_GOBO.search(b.label.lower())]
                break
        _GOBOS[key] = out
    return _GOBOS[key]


def _put(fx, el: str, have: set, src: dict) -> None:
    def k(a):
        return f"{el}.{a}" if el else a

    vals = {a: v for a, v in src.items() if not a.startswith("_")}
    dim = float(vals.get("dim", 0.0))
    # the look's color before any dimmer rides on it: what a wheel or a white-only light shows
    rgb = src.get("_rgb") or (float(vals.get("red", 0.0)), float(vals.get("green", 0.0)), float(vals.get("blue", 0.0)))
    colors = [c for c in ("red", "green", "blue", "amber", "white", "uv") if c in have]
    if not ({"red", "green", "blue"} & have):
        if "white" in have and "white" not in src:
            vals["white"] = max(rgb)
        if not colors and "dim" in have:   # a white-only light: as bright as the color is
            vals["dim"] = dim * max(max(rgb), float(src.get("amber", 0.0)))
        if "color" in have:
            slot = wheel_slot(fx, el, rgb if max(rgb) > 0 else (1, 1, 1))
            if slot is not None:
                vals["color"] = slot
    if "dim" not in have:   # no dimmer channel: the look's dimmer rides on the colors
        for c in ("red", "green", "blue", "amber", "white", "uv"):
            if c in vals:
                vals[c] = float(vals[c]) * dim
    if not isinstance(vals.get("color"), int):   # a color only as a wheel slot picked above
        vals.pop("color", None)
    if "gobo" in have and "_gobo" in src:   # the GigBAR slot onto this wheel's still gobos (0 = open)
        slots = gobo_slots(fx, el)
        if slots:
            vals["gobo"] = slots[min(len(slots) - 1, max(0, src["_gobo"]))]
    for a, v in vals.items():
        if a in have:
            fx.state[k(a)] = v


def project(ref: Rig, built: Built) -> None:
    """Set the DJ's rig to what the reference rig's frame asks of each role (module docstring)."""
    built.rig.clear()
    sources = {"wash": _wash_sources(ref), "movers": _mover_sources(ref),
               "effects": _effect_sources(ref), "strobes": _strobe_sources(ref)}
    for role, parts in built.parts.items():
        src = sources[role]
        if not src or not parts:
            continue
        n = len(parts)
        for i, (fx, el) in enumerate(parts):
            s = src[min(len(src) - 1, i * len(src) // n)]
            _put(fx, el, built.attrs[(id(fx), el)], s)


def render(ref: Rig, entries: "list | None" = None) -> bytearray:
    """The DJ's rig's universe for the reference rig's frame."""
    built = build(entries if entries is not None else lights())
    with built.lock:
        project(ref, built)
        return built.rig.render()


def universe(ref: Rig, config: "dict | None" = None) -> bytearray:
    """What the show sends: the DJ's own rig when rig.lights has any light, else his twelve exactly as before."""
    entries = lights()
    if entries:
        return render(ref, entries)
    return ref.render(config)


def white(entries: list, index: int) -> bytearray:
    """Test each light: light `index` (0-based) full white, heads centered, everything else dark."""
    built = build(entries)
    with built.lock:
        built.rig.clear()
        fx = built.slots[index] if 0 <= index < len(built.slots) else None
        if fx is not None:
            for el, have in fx.mode.elements().items():
                _put(fx, el, set(have), {"red": 1.0, "green": 1.0, "blue": 1.0, "white": 1.0, "dim": 1.0,
                                         "pan": 0.5, "tilt": 0.5, "_rgb": (1, 1, 1)})
        return built.rig.render()


def summary(entries: "list | None" = None) -> dict:
    """The Setup screen's view: each light with its channels, the problems, and the role counts."""
    entries = entries if entries is not None else lights()
    built = build(entries)
    rows = []
    for i, (e, fx) in enumerate(zip(entries, built.slots), 1):
        label = e.get("name") or f"Light {i}"
        lib = fixture_library.entry(e["profile"]) or {}
        rows.append({**e, "label": label, "manufacturer": lib.get("manufacturer", ""), "model": lib.get("model", ""),
                     "modes": lib.get("modes", []),
                     "channels": fx.mode.footprint if fx else 0,
                     "end": (int(e["address"]) + fx.mode.footprint - 1) if fx else None,
                     "parts": sorted({r for r in fx.element_roles().values()}) if fx else []})
    return {"lights": rows, "problems": built.problems,
            "roles": {r: len(p) for r, p in built.parts.items()},
            "next_address": max([r["end"] or 0 for r in rows] + [0]) + 1}
