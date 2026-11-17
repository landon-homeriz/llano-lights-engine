"""The shared fixture library (Llano BL #12136, phase 1 of the Lights business plan).

Until now rig.py knew three fixtures by hand (GigBAR Move 35CH, Venue Tetra 6, Freedom Stick 8CH),
so no other DJ's lights could run. This module reads a light from the two open fixture libraries
instead:

  QLC+ .qxf               mcallegari/qlcplus resources/fixtures, Apache 2.0 (about 1,800 fixtures)
  Open Fixture Library    open-fixture-library.org fixture JSON, MIT

and turns it into a PROFILE: each mode's channels in DMX order, each channel a short list of
FUNCTIONS that say which named attribute drives it and how (a 0..1 level onto a byte band, a
-1..1 rotation onto its clockwise and counter-clockwise bands, a choice of one band by name or
number, a fixed byte). Attributes are plain names (red, amber, uv, dim, strobe, pan, tilt, color,
gobo, rotate, program, speed), prefixed by the part of the light they belong to when it has several
("par1.red", "head2.pan", "derby1.color"). A look never writes channel numbers; it sets attributes.

The libraries describe what a channel CAN do, not how a show should drive it. What they lack lives
in an OVERRIDE layer (fixtures/overrides.json), keyed by profile and mode: channel names the app
uses, program channels held at zero so a light never runs its own show, strobe floors, the byte
picked inside a band, which part of a light plays which role, wireless (D-Fi) notes. The library
files themselves stay unmodified, so a newer copy drops straight in.

A RIG is then a list of (profile, mode, start address, role). Roles are wash, movers, effects and
strobes, so a look can address "every wash light" without knowing brands (ProfileRig.set_role).

Today's 12 lights run through this path too (rig.place): their profiles are the three QLC+ files
in fixtures/qlcplus plus their overrides, and their DMX bytes are byte-for-byte the hand-written
ones (pinned in tests/gigbar_lights/test_fixture_profiles.py against frames the released 1.19.3 and
1.37.0 rendered). Kill switch: LLANO_LIGHTS_PROFILES=0 sends the hand-written bytes again.

Stdlib only (the Windows app runs an embedded Python).
"""
from __future__ import annotations

import json
import math
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

HERE = Path(__file__).resolve().parent
LIBRARY_DIR = HERE / "fixtures"
QLC_DIR = LIBRARY_DIR / "qlcplus"
OVERRIDES_FILE = LIBRARY_DIR / "overrides.json"
UNIVERSE_SIZE = 512
ROLES = ("wash", "movers", "effects", "strobes")
KINDS = ("level", "bipolar", "choice", "fixed")

# Today's three kinds (rig.py's GigBarMove, Tetra6, FreedomStick): which library file and mode.
BUILTIN = {
    "gigbar": ("Chauvet-GigBAR-Move.qxf", "35-channel"),
    "tetra": ("Venue-Tetra-6.qxf", "6 Channel"),
    "stick": ("Chauvet-Freedom-Stick.qxf", "8 Channel"),
}


def enabled() -> bool:
    """Profiles drive the lights unless LLANO_LIGHTS_PROFILES=0 (the hand-written bytes again)."""
    return (os.environ.get("LLANO_LIGHTS_PROFILES") or "1").strip().lower() not in {"0", "off", "false", "no"}


def slug(text: str) -> str:
    """'Chauvet DJ' -> 'chauvet-dj', 'Par 1' -> 'par-1'."""
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


# ---------------------------------------------------------------------------------------------
# The profile model


@dataclass(frozen=True)
class Band:
    """One DMX range of a channel, as the library names it ("Strobe Slow-Fast", 128..239)."""
    label: str
    lo: int
    hi: int


@dataclass(frozen=True)
class Function:
    """How one attribute drives a channel.

    level    the attribute's 0..1 onto lo..hi (lo > hi runs the band backwards).
    bipolar  -1..1: above 0 onto lo..hi, below 0 onto neg_lo..neg_hi (either band may run backwards);
             0 or unset lets the channel's other functions play (a wheel's slot), and when none
             does the channel sends `zero` (the stop byte) rather than 0.
    choice   one of `bands`, by number (0 = the first band) or by name (a band label or an alias);
             the byte is band.lo + offset, or the band's middle when offset is None.
    fixed    always `byte`.
    `positive` skips a level or choice whose value is not above 0 (a strobe at 0 falls through to
    the dimmer that shares its channel). `when` applies only if one of those channels' bytes is not
    0; `unless` only if all of theirs are 0. A channel sends its first function that applies, else 0.
    """
    kind: str
    attr: str = ""
    lo: int = 0
    hi: int = 255
    neg_lo: int = 0
    neg_hi: int = 0
    zero: int = 0
    positive: bool = False
    bands: tuple = ()
    offset: Optional[int] = None
    aliases: tuple = ()      # ((name, band index), ...): hashable, so a Function stays frozen
    byte: int = 0
    when: tuple = ()
    unless: tuple = ()


@dataclass(frozen=True)
class Channel:
    """One DMX channel of a mode. `id` is the app's name for it ("par1.shutter"); its functions'
    attributes are prefixed by `element` ("par1" -> "par1.dim", "par1.strobe")."""
    id: str
    name: str
    element: str = ""
    functions: tuple = ()
    bands: tuple = ()        # every band the library lists, in order (a choice override reuses them)
    group: str = ""

    def key(self, attr: str) -> str:
        return f"{self.element}.{attr}" if self.element and attr else attr

    @cached_property
    def keys(self) -> tuple:
        """Each function's full attribute key, worked out once (encode runs 40 times a second)."""
        return tuple(self.key(f.attr) for f in self.functions)

    @cached_property
    def conditional(self) -> bool:
        return any(f.when or f.unless for f in self.functions)

    @cached_property
    def stop(self) -> int:
        """The byte when no function plays: a rotation's stop, else 0."""
        return next((f.zero for f in self.functions if f.kind == "bipolar"), 0)

    @property
    def attributes(self) -> tuple:
        seen = []
        for fn in self.functions:
            if fn.attr and self.key(fn.attr) not in seen:
                seen.append(self.key(fn.attr))
        return tuple(seen)


