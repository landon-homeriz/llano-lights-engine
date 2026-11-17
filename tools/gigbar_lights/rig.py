"""The 12-light rig: address plan, channel maps, and the DMX universe they render into.

Address plan is the room's (gigbar-laptop-controller, "Address plan for all 12 lights").
Channel orders come from the QLC+ fixture library (mcallegari/qlcplus resources/fixtures),
cross-checked against the GigBAR Move 35CH map the room took from Chauvet's manual Rev. 4:
  GigBAR Move 35-channel, Venue Tetra 6 "6 Channel", Chauvet Freedom Stick "8 Channel".

A look never writes channel numbers. It sets named attributes on fixtures (red, pan,
strobe, ...) as 0.0 to 1.0, and each fixture class owns the translation to DMX bytes.

Where those bytes land is data (2026-11-08): the settings' `rig` block (settings_contract.py)
holds each light's start address, each fixture type's channel order by name, which GigBAR head
is which and each head's pan/tilt invert and swap. It syncs from llano.app like the rest of the
settings and is read on every frame, so a mapping fix needs no app update. Its defaults are the
plan below, byte for byte.

Which byte each named attribute becomes is the fixture library's (2026-11-17, Llano BL #12136):
fixture_profiles reads the three QLC+ files in fixtures/qlcplus plus fixtures/overrides.json, and
place() encodes each light's attributes() through them. The channels() methods below are the
hand-written encoding the library replaced; LLANO_LIGHTS_PROFILES=0 (or a library file that will
not load) sends them again, and test_fixture_profiles.py pins the two byte for byte.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import fixture_profiles, show_settings
from .settings_contract import CHANNEL_NAMES, FIXTURES, HEAD_FLAGS

UNIVERSE_SIZE = 512
# The rig picker (1.13.0, his 11-08 "I've only got 3 tetras running right now"): how many of each
# kind are set up tonight, the first N of each; settings rig.counts, kept by settings_contract.
KINDS = (("bars", 2), ("tetras", 6), ("sticks", 4))


def _byte(x: float) -> int:
    return max(0, min(255, int(round(x * 255))))


def _in_range(lo: int, hi: int, x: float) -> int:
    """Map 0..1 onto the DMX sub-range lo..hi (a fixture's 'slow to fast' band)."""
    x = max(0.0, min(1.0, x))
    return int(round(lo + (hi - lo) * x))


@dataclass
class Par:
    """One of the GigBAR's two pars: RGB + UV + a shared dimmer/strobe channel."""
    red: float = 0.0
    green: float = 0.0
    blue: float = 0.0
    uv: float = 0.0
    dim: float = 0.0
    strobe: float = 0.0  # 0 = steady; >0 = strobe slow..fast

    def channels(self) -> list[int]:
        # Shutter channel: 0-127 dimmer 0-100%, 128-239 strobe slow-fast.
        shutter = _in_range(128, 239, self.strobe) if self.strobe > 0 else _in_range(0, 127, self.dim)
        return [_byte(self.red), _byte(self.green), _byte(self.blue), _byte(self.uv), shutter]


# Derby color wheel bands (0-24 blackout, then 25-wide bands). yellow/magenta/cyan/white are the
# manual's red+green, red+blue, green+blue and red+green+blue; auto = single colors, auto2 = two.
DERBY_COLORS = {
    "off": 0, "red": 25, "green": 50, "blue": 75, "yellow": 100,
    "magenta": 125, "cyan": 150, "white": 175, "auto": 200, "auto2": 225,
}


def _rotate(x: float) -> int:
    """-1..1 onto a derby / laser rotation channel: 5-127 clockwise, 134-255 counter-clockwise."""
    if x > 0:
        return _in_range(5, 127, x)
    if x < 0:
        return _in_range(134, 255, -x)
    return 0


@dataclass
class Derby:
    color: str = "off"
    strobe: float = 0.0
    rotate: float = 0.0  # -1..1, negative = counter-clockwise

    def channels(self) -> list[int]:
        strobe = _in_range(10, 239, self.strobe) if self.strobe > 0 else 0
        return [DERBY_COLORS[self.color] + 5, strobe, _rotate(self.rotate)]


# Ch17 bands (manual Rev. 3/4, QLC+): both = red + green; red_flash = green on with red strobing,
# green_flash = red on with green strobing, alternate = red and green strobing in turn.
ALL_STROBING = 200   # ch20 190-209: all 4 strobes flashing (manual Rev. 3/4)
LASER_COLORS = {"off": 0, "red": 40, "green": 80, "both": 120, "red_flash": 160, "green_flash": 200,
                "alternate": 240}


# The moving heads' real color wheel, by slot (Mover.color; DMX slot*32+4). Neither Chauvet's
# 35CH chart nor QLC+ names the slots ("Color 1".."Color 7"), so until 1.20 the app guessed a
# rainbow order and every dot but white and orange lit the wrong color. This order is what the
# operator saw on the real GigBAR Move heads, pressing each dot (Llano BL #12147, 2026-11-13).
HEAD_WHEEL = (("White", "#ffffff"), ("Dark blue", "#2040ff"), ("Orange", "#ff9020"), ("Red", "#ff3030"),
              ("Light blue", "#40c8ff"), ("Yellow", "#ffe030"), ("Green", "#30ff60"), ("Purple", "#a040ff"))
# The order a screen lists them in (rainbow, like the rest of the app): each entry is a slot above.
HEAD_DOT_ORDER = (0, 3, 2, 5, 6, 4, 1, 7)


def head_slot(name: str) -> int:
    """A color's wheel slot by its name ("red" -> 3); ValueError for a color the wheel lacks."""
    for i, (n, _hex) in enumerate(HEAD_WHEEL):
        if n.lower() == name.strip().lower():
            return i
    raise ValueError(f"the moving heads have no {name!r} on their wheel")


@dataclass
class Mover:
    pan: float = 0.5   # 540 degrees across 0..1
    tilt: float = 0.5  # 180 degrees across 0..1
    dim: float = 0.0
    strobe: float = 0.0
    color: int = 0     # 0 = open, 1..7 wheel slots
    gobo: int = 0      # 0 = open, 1..7

    def channels(self) -> list[int]:
        strobe = _in_range(10, 255, self.strobe) if self.strobe > 0 else 0
        return [_byte(self.pan), _byte(self.tilt), _byte(self.dim), strobe,
                self.color * 32 + 4, self.gobo * 32 + 4]


@dataclass
class GigBarMove:
    """Chauvet GigBAR Move in 35CH mode (the only mode with per-head pan/tilt/color/gobo)."""
    name: str
    address: int
    pars: list[Par] = field(default_factory=lambda: [Par(), Par()])
    derbies: list[Derby] = field(default_factory=lambda: [Derby(), Derby()])
    laser: str = "off"
    laser_strobe: float = 0.0  # ch18: 0 = steady, >0 = strobe slow..fast
    laser_rotate: float = 0.0  # ch19: -1..1, negative = counter-clockwise
    strobe_program: int = 0    # ch20: 0 off, 1-9 the bar's own strobe programs, 10 all strobing
    strobe_white: float = 0.0  # ch21 white strobe level
    strobe_uv: float = 0.0     # ch22 UV strobe level; the manual: ch21 and ch22 can't be used together
    strobe_speed: float = 0.0
    movers: list[Mover] = field(default_factory=lambda: [Mover(), Mover()])
    footprint = 35
    kind = "gigbar"

    def channels(self) -> list[int]:
        out: list[int] = []
        for p in self.pars:
            out += p.channels()                     # 1-10
        for d in self.derbies:
            out += d.channels()                     # 11-16
        laser_strobe = _in_range(10, 239, self.laser_strobe) if self.laser_strobe > 0 else 0
        out += [LASER_COLORS[self.laser] + 5, laser_strobe, _rotate(self.laser_rotate)]  # 17-19
        prog = max(0, min(10, int(self.strobe_program)))
        white = _byte(self.strobe_white)
        uv = 0 if white else _byte(self.strobe_uv)   # white wins: never both at once
        # Ch20 0-9 is the strobes' blackout (manual Rev. 3/4, 35CH): until 1.14.1 the show sent 0
        # there under every white or UV level, so the 4 strobes never flashed. With no program
        # chosen, a white or UV level now runs "All strobing" (190-209) at ch21/22's level and ch23's speed.
        ctl = prog * 20 - 5 if prog else (ALL_STROBING if white or uv else 0)
        out += [ctl, white, uv, _byte(self.strobe_speed)]  # 20-23
        for m in self.movers:
            out += m.channels()                     # 24-35
        assert len(out) == self.footprint
        return out

    def attributes(self) -> dict:
        """Every named attribute, as the fixture library reads them (fixture_profiles.encode)."""
        a: dict = {}
        for i, p in enumerate(self.pars, 1):
            a.update({f"par{i}.red": p.red, f"par{i}.green": p.green, f"par{i}.blue": p.blue,
                      f"par{i}.uv": p.uv, f"par{i}.dim": p.dim, f"par{i}.strobe": p.strobe})
        for i, d in enumerate(self.derbies, 1):
            a.update({f"derby{i}.color": d.color, f"derby{i}.strobe": d.strobe, f"derby{i}.rotate": d.rotate})
        a.update({"laser.color": self.laser, "laser.strobe": self.laser_strobe, "laser.rotate": self.laser_rotate,
                  "strobe.program": max(0, min(10, int(self.strobe_program))),
                  "strobe.white": self.strobe_white, "strobe.uv": self.strobe_uv,
                  "strobe.speed": self.strobe_speed})
        for i, m in enumerate(self.movers, 1):
            a.update({f"head{i}.pan": m.pan, f"head{i}.tilt": m.tilt, f"head{i}.dim": m.dim,
                      f"head{i}.strobe": m.strobe, f"head{i}.color": m.color, f"head{i}.gobo": m.gobo})
        return a


@dataclass
class Tetra6:
    """Venue Tetra 6 in 6c mode: R, G, B, Amber, Dimmer, Strobe."""
    name: str
    address: int
    red: float = 0.0
    green: float = 0.0
    blue: float = 0.0
    amber: float = 0.0
    dim: float = 0.0
    strobe: float = 0.0
    footprint = 6
    kind = "tetra"

    def channels(self) -> list[int]:
        strobe = _in_range(10, 255, self.strobe) if self.strobe > 0 else 0
        return [_byte(self.red), _byte(self.green), _byte(self.blue), _byte(self.amber),
                _byte(self.dim), strobe]

    def attributes(self) -> dict:
        return {"red": self.red, "green": self.green, "blue": self.blue, "amber": self.amber,
                "dim": self.dim, "strobe": self.strobe}


@dataclass
class FreedomStick:
    """Chauvet Freedom Stick in 8-CH mode, reached over D-Fi through the Hub 2."""
    name: str
    address: int
    red: float = 0.0
    green: float = 0.0
    blue: float = 0.0
    dim: float = 0.0
    strobe: float = 0.0
    footprint = 8
    kind = "stick"

    def channels(self) -> list[int]:
        strobe = _in_range(11, 255, self.strobe) if self.strobe > 0 else 0
        # 5 color macro, 7 auto program and 8 speed stay at 0 (no function) so the
        # stick follows our RGB and never runs its own show.
        return [_byte(self.dim), _byte(self.red), _byte(self.green), _byte(self.blue),
                0, strobe, 0, 0]

    def attributes(self) -> dict:
        # macro, program and speed are held at 0 by the library's override layer, not set here
        return {"dim": self.dim, "red": self.red, "green": self.green, "blue": self.blue, "strobe": self.strobe}


@dataclass
class Rig:
    bars: list[GigBarMove]
    tetras: list[Tetra6]
    sticks: list[FreedomStick]

    @property
    def fixtures(self) -> list:
        return [*self.bars, *self.tetras, *self.sticks]

    def present(self, counts=None) -> "Rig":
        """The lights set up tonight (rig.counts), the first N of each kind: the same fixture
        objects, so a look that sets them sets this rig. Addresses never move."""
        n = active_counts(counts)
        return Rig(self.bars[:n["bars"]], self.tetras[:n["tetras"]], self.sticks[:n["sticks"]])

    def render(self, config: "dict | None" = None) -> bytearray:
        """Return the 512-slot DMX universe (slot 1 at index 0), laid out by the rig block
        (`config`, else the settings in force). A light not set up tonight (rig.counts) sends
        nothing: its slots stay 0."""
        cfg = config if config is not None else show_settings.current()["rig"]
        on = {id(fx) for fx in self.present(cfg.get("counts")).fixtures}
        universe = bytearray(UNIVERSE_SIZE)
        for fid, fx in zip(FIXTURES, self.fixtures):
            if id(fx) not in on:
                continue
            chans = place(fx, fid, cfg)
            start = cfg["addresses"][fid] - 1
            chans = chans[:UNIVERSE_SIZE - start]
            universe[start:start + len(chans)] = bytes(chans)
        return universe

    def reset(self) -> None:
        """Everything dark, movers parked at center; nothing strobing. In place: a fixture held
        across a reset (Test each light walks rig.fixtures) is still the one that renders."""
        fresh = default_rig()
        pairs = [*zip(self.bars, fresh.bars), *zip(self.tetras, fresh.tetras), *zip(self.sticks, fresh.sticks)]
        for mine, new in pairs:   # kind by kind, so a present() view resets its own lights
            name, address = mine.name, mine.address
            mine.__dict__.update(new.__dict__)
            mine.name, mine.address = name, address


def place(fx, fid: str, cfg: dict) -> list[int]:
    """One fixture's bytes in the order its channel list (the rig block) names them."""
    named = named_bytes(fx)
    _head_flags(named, cfg["heads"].get(fid))
    return [int(n[1:]) if n.startswith("=") else named[n] for n in cfg["channels"][fx.kind]]


_log = logging.getLogger(__name__)
_PROFILE_MODES: dict = {}


def profile_mode(kind: str):
    """The fixture library's mode for one of today's kinds, or None when it cannot drive it: a
    library file missing or unreadable, or channels that are not this kind's CHANNEL_NAMES (the
    rig block's channel lists name them). Read once; None means the hand-written bytes."""
    if kind not in _PROFILE_MODES:
        try:
            mode = fixture_profiles.builtin_mode(kind)
            if mode.ids != CHANNEL_NAMES[kind]:
                raise ValueError(f"channels {mode.ids} are not {CHANNEL_NAMES[kind]}")
        except Exception as e:  # noqa: BLE001 -- ok: never dark over a library file; said in the log
            _log.warning("fixture library cannot drive %s (%s); sending the built-in bytes", kind, e)
            mode = None
        _PROFILE_MODES[kind] = mode
    return _PROFILE_MODES[kind]


def named_bytes(fx) -> dict:
    """A light's DMX bytes by channel name (CHANNEL_NAMES order): through the fixture library, or
    the hand-written channels() when LLANO_LIGHTS_PROFILES=0 or the library cannot drive it. A library
    that fails mid-show sends the hand-written bytes from then on (logged), never a dark frame."""
    mode = profile_mode(fx.kind) if fixture_profiles.enabled() else None
    if mode is not None:
        try:
            return fixture_profiles.encode(mode, fx.attributes())
        except Exception as e:  # noqa: BLE001 -- ok: the built-in bytes for this kind from now on; logged
            _log.warning("fixture library failed on %s (%s); sending the built-in bytes", fx.kind, e)
            _PROFILE_MODES[fx.kind] = None
    return dict(zip(CHANNEL_NAMES[fx.kind], fx.channels()))


def profile_rig(rig: "Rig | None" = None, config: "dict | None" = None) -> "fixture_profiles.ProfileRig":
    """Today's lights as a rig of library profiles (profile, mode, address, role), each light's state
    read live from `rig` (default_rig() when none) and placed by the rig block (`config`, else the
    settings in force): its addresses, and only the lights set up tonight (counts). Anything built on
    ProfileRig drives his lights as it would any DJ's. Roles: the GigBARs' parts by the library's
    override (pars wash, derbies and laser effects, strobes strobes, heads movers); Tetras and sticks
    wash. The rig block's channel-order and head-flag rewrites stay Rig.render's: under the default
    channel lists and head flags the two render the same universe (test_fixture_profiles.py).
    Raises when the library can't load: this is the data view, not the live output."""
    rig = rig or default_rig()
    cfg = config if config is not None else show_settings.current()["rig"]
    on = {id(fx) for fx in rig.present(cfg.get("counts")).fixtures}
    out = []
    for fid, fx in zip(FIXTURES, rig.fixtures):
        if id(fx) not in on:
            continue
        mode = fixture_profiles.builtin_mode(fx.kind)
        out.append(_LiveFixture(fixture_profiles.builtin_profile(fx.kind), mode, cfg["addresses"][fid],
                                "wash", fx.name, fx))
    return fixture_profiles.ProfileRig(out)


class _LiveFixture(fixture_profiles.RigFixture):
    """A RigFixture whose state is one of rig.py's lights, read at render time."""

    def __init__(self, profile, mode, address, role, name, light):
        super().__init__(profile, mode, address, role, name)
        self.light = light

    def frame(self) -> list:
        state = self.light.attributes()
        state.update(self.state)   # set_role/set on top of the light's own values
        return fixture_profiles.frame(self.mode, state)


def _head_flags(named: dict, heads: "dict | None") -> None:
    """A bar's head settings, in place: swap the heads, invert pan or tilt, swap pan and tilt. Works
    on bytes (place) and on the room picture's unrounded values (head_picture) alike."""
    if not heads:
        return
    if heads["swap_heads"]:   # the engine's head 1 goes out on head 2's channels, and back
        for c in ("pan", "tilt", "dim", "strobe", "color", "gobo"):
            if f"head1.{c}" in named:
                named[f"head1.{c}"], named[f"head2.{c}"] = named[f"head2.{c}"], named[f"head1.{c}"]
    for h in ("head1", "head2"):
        flags = heads[h]
        if flags["pan_invert"]:
            named[f"{h}.pan"] = 255 - named[f"{h}.pan"]
        if flags["tilt_invert"]:
            named[f"{h}.tilt"] = 255 - named[f"{h}.tilt"]
        if flags["pan_tilt_swap"]:
            named[f"{h}.pan"], named[f"{h}.tilt"] = named[f"{h}.tilt"], named[f"{h}.pan"]


def head_picture(heads: dict, config: "dict | None" = None) -> dict[int, float]:
    """The universe slots of every GigBAR head's pan and tilt, as unrounded 0..255 values, for the
    room picture (1.16.3): `heads` maps (bar index, head index) to (pan, tilt) raw 0..1, and each
    lands on the slot Rig.render would put its byte in, through the same head settings."""
    cfg = config if config is not None else show_settings.current()["rig"]
    names = cfg["channels"]["gigbar"]
    out: dict[int, float] = {}
    for b, fid in enumerate(f for f in FIXTURES if f.startswith("bar")):
        if fid not in cfg["addresses"]:
            continue
        named = {}
        for m in (0, 1):
            pan, tilt = heads.get((b, m), (None, None))
            if pan is None:
                break
            named[f"head{m + 1}.pan"], named[f"head{m + 1}.tilt"] = pan * 255.0, tilt * 255.0
        else:
            _head_flags(named, cfg["heads"].get(fid))
            start = cfg["addresses"][fid] - 1
            for i, n in enumerate(names):
                if n in named and start + i < UNIVERSE_SIZE:
                    out[start + i] = named[n]
    return out


assert set(HEAD_FLAGS) == {"pan_invert", "tilt_invert", "pan_tilt_swap"}


def default_rig() -> Rig:
    """The room's plan: round-ten start addresses with room to spare."""
    return Rig(
        bars=[GigBarMove("GigBAR Move 1", 1), GigBarMove("GigBAR Move 2", 41)],
        tetras=[Tetra6(f"Tetra 6 #{i + 1}", 81 + 10 * i) for i in range(6)],
        sticks=[FreedomStick(f"Freedom Stick #{i + 1}", 151 + 10 * i) for i in range(4)],
    )


def active_counts(counts) -> dict:
    """How many of each kind run: rig.counts clamped to the rig, every light when unset."""
    counts = counts if isinstance(counts, dict) else {}
    out = {}
    for kind, most in KINDS:
        v = counts.get(kind, most)
        out[kind] = max(0, min(most, v)) if isinstance(v, int) and not isinstance(v, bool) else most
    return out
