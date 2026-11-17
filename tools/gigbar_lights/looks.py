"""The looks engine: turns beat position + song section into a state for all 12 lights.

What it matches from SoundSwitch (room: "What SoundSwitch's shows do"):
- every change locks to the beat grid and follows the deck (tempo, pause, loops, cues);
- scripted mode: a look per song section, with new colors and positions at each section
  start; builds rise (beams tilt up, the pulse subdivides 1 > 1/2 > 1/4, intensity climbs);
  the drop hits on beat one (white strobe burst, full rig, new palette); sudden silence
  goes dark;
- autoloop mode when a track has no script: 8-bar looks cycling on bar lines, with
  hold/next/previous, plus an override that forces autoloops over a script;
- Loop Auto-Strobe: a DJ loop or roll of 1/2 beat or less strobes white while it is held;
- fixture roles (primary wash, secondary wash, effects, movers, strobe), so groups do
  different things instead of everything firing together (a common SoundSwitch complaint);
- named mover positions ("booth", "crowd", ...) re-aimable per venue without touching looks;
  with a venue layout (venue.py) each head aims from where it really sits, and chases and
  left/right moves follow where each light stands in the room;
- derbies have no dimmer, so "off" for them is the black color slot;
- manual overrides: blackout, strobe, color hold, master intensity;
- his settings (show_settings.py, editable here and live from Llano): palettes, which palette
  each section uses, saturation, drop and strobe strength, autoloop looks and bars, overall
  brightness, and (1.4.0) the show itself per section: wash/mover levels, pulse depth,
  strobe, derby and laser on or off, bars per color change, and the move between NAMED
  positions (shape, from, to, size, beats, spread), so a venue layout still re-aims it.
  A song filed under a saved style plays that style; a draft Llano asked to play wins over
  both until it expires. Read once per frame, so a change lands on the next frame; the
  defaults encode the constants and moves below, so with no settings the show is exactly
  what it always was.

Roles on this rig: Tetras = primary wash; Freedom Sticks = secondary wash; GigBAR pars =
accent wash; derbies + laser = effects; GigBAR moving heads = movers; GigBAR white strobe =
strobe.
"""
from __future__ import annotations

import colorsys
import math
import os
import random
from dataclasses import dataclass, field, replace
from typing import Optional

from . import settings_contract as contract
from . import show_settings, song_match
from .rig import Rig, active_counts
from .settings_contract import STYLE_KEYS
from . import venue
from .show_script import Section

# The part-of-the-night limit (1.20.0, his rule 2026-11-13): cocktail hour and dinner are a soft warm
# wash only. No moving heads on people, no spotlights, no strobe, no laser, whatever look a design,
# Llano or a hand pick gave the song. It is applied twice: to the settings the frame plays from
# (soft_settings, so the wash looks right) and to the frame itself as it leaves (soften, so nothing
# an autoloop, a drop burst or a loop strobe lit gets through).
SOFT_WASH, SOFT_PULSE, SOFT_DROP = 0.7, 0.25, 0.4


def soft_settings(cfg: dict) -> dict:
    """`cfg` (the settings a frame plays from) held to a soft wash."""
    out = dict(cfg)
    secs = {}
    for name, sec in (cfg.get("sections") or {}).items():
        secs[name] = {**sec, "movers": 0.0, "strobe": 0.0, "derby": False, "laser": False,
                      "pulse": min(float(sec.get("pulse", 1.0)), SOFT_PULSE),
                      "wash": min(float(sec.get("wash", 1.0)), SOFT_WASH),
                      "move": {**(sec.get("move") or {}), "shape": "hold"}}
    out["sections"] = secs
    out["drop"] = {**(cfg.get("drop") or {}), "intensity": min(float((cfg.get("drop") or {}).get("intensity", 1.0)), SOFT_DROP),
                   "burst": False}
    out["strobe"] = {**(cfg.get("strobe") or {}), "intensity": 0.0, "build_ramp": False, "loop_auto": False}
    return out


def soften(rig: Rig) -> None:
    """The backstop: whatever was asked for, only a steady soft wash leaves this frame. Moving heads
    dark (so no beam on a guest and no spotlight), derbies, laser and every strobe off."""
    for bar in rig.bars:
        for m in bar.movers:
            m.dim, m.strobe = 0.0, 0.0
        for d in bar.derbies:
            d.color, d.strobe, d.rotate = "off", 0.0, 0.0
        bar.laser, bar.laser_strobe, bar.laser_rotate = "off", 0.0, 0.0
        bar.strobe_program, bar.strobe_white, bar.strobe_uv, bar.strobe_speed = 0, 0.0, 0.0, 0.0
        for p in bar.pars:
            p.strobe, p.dim = 0.0, min(p.dim, SOFT_WASH)
    for fx in (*rig.tetras, *rig.sticks):
        fx.strobe, fx.dim = 0.0, min(fx.dim, SOFT_WASH)


# Moving heads only in Dancing (Llano BL #12339, his rule 2026-11-14): a hold or a moment's song that
# is not Dancing plays its look with every moving head dark and still. Applied the same two ways as
# the soft limit: to the settings (still_settings) and to the frame as it leaves (still_heads).
def still_settings(cfg: dict) -> dict:
    """`cfg` with the moving heads off and holding still; the rest of the look as it was."""
    out = dict(cfg)
    out["sections"] = {name: {**sec, "movers": 0.0, "move": {**(sec.get("move") or {}), "shape": "hold"}}
                       for name, sec in (cfg.get("sections") or {}).items()}
    return out


def still_heads(rig: Rig) -> None:
    """The backstop: every moving head dark (no beam, no spot, no strobe) whatever lit it."""
    for bar in rig.bars:
        for m in bar.movers:
            m.dim, m.strobe = 0.0, 0.0


# The first dance and the parent dances (changed 2026-11-14: the heads move on their
# own in the dances): the heads move by themselves, but gently. One slow glide on the dance floor
# between the front of the booth and the middle of the floor, never up toward eyes or out over the
# tables (no "fan", "cross" or "ceiling"), no strobe, at most GENTLE_HEADS bright. Since 1.35 "crowd"
# spans the floor's whole width (venue.Layout._wide), so the glide fans out across the floor; it still
# never tilts past "crowd", the couple's eyes (Llano PM #23789 kept that rule).
GENTLE_HEADS = 0.6
SPOT_ROOM = 0.5   # a spotlight look's wash, as a share of the look's own (Llano PM #23789)


def spot_bright() -> bool:
    """Spotlight looks at full head level with the wash dipped (Llano PM #23789). LLANO_LIGHTS_SPOT_BRIGHT=0
    puts back 1.34's levels without a build."""
    return (os.environ.get("LLANO_LIGHTS_SPOT_BRIGHT") or "").strip().lower() not in ("0", "off", "false", "no")

GENTLE_MOVE = {"shape": "glide", "from": "booth", "to": "crowd", "size": 0.3, "beats": 32, "spread": "mirror"}


def gentle_settings(cfg: dict) -> dict:
    """`cfg` with the moving heads on one slow glide over the dance floor; the rest of the look as it was."""
    out = dict(cfg)
    out["sections"] = {name: {**sec, "movers": min(GENTLE_HEADS, max(0.45, float(sec.get("movers") or 0.0))),
                              "move": dict(GENTLE_MOVE)}
                       for name, sec in (cfg.get("sections") or {}).items()}
    return out


def gentle_heads(rig: Rig) -> None:
    """The backstop: no head strobes or shines brighter than GENTLE_HEADS, whatever lit it."""
    for bar in rig.bars:
        for m in bar.movers:
            m.dim, m.strobe = min(m.dim, GENTLE_HEADS), 0.0


# Palettes are (hue, hue) pairs: primary wash and secondary wash/accent, 0..1 hue.
# These are the defaults; the show reads them from settings (settings_contract.DEFAULTS).
PALETTES = {
    "warm": [(0.02, 0.08), (0.95, 0.06), (0.08, 0.0)],          # amber, red, magenta-red
    "cool": [(0.62, 0.50), (0.70, 0.55), (0.55, 0.78)],          # blue, cyan, violet
    "hot": [(0.33, 0.83), (0.0, 0.62), (0.15, 0.75), (0.83, 0.5), (0.58, 0.08)],
    # intro / outro: soft but clearly different colors (until 1.2.3 they used "warm", all reds)
    "calm": [(0.08, 0.75), (0.58, 0.08), (0.83, 0.50), (0.42, 0.75)],  # amber+violet, blue+amber, magenta+cyan, green+violet
}
SECTION_PALETTE = {"intro": "calm", "verse": "warm", "build": "cool", "drop": "hot",
                   "main": "hot", "breakdown": "cool", "outro": "calm"}
# How often colors step, how the movers travel, levels, derby and laser come per section
# from the settings (settings_contract SECTION_DEFAULTS: today's show, encoded).
LONG_INTRO_BEATS = 64  # past 16 bars a held "intro" is really a groove: it moves like a verse
FIGURES = ("circle", "eight", "line")
FIGURE_PAN = 180.0 / 540.0   # raw pan per raw tilt for the same angle (GigBAR: 540 pan, 180 tilt)

# Mover positions per head as (pan, tilt), 0..1. Re-aim these per venue. The heads hang under
# the bar (venue.py): tilt 0.5 is straight down and 1 is level toward the front, so every
# position tilts at or above 0.5. Before 1.10.1 these read tilt 0.5 as level: "booth" pointed
# back under the bar, and "crowd", "fan", "cross" and "ceiling" tipped past straight down to
# the wall behind it. "ceiling" is now "as high as safe", a beam just under level.
# The arrival line-up check: its known spots (venue.Layout.targets) and each head's wheel color.
LINEUP_SPOTS = {"center": "the middle of the dance floor", "booth": "the front of the DJ booth", "down": "straight down",
                "middle": "DMX middle (pan 128, tilt 128)"}
# "middle" is raw, not aimed (his 11-09 note: the heads power up facing straight ahead): every head
# at the middle of its pan and tilt, so he can see whether that is the power-up pose.

CAL_OTHERS = 0.15   # while one head is calibrated the others glow this dim, so he can tell them apart