@dataclass(frozen=True)
class Mode:
    name: str
    channels: tuple

    @property
    def footprint(self) -> int:
        return len(self.channels)

    @property
    def ids(self) -> tuple:
        return tuple(c.id for c in self.channels)

    @cached_property
    def by_id(self) -> dict:
        return {c.id: c for c in self.channels}

    @property
    def attributes(self) -> tuple:
        out: list = []
        for c in self.channels:
            out += [a for a in c.attributes if a not in out]
        return tuple(out)

    def elements(self) -> dict:
        """{element: [local attribute names]}; '' holds a single-part light's attributes."""
        out: dict = {}
        for c in self.channels:
            for fn in c.functions:
                if fn.attr:
                    names = out.setdefault(c.element, [])
                    if fn.attr not in names:
                        names.append(fn.attr)
        return out


@dataclass
class Profile:
    manufacturer: str
    model: str
    modes: dict
    library: str               # "qlcplus" | "ofl"
    origin: str                # the file it was read from
    license: str
    notes: tuple = ()
    roles: dict = field(default_factory=dict)   # element family ("par", "head") -> role
    default_role: str = ""
    wireless: str = ""

    @property
    def key(self) -> str:
        return f"{slug(self.manufacturer)}/{slug(self.model)}"

    def mode(self, name: str) -> Mode:
        """A mode by its library name, or loosely: '35CH', '35 channel' and '35-channel' are one mode
        when exactly one mode has that channel count in its name."""
        if name in self.modes:
            return self.modes[name]
        want = slug(name)
        for n, m in self.modes.items():
            if slug(n) == want:
                return m
        num = re.match(r"\s*(\d+)", str(name))
        if num:
            hits = [m for n, m in self.modes.items() if re.match(rf"\s*{num.group(1)}(?!\d)", n)]
            if len(hits) == 1:
                return hits[0]
        raise KeyError(f"{self.manufacturer} {self.model} has no mode {name!r}; it has {', '.join(self.modes)}")

    def role_of(self, element: str, fallback: str) -> str:
        family = re.sub(r"\d+$", "", element)
        if family in self.roles:
            return self.roles[family]
        return fallback or self.default_role or "wash"


# ---------------------------------------------------------------------------------------------
# Attributes -> bytes


def _finite(v: Any) -> Optional[float]:
    if isinstance(v, str):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None   # a NaN sends nothing (dark), never a full byte


def _level(lo: int, hi: int, x: float) -> int:
    """0..1 onto lo..hi, rounded like rig._in_range (and rig._byte when the band is 0..255)."""
    x = max(0.0, min(1.0, x))
    return int(round(lo + (hi - lo) * x))


def _band_index(fn: Function, v: Any) -> Optional[int]:
    if isinstance(v, str):
        want = v.strip().lower()
        for name, i in fn.aliases:
            if name == want:
                return i
        for i, b in enumerate(fn.bands):
            if b.label.strip().lower() == want:
                return i
        return None
    x = _finite(v)
    if x is None or x != int(x):
        return None
    i = int(x)
    return i if 0 <= i < len(fn.bands) else None


def _apply(fn: Function, key: str, state: Mapping, byte_of: Optional[Callable[[str], int]]) -> Optional[int]:
    if fn.when and not any(byte_of(c) for c in fn.when):
        return None
    if fn.unless and any(byte_of(c) for c in fn.unless):
        return None
    if fn.kind == "fixed":
        return fn.byte
    if key not in state:
        return None
    v = state[key]
    if fn.kind == "choice":
        i = _band_index(fn, v)
        if i is None or (fn.positive and i == 0):
            return None
        band = fn.bands[i]
        off = fn.offset if fn.offset is not None else (band.hi - band.lo) // 2
        return max(band.lo, min(band.hi, band.lo + off))
    x = _finite(v)
    if x is None:
        return None
    if fn.kind == "bipolar":
        if x > 0:
            return _level(fn.lo, fn.hi, x)
        if x < 0:
            return _level(fn.neg_lo, fn.neg_hi, -x)
        return None   # not turning: the channel's other functions, else its stop byte
    if fn.positive and not x > 0:
        return None
    return _level(fn.lo, fn.hi, x)


def _channel_byte(ch: Channel, state: Mapping, byte_of: Optional[Callable[[str], int]]) -> int:
    for fn, key in zip(ch.functions, ch.keys):
        r = _apply(fn, key, state, byte_of)
        if r is not None:
            return r
    return ch.stop


def encode(mode: Mode, state: Mapping) -> dict:
    """Every channel's byte by channel id, from attribute values (`state`, keyed "par1.red" etc.).
    Channels with no condition first, then the ones whose functions read other channels' bytes."""
    out: dict = {}
    pending = []
    for ch in mode.channels:
        if ch.conditional:
            pending.append(ch)
        else:
            out[ch.id] = _channel_byte(ch, state, None)
    if pending:
        chans, busy = mode.by_id, set()

        def byte_of(cid: str) -> int:
            if cid in out:
                return out[cid]
            ch = chans.get(cid)
            if ch is None or cid in busy:   # an unknown or circular reference reads as 0
                return 0
            busy.add(cid)
            out[cid] = b = _channel_byte(ch, state, byte_of)
            busy.discard(cid)
            return b

        for ch in pending:
            byte_of(ch.id)
    return out


def frame(mode: Mode, state: Mapping) -> list:
    """The mode's bytes in DMX order."""
    named = encode(mode, state)
    return [named[c.id] for c in mode.channels]


# ---------------------------------------------------------------------------------------------
# Reading the libraries: what each capability means

_STROBE_WORDS = ("strobe", "flash", "pulse")
_NOT_STROBE = ("sound", "no strobe", "strobe off", "no function", "open", "off")
_DIM_RE = re.compile(r"dimmer|intensity|0\s*[-–]\s*100\s*%|brightness")
_ROTATE_RE = re.compile(r"\brotat|\bccw\b|\bcw\b|clockwise|spin")
_STOP_RE = re.compile(r"\bstop|no rotation|no function|index")


def _is_strobe_text(t: str) -> bool:
    t = t.lower()
    return any(w in t for w in _STROBE_WORDS) and not any(w in t for w in _NOT_STROBE)


def _is_open_text(t: str) -> bool:
    t = t.lower()
    return bool(re.search(r"\bopen\b|no strobe|shutter open|strobe off", t)) and "close" not in t


def _ccw(t: str) -> bool:
    t = t.lower()
    return bool(re.search(r"\bccw\b|counter|anti", t))


def _fast_to_slow(t: str) -> bool:
    """'CW fast to slow', 'Rotation fast-slow': a band whose speed falls as the byte rises."""
    return bool(re.search(r"fast\s*(?:to|-|–|>|\.\.)\s*slow", t.lower()))


def _color_attr(name: str) -> str:
    return slug(name).replace("-", "_") if name else ""


def _build_functions(caps: list) -> tuple:
    """Functions for one channel from its classified capabilities.

    `caps` is [(kind, attr, band, extra)] in DMX order, kind in strobe/level/rotate_cw/rotate_ccw/
    choice/open/skip. Order of what comes out: a strobe (only above 0), a rotation, a choice, a level
    (the dimmer that shares a shutter channel), then the shutter's open byte as the fallback."""
    out: list = []
    strobe = next((c for c in caps if c[0] == "strobe"), None)
    if strobe:
        _k, attr, b, extra = strobe
        lo, hi = (b.hi, b.lo) if extra.get("reverse") else (b.lo, b.hi)
        out.append(Function("level", attr, lo, hi, positive=True))
    cw = next((c for c in caps if c[0] == "rotate_cw"), None)
    ccw = next((c for c in caps if c[0] == "rotate_ccw"), None)
    if cw or ccw:
        def span(c):   # 0..1 is slow..fast: a band the library lists fast-to-slow runs backwards
            if c is None:
                return 0, 0
            return (c[2].hi, c[2].lo) if c[3].get("reverse") else (c[2].lo, c[2].hi)
        lo, hi = span(cw)
        nlo, nhi = span(ccw)
        stop = next((c[2].lo for c in caps if c[0] == "stop"), 0)
        out.append(Function("bipolar", (cw or ccw)[1], lo, hi, neg_lo=nlo, neg_hi=nhi, zero=stop))
    choice = next((c for c in caps if c[0] == "choice"), None)
    if choice:
        bands = tuple(c[2] for c in caps)
        aliases = tuple((a, i) for i, c in enumerate(caps) for a in c[3].get("aliases", ()))
        out.append(Function("choice", choice[1], bands=bands, aliases=aliases))
    levels: dict = {}
    for k, attr, b, extra in caps:
        if k == "level" and attr not in levels:   # the first band of an attribute is its level
            levels[attr] = Function("level", attr, b.lo, b.hi)
    out += levels.values()
    opened = next((c for c in caps if c[0] == "open"), None)
    if opened:   # a shutter sends its open byte when nothing else plays (closed would black the light out)
        out.append(Function("fixed", byte=opened[2].lo))
    return tuple(out)


_NUMBERED = re.compile(r"^(?P<el>[A-Za-z]+(?:\s+[A-Za-z]+)?)\s*(?P<n>\d+)\b\s*(?P<rest>.*)$")


def _element_of(name: str) -> tuple:
    """('Par 1 Red') -> ('par1', 'Red'); a name with no numbered part -> ('', name)."""
    m = _NUMBERED.match(name.strip())
    if m and m.group("rest").strip():
        return f"{slug(m.group('el')).replace('-', '')}{m.group('n')}", m.group("rest").strip()
    return "", name.strip()


def _pixel_element(key: str) -> str:
    """An OFL pixel key as a part name: 'Par 1' -> 'par1', '1/4' -> 'pixel1_4', 'Master' -> '' (whole light)."""
    key = key.strip()
    if key.lower() in ("master", "all"):
        return ""
    s = slug(key)
    return s.replace("-", "") if s[:1].isalpha() else "pixel" + s.replace("-", "_")


def _channel_id(element: str, rest: str, functions: tuple) -> str:
    attrs = [f.attr for f in functions if f.attr]
    local = attrs[0] if len(set(attrs)) == 1 else slug(rest).replace("-", "_") or "channel"
    return f"{element}.{local}" if element else local


def _unique_ids(channels: list) -> list:
    seen: dict = {}
    out = []
    for c in channels:
        n = seen.get(c.id, 0)
        seen[c.id] = n + 1
        out.append(c if n == 0 else replace(c, id=f"{c.id}_{n + 1}"))
    return out


# --- QLC+ .qxf ---------------------------------------------------------------------------------

_QLC_NS = "{http://www.qlcplus.org/FixtureDefinition}"
_QLC_COLOR = {f"Intensity{c}": c.lower() for c in
              ("Red", "Green", "Blue", "Amber", "White", "UV", "Cyan", "Magenta", "Yellow", "Lime", "Indigo")}
_QLC_LEVEL = {
    "IntensityMasterDimmer": "dim", "IntensityDimmer": "dim",
    "IntensityMasterDimmerFine": "dim_fine", "IntensityDimmerFine": "dim_fine",
    "PositionPan": "pan", "PositionTilt": "tilt", "PositionPanFine": "pan_fine", "PositionTiltFine": "tilt_fine",
    "PositionXAxis": "x", "PositionYAxis": "y",
    "SpeedPanSlowFast": "speed", "SpeedTiltSlowFast": "speed", "SpeedPanTiltSlowFast": "speed",
    "ShutterIrisMinToMax": "iris", "BeamFocusNearFar": "focus", "BeamZoomSmallBig": "zoom",
    "IntensityHue": "hue", "IntensitySaturation": "saturation", "IntensityLightness": "lightness",
    "IntensityValue": "value",
}
_QLC_REVERSED = {"SpeedPanFastSlow": "speed", "SpeedTiltFastSlow": "speed", "SpeedPanTiltFastSlow": "speed",
                 "ShutterIrisMaxToMin": "iris", "BeamFocusFarNear": "focus", "BeamZoomBigSmall": "zoom"}
_QLC_STROBE_PRESETS = ("StrobeSlowToFast", "StrobeFastToSlow", "StrobeFrequency", "StrobeFreqRange",
                       "PulseSlowToFast", "PulseFastToSlow", "PulseFrequency", "PulseFreqRange",
                       "RampUpSlowToFast", "RampUpFastToSlow", "RampDownSlowToFast", "RampDownFastToSlow")
_QLC_CHOICE_GROUPS = {"colour": "color", "gobo": "gobo", "effect": "program", "prism": "prism",
                      "maintenance": "maintenance", "beam": "beam", "nothing": ""}