# The Freedom Sticks' lift (his 11-15 report "the sticks look really dim", rev #93 at master 1.0 and
# wash 1.0). The looks write the sticks as the secondary wash, so in his A&J Wedding show their
# dimmer byte averaged 50 to 140 of 255 (verse 140, slow-dance 98, a build 50), under the Tetras in
# every section, on a fixture with far less light than a Tetra. Every look's stick level now goes
# out raised to this power before master: 0 stays 0 and 1 stays 1, so a pulse or chase still reads,
# but 0.55 leaves at 0.74 and 0.38 at 0.62. The lift is on the look's own shape only: the section wash
# and drop intensity stay linear (wash 0.5 still halves the sticks), and master, the studio's Sticks
# fader and the cocktail-hour soft-wash cap apply after it. 1.0 (or LLANO_LIGHTS_STICK_LIFT=0 on the
# laptop) puts back the old levels.
STICK_LIFT = 0.5


def stick_lift() -> float:
    """STICK_LIFT unless LLANO_LIGHTS_STICK_LIFT=0, which sends the sticks the looks' levels as they were."""
    off = (os.environ.get("LLANO_LIGHTS_STICK_LIFT") or "1").strip().lower() in {"0", "off", "false", "no"}
    return 1.0 if off else STICK_LIFT

DEFAULT_POSITIONS = {
    "home": [(0.5, 0.75), (0.5, 0.75)],
    "booth": [(0.5, 0.62), (0.5, 0.62)],
    "crowd": [(0.42, 0.80), (0.58, 0.80)],
    "fan": [(0.30, 0.86), (0.70, 0.86)],
    "ceiling": [(0.5, 0.97), (0.5, 0.97)],
    "cross": [(0.62, 0.83), (0.38, 0.83)],
}
# Without a venue the sweep look swings fan <-> cross, as it always has.
DEFAULT_POSITIONS["sweep_left"] = DEFAULT_POSITIONS["fan"]
DEFAULT_POSITIONS["sweep_right"] = DEFAULT_POSITIONS["cross"]


def rgb(hue: float, sat: float = 1.0) -> tuple[float, float, float]:
    return colorsys.hsv_to_rgb(hue % 1.0, sat, 1.0)


def pulse(phase: float, sharpness: float = 4.0) -> float:
    """1.0 on the hit, decaying through the rest of the subdivision."""
    return math.exp(-sharpness * (phase % 1.0))


def ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


# Fluid travel (Llano BL #12400, the 11-14 report: the heads paused mid-sweep instead of sweeping fluidly).
# A GigBAR head takes one 8-bit pan and tilt and its motor runs each DMX step at full speed, so the glide
# (glide.py, No crawling) holds a target moving slower than CRAWL_STEPS a second and catches up in short moves.
# On a slow glide or sweep that is a stop every second or two half way across (his Stage room on 1.26.4, a verse
# glide: 32-41 stops of 0.2 s or more a minute mid-sweep, the longest 1.25 s). Such a leg now travels at an even
# pace the glide tracks frame for frame, the axis that moves most at FLUID_STEPS a second and every other axis
# moving CARRY_STEPS or more no slower than CARRY_FLUID (so none is held mid-travel), and rests at both ends for
# the time that saves: the same two spots and the same beats per leg, the stop where the sweep turns round, and
# the glide's acceleration limit eases each start and stop. A leg already that fast plays as before, byte for
# byte. Kill switch: LLANO_LIGHTS_FLUID_TRAVEL=0 (1.27.0's slow legs).
FLUID_STEPS = 22.0   # DMX steps a second, the axis that moves most
CARRY_STEPS = 6.0    # every other axis moving this many steps or more in a leg (glide.PAN_GATE_STEPS) ...
CARRY_FLUID = 14.0   # ... travels at least this fast, above glide.CRAWL_STEPS, so the glide tracks it too
LEG_PEAK = {"glide": 1.5, "sweep": 0.75 * math.pi}   # a leg's peak speed over its average (ease; ease of a sine)


def fluid_travel() -> bool:
    """Fluid travel (above) unless LLANO_LIGHTS_FLUID_TRAVEL=0."""
    return (os.environ.get("LLANO_LIGHTS_FLUID_TRAVEL") or "1").strip().lower() not in {"0", "off", "false", "no"}


def travel_share(shape: str, travels, beats: float, bpm: float) -> float:
    """The share of each leg a glide or sweep spends travelling at an even pace (Fluid travel), or 1: the leg
    plays as before, eased over all of it. `travels` is each head axis's travel in DMX steps in a leg of
    `beats` at `bpm`. A leg is fluid when the axis that moves most would peak under FLUID_STEPS eased over the
    whole leg (a faster leg, a fast look, is left alone); it then travels as long as keeps that axis at
    FLUID_STEPS and every axis moving CARRY_STEPS or more at CARRY_FLUID or faster."""
    travels = [t for t in travels if t > 0]
    if shape not in LEG_PEAK or not fluid_travel() or bpm <= 0 or beats <= 0 or not travels:
        return 1.0
    leg = beats * 60.0 / bpm
    if LEG_PEAK[shape] * max(travels) / leg >= FLUID_STEPS:
        return 1.0
    return min([max(travels) / FLUID_STEPS] + [x / CARRY_FLUID for x in travels if x >= CARRY_STEPS]) / leg


def leg_mix(shape: str, beat: float, n: float, q: float = 1.0) -> float:
    """Where a glide or sweep is between its two spots, eased (0..1): over each whole leg of `n` beats as before,
    or (q < 1, Fluid travel) at an even pace over the middle `q` of the leg, resting at the ends for the rest."""
    if q >= 1.0:
        return ease((beat % n) / n) if shape == "glide" else ease(0.5 + 0.5 * math.sin(beat / n * math.pi))
    if shape == "glide":
        return min(1.0, max(0.0, ((beat % n) / n - (1.0 - q) / 2) / q))
    u = beat / n + 0.5            # sweep: leg k runs from u = k (one end) to k + 1 (the other)
    leg = math.floor(u)
    w = min(1.0, max(0.0, (u - leg - (1.0 - q) / 2) / q))
    return w if leg % 2 == 0 else 1.0 - w


@dataclass
class Overrides:
    blackout: bool = False
    strobe: bool = False                 # held strobe button
    color_hold: Optional[float] = None   # hue to pin every wash to
    autoloop_override: bool = False      # autoloops even when a script exists
    hold_loop: bool = False              # repeat the current autoloop
    loop_shift: int = 0                  # next/previous autoloop
    master: float = 1.0                  # overall intensity
    scene: Optional[str] = None          # a scene pad pressed on this laptop (the newest press wins: active_scene)
    lineup: Optional[tuple] = None       # (bar 0|1|2, spot): the arrival line-up check (1.7.0); 0 = both
    raw_head: Optional[tuple] = None     # (bar, head, pan, tilt): calibrating one head by raw values (1.12.1)
    lights_on: bool = True               # line-up / calibration: the heads lit white, or dark (1.12.3)
    lights_whole: bool = False           # ... and with them every other part of the bar (1.14.1)
    # Line up my lights, one spot (1.16.0): {"poses": {(bar, head): (pan, tilt)}, "focus": (bar, head)
    # or None, "others": dimmer of the heads not in focus}. Only these heads are lit, nothing else.
    aim_set: Optional[dict] = None
    # The Light studio (1.20.0, studio.py). simple: a held simple look, {"name", "rgb" or None};
    # color: (hue, saturation) every look's washes take instead of their palette; speed: how fast a
    # simple look breathes and drifts (0.5, 1 or 2). None / 1.0 = the show exactly as it was.
    simple: Optional[dict] = None
    color: Optional[tuple] = None
    speed: float = 1.0


@dataclass
class Frame:
    """What the looks engine knows at one moment."""
    beat: float                          # absolute beat, 0 = grid's first beat
    bpm: float
    playing: bool
    level: float = 0.0                   # deck VU 0..1 (live energy)
    loop_beats: float = 0.0              # active DJ loop length, 0 = none
    section: Optional[Section] = None
    next_section: Optional[Section] = None
    track_key: int = 0                   # seeds variety per track
    song: str = ""                       # contract.track_key(artist, title): picks a saved style
    song_keys: tuple = ()                # song_match.candidates(): other spellings of the same song
    now: float = 0.0                     # the frame's clock time (s): a simple look breathes on it, not on the beat
    # The cue timeline (cues.py, Llano PM #23787): seconds into the original recording (None when the
    # deck's grid can't say), the song's cues, and the feel (bigger/softer, color) of the stretch it is in.
    secs: Optional[float] = None
    cues: tuple = ()
    feel: tuple = ("", "")

    @property
    def bar(self) -> int:
        return int(math.floor(self.beat / 4))

    @property
    def beat_in_bar(self) -> float:
        return self.beat % 4