def _qlc_caps(el: ET.Element, group: str, colour: str) -> list:
    """[(kind, attr, Band, extra)] for every <Capability> of a channel."""
    caps = []
    grp = group.lower()
    for cap in el.findall(f"{_QLC_NS}Capability"):
        text = (cap.text or "").strip()
        b = Band(text, int(cap.get("Min", 0)), int(cap.get("Max", 255)))
        preset = cap.get("Preset", "")
        low = text.lower()
        extra: dict = {"aliases": tuple(a for a in {low, (cap.get("Res1") or cap.get("Res") or "").lower()} if a)}
        if preset in _QLC_STROBE_PRESETS or (grp in ("shutter", "intensity", "") and _is_strobe_text(text)):
            caps.append(("strobe", "strobe", b, {"reverse": "FastToSlow" in preset}))
        elif grp in ("speed", "pan", "tilt", "effect", "gobo", "colour", "prism", "beam") and \
                _ROTATE_RE.search(low) and not _STOP_RE.search(low):
            caps.append(("rotate_ccw" if _ccw(low) else "rotate_cw", "rotate", b,
                         {**extra, "reverse": _fast_to_slow(low)}))
        elif grp in ("pan", "tilt"):   # a Pan or Tilt channel listed without its preset
            caps.append(("level", grp, b, extra))
        elif grp == "speed" and _STOP_RE.search(low):
            caps.append(("stop", "rotate", b, extra))
        elif grp in _QLC_CHOICE_GROUPS and _QLC_CHOICE_GROUPS[grp]:
            caps.append(("choice", _QLC_CHOICE_GROUPS[grp], b, extra))
        elif grp == "shutter" and (preset == "ShutterOpen" and not _DIM_RE.search(low) or _is_open_text(text)):
            caps.append(("open", "", b, extra))
        elif _DIM_RE.search(low) or grp == "intensity" and not re.search(r"blackout|\boff\b|no function", low):
            attr = colour or "dim"
            caps.append(("level", attr, b, extra))
        elif grp == "speed":
            caps.append(("level", "speed", b, extra))
        else:
            caps.append(("skip", "", b, extra))
    return caps


def _qlc_channel(el: ET.Element) -> tuple:
    """(functions, bands, group) for one <Channel> definition."""
    name = el.get("Name", "")
    preset = el.get("Preset", "")
    g = el.find(f"{_QLC_NS}Group")
    group = (g.text or "").strip() if g is not None else ""
    c = el.find(f"{_QLC_NS}Colour")
    colour = _color_attr((c.text or "").strip()) if c is not None else ""
    if preset:
        band = (Band(preset, 0, 255),)
        if preset in _QLC_COLOR:
            return (Function("level", _QLC_COLOR[preset]),), band, "Intensity"
        if preset in _QLC_LEVEL:
            return (Function("level", _QLC_LEVEL[preset]),), band, group
        if preset in _QLC_REVERSED:
            return (Function("level", _QLC_REVERSED[preset], 255, 0),), band, group
        if preset == "ShutterStrobeSlowFast":
            return (Function("level", "strobe", positive=True),), band, "Shutter"
        if preset == "ShutterStrobeFastSlow":
            return (Function("level", "strobe", 255, 0, positive=True),), band, "Shutter"
        if not el.findall(f"{_QLC_NS}Capability"):
            low = name.lower()
            attr = "color" if "color" in low or "colour" in low else "gobo" if "gobo" in low else ""
            return ((Function("level", attr),) if attr else ()), band, group
    caps = _qlc_caps(el, group, colour)
    bands = tuple(c[2] for c in caps)
    if not caps and group.lower() == "intensity":
        return (Function("level", colour or "dim"),), (Band(name, 0, 255),), group
    return _build_functions(caps), bands, group


def load_qxf(source: "str | Path", table: Optional[dict] = None) -> Profile:
    """A QLC+ fixture definition (.qxf path, or its XML text) as a Profile, with overrides.json's
    entry for it applied (or `table`'s; table={} reads the library as it is)."""
    text = source if isinstance(source, str) and source.lstrip().startswith("<") else Path(source).read_text("utf-8")
    origin = "" if isinstance(source, str) and source.lstrip().startswith("<") else str(source)
    root = ET.fromstring(text)
    if root.tag != f"{_QLC_NS}FixtureDefinition":
        raise ValueError(f"{origin or 'text'} is not a QLC+ fixture definition (root <{root.tag}>)")
    manufacturer = (root.findtext(f"{_QLC_NS}Manufacturer") or "").strip()
    model = (root.findtext(f"{_QLC_NS}Model") or "").strip()
    defs = {}
    for el in root.findall(f"{_QLC_NS}Channel"):
        defs[el.get("Name", "").strip()] = _qlc_channel(el)
    folded = {k.lower(): k for k in defs}   # some library files name a channel 'Red ' or 'red'

    modes = {}
    for m in root.findall(f"{_QLC_NS}Mode"):
        nums = []
        for ch in m.findall(f"{_QLC_NS}Channel"):
            nums.append((int(ch.get("Number", len(nums))), (ch.text or "").strip()))
        names = [n for _i, n in sorted(nums)]
        heads = [[int(c.text) for c in h.findall(f"{_QLC_NS}Channel")] for h in m.findall(f"{_QLC_NS}Head")]
        head_of = {}
        if len(heads) > 1:
            for hi, members in enumerate(heads):
                for idx in members:
                    head_of.setdefault(idx, hi)
        channels = []
        for idx, name in enumerate(names):
            name = name if name in defs else folded.get(name.lower(), name)
            if name not in defs:
                raise ValueError(f"{manufacturer} {model} mode {m.get('Name')!r} uses undefined channel {name!r}")
            functions, bands, group = defs[name]
            element, rest = _element_of(name)
            if not element and idx in head_of:
                element = f"head{head_of[idx] + 1}"
            channels.append(Channel(_channel_id(element, rest, functions), name, element, functions, bands, group))
        mname = (m.get("Name") or "").strip() or f"{len(names)} Channel"
        modes[mname] = Mode(mname, tuple(_unique_ids(channels)))
    profile = Profile(manufacturer, model, modes, "qlcplus", origin, "Apache-2.0")
    return apply_overrides(profile, table)


# --- Open Fixture Library JSON -----------------------------------------------------------------

_OFL_LEVEL = {"Intensity": "dim", "Pan": "pan", "Tilt": "tilt", "Zoom": "zoom", "Focus": "focus",
              "Iris": "iris", "ColorTemperature": "cct", "Speed": "speed", "EffectSpeed": "speed",
              "PanTiltSpeed": "speed", "BeamAngle": "zoom", "Fog": "fog", "FogOutput": "fog"}
_OFL_ROTATION = ("Rotation", "WheelRotation", "WheelSlotRotation", "PrismRotation", "GoboStencilRotation",
                 "PanContinuous", "TiltContinuous")
_OFL_CHOICE = {"WheelSlot": "", "ColorPreset": "color", "Effect": "program", "Prism": "prism",
               "WheelShake": "", "BeamPosition": "beam"}


def _ofl_range(cap: dict, single: bool) -> tuple:
    lo, hi = cap.get("dmxRange", [0, 255]) if not single else (0, 255)
    if hi > 255:   # a 16-bit channel's range, in coarse bytes
        lo, hi = lo >> 8, hi >> 8
    return int(lo), int(hi)


def _ofl_caps(ch: dict, name: str) -> list:
    single = "capability" in ch
    raw = [ch["capability"]] if single else ch.get("capabilities", [])
    low_name = name.lower()
    caps = []
    for cap in raw:
        lo, hi = _ofl_range(cap, single)
        t = cap.get("type", "")
        label = cap.get("comment") or cap.get("effectName") or cap.get("effectPreset") or t
        b = Band(str(label), lo, hi)
        aliases = tuple(a.lower() for a in (cap.get("comment"), cap.get("effectName"), *cap.get("colors", ()))
                        if isinstance(a, str) and a)
        speeds = " ".join(str(cap.get(k, "")) for k in ("speed", "speedStart", "speedEnd")).lower()
        if t == "ShutterStrobe":
            eff = cap.get("shutterEffect", "")
            if eff in ("Open",):
                caps.append(("open", "", b, {}))
            elif eff == "Closed" or cap.get("soundControlled") or cap.get("randomTiming"):
                caps.append(("skip", "", b, {}))
            else:
                start = str(cap.get("speedStart", "")).lower()
                caps.append(("strobe", "strobe", b, {"reverse": start.startswith("fast")}))
        elif t == "ColorIntensity":
            attr = _color_attr(cap.get("color", ""))
            constant = "brightness" in cap and "brightnessStart" not in cap
            caps.append(("level" if not constant or cap.get("brightness") != "off" else "skip", attr, b,
                         {"constant": constant}))
        elif t in _OFL_ROTATION:
            if "stop" in speeds or cap.get("speed") == "0" or not speeds.strip():
                caps.append(("stop", "rotate", b, {}))
            else:   # speedStart 'fast CCW' -> 'slow CCW' runs backwards, whichever way it turns
                caps.append(("rotate_ccw" if _ccw(speeds) else "rotate_cw", "rotate", b,
                             {"reverse": str(cap.get("speedStart", "")).lower().startswith("fast")}))
        elif t in _OFL_CHOICE:
            attr = _OFL_CHOICE[t] or ("gobo" if "gobo" in (cap.get("wheel") or low_name)
                                      else "color" if "colo" in (cap.get("wheel") or low_name)
                                      else slug(cap.get("wheel") or name).replace("-", "_"))
            caps.append(("choice", attr, b, {"aliases": aliases}))
        elif t in _OFL_LEVEL:
            constant = "brightness" in cap and "brightnessStart" not in cap
            caps.append(("level", _OFL_LEVEL[t], b, {"constant": constant}))
        else:
            caps.append(("skip", "", b, {}))
    # A level prefers a band that runs (a constant "on" band only when nothing else does).
    runs = {c[1] for c in caps if c[0] == "level" and not c[3].get("constant")}
    caps = [c if not (c[0] == "level" and c[3].get("constant") and c[1] in runs) else ("skip", "", c[2], {})
            for c in caps]
    return caps


def _ofl_functions(ch: dict, name: str) -> tuple:
    caps = _ofl_caps(ch, name)
    return _build_functions(caps), tuple(c[2] for c in caps)