@dataclass
class LooksEngine:
    positions: dict = field(default_factory=lambda: {k: list(v) for k, v in DEFAULT_POSITIONS.items()})
    overrides: Overrides = field(default_factory=Overrides)
    autoloop_bars: int = 8
    silence_level: float = 0.02
    mode: str = "idle"                   # what ran last: scripted / autoloop / idle / ...
    # From a venue layout: chase offset per Tetra / stick (0..1, left to right) and which
    # side of the dance floor each stick is on (0 or 0.5). None = evenly spaced, as listed.
    tetra_order: Optional[list] = None
    stick_order: Optional[list] = None
    stick_sides: Optional[list] = None
    venue: Optional[object] = None
    _venue_counts: dict = field(default_factory=dict, repr=False)
    # The settings snapshot for this frame (render() takes show_settings.current()); a test
    # may pin one by passing settings=...
    settings: Optional[dict] = None
    # A pad's preview (1.20.0, studio_peek.py) plays on an engine of its own: it never reads the
    # draft, the saved show's looks or Llano's scene pad the real show is playing, only `play`.
    isolated: bool = False
    play: Optional[dict] = None          # an isolated engine's own draft style
    showing: str = ""                    # what the last frame played: "", "draft", "style:<name>"
    move_shape: str = ""                 # the last frame's head move ("snap" glides harder, glide.py)
    _cfg: dict = field(default_factory=dict, repr=False)
    _sat: float = 1.0
    _sec_strobe: float = 1.0
    _show_key: tuple = field(default=(), repr=False)
    _song_key: tuple = field(default=(), repr=False)
    _show_pick: tuple = field(default=(), repr=False)
    _look_cache: tuple = field(default=(), repr=False)
    _song_style: Optional[str] = field(default=None, repr=False)
    _show: tuple = field(default=(), repr=False)
    limit: str = ""                      # the part-of-the-night limit on the last frame: "", "soft", "still" or "gentle"
    _soft_pick: tuple = field(default=(), repr=False)
    _still_pick: tuple = field(default=(), repr=False)
    _gentle_pick: tuple = field(default=(), repr=False)
    soft_part: str = ""                  # "cocktail" / "dinner": the soft part the last frame played in
    _soft_cfg: tuple = field(default=(), repr=False)
    _full_ok: bool = field(default=False, repr=False)
    # How far the heads go (venue.Layout.limits, PM #23796): per head the squeeze from apply_venue, the poses the
    # looks asked for last frame (what a held aim holds, so a dark beat never squeezes twice) and what went out.
    _box: list = field(default_factory=list, repr=False)
    _intent: Optional[list] = field(default=None, repr=False)
    _boxed: Optional[list] = field(default=None, repr=False)
    _spot_frame: bool = field(default=False, repr=False)   # this frame's heads are a roaming spotlight

    def apply_venue(self, layout, counts=None) -> None:
        """Aim, chase order and left/right from where the lights sit (venue.Layout), over the
        lights set up tonight (rig.counts) so 3 Tetras chase as a row of 3."""
        n = active_counts(counts)
        new = ({**{k: list(v) for k, v in DEFAULT_POSITIONS.items()}, **layout.positions()},
               layout.order("tetra", n["tetras"]), layout.order("stick", n["sticks"]),
               layout.sides("stick", n["sticks"]))
        try:
            box = layout.limit_maps()
        except Exception:  # noqa: BLE001 -- ok: a box the model can't read leaves the heads as they were, never no show
            box = []
        # Worked out first, swapped in together, so no frame mixes two layouts.
        self.positions, self.tetra_order, self.stick_order, self.stick_sides = new
        self.venue, self._venue_counts, self._box = layout, n, box

    def _t(self, i: int, n: int) -> float:
        return self.tetra_order[i] if self.tetra_order else i / n

    def _s(self, i: int, n: int) -> float:
        return self.stick_order[i] if self.stick_order else i / n

    def _side(self, i: int) -> float:
        return self.stick_sides[i] if self.stick_sides else (i % 2) / 2

    # --- helpers ------------------------------------------------------------------

    def _palette(self, f: Frame, kind: str, index: int) -> tuple[float, float]:
        cfg = self._cfg or show_settings.current()
        self._sat = cfg["saturation"].get(kind, 1.0)
        if self.overrides.color is not None:   # the studio's color for any look
            h, self._sat = self.overrides.color
            return h, h
        if self.overrides.color_hold is not None:
            h = self.overrides.color_hold
            return h, h
        palettes = cfg["palettes"]
        choices = palettes.get(cfg["section_palette"].get(kind, "warm")) or next(iter(palettes.values()))
        return tuple(random.Random(f.track_key * 1009 + index).choice(choices))

    def _phrase_palette(self, f: Frame, kind: str, start: int, phrase: int) -> tuple[float, float]:
        """The section's palette, stepping to the next color of its set every phrase.
        (Until 1.4.0 this read the built-in palettes, so the page's pickers and saturation for
        intro, verse, breakdown and outro did nothing.)"""
        cfg = self._cfg or show_settings.current()
        if self.overrides.color_hold is not None or self.overrides.color is not None:
            return self._palette(f, kind, start)
        self._sat = cfg["saturation"].get(kind, 1.0)
        palettes = cfg["palettes"]
        choices = palettes.get(cfg["section_palette"].get(kind, "warm")) or next(iter(palettes.values()))
        first = random.Random(f.track_key * 1009 + start).randrange(len(choices))
        return tuple(choices[(first + phrase) % len(choices)])

    @staticmethod
    def _phrase(f: Frame, sec: dict) -> int:
        """Which color phrase of the section this is: a new one every color_bars bars (0 = one
        color for the section). With no section (idle) it steps every 8 bars."""
        if not f.section:
            return f.bar // 8
        per = sec["color_bars"] * 4
        return int(max(0.0, f.beat - f.section.start_beat) // per) if per else 0

    @staticmethod
    def _step_index(f: Frame, sec: dict) -> int:
        """The palette pick seed for builds and drops: the section's start, plus one per
        color_bars bars."""
        start = f.section.start_beat if f.section else 0
        per = sec["color_bars"] * 4
        return start + int((f.beat - start) // per) if per else start

    @staticmethod
    def _depth(hit: float, depth: float) -> float:
        """A beat pulse at the section's pulse depth: 1 = as built, 0 = steady at half."""
        return hit if depth >= 1.0 else 0.5 * (1.0 - depth) + depth * hit

    def _aim(self, rig: Rig, name: str, other: Optional[str] = None, mix: float = 0.0) -> None:
        a = self.positions.get(name, self.positions["home"])
        b = self.positions.get(other, a) if other else a
        m = ease(mix)
        heads = [h for bar in rig.bars for h in bar.movers]
        # A position lists one pan/tilt per head of a bar (both bars alike) or, from a
        # venue, one per head of the whole rig.
        for k, head in enumerate(heads):
            pa, pb = a[k % len(a)], b[k % len(b)]
            head.pan = pa[0] + (pb[0] - pa[0]) * m
            head.tilt = pa[1] + (pb[1] - pa[1]) * m

    def _head(self, mv: dict, k: int, beat: float, progress: float, flip: bool = False, q: float = 1.0) -> tuple[float, float]:
        """One head's pan/tilt for the section's move, from its own spot of each position.
        `flip` mirrors a figure left-right (the mirror spread's right-hand heads); `q` is the share of
        each glide or sweep leg spent traveling (Fluid travel)."""
        a = self.positions.get(mv["from"], self.positions["home"])
        b = self.positions.get(mv["to"], a)
        pa, pb = a[k % len(a)], b[k % len(b)]
        shape, n = mv["shape"], mv["beats"]
        if shape in FIGURES:
            # The same size in degrees both ways: pan spans 540 degrees and tilt 180, so a pan
            # radius in raw units (as before 1.9.0) swung the heads up to 135 degrees round, past
            # the side of the bar to the wall behind it.
            r, ang = mv["size"] * 0.25, 2 * math.pi * (beat / n)
            rp = r * FIGURE_PAN * (-1 if flip else 1)
            if shape == "circle":
                return pa[0] + rp * math.cos(ang), pa[1] + r * math.sin(ang)
            if shape == "eight":
                return pa[0] + rp * math.sin(ang), pa[1] + r * math.sin(2 * ang)
            return pa[0] + rp * math.sin(ang), pa[1]
        if shape == "glide":       # ease from -> to over `beats`, then back
            seg = int(beat // n) % 2
            pa, pb = (pa, pb) if seg == 0 else (pb, pa)
            mix = leg_mix(shape, beat, n, q)
        elif shape == "snap":      # jump between them every `beats`
            return pb if int(math.floor(beat / n)) % 2 else pa
        elif shape == "sweep":     # smooth swing
            mix = leg_mix(shape, beat, n, q)
        elif shape == "rise":      # from -> to across the section
            mix = progress
        else:                      # hold
            return pa
        m = mix if shape in LEG_PEAK else ease(mix)   # leg_mix eases a glide or sweep itself
        return pa[0] + (pb[0] - pa[0]) * m, pa[1] + (pb[1] - pa[1]) * m

    def _move(self, f: Frame, rig: Rig, mv: dict, progress: float) -> None:
        """Aim every head by the section's move. Glide, snap and sweep run on the song's beat
        (as the built-in moves always did), rise on the section's progress. Spread: parallel
        (all alike), mirror (right-hand heads mirror the left one's move), serial (head k runs
        k/n of a pass behind; rise follows the section, so serial leaves it as parallel)."""
        heads = [h for bar in rig.bars for h in bar.movers]
        n, spread = len(heads), mv["spread"]
        self.move_shape = mv["shape"]
        if spread in ("spotlight", "spotlights") and self.venue is not None:
            return self._spotlight(f, rig, mv, progress, pairs=spread == "spotlights")
        period = mv["beats"] if mv["shape"] in FIGURES else 2 * mv["beats"]
        q = 1.0
        if mv["shape"] in LEG_PEAK:   # Fluid travel: the head axis that moves most sets the pace
            a = self.positions.get(mv["from"], self.positions["home"])
            b = self.positions.get(mv["to"], a)
            q = travel_share(mv["shape"], [abs(y - x) * 255 for k in range(n) for x, y in zip(a[k % len(a)], b[k % len(b)])],
                             mv["beats"], f.bpm)
        for k, head in enumerate(heads):
            if spread == "mirror" and k % 2:
                # A right-hand head travels between its OWN spots of each position, with a figure
                # flipped left-right. The positions are already mirror images left to right, so
                # without a venue this is exactly the old "flip the left head's move" (byte for
                # byte); with one it still lands on the target. Flipping the left head's change
                # around this head's own spot (before 1.9.0) sent it the other way: on a glide
                # from the booth to the crowd, head 2 of each bar turned ~145 degrees round to
                # face the wall behind the bar.
                pan, tilt = self._head(mv, k, f.beat, progress, flip=True, q=q)
            elif spread == "serial":
                pan, tilt = self._head(mv, k, f.beat - k / max(1, n) * period, progress, q=q)
            else:
                pan, tilt = self._head(mv, k, f.beat, progress, q=q)
            if spread != "parallel" or mv["shape"] in FIGURES:
                pan, tilt = min(1.0, max(0.0, pan)), min(1.0, max(0.0, tilt))
            head.pan, head.tilt = pan, tilt

    def _spot_path(self, mv: dict, beat: float, progress: float, q: float = 1.0) -> tuple[float, float]:
        """Where a roaming spotlight sits on the floor (1.16.0): the move's shape traced in the room,
        between the floor points under its `from` and `to` positions (each the middle of where the
        position sends the heads), or a figure around `from`, `size` big against the dance floor."""
        tg, fl = self.venue.targets(), self.venue.floor
        def under(name):
            pts = tg.get(name) or tg["home"]
            return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        a, b = under(mv["from"]), under(mv["to"])
        shape, n = mv["shape"], mv["beats"]
        if shape in FIGURES:
            r, ang = mv["size"] * min(fl.w, fl.d) / 2, 2 * math.pi * (beat / n)
            if shape == "circle":
                x, y = a[0] + r * math.cos(ang), a[1] + r * math.sin(ang)
            elif shape == "eight":
                x, y = a[0] + r * math.sin(ang), a[1] + r * 0.6 * math.sin(2 * ang)
            else:
                x, y = a[0] + r * math.sin(ang), a[1]
        else:
            if shape == "glide":
                seg = int(beat // n) % 2
                mix = leg_mix(shape, beat, n, q) if seg == 0 else 1 - leg_mix(shape, beat, n, q)
            elif shape == "snap":
                mix = float(int(math.floor(beat / n)) % 2)
            elif shape == "sweep":
                mix = leg_mix(shape, beat, n, q)
            elif shape == "rise":
                mix = progress
            else:
                mix = 0.0
            m = mix if shape == "snap" or shape in LEG_PEAK else ease(mix)   # leg_mix eases a glide or sweep itself
            x, y = a[0] + (b[0] - a[0]) * m, a[1] + (b[1] - a[1]) * m
        # stays on the dance floor, where the people are
        return min(fl.x + fl.w, max(fl.x, x)), min(fl.y + fl.d, max(fl.y, y))

    def _spotlight(self, f: Frame, rig: Rig, mv: dict, progress: float, pairs: bool) -> None:
        """Every head on one roaming spot, or (pairs) each GigBAR's two heads on its own spot, the
        second mirrored across the dance floor (1.16.0). Aimed through the venue, so it lands where
        Line up my lights says each head really points."""
        q = 1.0
        if mv["shape"] in LEG_PEAK and fluid_travel():   # Fluid travel: each head's turn between the path's two ends
            ends = [self._spot_path(mv, e * mv["beats"], 0.0) for e in (0.0, 1.0)] if mv["shape"] == "glide" else \
                [self._spot_path(mv, e * mv["beats"], 0.0) for e in (-0.5, 0.5)]
            steps = []
            for b, bar in enumerate(rig.bars):
                for m, _ in enumerate(bar.movers):
                    h = self.venue.heads(b + 1)[m]
                    (p0, t0), (p1, t1) = (self.venue.aim(b + 1, h, (x, y, 0.0), m) for x, y in ends)
                    steps += [abs(p1 - p0) * 255, abs(t1 - t0) * 255]
            q = travel_share(mv["shape"], steps, mv["beats"], f.bpm)
        x, y = self.venue.floor_into_box(*self._spot_path(mv, f.beat, progress, q))   # head limits: roams inside
        self._spot_frame = True
        lim = getattr(self.venue, "limits", None)   # Two spotlights mirror across the box's middle when it has one
        cx = lim.cx if lim is not None else self.venue.floor.cx
        for b, bar in enumerate(rig.bars):
            tx = 2 * cx - x if pairs and b == 1 else x
            for m, head in enumerate(bar.movers):
                # On the floor: this spot roams by itself with nobody under it, so a beam at chest height
                # would cross the room at face height. Follow someone, steered onto a person, aims at
                # chest height (studio, venue.spot_target).
                head.pan, head.tilt = self.venue.aim(b + 1, self.venue.heads(b + 1)[m], (tx, y, 0.0), m)
                if head.dim > 0.0:   # a spotlight is open white, no gobo, steady (Llano PM #23789)
                    head.color, head.gobo, head.strobe = 0, 0, 0.0

    def _washes(self, rig: Rig, hue_a: float, hue_b: float, level_a, level_b, amber: float = 0.0):
        """level_a/level_b: callables index -> 0..1 for primary (Tetras) and secondary (sticks)."""
        sat = self._sat
        for i, t in enumerate(rig.tetras):
            t.red, t.green, t.blue = rgb(hue_a, sat)
            t.amber, t.dim = amber, level_a(i)
        for i, s in enumerate(rig.sticks):
            s.red, s.green, s.blue = rgb(hue_b, sat)
            s.dim = level_b(i)
        for bar in rig.bars:
            for p in bar.pars:
                p.red, p.green, p.blue = rgb(hue_b, sat)

    # --- section looks --------------------------------------------------------------

    def _ambient(self, f: Frame, rig: Rig, kind: str, progress: float, sec: dict) -> None:
        """intro / outro / breakdown: breathing color with a soft kick on every beat, a new color
        every few bars, movers placed, no effects. (Before 1.2.2 it had no beat and one color for
        the whole section, so a long intro, 27 seconds in the Neon Hyperdrive demo, read as stuck.)"""
        start = f.section.start_beat if f.section else 0
        hue_a, hue_b = self._phrase_palette(f, kind, start, self._phrase(f, sec))
        kick = pulse(f.beat, 4.0) * (0.2 if kind == "breakdown" else 0.35) * sec["pulse"] if f.playing else 0.0
        breathe = 0.45 + 0.2 * math.sin(f.beat / 8 * math.pi) + kick  # one breath per 2 bars
        fade = 1.0 - 0.7 * progress if kind == "outro" else 1.0
        amber = 0.6 if kind != "breakdown" else 0.0
        w, mvl = sec["wash"], sec["movers"]
        self._k = w   # the section wash: STICK_LIFT leaves it linear
        self._washes(rig, hue_a, hue_b, lambda i: breathe * fade * w,
                     lambda i: (0.35 + 0.15 * math.sin(f.beat / 8 * math.pi + i) + 0.6 * kick) * fade * w, amber)
        for bar in rig.bars:
            for p in bar.pars:
                p.dim = 0.3 * fade * w
            for m in bar.movers:
                m.dim = (0.35 if kind == "breakdown" else 0.25) * fade * mvl
        self._move(f, rig, sec["move"], progress)

    def _full(self, sec: dict) -> bool:
        """Full power (settings full_power, Llano PM #23796) for this section: on, playing a song's dancing
        sections (not a held moment, not a soft part of the night), with the section's wash and heads at full."""
        return bool(self._full_ok and self._cfg.get("full_power") and not self.limit
                    and sec.get("wash", 0.0) >= 1.0 and sec.get("movers", 0.0) >= 1.0)

    def _verse(self, f: Frame, rig: Rig, kind: str, sec: dict, progress: float) -> None:
        start = f.section.start_beat if f.section else 0
        hue_a, hue_b = self._phrase_palette(f, kind, start, self._phrase(f, sec))
        soft = 0.5 + 0.4 * self._depth(pulse(f.beat / 2, 3.0), sec["pulse"])  # soft push on beats 1 and 3
        # Full power: the verse peaks at full on every light (Tetras on the push, sticks, pars, heads).
        full = self._full(sec)
        if full:
            soft /= 0.9
        # A spotlight look (Spotlight, Two spotlights) reads bright (Llano PM #23789, his 11-15 "the spotlight
        # is too dim"): the heads at the look's full level, not the 60% a moving verse beam gets, and the wash
        # around them dipped to SPOT_ROOM of the look's, so the spot stands out. spot_bright() off: 1.34's levels.
        spot = sec["move"]["spread"] in ("spotlight", "spotlights") and self.venue is not None and spot_bright()
        w = sec["wash"] * (SPOT_ROOM if spot else 1.0)
        self._k = w   # the section wash: STICK_LIFT leaves it linear
        self._washes(rig, hue_a, hue_b, lambda i: soft * w, lambda i: (1.0 if full else 0.55) * w)
        for bar in rig.bars:
            for p in bar.pars:
                p.dim = (1.0 if full else 0.5) * w
            for d in bar.derbies:
                d.color, d.rotate = "white", 0.15
            for m in bar.movers:
                m.dim, m.color = (1.0 if spot or full else 0.6) * sec["movers"], 0
        self._move(f, rig, sec["move"], progress)  # by default: glide crowd <-> fan, 4 bars a way

    def _build(self, f: Frame, rig: Rig, progress: float, sec: dict) -> None:
        """Rising tension: beams tilt up, pulse subdivides, intensity climbs (the dark last beat
        before a drop is render()'s)."""
        hue_a, hue_b = self._palette(f, "build", self._step_index(f, sec))
        sub = 1 if progress < 0.5 else 2 if progress < 0.75 else 4
        hit = pulse(f.beat * sub, 5.0)
        h = self._depth(hit, sec["pulse"])
        base = 0.25 + 0.6 * progress
        if self._full(sec):   # Full power: the build's last bar is at full, not 85%
            base = min(1.0, base / 0.83)
        w = sec["wash"]
        self._k = w   # the section wash: STICK_LIFT leaves it linear
        self._washes(rig, hue_a, hue_b, lambda i: base * (0.5 + 0.5 * h) * w, lambda i: base * h * w)
        for bar in rig.bars:
            for p in bar.pars:
                p.dim = base * h * w
            for m in bar.movers:
                m.dim = base * sec["movers"]
        self._move(f, rig, sec["move"], progress)  # by default: rise crowd -> ceiling
        if progress > 0.75 and self._cfg["strobe"]["build_ramp"]:  # last quarter: strobe ramps up
            for bar in rig.bars:
                bar.strobe_white = 0.5 * hit
                bar.strobe_speed = (progress - 0.75) * 4
        elif progress > 0.5 and self._cfg["strobe"]["build_ramp"]:  # third quarter: the UV strobe leads in (1.12.3)
            for bar in rig.bars:
                bar.strobe_uv = 0.6 * hit
                bar.strobe_speed = (progress - 0.5) * 2

    def _drop(self, f: Frame, rig: Rig, kind: str, sec: dict, progress: float) -> None:
        """drop / main: saturated palette changing every few bars, chases, movers on the bar."""
        hue_a, hue_b = self._palette(f, kind, self._step_index(f, sec))
        beat, p = f.beat, sec["pulse"]
        w, mvl = sec["wash"], sec["movers"]
        self._k = w   # the section wash: STICK_LIFT leaves it linear
        # Primary wash chases left to right on the beat; secondary alternates pairs.
        n_t, n_s = len(rig.tetras), len(rig.sticks)
        self._washes(rig, hue_a, hue_b,
                     lambda i: (0.35 + 0.65 * self._depth(pulse(beat - self._t(i, n_t), 3.0), p)) * w,
                     lambda i: (0.3 + 0.7 * self._depth(pulse(beat / 2 + self._side(i), 3.0), p)) * w)
        turn = 1 if int(beat // 32) % 2 == 0 else -1   # derbies and laser change direction every 8 bars (1.12.3)
        for bar in rig.bars:
            for px in bar.pars:
                px.dim = (0.4 + 0.6 * self._depth(pulse(beat, 4.0), p)) * w
            for d, colr in zip(bar.derbies, ("red", "blue") if int(beat // 4) % 2 else ("green", "magenta")):
                d.color, d.rotate = colr, 0.6 * turn
            bar.laser, bar.laser_rotate = ("both" if kind == "drop" else "green"), 0.4 * turn
            if kind == "drop" and beat % 16 >= 14:   # the last half bar of every 4: the laser flashes
                bar.laser_strobe = 0.5
            for m in bar.movers:
                m.dim = (0.7 + 0.3 * self._depth(pulse(beat, 2.0), p)) * mvl
                m.color = 1 + (int(beat // 8) % 7)
                m.gobo = 1 + (int(beat // 16) % 7)
        self._move(f, rig, sec["move"], progress)  # by default: snap crossed <-> fanned each bar
        # The drop's first beat: white strobe burst and everything up.
        if kind == "drop" and f.section and f.beat - f.section.start_beat < 1.0 and self._cfg["drop"]["burst"]:
            for bar in rig.bars:
                bar.strobe_white, bar.strobe_speed = 1.0, 1.0
                for px in bar.pars:
                    px.red = px.green = px.blue = 1.0
                    px.dim = 1.0

    def _effects(self, rig: Rig, sec: dict) -> None:
        """The section's derby and laser switches, and its strobe level. A section that turns
        on an effect its look has none of gets a calm one (white derbies, a slow green laser)."""
        for bar in rig.bars:
            for d in bar.derbies:
                if not sec["derby"]:
                    d.color, d.rotate = "off", 0.0
                elif d.color == "off":
                    d.color, d.rotate = "white", 0.15
            if not sec["laser"]:
                bar.laser, bar.laser_rotate = "off", 0.0
            elif bar.laser == "off":
                bar.laser, bar.laser_rotate = "green", 0.2
            if not sec["laser"]:
                bar.laser_strobe = 0.0
            if sec["strobe"] < 1.0:
                bar.strobe_white *= sec["strobe"]
                bar.strobe_uv *= sec["strobe"]

    # --- autoloops (no script) --------------------------------------------------------

    AUTOLOOPS = ("color pulse", "chase", "sweep", "rainbow")

    def _loops(self) -> tuple:
        looks = (self._cfg or show_settings.current())["looks"]
        return tuple(looks["autoloops"]) or self.AUTOLOOPS, looks["autoloop_bars"] or self.autoloop_bars

    def autoloop_name(self, f: Frame) -> str:
        loops, bars = self._loops()
        if self.overrides.hold_loop:
            idx = self.overrides.loop_shift
        else:
            idx = f.bar // bars + self.overrides.loop_shift
        return loops[idx % len(loops)]

    def _autoloop(self, f: Frame, rig: Rig) -> None:
        name = self.autoloop_name(f)
        loop_index = f.bar // self._loops()[1]
        hue_a, hue_b = self._palette(f, "main" if f.level > 0.5 else "verse", loop_index)
        beat = f.beat
        energy = 0.5 + 0.5 * min(1.0, f.level * 1.4)
        if name == "color pulse":
            self._washes(rig, hue_a, hue_b, lambda i: energy * (0.4 + 0.6 * pulse(beat)),
                         lambda i: energy * 0.6)
            self._aim(rig, "crowd")
        elif name == "chase":
            n, n_s = len(rig.tetras), len(rig.sticks)
            self._washes(rig, hue_a, hue_b, lambda i: energy * pulse(beat - self._t(i, n), 2.5),
                         lambda i: energy * pulse(beat - self._s(i, n_s), 2.5))
            self._aim(rig, ("cross", "fan")[f.bar % 2])
        elif name == "sweep":
            self._washes(rig, hue_a, hue_b, lambda i: energy * 0.7, lambda i: energy * 0.5)
            self._aim(rig, "sweep_left", "sweep_right", 0.5 + 0.5 * math.sin(beat / 8 * math.pi))
        else:  # rainbow: hues roll through the rig, one turn per 4 bars
            for i, t in enumerate(rig.tetras):
                t.red, t.green, t.blue = rgb(beat / 16 + self._t(i, len(rig.tetras)))
                t.dim = energy * 0.8
            for i, s in enumerate(rig.sticks):
                s.red, s.green, s.blue = rgb(beat / 16 + self._s(i, len(rig.sticks)) + 0.5)
                s.dim = energy * 0.7
            self._aim(rig, "crowd", "fan", 0.5 + 0.5 * math.sin(beat / 16 * math.pi))
        for bar in rig.bars:
            for p in bar.pars:
                p.dim = energy * 0.5 * (0.5 + 0.5 * pulse(beat))
            for m in bar.movers:
                m.dim = energy * 0.6
            if f.level > 0.6:
                for d in bar.derbies:
                    d.color, d.rotate = "auto", 0.4

    # --- top level --------------------------------------------------------------------

    def song_style(self, songs: dict, keys: tuple) -> Optional[str]:
        """The style name the song is filed under, forgiving spelling (song_match.pick);
        worked out once per song and settings change, not per frame."""
        if not (self._song_key and self._song_key[0] is songs and self._song_key[1] == keys):
            hit = song_match.pick(songs, keys)
            self._song_key, self._song_style = (songs, keys), songs[hit] if hit else None  # holds songs: no id reuse
        return self._song_style

    def show_for(self, base: dict, song: str = "", keys: tuple = ()) -> tuple[dict, str]:
        """The settings this frame plays and what they are (_show_for), held to the part-of-the-night
        limit: a song from cocktail hour or dinner plays a soft wash whatever it was given. A draft or
        a look he is holding by hand is his own press and is left as it is."""
        cfg, what = self._show_for(base, song, keys)
        soft = frozenset() if self.isolated else show_settings.soft_songs()
        spared = None if self.isolated else show_settings.soft_now()   # the night stands on cocktail hour or dinner
        want = keys or ((song,) if song else ())
        if not (self._soft_pick and self._soft_pick[0] is soft and self._soft_pick[1] == want and self._soft_pick[3] is spared):
            held = (bool(soft) and any(k in soft for k in want)) or (spared is not None and not any(k in spared for k in want))
            self._soft_pick = (soft, want, held, spared)   # once per song
        self.limit = "soft" if self._soft_pick[2] and what != "draft" else ""
        # which soft part the song plays in, for its mood (BL #12340); asked per frame, it is two dict looks
        self.soft_part = show_settings.soft_part(want) if self.limit and not self.isolated else ""
        if not self.limit and what != "draft":   # moving heads only in Dancing (BL #12339)
            still = frozenset() if self.isolated else show_settings.still_songs()
            stand = None if self.isolated else show_settings.still_now()
            if not (self._still_pick and self._still_pick[0] is still and self._still_pick[1] == want
                    and self._still_pick[3] is stand):
                held = (bool(still) and any(k in still for k in want)) or (stand is not None and not any(k in stand for k in want))
                self._still_pick = (still, want, held, stand)   # once per song
            self.limit = "still" if self._still_pick[2] else ""
        if not self.limit and what != "draft":   # ... and gently in the first dance and parent dances
            gentle = frozenset() if self.isolated else show_settings.gentle_songs()
            stand = None if self.isolated else show_settings.gentle_now()
            if not (self._gentle_pick and self._gentle_pick[0] is gentle and self._gentle_pick[1] == want
                    and self._gentle_pick[3] is stand):
                held = (bool(gentle) and any(k in gentle for k in want)) or (stand is not None and not any(k in stand for k in want))
                self._gentle_pick = (gentle, want, held, stand)   # once per song
            self.limit = "gentle" if self._gentle_pick[2] else ""
        if not self.limit:
            return cfg, what
        if not (self._soft_cfg and self._soft_cfg[0] is cfg and self._soft_cfg[2] == self.limit):
            # one merge per change, not per frame
            limited = {"soft": soft_settings, "still": still_settings, "gentle": gentle_settings}[self.limit](cfg)
            self._soft_cfg = (cfg, limited, self.limit)
        return self._soft_cfg[1], what

    def _show_for(self, base: dict, song: str = "", keys: tuple = ()) -> tuple[dict, str]:
        """The settings this frame plays, and what they are: a draft Llano asked to play
        ("draft"), the look a playing saved show gives the song ("show:<look>"), the style the song is
        filed under ("style:<name>"), or the saved settings ("")."""
        style, what = (self.play if self.isolated else show_settings.playing()), "draft"
        show = None if self.isolated else show_settings.show_looks()
        if style is None and show:   # a saved show playing: its look for this song wins
            want = keys or ((song,) if song else ())
            if not (self._show_pick and self._show_pick[0] is show and self._show_pick[1] == want):
                self._show_pick = (show, want, song_match.pick(show, want))   # once per song, not per frame
            hit = self._show_pick[2]
            if hit is not None:
                look = show[hit]
                # Worked out against the settings in force (a change from Llano mid-show applies),
                # once per settings snapshot and look, not per frame.
                own = show_settings.show_own_looks()
                if not (self._look_cache and self._look_cache[0] is base and self._look_cache[2] is own):
                    self._look_cache = (base, {}, own)
                if look not in self._look_cache[1]:
                    self._look_cache[1][look] = contract.look_style(look, base["styles"], base, own)
                style = self._look_cache[1][look]
                if style is None:
                    return base, f"show:{look or 'house'}"
                what = f"show:{look}"
        if style is None:
            name = self.song_style(base["songs"], keys or ((song,) if song else ()))
            style, what = (base["styles"].get(name), f"style:{name}") if name else (None, "")
            if style is None:
                return base, ""
        key = (id(base), id(style))
        if self._show_key != key:   # one merge per change, not per frame
            self._show_key, self._show = key, (base, style, {**base, **{k: style[k] for k in STYLE_KEYS}})
        return self._show[2], what

    def render(self, f: Frame, rig: Rig) -> Rig:
        """The frame's look on `rig`, played only on the lights set up tonight (rig.counts):
        the others stay dark and send nothing (Rig.render)."""
        base = self.settings if self.settings is not None else show_settings.current()
        counts = (base.get("rig") or {}).get("counts")
        if self.venue is not None and active_counts(counts) != self._venue_counts:
            self.apply_venue(self.venue, counts)
        self._aim_before = [(m.pan, m.tilt) for bar in rig.bars for m in bar.movers]
        if self._intent is not None and len(self._intent) == len(self._aim_before):
            self._aim_before = list(self._intent)   # held aims hold what the looks asked for, squeezed once below
        rig.reset()
        self._render(f, rig.present(counts), base)
        ov = self.overrides
        # The limits' backstop. A look he holds by hand (a pad, a scene) and the line-up screens are his.
        if self.limit and not (ov.simple or ov.scene or ov.lineup or ov.raw_head or ov.aim_set):
            if self.limit == "soft":
                if self.soft_part:   # cocktail hour or dinner plays its mood, not the song's colors
                    self._mood(f, rig, show_settings.moods().get(self.soft_part))
                soften(rig)
            elif self.limit == "still":
                still_heads(rig)
            if self.limit == "gentle":
                gentle_heads(rig)   # the heads keep their slow glide
            else:
                self._hold_aim(rig)   # dark heads stay where they point: nothing moves by itself
        self._limit_heads(rig)
        return rig

    def _limit_heads(self, rig: Rig) -> None:
        """How far the heads go (PM #23796): every head's move squeezed into the venue's box, once a frame. The
        line-up screens are his and go anywhere (and start the next frame afresh)."""
        ov = self.overrides
        if not self._box or ov.lineup or ov.raw_head or ov.aim_set:
            self._intent = self._boxed = None
            return
        heads = [m for bar in rig.bars for m in bar.movers]
        self._intent = [(m.pan, m.tilt) for m in heads]
        # A roaming spotlight already roams inside the box (_spotlight, floor_into_box), every head on one point:
        # squeezing each head on its own would split that point in four, so it is only held at the edge.
        fit = venue.hold_pose if self._spot_frame else venue.squeeze_pose
        for k, m in enumerate(heads):
            if k < len(self._box):
                m.pan, m.tilt = fit(self._box[k], m.pan, m.tilt)
        self._boxed = [(m.pan, m.tilt) for m in heads]

    def _hold_in_box(self, rig: Rig) -> None:
        """After the Light studio's layers: a head it moved (Follow someone, a steered spot) is held inside the
        box at its edge, never squeezed (a spot lands where he points); one it left alone was squeezed already."""
        if not self._box or self._boxed is None:
            return
        for k, m in enumerate(m for bar in rig.bars for m in bar.movers):
            if k < len(self._box) and k < len(self._boxed) and (m.pan, m.tilt) != self._boxed[k]:
                m.pan, m.tilt = venue.hold_pose(self._box[k], m.pan, m.tilt)

    def _hold_aim(self, rig: Rig) -> None:
        """Dark, the heads stay where they point (Hold through the dark, 1.16.7, his 11-09 clip
        20261109_190016): a reset parks every head at pan 0.5 / tilt 0.5, so the one dark beat before
        a drop, a silence and a blackout swung each head toward straight down and back again, about a
        quarter turn on his heads, and the picture's beams shrank and flew back as the drop landed."""
        held = iter(getattr(self, "_aim_before", ()) or ())
        for bar in rig.bars:
            for m in bar.movers:
                m.pan, m.tilt = next(held, (m.pan, m.tilt))

    def _render(self, f: Frame, rig: Rig, base: dict) -> Rig:
        cfg, self.showing = self.show_for(base, f.song, f.song_keys)
        self.move_shape = ""
        self._sec_strobe = 1.0
        self._cfg = cfg
        self._sat = 1.0
        self._k = 1.0   # the linear knobs (wash, drop intensity) in this frame's stick level
        self._full_ok = False   # set on the song-section path below (Full power)
        self._spot_frame = False
        ov = self.overrides
        if ov.aim_set:   # Line up my lights, one spot (1.16.0): the heads being aimed, nothing else lit
            return self._aim_set(rig, ov.aim_set)
        if ov.raw_head:   # calibrating: the head he nudges at its raw pan/tilt, the others on the spot
            bar, m, pan, tilt = ov.raw_head
            self._lineup(rig, 0, (ov.lineup or (0, "center"))[1])
            if bar > len(rig.bars):   # the rig picker left this GigBAR out tonight
                self.mode = f"calibrating: GigBAR {bar} isn't in tonight's rig"
                return rig
            head = rig.bars[bar - 1].movers[m]
            head.pan, head.tilt = pan, tilt
            for other in (h for gb in rig.bars for h in gb.movers if h is not head):   # 1.16.0: his head stands out
                other.dim *= CAL_OTHERS
            side = ("right", "left")[m]   # as you face the bar from the dance floor (1.12.3)
            self.mode = (f"calibrating GigBAR {bar} {side} head: pan {round(pan * 255)}, tilt {round(tilt * 255)}"
                         + ("" if ov.lights_on else ", lights off"))
            return rig
        if ov.lineup:   # setting up: one GigBAR alone, aimed at a known spot, nothing else lit
            return self._lineup(rig, *ov.lineup)
        scene = self.active_scene()
        if ov.blackout or scene == "blackout":
            self.mode = "blackout" if ov.blackout else "scene:blackout"
            self._hold_aim(rig)
            return rig
        if scene == "whiteout":   # a full white hit, held as long as the pad is
            self.mode = "scene:whiteout"
            for fx in (*rig.tetras, *rig.sticks):
                fx.red = fx.green = fx.blue = 1.0
                fx.dim = 1.0
            for bar in rig.bars:
                for p in bar.pars:
                    p.red = p.green = p.blue = 1.0
                    p.dim = 1.0
                for m in bar.movers:
                    m.dim = 1.0
                bar.strobe_white = 1.0
            self._aim(rig, "crowd")
            return self._finish(f, rig, cfg, ov)
        if ov.simple:
            # A simple look he holds in the Light studio: it never reads the beat, the section or
            # the music level, so it stays exactly what its pad says until he releases it.
            self._simple(f, rig, cfg, ov.simple)
        elif scene in ("calm", "party", "hype", "party-mode"):
            self._scene(f, rig, cfg, scene)
        elif self.is_still(cfg):
            # A look where nothing moves (Photo mode, Toast): one steady frame, whatever the music
            # does. Played through the song's sections it breathed, ramped through each build, went
            # dark a beat before each drop and dimmed in the drop (his 1.17.1 report, BL #12093).
            self._still(f, rig, cfg)
        elif self.is_one_look(cfg) and (self.showing == "draft" or not ov.autoloop_override):
            # A cue that is one look in every section (Cake cutting, Spotlight, Two spotlights): it
            # plays that look, moving and breathing, until he picks something else. Through the
            # song it went dark a beat before each drop, dimmed in the drop, blacked out in a hard
            # stop and fell to the autoloops on a song with no section script (BL #12095). The
            # autoloop key still means autoloops for a saved show's look; a moment he picked holds.
            self._held(f, rig, cfg, "main")
        elif not f.playing:
            self.mode = "idle"
            self._ambient(f, rig, "intro", 0.0, cfg["sections"]["intro"])
            for fx in (*rig.tetras, *rig.sticks):
                fx.dim *= 0.4
        elif f.level < self.silence_level and f.section and f.section.kind != "intro":
            self.mode = "silence"  # a hard stop in the music: go dark
            self._hold_aim(rig)
        elif (f.section or self.showing.startswith(("show:", "style:"))) and not ov.autoloop_override:
            # A song with a look of its own (the show's, or the style it is filed under) and no
            # sections yet (Mixxx has not analyzed it, or a show song with none) plays that look's
            # verse in 32-beat waves. It used to fall to the autoloops, so a first dance tied to
            # slow-dance played chase and rainbow (whole-app audit, 2026-11-12).
            s = f.section or Section("verse", int(f.beat // 32) * 32, int(f.beat // 32) * 32 + 32, 0.5)
            self.mode = f"scripted:{s.kind}" if f.section else f"look:{s.kind}"
            secs = cfg["sections"]
            sec = secs.get(s.kind) or secs["main"]
            self._full_ok = True   # Full power applies to a song's dancing sections only
            progress = (f.beat - s.start_beat) / max(1, s.end_beat - s.start_beat)
            if s.kind == "intro" and f.beat - s.start_beat >= LONG_INTRO_BEATS and sec["move"]["shape"] == "hold":
                # Basi Beta's analyzed intro runs 2 of its 3 minutes: a held intro past 16 bars
                # moves and sparkles like the verse, in the intro's colors and levels.
                verse = secs["verse"]
                sec = {**sec, "move": verse["move"], "derby": verse["derby"]}
                self._verse(f, rig, "intro", sec, progress)
            elif s.kind in ("intro", "outro", "breakdown"):
                self._ambient(f, rig, s.kind, progress, sec)
            elif s.kind == "verse":
                self._verse(f, rig, "verse", sec, progress)
            elif s.kind == "build":
                self._build(f, rig, progress, sec)
            else:
                self._drop(f, rig, s.kind, sec, progress)
            self._effects(rig, sec)
            self._sec_strobe = sec["strobe"]
            if s.kind == "build" and f.next_section and f.next_section.kind == "drop" and s.end_beat - f.beat <= 1.0:
                rig.reset()  # one dark beat, so the drop lands
                self._hold_aim(rig)
            elif s.kind not in ("intro", "verse", "build", "outro", "breakdown") and not self._full(sec):
                self._scale_levels(rig, cfg["drop"]["intensity"])   # Full power reads the drop intensity as full
        elif self.showing == "draft":
            # A moment he picked (or a draft Llano plays) over a song with no section script, or
            # with the autoloop key on: its own look, the way the song's verse plays it, never the
            # autoloops' chase and rainbow (BL #12095: Grand entrance turned into a party look).
            self._held(f, rig, cfg, "verse")
        else:
            self.mode = f"autoloop:{self.autoloop_name(f)}"
            self._autoloop(f, rig)

        return self._finish(f, rig, cfg, ov)

    @staticmethod
    def is_one_look(cfg: dict) -> bool:
        """True when every section of the look is the same (the cues written with moments._same):
        it is meant as one look for the whole song, so no section of the song changes it."""
        secs = list((cfg.get("sections") or {}).values())
        return bool(secs) and all(sec == secs[0] for sec in secs[1:])

    def _held(self, f: Frame, rig: Rig, cfg: dict, kind: str) -> None:
        """Section `kind` of the look, played on its own: its colors, levels, move and gentle
        pulse, on the beat, but never the song's sections, its drop, a build's dark beat, a
        silence or the autoloops. The heads keep moving (a spotlight roams) while the music
        plays and hold where they are when it stops."""
        self.mode = f"held:{kind}"
        sec = cfg["sections"][kind]
        free = replace(f, section=None, next_section=None)
        self._verse(free, rig, kind, sec, (f.beat % 32) / 32)
        self._effects(rig, sec)
        self._sec_strobe = sec["strobe"]

    @staticmethod
    def is_still(cfg: dict) -> bool:
        """True when every section of the look holds still: the heads hold, nothing pulses, no
        strobe, derby or laser. Such a look is meant steady (Photo mode: "no strobe, no movement,
        no color shifts"), so it plays as one held frame, not through the song's sections."""
        secs = cfg.get("sections") or {}
        return bool(secs) and all(
            sec["move"]["shape"] == "hold" and sec["pulse"] <= 0 and sec["strobe"] <= 0
            and not sec["derby"] and not sec["laser"] for sec in secs.values())

    def _still(self, f: Frame, rig: Rig, cfg: dict) -> None:
        """A still look's one steady frame: the washes and pars at the look's level, in its first
        color, the heads at their spot at the look's mover level, no effects. It never reads the
        beat, the section, the music level or the drop, so it holds the same until he picks
        something else, music or none."""
        self.mode = "still"
        sec = cfg["sections"]["main"]
        self._sat = cfg["saturation"].get("main", 1.0)
        if self.overrides.color is not None:
            hue_a, self._sat = self.overrides.color
            hue_b = hue_a
        elif self.overrides.color_hold is not None:
            hue_a = hue_b = self.overrides.color_hold
        else:
            palettes = cfg["palettes"]
            choices = palettes.get(cfg["section_palette"].get("main", "warm")) or next(iter(palettes.values()))
            hue_a, hue_b = choices[0]
        w = sec["wash"]
        self._k = w   # the section wash: STICK_LIFT leaves it linear
        self._washes(rig, hue_a, hue_b, lambda i: 0.85 * w, lambda i: 0.85 * w, amber=0.6)
        for bar in rig.bars:
            for p in bar.pars:
                p.dim = 0.6 * w
            for m in bar.movers:
                m.dim, m.color = 0.6 * sec["movers"], 0
        self._move(f, rig, sec["move"], 0.0)
        self._sec_strobe = 0.0

    def _lineup(self, rig: Rig, bar: int, spot: str) -> Rig:
        """The arrival line-up check (his recording, 5:02): a GigBAR's two heads aim at a known spot
        so he can see where they land and nudge them until they match the picture. Bar 0 is both
        bars (1.11.3, his 2:40 PM recording 2:02): at "center" all four heads should meet on one dot.
        Lights on (1.12.3, his 11-08 report "how do i turn the lights on"): every aimed head is a
        white spot at full, strobe channel at 0 (steady, the manual's no-strobe end), color wheel
        and gobo open, no master dimmer; Lights off keeps them aimed but dark. Whole bar (1.14.1, his
        11-08 correction): the rest of the bar too, so he sees all 11 parts: both pars white, both
        derbies white and still, both lasers on, the 4 strobes flashing white slowly."""
        bars = [b for b in ((1, 2) if bar == 0 else (bar,)) if b <= len(rig.bars)]   # set up tonight
        where = LINEUP_SPOTS.get(spot, spot)
        if not bars:
            self.mode = f"line-up: GigBAR {bar} isn't in tonight's rig" if bar else "line-up: no GigBAR in tonight's rig"
            return rig
        self.mode = (f"line-up: both GigBARs at {where}" if bar == 0 else f"line-up: GigBAR {bar} at {where}") \
            + ("" if self.overrides.lights_on else ", lights off") \
            + (", whole bar" if self.overrides.lights_on and self.overrides.lights_whole else "")
        pos = [(0.5, 0.5)] if spot == "middle" else self.positions.get(spot, self.positions["home"])
        for b in bars:
            for m, head in enumerate(rig.bars[b - 1].movers):
                k = (b - 1) * 2 + m
                head.pan, head.tilt = pos[k % len(pos)]
                head.dim = 1.0 if self.overrides.lights_on else 0.0
                head.strobe, head.color, head.gobo = 0.0, 0, 0
            if self.overrides.lights_on and self.overrides.lights_whole:
                gb = rig.bars[b - 1]
                for p in gb.pars:
                    p.red = p.green = p.blue = p.dim = 1.0
                    p.strobe = 0.0
                for d in gb.derbies:
                    d.color, d.strobe, d.rotate = "white", 0.0, 0.0
                gb.laser, gb.laser_strobe, gb.laser_rotate = "both", 0.0, 0.0
                gb.strobe_program, gb.strobe_white, gb.strobe_uv, gb.strobe_speed = 0, 1.0, 0.0, 0.1
        return rig

    def _aim_set(self, rig: Rig, aim: dict) -> Rig:
        """Line up my lights on one spot (1.16.0): each listed head at its raw pan/tilt as a white
        spot, the head in focus at full and the rest at `others` (0 = dark), every other light off
        (washes, pars, derbies, laser, strobes), so the only beams in the room are the ones he lines up."""
        focus, others = aim.get("focus"), aim.get("others", CAL_OTHERS)
        lit = []
        for (b, m), (pan, tilt) in aim["poses"].items():
            if b > len(rig.bars):   # left out of tonight's rig
                continue
            head = rig.bars[b - 1].movers[m]
            head.pan, head.tilt = pan, tilt
            head.strobe, head.color, head.gobo = 0.0, 0, 0
            head.dim = 0.0 if not self.overrides.lights_on else 1.0 if focus in (None, (b, m)) else others
            lit.append((b, m))
        if focus and focus[0] <= len(rig.bars):
            self.mode = f"line-up: GigBAR {focus[0]} {('right', 'left')[focus[1]]} head, the others " \
                        + ("dark" if others <= 0 else "dimmed")
        else:
            self.mode = f"line-up: {len(lit)} heads on one spot"
        if not self.overrides.lights_on:
            self.mode += ", lights off"
        return rig

    def _finish(self, f: Frame, rig: Rig, cfg: dict, ov: Overrides) -> Rig:
        """The forward guard, the strobe key, Loop Auto-Strobe, strobe strength, master and the
        crowd-safe cap."""
        self._forward(rig)
        st = cfg["strobe"]
        if (f.playing and 0 < f.loop_beats <= 0.5 and st["loop_auto"]) or ov.strobe:  # Loop Auto-Strobe / button
            for fx in (*rig.tetras, *rig.sticks):
                fx.red = fx.green = fx.blue = 1.0
                fx.dim, fx.strobe = st["intensity"], 0.85 * st["speed"]
            # The held button is his; Loop Auto-Strobe keeps the section's strobe level.
            auto = 1.0 if ov.strobe else self._sec_strobe
            for bar in rig.bars:
                bar.strobe_white, bar.strobe_speed = 1.0, 0.9
                if auto < 1.0:
                    bar.strobe_white *= auto
            self.mode += "+strobe"
        if st["intensity"] < 1.0 or st["speed"] < 1.0:
            for bar in rig.bars:
                bar.strobe_white *= st["intensity"]
                bar.strobe_uv *= st["intensity"]
                bar.strobe_speed *= st["speed"]
        # STICK_LIFT: the look's own stick level goes out bright; the section wash and drop intensity
        # (self._k) stay linear on top of it, and master after it, so every knob still means what it says.
        k, lift = getattr(self, "_k", 1.0), stick_lift()
        for s in rig.sticks:
            if 0.0 < s.dim < k and lift != 1.0:   # a level set past the wash (the strobe key) is left as it was
                s.dim = (s.dim / k) ** lift * k
        master = ov.master * cfg["master"]
        if master < 1.0:
            for fx in (*rig.tetras, *rig.sticks):
                fx.dim *= master
            for bar in rig.bars:
                for p in bar.pars:
                    p.dim *= master
                for m in bar.movers:
                    m.dim *= master
                bar.strobe_white *= master
                bar.strobe_uv *= master
                if master <= 0.05:  # master down means everything, laser included
                    bar.laser, bar.laser_rotate, bar.laser_strobe, bar.strobe_program = "off", 0.0, 0.0, 0
                    for d in bar.derbies:
                        d.color, d.rotate, d.strobe = "off", 0.0, 0.0
        if cfg.get("crowd_safe", True):
            self._crowd_safe(rig)
        return rig

    def _forward(self, rig: Rig) -> None:
        """No head turns round to the wall behind its bar (venue.forward), nor tilts past straight
        down to the back side (venue.front: the heads hang under the bar)."""
        for b, bar in enumerate(rig.bars):
            for k, m in enumerate(bar.movers):
                if self.venue is not None:
                    m.pan, m.tilt = self.venue.forward(b + 1, m.pan, k), self.venue.front(b + 1, m.tilt, k)
                else:
                    m.tilt = max(m.tilt, venue.TILT_DOWN_AT_CENTER)

    def guard(self, rig: Rig) -> None:
        """The guards again, after the Light studio's layers changed the frame (studio.Studio.post):
        a steered spot never turns a head to the wall behind its bar, and a held button never
        strobes past the crowd-safe limit."""
        self._forward(rig)
        self._hold_in_box(rig)
        if (self._cfg or show_settings.current()).get("crowd_safe", True):
            self._crowd_safe(rig)

    # Simple looks (1.20.0, the Light studio): what each pad says, and nothing else.
    SIMPLE_LEVELS = {  # wash (Tetras), sticks, bar pars, moving heads
        "steady": (0.85, 0.85, 0.6, 0.5), "pulse": (0.85, 0.85, 0.6, 0.5), "fade": (0.8, 0.8, 0.55, 0.4),
        "glow": (0.3, 0.3, 0.0, 0.0), "house": (1.0, 1.0, 1.0, 1.0)}
    PULSE_S, FADE_STEP_S = 6.0, 20.0

    def _simple(self, f: Frame, rig: Rig, cfg: dict, look: dict) -> None:
        """A simple look: steady (one color, nothing changes), pulse (it breathes, one breath every
        6 seconds), fade (it drifts through the show's colors, a new one every 20 seconds), glow (only
        the wash lights, low) and house (everything bright white). On the clock, never on the beat."""
        name = look.get("name") if look.get("name") in self.SIMPLE_LEVELS else "steady"
        self.mode = f"simple:{name}"
        t = self._simple_time(f.now)
        rgb_ = look.get("rgb")
        if name == "house":
            rgb_ = (1.0, 1.0, 1.0)
        elif name == "fade":
            rgb_ = self._fade_color(cfg, rgb_, t)
        elif rgb_ is None:
            rgb_ = (1.0, 0.85, 0.64)   # warm white
        k = 0.65 + 0.35 * math.sin(2 * math.pi * t / self.PULSE_S) if name == "pulse" else 1.0
        wash, sticks, pars, heads = (v * k for v in self.SIMPLE_LEVELS[name])
        r, g, b = rgb_
        amber = 0.5 * max(0.0, r - b) if g >= 0.6 and name != "house" else 0.0   # a warm color gets the Tetras' amber
        for tt in rig.tetras:
            tt.red, tt.green, tt.blue, tt.amber, tt.dim = r, g, b, amber, wash
        for s in rig.sticks:
            s.red, s.green, s.blue, s.dim = r, g, b, sticks
        for bar in rig.bars:
            for p in bar.pars:
                p.red, p.green, p.blue, p.dim = r, g, b, pars
            for m in bar.movers:
                m.dim, m.color, m.gobo = heads, 0, 0
        self._aim(rig, "crowd")
        self._sec_strobe = 0.0

    MOOD_MELT_S = 60.0   # a slow fade melts into its next color over a full minute, then rests

    @classmethod
    def mood_color(cls, mood: dict, t: float) -> tuple:
        """A mood's color (r, g, b, 0..1) at clock time `t` seconds: one color holds; a slow fade melts
        from each color to the next over MOOD_MELT_S at the start of every `every` minutes."""
        cols = [tuple(int(c[i:i + 2], 16) / 255.0 for i in (1, 3, 5)) for c in mood.get("colors") or ["#ffe4c4"]]
        if mood.get("kind") != "fade" or len(cols) < 2:
            return cols[0]
        step = 60.0 * float(mood.get("every") or 5)
        i, into = divmod(max(0.0, t), step)
        a, b = cols[(int(i) - 1) % len(cols)], cols[int(i) % len(cols)]
        m = ease(min(1.0, into / cls.MOOD_MELT_S))
        return tuple(x + (y - x) * m for x, y in zip(a, b))

    def _mood(self, f: Frame, rig: Rig, mood: Optional[dict]) -> None:
        """Cocktail hour's or dinner's mood on the wash lights: its color now, at its brightness
        (full brightness = the soft wash's ceiling). The heads stay dark (soften does that next)."""
        if not mood:
            return
        r, g, b = self.mood_color(mood, f.now)
        level = SOFT_WASH * float(mood.get("bright") or 0.5)
        amber = 0.5 * max(0.0, r - b) if g >= 0.6 else 0.0
        for tt in rig.tetras:
            tt.red, tt.green, tt.blue, tt.amber, tt.dim, tt.strobe = r, g, b, amber, level, 0.0
        for s in rig.sticks:
            s.red, s.green, s.blue, s.dim, s.strobe = r, g, b, level, 0.0
        for bar in rig.bars:
            for p in bar.pars:
                p.red, p.green, p.blue, p.uv, p.dim, p.strobe = r, g, b, 0.0, level, 0.0
        self.mode = f"mood:{self.soft_part}"

    def _simple_time(self, now: float) -> float:
        """The simple looks' own clock: it runs at the studio's speed, and a change of speed never
        jumps the breath or the drift (the clock keeps its place, only its pace changes)."""
        last, t = getattr(self, "_simple_clock", (now, 0.0))
        dt = now - last
        t += max(0.0, min(1.0, dt)) * (self.overrides.speed or 1.0)
        self._simple_clock = (now, t)
        return t

    def _fade_color(self, cfg: dict, rgb_: Optional[tuple], t: float) -> tuple:
        """Color fade's color now: the show's own colors in turn (its verse and main palettes), or,
        with a color he picked, that color and its two neighbors; each held and melted into the next
        over FADE_STEP_S."""
        if rgb_ is not None:
            h, sat, _ = colorsys.rgb_to_hsv(*rgb_)
            stops = [(h, sat), ((h + 0.07) % 1.0, sat), ((h - 0.07) % 1.0, sat)]
        else:
            stops = []
            for kind in ("verse", "main"):
                pairs = cfg["palettes"].get(cfg["section_palette"].get(kind, "")) or []
                sat = cfg["saturation"].get(kind, 1.0)
                for pair in pairs:
                    if all(abs(pair[0] % 1.0 - s0) > 0.02 for s0, _ in stops):
                        stops.append((pair[0] % 1.0, sat))
            stops = stops or [(0.08, 0.8), (0.92, 0.8), (0.62, 0.8)]
        i, part = divmod(t / self.FADE_STEP_S, 1.0)
        a, b2 = stops[int(i) % len(stops)], stops[(int(i) + 1) % len(stops)]
        m = ease(max(0.0, (part - 0.5) * 2))   # hold the color for half the step, melt over the other half
        ra, rb = colorsys.hsv_to_rgb(a[0], a[1], 1.0), colorsys.hsv_to_rgb(b2[0], b2[1], 1.0)
        return tuple(x + (y - x) * m for x, y in zip(ra, rb))

    @staticmethod
    def _crowd_safe(rig: Rig) -> None:
        """Every strobe channel at the slow end of its range (contract.SAFE_STROBE_MAX), whatever
        a look, the strobe key or a drop burst asked for."""
        cap = contract.SAFE_STROBE_MAX
        for fx in (*rig.tetras, *rig.sticks):
            fx.strobe = min(fx.strobe, cap)
        for bar in rig.bars:
            for p in bar.pars:
                p.strobe = min(p.strobe, cap)
            for m in bar.movers:
                m.strobe = min(m.strobe, cap)
            for d in bar.derbies:
                d.strobe = min(d.strobe, cap)
            bar.strobe_speed = min(bar.strobe_speed, cap)
            bar.laser_strobe = min(bar.laser_strobe, cap)
            bar.strobe_program = 0   # the bar's own strobe programs run at their own speed: never capped
            if bar.laser in ("red_flash", "green_flash", "alternate"):   # flash at the bar's own rate
                bar.laser = "both"

    # Scene pads (1.6.0): a scene plays over the show until "back to the show".
    def active_scene(self) -> Optional[str]:
        """The scene pad playing: the newest press wins, whichever side it came from (whole-app audit,
        2026-11-12). A press in the window (or from the phone over Wi-Fi) drops Llano's pad on this
        laptop (handle_key), so a Llano pad still in force was pressed after it and replaces it here.
        Before, the window's pad always won: a pad pressed on llano.app over one picked in the window
        did nothing, and Back to the show in the window brought back a party pressed on the phone
        hours earlier. A held white-out from Llano only covers the window's pad while it is held."""
        ov, llano = self.overrides, (None if self.isolated else show_settings.scene())
        if llano == "whiteout":
            return llano
        if llano and ov.scene:
            ov.scene = None
        return ov.scene or llano

    PARTY_MODE = ("party", "hype", "chase", "hype", "party", "rainbow")

    def _scene(self, f: Frame, rig: Rig, cfg: dict, scene: str) -> None:
        secs = cfg["sections"]
        if scene == "party-mode":   # steps through high-energy looks every 8 bars, on the beat
            scene = self.PARTY_MODE[(f.bar // 8) % len(self.PARTY_MODE)]
            if scene in ("chase", "rainbow"):
                self.mode = f"scene:party-mode:{scene}"
                ov = self.overrides
                held = (ov.hold_loop, ov.loop_shift)
                loops = self._loops()[0]
                ov.hold_loop, ov.loop_shift = True, loops.index(scene) if scene in loops else 0
                try:
                    if scene in loops:
                        self._autoloop(f, rig)
                    else:
                        self._drop(f, rig, "main", secs["main"], (f.beat % 32) / 32)
                finally:
                    ov.hold_loop, ov.loop_shift = held
                return
            self.mode = f"scene:party-mode:{scene}"
        else:
            self.mode = f"scene:{scene}"
        progress = (f.beat % 32) / 32
        if scene == "calm":
            sec = {**secs["breakdown"], "pulse": 0.2, "strobe": 0.0, "derby": False, "laser": False,
                   "move": {**secs["breakdown"]["move"], "shape": "sweep", "beats": 32}}
            self._ambient(f, rig, "breakdown", progress, sec)
            self._effects(rig, sec)
            self._sec_strobe = 0.0
        elif scene == "party":
            sec = {**secs["main"], "laser": False}
            self._drop(f, rig, "main", sec, progress)
            self._effects(rig, sec)
            self._sec_strobe = sec["strobe"]
        else:   # hype: the drop, everything on
            sec = {**secs["drop"], "derby": True, "laser": True}
            self._drop(f, rig, "drop", sec, progress)
            self._effects(rig, sec)
            self._sec_strobe = sec["strobe"]

    def _scale_levels(self, rig: Rig, k: float) -> None:
        """Drop intensity: every wash, par and mover level in a drop / main section."""
        if k >= 1.0:
            return
        self._k *= k
        for fx in (*rig.tetras, *rig.sticks):
            fx.dim *= k
        for bar in rig.bars:
            for p in bar.pars:
                p.dim *= k
            for m in bar.movers:
                m.dim *= k