def _natural(key: str) -> list:
    """Sort key like OFL's localeCompare(numeric): '2' before '10', '(1, 2)' before '(1, 10)'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(key))]


def _ofl_pixels(matrix: dict) -> tuple:
    """({pixel key: (x, y, z)}, {group key: [pixel keys]}) per OFL's lib/model/Matrix.js: keys from
    `pixelKeys` (z, y, x nesting, null = no pixel) or default ones from `pixelCount` ('3' in one
    dimension, '(x, y)' in two, '(x, y, z)' in three)."""
    pos: dict = {}
    if matrix.get("pixelKeys"):
        for z, plane in enumerate(matrix["pixelKeys"], 1):
            for y, row in enumerate(plane, 1):
                for x, k in enumerate(row, 1):
                    if k:
                        pos[k] = (x, y, z)
    elif matrix.get("pixelCount"):
        nx, ny, nz = (list(matrix["pixelCount"]) + [1, 1, 1])[:3]
        axes = [a for a, n in zip("XYZ", (nx, ny, nz)) if n > 1]
        for z in range(1, nz + 1):
            for y in range(1, ny + 1):
                for x in range(1, nx + 1):
                    if len(axes) <= 1:
                        k = str(max(x, y, z))
                    elif len(axes) == 2:
                        k = f"({x if 'X' in axes else y}, {y if 'Y' in axes else z})"
                    else:
                        k = f"({x}, {y}, {z})"
                    pos[k] = (x, y, z)
    groups: dict = {}
    for g, spec in (matrix.get("pixelGroups") or {}).items():
        if isinstance(spec, list):
            groups[g] = spec
        elif spec == "all":
            groups[g] = sorted(pos, key=_natural)
        else:
            groups[g] = sorted(pos, key=_natural)   # constraint groups: membership is not needed to drive
    return pos, groups


def load_ofl(source: "str | Path | dict", manufacturer: str = "", table: Optional[dict] = None) -> Profile:
    """An Open Fixture Library fixture (its JSON file, text or parsed dict) as a Profile, overrides
    applied as load_qxf does. The manufacturer is the JSON's folder name ('chauvet-dj') unless given."""
    origin = ""
    if isinstance(source, dict):
        d = source
    elif isinstance(source, str) and source.lstrip().startswith("{"):
        d = json.loads(source)
    else:
        origin = str(source)
        d = json.loads(Path(source).read_text("utf-8"))
        manufacturer = manufacturer or Path(source).parent.name
    if "redirectTo" in d:
        to = d["redirectTo"] if isinstance(d["redirectTo"], str) else d["redirectTo"].get("fixture")
        raise ValueError(f"{d.get('name') or origin}: the library moved it to {to!r} "
                         f"({d.get('reason', 'redirect')}); load that file instead")
    if "availableChannels" not in d and "templateChannels" not in d or "modes" not in d:
        raise ValueError(f"{origin or 'that JSON'} is not an Open Fixture Library fixture")
    manufacturer = manufacturer or d.get("manufacturerKey", "") or "unknown"
    available = d.get("availableChannels", {})
    templates = d.get("templateChannels", {})
    positions, groups = _ofl_pixels(d.get("matrix") or {})
    pixel_keys = set(positions) | set(groups) | {"Master", "master", "all"} if positions or groups else set()
    fine: dict = {}
    switch: dict = {}   # alias -> (controlling channel, [(lo, hi, target channel)])
    for cname, ch in {**available, **templates}.items():
        for alias in ch.get("fineChannelAliases", ()):
            fine[alias] = cname
        for cap in ch.get("capabilities", ()):
            for alias, target in (cap.get("switchChannels") or {}).items():
                lo, hi = cap.get("dmxRange", [0, 255])
                switch.setdefault(alias, (ch, []))[1].append((lo, hi, target))

    def template_match(cname: str, names) -> Optional[tuple]:
        hits = []
        for tname in names:
            if "$pixelKey" not in tname:
                continue
            parts = re.escape(tname).split(re.escape("$pixelKey"))   # a key used twice must be one key
            pat = "^" + parts[0] + "(?P<k>.+)" + "(?P=k)".join(parts[1:]) + "$"
            m = re.match(pat, cname)
            if m and (not pixel_keys or m.group("k").strip() in pixel_keys):
                hits.append((len(tname), tname, m.group("k")))
        # the most specific template: 'White / UV $pixelKey Speed' over 'White $pixelKey'
        return max(hits, key=lambda h: h[0]) if hits else None

    def resolve(cname: str, depth: int = 0) -> tuple:
        """(channel dict, element, local name) for a channel name: plain, fine, switched or templated."""
        if depth > 4:
            raise ValueError(f"{d.get('name')}: channel {cname!r} switches in a loop")
        if cname in available:
            el, rest = _element_of(cname)
            return available[cname], el, rest
        sw, key = (cname, None) if cname in switch else (None, None)
        if sw is None:
            hit = template_match(cname, [a for a in switch if "$pixelKey" in a])
            if hit:
                sw, key = hit[1], hit[2]
        if sw is not None:   # a switching channel plays what its controller's default selects
            ctl, options = switch[sw]
            dv = ctl.get("defaultValue", 0)
            dv = int(dv) if isinstance(dv, (int, float)) else 0
            target = next((t for lo, hi, t in options if lo <= dv <= hi), options[0][2])
            if target is None:   # no channel in that state: nothing to drive
                return {}, "", cname
            return resolve(target.replace("$pixelKey", key) if key is not None else target, depth + 1)
        base_name, key = fine.get(cname), None
        if base_name is None:
            hit = template_match(cname, [a for a in fine if "$pixelKey" in a])
            if hit:
                base_name, key = fine[hit[1]].replace("$pixelKey", hit[2]), hit[2]
        if base_name is not None:
            base, el, rest = resolve(base_name, depth + 1)
            attrs = [f.attr for f in _ofl_functions(base, rest)[0] if f.attr]
            fine_attr = f"{attrs[0]}_fine" if attrs else slug(cname).replace("-", "_")
            return {"capability": {"type": "_fine", "attr": fine_attr}}, el, cname
        hit = template_match(cname, templates)
        if hit:
            _n, tname, key = hit
            return templates[tname], _pixel_element(key), tname.replace("$pixelKey", "").strip()
        raise ValueError(f"{d.get('name')} uses a channel the file does not define: {cname!r}")

    def repeat_keys(keys) -> list:
        if isinstance(keys, list):
            return keys
        if keys == "eachPixelGroup":
            return list(groups)
        if keys == "eachPixelABC":
            return sorted(positions, key=_natural)
        order = str(keys).replace("eachPixel", "")
        if sorted(order) == ["X", "Y", "Z"]:   # eachPixelXYZ: X fastest, then Y, then Z
            ix = ["XYZ".index(a) for a in order]
            return sorted(positions, key=lambda k: (positions[k][ix[2]], positions[k][ix[1]], positions[k][ix[0]]))
        raise ValueError(f"{d.get('name')}: unknown matrix order {keys!r}")

    def expand(entry) -> list:
        if entry is None:
            return [None]
        if isinstance(entry, str):
            return [entry]
        if isinstance(entry, dict) and entry.get("insert") == "matrixChannels":
            keys = repeat_keys(entry.get("repeatFor"))
            tpl = entry.get("templateChannels", [])
            fill = lambda t, k: None if t is None else t.replace("$pixelKey", k)   # noqa: E731 -- null = unused
            if entry.get("channelOrder") == "perChannel":
                return [fill(t, k) for t in tpl for k in keys]
            return [fill(t, k) for k in keys for t in tpl]
        raise ValueError(f"{d.get('name')}: unknown channel entry {entry!r}")

    modes = {}
    for m in d["modes"]:
        channels = []
        for entry in m.get("channels", []):
            for cname in expand(entry):
                if cname is None:
                    channels.append(Channel("unused", "(unused)"))
                    continue
                ch, element, rest = resolve(cname)
                if ch.get("capability", {}).get("type") == "_fine":
                    fns, bands = (Function("level", ch["capability"]["attr"]),), (Band(cname, 0, 255),)
                else:
                    fns, bands = _ofl_functions(ch, cname)
                channels.append(Channel(_channel_id(element, rest, fns), cname, element, fns, bands))
        mname = m.get("name") or f"{len(channels)}-channel"
        modes[mname] = Mode(mname, tuple(_unique_ids(channels)))
    profile = Profile(manufacturer.replace("-", " ").title() if manufacturer.islower() else manufacturer,
                      d.get("name", ""), modes, "ofl", origin, "MIT")
    return apply_overrides(profile, table)


# ---------------------------------------------------------------------------------------------
# The override layer


@lru_cache(maxsize=1)
def _overrides_doc() -> dict:
    return json.loads(OVERRIDES_FILE.read_text("utf-8")) if OVERRIDES_FILE.is_file() else {}


def overrides() -> dict:
    """fixtures/overrides.json, keyed by profile key ('chauvet/gigbar-move'); '_' keys are comments."""
    return {k: v for k, v in _overrides_doc().items() if not k.startswith("_")}


_FN_KEYS = {"kind", "attr", "lo", "hi", "neg_lo", "neg_hi", "zero", "positive", "bands", "offset",
            "aliases", "byte", "when", "unless"}


def _fn_from(spec: dict, ch: Channel) -> Function:
    """One override function, every field checked: a typo raises here, at load (and the light falls
    back to its built-in bytes), never as a wrong byte or an error on every frame."""
    where = f"{ch.name}: override function"
    if not isinstance(spec, dict):
        raise ValueError(f"{where} {spec!r} is not an object")
    if set(spec) - _FN_KEYS:
        raise ValueError(f"{where}: unknown fields {sorted(set(spec) - _FN_KEYS)}")
    kind = spec.get("kind", "level")
    if kind not in KINDS:
        raise ValueError(f"{ch.name}: unknown function kind {kind!r}")

    def byte(k: str, default: int) -> int:
        v = spec.get(k, default)
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 255:
            raise ValueError(f"{where}: {k} must be a whole number 0-255, not {v!r}")
        return v

    def names(k: str) -> tuple:
        v = spec.get(k, [])
        if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
            raise ValueError(f"{where}: {k} must be a list of channel names, not {v!r}")
        return tuple(v)

    attr = spec.get("attr", "")
    if not isinstance(attr, str) or (kind != "fixed" and not attr):
        raise ValueError(f"{where}: a {kind} needs an attr name, not {attr!r}")
    if not isinstance(spec.get("positive", False), bool):
        raise ValueError(f"{where}: positive must be true or false")
    offset = spec.get("offset")
    if offset is not None and (isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 255):
        raise ValueError(f"{where}: offset must be a whole number 0-255, not {offset!r}")
    bands = ch.bands
    if spec.get("bands") is not None:
        try:
            bands = tuple(Band(str(b[0]), int(b[1]), int(b[2])) for b in spec["bands"])
        except (TypeError, ValueError, IndexError) as e:
            raise ValueError(f"{where}: bands must be [label, lo, hi] lists ({e})") from None
    if kind == "choice" and not bands:
        raise ValueError(f"{ch.name}: a choice needs the library's bands or its own")
    al = spec.get("aliases") or {}
    if not isinstance(al, dict) or not all(isinstance(v, int) and not isinstance(v, bool) for v in al.values()):
        raise ValueError(f"{where}: aliases must map names to band numbers")
    aliases = tuple((str(k).lower(), v) for k, v in al.items())
    for _n, i in aliases:
        if not 0 <= i < len(bands):
            raise ValueError(f"{ch.name}: alias band {i} is not one of its {len(bands)} bands")
    return Function(kind, attr, byte("lo", 0), byte("hi", 255), byte("neg_lo", 0), byte("neg_hi", 0),
                    byte("zero", 0), spec.get("positive", False), bands if kind == "choice" else (),
                    offset, aliases, byte("byte", 0), names("when"), names("unless"))


def _override_channel(ch: Channel, spec: dict) -> Channel:
    element = spec.get("element", ch.element)
    functions = ch.functions
    if "hold" in spec:
        functions = (Function("fixed", byte=int(spec["hold"])),)
    elif "functions" in spec:
        functions = tuple(_fn_from(f, ch) for f in spec["functions"])
    elif "attr" in spec:
        if len({f.attr for f in functions if f.attr}) != 1:
            raise ValueError(f"{ch.name}: 'attr' renames a one-attribute channel; give 'functions' instead")
        functions = tuple(replace(f, attr=spec["attr"]) if f.attr else f for f in functions)
    out = replace(ch, element=element, functions=functions)
    _e, rest = _element_of(ch.name)
    cid = spec.get("id") or _channel_id(element, rest, functions)
    return replace(out, id=cid)


def _distinct_attributes(mode: Mode) -> Mode:
    """Two channels never share an attribute: a later channel whose attribute key an earlier one
    already drives gets a numbered one ("dim" -> "dim_2"), so one value can't set two different
    channels (QLC+'s GigBAR 2 calls its white and UV strobe dimmers both just "dim")."""
    seen: set = set()
    chans = []
    for c in mode.channels:
        mine = c.attributes
        taken = [a for a in mine if a in seen]
        if taken:
            ren = {}
            for fn in c.functions:
                if fn.attr and c.key(fn.attr) in taken and fn.attr not in ren:
                    n = 2
                    while c.key(f"{fn.attr}_{n}") in seen or c.key(f"{fn.attr}_{n}") in mine:
                        n += 1
                    ren[fn.attr] = f"{fn.attr}_{n}"
            c = replace(c, functions=tuple(replace(f, attr=ren.get(f.attr, f.attr)) for f in c.functions))
        seen.update(c.attributes)
        chans.append(c)
    return Mode(mode.name, tuple(chans))


def apply_overrides(profile: Profile, table: Optional[dict] = None) -> Profile:
    """The profile with what fixtures/overrides.json (or `table`) says about it. An override naming a
    mode or channel the library no longer has raises: a library update never quietly mis-maps a light.
    Then no two channels of a mode share an attribute (_distinct_attributes)."""
    spec = (overrides() if table is None else table).get(profile.key)
    if not spec:
        return replace(profile, modes={n: _distinct_attributes(m) for n, m in profile.modes.items()})
    renames = spec.get("elements", {})   # a part's library name -> the app's ("mover1" -> "head1")
    modes = {n: Mode(m.name, tuple(_unique_ids([
        _override_channel(c, {"element": renames[c.element]}) if c.element in renames else c
        for c in m.channels]))) for n, m in profile.modes.items()}
    for mname, mspec in (spec.get("modes") or {}).items():
        mode = replace(profile, modes=modes).mode(mname)
        names = {c.name for c in mode.channels}
        for cname in mspec.get("channels", {}):
            if cname not in names:
                raise ValueError(f"override for {profile.key} {mode.name!r} names {cname!r}, "
                                 f"which the library's mode does not have")
        chans = [_override_channel(c, mspec["channels"][c.name]) if c.name in mspec.get("channels", {}) else c
                 for c in mode.channels]
        modes[mode.name] = Mode(mode.name, tuple(_unique_ids(chans)))
    roles = dict(spec.get("roles", {}))
    bad = [r for r in [*roles.values(), spec.get("default_role", "")] if r and r not in ROLES]
    if bad:
        raise ValueError(f"override for {profile.key}: unknown role {bad[0]!r} (roles: {', '.join(ROLES)})")
    modes = {n: _distinct_attributes(m) for n, m in modes.items()}
    return replace(profile, modes=modes, notes=tuple(spec.get("notes", ())), roles=roles,
                   default_role=spec.get("default_role", ""), wireless=spec.get("wireless", ""))


# ---------------------------------------------------------------------------------------------
# Finding a profile


def library_profile(ref: "str | Path", manufacturer: str = "") -> Profile:
    """A profile by file: 'Chauvet-GigBAR-Move.qxf' (the bundled QLC+ files), any .qxf path, or an
    Open Fixture Library .json path. 'qlcplus:' and 'ofl:' prefixes say which library outright."""
    s = str(ref)
    lib = ""
    if s.startswith(("qlcplus:", "ofl:")):
        lib, s = s.split(":", 1)
    p = Path(s)
    if not p.is_absolute() and not p.exists() and (QLC_DIR / p).is_file():
        p = QLC_DIR / p
    if lib == "ofl" or (not lib and p.suffix.lower() == ".json"):
        return load_ofl(p, manufacturer)
    return load_qxf(p)


@lru_cache(maxsize=None)
def builtin_profile(kind: str) -> Profile:
    file, _mode = BUILTIN[kind]
    return load_qxf(QLC_DIR / file)


@lru_cache(maxsize=None)
def builtin_mode(kind: str) -> Mode:
    """The mode today's rig runs one of its three kinds in ('gigbar', 'tetra', 'stick')."""
    return builtin_profile(kind).mode(BUILTIN[kind][1])


# ---------------------------------------------------------------------------------------------
# A rig of profiles, addressed by role


@dataclass
class RigFixture:
    profile: Profile
    mode: Mode
    address: int              # DMX start address, 1..512
    role: str = ""            # the light's role; a part of it can play another (a GigBAR's heads)
    name: str = ""
    state: dict = field(default_factory=dict)

    def element_roles(self) -> dict:
        """{element: role} for every part of this light that has attributes. The light's own role (the
        rig entry's) is what a one-part light plays, a moving head included; a light of several parts
        plays each part's role from its profile (a GigBAR's pars wash, its heads movers), a part that
        aims plays movers, and any other part the light's role."""
        out = {}
        mine = self.role or ""
        for el, attrs in self.mode.elements().items():
            aims = bool({"pan", "tilt"} & set(attrs))
            if not el:
                out[el] = mine or ("movers" if aims else self.profile.default_role or "wash")
            elif re.sub(r"\d+$", "", el) in self.profile.roles:
                out[el] = self.profile.role_of(el, mine)
            else:
                out[el] = "movers" if aims else mine or self.profile.default_role or "wash"
        return out

    def set(self, **attrs) -> None:
        """Set attributes by their full names: fx.set(red=1.0) or fx.set(**{'par1.red': 1.0})."""
        self.state.update(attrs)

    def frame(self) -> list:
        return frame(self.mode, self.state)


class ProfileRig:
    """A rig as data: lights from any library, each at its address in its role."""

    def __init__(self, fixtures: Iterable[RigFixture]):
        self.fixtures = list(fixtures)

    def problems(self) -> list:
        """What would stop this rig playing: an unknown role, a light off the universe, two lights
        on the same channels. An empty list means it plays."""
        out = []
        taken: dict = {}
        for i, fx in enumerate(self.fixtures, 1):
            label = fx.name or f"light {i}"
            if fx.role and fx.role not in ROLES:
                out.append(f"{label}: unknown role {fx.role!r} (roles: {', '.join(ROLES)})")
            end = fx.address + fx.mode.footprint - 1
            if fx.address < 1 or end > UNIVERSE_SIZE:
                out.append(f"{label}: channels {fx.address}-{end} are outside 1-{UNIVERSE_SIZE}")
                continue
            for slot in range(fx.address, end + 1):
                if slot in taken:
                    out.append(f"{label} overlaps {taken[slot]} at channel {slot}")
                    break
            for slot in range(fx.address, end + 1):
                taken.setdefault(slot, label)
        return out

    def by_role(self, role: str) -> list:
        """[(fixture, element)] for every part of every light playing `role`."""
        if role not in ROLES:
            raise ValueError(f"unknown role {role!r} (roles: {', '.join(ROLES)})")
        return [(fx, el) for fx in self.fixtures for el, r in fx.element_roles().items() if r == role]

    def set_role(self, role: str, **attrs) -> int:
        """Set attributes (local names: red=1.0, pan=0.5) on every part playing `role`, whatever the
        light; a part without that attribute is left alone. Returns how many values were set."""
        n = 0
        for fx, el in self.by_role(role):
            have = fx.mode.elements().get(el, [])
            for a, v in attrs.items():
                if a in have:
                    fx.state[f"{el}.{a}" if el else a] = v
                    n += 1
        return n

    def clear(self) -> None:
        for fx in self.fixtures:
            fx.state.clear()

    def render(self) -> bytearray:
        universe = bytearray(UNIVERSE_SIZE)
        for fx in self.fixtures:
            start = fx.address - 1
            if start < 0 or start >= UNIVERSE_SIZE:
                continue
            chans = fx.frame()[:UNIVERSE_SIZE - start]
            universe[start:start + len(chans)] = bytes(chans)
        return universe


def load_rig(doc: dict, resolve: Callable[[str], Profile] = library_profile) -> ProfileRig:
    """{"fixtures": [{"profile": "Venue-Tetra-6.qxf", "mode": "6 Channel", "address": 81,
    "role": "wash", "name": "Tetra 1"}, ...]} as a ProfileRig. Raises ValueError naming the light
    on a bad entry; the rig's own problems() say whether it can play."""
    out = []
    cache: dict = {}
    fixtures = doc.get("fixtures", []) if isinstance(doc, dict) else None
    if not isinstance(fixtures, list):
        raise ValueError('a rig is {"fixtures": [...]}')
    for i, entry in enumerate(fixtures, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"light {i}: {entry!r} is not a light (profile, mode, address, role)")
        try:
            ref = entry["profile"]
            if ref not in cache:
                cache[ref] = resolve(ref)
            prof = cache[ref]
            if not prof.modes:
                raise ValueError(f"{prof.manufacturer} {prof.model} has no modes")
            mode = prof.mode(str(entry.get("mode") or next(iter(prof.modes))))
            address = int(entry["address"])
        except (KeyError, TypeError, ValueError, OSError, ET.ParseError) as e:
            raise ValueError(f"light {i} ({entry.get('name') or entry.get('profile')}): {e}") from e
        out.append(RigFixture(prof, mode, address, str(entry.get("role") or ""), str(entry.get("name") or "")))
    return ProfileRig(out)
