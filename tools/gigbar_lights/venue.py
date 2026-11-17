"""Where the 12 lights sit in the room, and what that means for the show.

A layout places every fixture in a top-down room plan (meters). It never touches the
address plan: the rig's DMX addresses come from rig.py and stay fixed; a layout only says
where each named fixture stands. From a layout the venue works out:

- mover aim: each named position ("booth", "crowd", "fan", "cross", "ceiling", "sweep_left",
  "sweep_right") becomes a real point in the room, and each GigBAR head gets the pan/tilt
  that points it there from where it actually sits;
- chase order: Tetras and Freedom Sticks pulse in left-to-right order of where they stand;
- left/right: sticks on the left of the dance floor alternate with sticks on the right.

Room frame (top-down, as the preview draws it): x runs left to right across the room,
y runs from the booth wall (y = 0) toward the back of the room, z is height above the
floor. A fixture's facing is in degrees, 0 = facing +y (out from the booth wall),
90 = facing +x. Left and right are as the preview shows them (house left = small x).

Pan/tilt model for a GigBAR head (Rev. 4 manual: 540 degrees pan, 180 degrees tilt). Both heads
hang UNDER the T-bar, base up (manual p. 8, front panel drawing), so a head points straight down
at mid tilt and tilts 90 degrees either way to level; it can never point up (1.10.1: before it, tilt
0.5 was level and 1 straight up, so every aim on the real lights landed steeper than drawn and
"ceiling" tipped past straight down to the wall behind the bar). pan 0.5 = the bar's facing, each
1/540 is one degree; tilt 0.5 = straight down (`TILT_DOWN_AT_CENTER`), and each 1/180 above it
tilts one degree toward the pan's heading (the front side), up to level at 1; below 0.5 the head
tilts the other way, toward the back. Which side is the front is a best guess until the arrival
line-up check: if "center" lands behind the bar, a `pan_trim` of 180 puts the front side forward.
Pan 0.5 does NOT face the bar's front (his 11-08 photos, Center all at the middle of the dance
floor, 1.14.0): each head points out along the bar toward its OWN end, head 1 (ch24-29, his right
from the floor) to the bar's own left and head 2 to its own right; the two are mounted mirrored.
`HEAD_HOME` holds those headings (degrees off the bar's facing). Which way pan turns as it rises
is still the guess above; a bar whose Center all lands behind it turns the other way (Mirror,
`pan_invert`), and Set center on each head replaces the guess outright.

Which end is which (1.16.0, his 11-09 screenshot: GigBAR 2 right selected, the real right head moved
but both pictures moved the left one): until 1.16.0 the code took (cos f, -sin f) for the bar's
right-hand side. Seen from above that is its LEFT (facing +y, down the plan, your right hand is at
small x), so head 1 was drawn at the end on his left from the dance floor, on both bars, and every
"bar's own left" above was really its right. HEAD_HOME and the guessed turn direction are written in
that mirrored frame: `_side()` turns them into the room, so the raw pan/tilt a head gets for a target
is exactly what it got before (the lights do the same thing); only where each head sits, and so
which beam the pictures move, changed.
Both are best guesses until the arrival line-up check
(Show Designer, 1.7.0): `pan_trim` / `tilt_trim` (degrees) on a bar correct them without
touching any look, and `pan_invert` mirrors a bar hung the other way round. Whatever a move
asks for, a head never turns more than 90 degrees off its bar's facing (`forward`, 1.9.0): the
spots always light the room in front of the bar, never the wall behind it.

Calibration (1.12.1, the real-rig report 2026-11-08: the spots did not follow the paths drawn
in the preview): the model above is a guess, and the preview draws through the same
guess, so it always looked right. Per head, `HeadCal` holds what the real head did: the raw
pan/tilt that put its beam on the dance floor's center dot (`center`), raw pan/tilt for up to two
more dots (`points`: "near", the floor edge nearest the booth, and "side", its house-left edge),
which way each motor turns, a pan/tilt swap, and the degree ranges (manual: 540 / 180). A head
with a center aims outward from it: heading = the center's heading + pan sign * (raw - center
raw) * range, the same for tilt off straight down. With two or more dots the signs and swap are
fitted (`fit_head`): the combination whose beams land nearest the dots. A flip (`flip_pan`)
reverses pan around the calibrated center, never raw pan 0.5 (the old Mirror button pivoted on
raw 0.5, so any offset in the guess doubled and both heads left the floor). A head without a
center keeps the guessed model and the bar's trims.

Middle twin and Facing the spot (1.16.4, his 11-09 reports on head 4: a full turn at power-up and at
rest, a hard-stop noise, and backwards after Line up my lights). Pan turns 540 degrees over DMX 0..255
(manual Rev. 4 specs), so a heading is reached at two raw pans one motor turn (360 / 540) apart: a
saved center now sits on the twin nearest DMX middle (`HeadCal`, `mid_twin`), whichever way he nudged,
so aims keep well inside the range and never flip turns at an end. And a spot is reached two ways,
turned toward it or turned round and tilted over: a head saved the other way round from the rig's
other heads is turned to face its spots like them (`facing_cal`), every beam pointing where it did. A
center that can't be used either way is named in plain words at Line up (`cal_problem`).

Which side of down and Rest on the facing side (1.16.7, his 11-09 recording 20261109_201341). Tilt 0.5
points straight down at every pan (manual p. 8; his Power-up check), so a center's tilt above or
below 0.5 says which side of straight down the head reached the dot from. A center saved with no dots
(Set center, nudges) kept whatever tilt direction an older line-up left: his head 4 was nudged onto
the dot from the low side (tilt 49) with the high side's direction, so the model put its straight
down at tilt 0 (it pointed out into the room), aimed the middle of the floor behind the bar, and
the picture tilted the other way from the head while he nudged it. Such a center now takes the tilt
direction whose straight down is the fixture's (`side_cal`), before it is turned to face its spots
(`facing_cal`). And rest (`rest_pose`), straight ahead and level, is the same beam both ways round:
when the rig's heads face their spots over the top (tilt above 0.5, his three), it is held that way
round too (`facing_pose`), so starting and ending a line-up no longer turns each head half a turn
and swings it through straight down to point about where it already was.

Confirmed spots stay put, and lights stand where they really are (1.17.0, Llano BL #11766, his 11-10 report:
lining up a second spot moved the first). Each spot he lines up is kept on each head as an anchor, and aims
bend toward the anchors' poses (`aim`, `_anchor_pull`), so every confirmed spot plays back exactly; a spot the
heads can't agree on is named (`converge`). Every light has a position he can measure from the DJ booth's
center and edit on his phone (`measurements`, `set_position`), the plan is kept for Reset to plan, a lost
light is marked `out` and its row closes the gap (`order`, `sides`), and one GigBAR's line-up can be cleared.

An open-space layout (`open`, 1.7.0: outdoors, a tent with no walls) has no walls or ceiling
for beams to land on; the room's size is only the area drawn.

"ceiling" is "as high as safe": a hung head cannot reach the ceiling, so it aims at the back of
the room (the back wall, or the far edge of the drawn area outdoors) at HEAD_CLEAR, a beam that
passes over the dancers' heads, never a level beam at head height. A bar hung lower than that
aims at the far edge of the floor instead.

Room elements and the Stage setup (Llano BL #12344, 2026-11-14: a DJ often can't see the venue until they
arrive). A layout may hold `zones`: a stage, a table area or a no-beam zone, each a rectangle he drags and
sizes on the laptop. The named moving looks (`positions`) never aim a beam into a table area or a no-beam
zone: a floor-level target there is pulled onto the dance floor (`keep_out`), and "ceiling" stops at the
dance floor's far edge instead of crossing the room to the back wall. A spot he steers by hand, and every
line-up spot, still goes exactly where he puts it (a spotlight on the cake table is his call). `stage_layout`
draws a whole room from three numbers (stage width, dance floor depth, GigBAR height above the dance floor):
the bars on the stage's front corners, 2 ft in from each edge, turned in to the middle of the floor.

How far the heads go (Llano PM #23796, asked 11-16 for a wedding: set how high and how far the heads
can go at the venue). A layout may hold `limits`, a box on the room plan drawn and dragged like a room element:
its left and right edges, its near edge (the lowest the beams go) and its far edge (the highest). With `over`
(the default) the far edge is where the highest beam passes over the dancers' heads (HEAD_CLEAR), not where it
lands, so the same box stays right when the GigBARs go up on a 7 ft stand or down onto the stage floor: the
heads' reach is worked out from where they hang now. A bar hung too low to clear heads reads the far edge on
the floor. He sets the box on site in Line up my lights (every head on one spot he steers to each edge), or
drags it. Each head turns the box into a raw pan and tilt range (`head_box`), and the show's own reach for
that head (`head_reach`: every named position, plus a figure's swing) is squeezed into it, axis by axis
(`limit_maps`, applied once a frame by looks.LooksEngine.render): a sweep still sweeps, smaller, and no move
parks on the box's edge. Whatever still reaches past it (a spot he steers, Follow someone) is held at the edge.

Numbering (Llano BL #12396): his Tetra cords run from the right, so Tetra 1 stands on the right and 2, 3
go left (BL #12378). Which end light 1 starts at is a rig fact (settings `rig.numbering`, set by the Show
Designer's Flip the Tetra / stick numbers buttons); every room Llano draws (the presets, the Stage setup)
numbers its Tetras and sticks from that end (`numbered`), so a fresh Stage setup never renumbers his
lights left to right again. A room he saved keeps the numbers it was saved with.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

PAN_RANGE = 540.0
TILT_RANGE = 180.0
TILT_DOWN_AT_CENTER = 0.5     # the tilt that points a hung head straight down (manual p. 8)
# The three above are the manual's numbers and the defaults; the settings' rig.calibration
# (synced from llano.app) replaces them through set_calibration_defaults(), read at call time.
HEAD_CLEAR = 2.0              # meters: "ceiling" beams stay at or above this, over the dancers' heads
SPOT_HEIGHT = 1.5             # meters: a spotlight on a person aims at chest/face height, not their feet
BOOTH_FRONT = 0.5             # meters in front of the booth where "booth" aims (the DJ)
FORWARD_MAX = 90.0            # degrees off the bar's facing a head may turn: never behind the bar
HEAD_HOME = (-90.0, -90.0)    # where each head points at pan 0.5, degrees off the bar's facing (above, 1.31.1)
GUESS_TURN = -1               # which way the guessed heading turns as raw pan rises, in the mirrored frame (1.31.1)
HEAD_SPACING = 0.9            # meters between the two heads on a GigBAR's T-bar
FIXTURE_IDS = ("bar1", "bar2", *(f"tetra{i}" for i in range(1, 7)), *(f"stick{i}" for i in range(1, 5)))
DEFAULT_LAYOUT = "small-room-front"


REF_POINTS = ("center", "near", "side")   # the calibration dots on the dance floor
# The Light doctor's poses (BL #11615): today's aim at the floor's middle, then a step each way in
# pan and in tilt. A plus around the guess, not aims at five spots: a head that turns the other way
# (or has pan and tilt swapped) still lands the middle and one of each pair on the floor to tap.
DOCTOR_PLUS = ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))
DOCTOR_REACH = 0.35   # each step turns the beam this share of the floor's half-width, seen from the head
DOCTOR_MIN_TAPS = 3
DOCTOR_SEEDS = 12     # coarse cells refined per turn direction (pan's twins land in different cells)
# One spot (1.16.0): every head lined up on one spot he picks. His facts: the heads face straight ahead
# at pan 0, tilt 0 (power-up, and where Stop leaves them); at pan 0.5 each points along the bar
# (HEAD_HOME, his 11-08 photos), at tilt 0.5 straight down (1.10.1). With that pose known, the pose
# each head needed for the spot gives its bar's facing and height (`converge`).
HOME_POSE = (0.0, 0.0)          # raw pan, tilt of straight ahead and level
CONVERGE_FIT_M = 0.35           # the bar's facing and height are kept when the heads agree this well
CAL_DOWN_SLACK = 30.0           # degrees a saved center's straight down may sit off the fixture's (cal_problem)
CONVERGE_TURN = 75.0            # a solved facing stays within this many degrees of facing the dance floor
# Confirmed spots stay put (BL #11766, his 11-10 report on 1.16.8: lining up a second spot moved the first one
# by up to 0.59 m). No one model of a head (center, turn directions, ranges) lands his real poses on three
# spots at once: on his rig the best fit, bars free to move too, still misses by 0.24-0.48 m, more than one
# 8-bit pan step (2.1 degrees, ~0.15 m). So each spot he confirms is kept on the head as an anchor (where it
# is, the raw pose that put the beam on it), and an aim near anchors bends the model's pose by their misses:
# exactly onto an anchor at its spot, fading back to the model away from them (ANCHOR_REACH).
ANCHOR_REACH = 20.0             # degrees, seen from the head: an anchor's pull halves about this far from it
ANCHOR_MAX = 30.0               # degrees an anchor may sit off the model before it is ignored as a bad line-up
ANCHOR_WARN_M = 0.3             # meters: a spot the model misses by more is named as disagreeing with the rest
ANCHORS_MAX = 8                 # anchors kept per head (the newest spots win)
MOVE_BETTER = 0.85              # a bar is moved to where its spots say it stands only if that fits this much better
MOVE_MIN_M = 0.25               # ... and only by at least this much (less is within his tape measure)
MOVE_MAX_M = 2.0                # ... and never further than this from where the layout had it
BOUND_M = 0.05                  # a solved height this close to the search's floor or ceiling bound is no answer
FT = 0.3048                     # meters in a foot: he measures in feet (BL #12344)
STAGE_INSET = 2 * FT            # a GigBAR stands this far in from the stage's side and front edges (tripod legs on)
ZONE_KINDS = {"stage": "Stage", "tables": "Tables", "nobeam": "No beams"}   # room elements (BL #12344)
BEAM_FREE = ("tables", "nobeam")   # the moving looks keep their beams out of these
ZONES_MAX = 12
LIMIT_MIN_M = 0.5               # the head-limits box is at least this wide and deep
LIMIT_SAMPLES = 6               # points per edge the box's raw range is read from
LIMIT_CURVE = 16                # headings across the box the pan-dependent tilt range is read at
FIGURE_SWING = (0.125 * 180.0 / 540.0, 0.125)   # raw pan, tilt a size-0.5 circle or eight swings round its spot
MOVE_CAP = 1.0                  # m^2: one pose's pull on where the bar stands is capped (a slipped pose can't drag it)


@dataclass
class HeadCal:
    """One head's calibration (1.12.1); empty until the line-up page's Set center."""
    center: Optional[tuple] = None              # raw (pan, tilt) 0..1 on the floor's center dot
    points: dict = field(default_factory=dict)  # "near" / "side" -> raw (pan, tilt)
    pan_invert: bool = False
    tilt_invert: bool = False
    swap: bool = False                          # the pan channel drives tilt and the other way round
    pan_range: float = field(default_factory=lambda: PAN_RANGE)
    tilt_range: float = field(default_factory=lambda: TILT_RANGE)
    anchors: list = field(default_factory=list)  # confirmed spots (BL #11766): (x, y, raw pan, raw tilt)

    def __post_init__(self):
        # Middle twin (1.16.4, above): the center on the pan twin nearest DMX middle, each dot on its
        # twin nearest the center. Every heading is unchanged; only which turn of the motor reaches it.
        if not self.center:
            return
        i = 1 if self.swap else 0      # the channel that turns 540 degrees
        step = 360.0 / self.pan_range
        center = list(self.center)
        center[i] = mid_twin(center[i], step)
        self.center = tuple(center)
        for name, pt in self.points.items():
            pt = list(pt)
            pt[i] = mid_twin(pt[i], step, near=center[i])
            self.points[name] = tuple(pt)

    def down_tilt(self, center_off: float) -> float:
        """The tilt motor's raw value pointing straight down, by this calibration: `center_off` is the
        angle off straight down from the head to the center dot (the motor's channel, swap or not)."""
        tc = self.center[0] if self.swap else self.center[1]
        return tc - (-1 if self.tilt_invert else 1) * center_off / self.tilt_range

    def to_dict(self) -> dict:
        out = {k: v for k, v in (("center", list(self.center) if self.center else None),
                                 ("points", {k: list(v) for k, v in self.points.items()} or None)) if v}
        out.update({k: True for k in ("pan_invert", "tilt_invert", "swap") if getattr(self, k)})
        if self.pan_range != PAN_RANGE:
            out["pan_range"] = self.pan_range
        if self.tilt_range != TILT_RANGE:
            out["tilt_range"] = self.tilt_range
        if self.anchors:
            out["anchors"] = [list(a) for a in self.anchors]
        return out

    @classmethod
    def from_dict(cls, d, what: str) -> "HeadCal":
        if d is None:
            return cls()
        if not isinstance(d, dict):
            raise ValueError(f"{what}: calibration must be an object")

        def raw(v, name):
            if not (isinstance(v, (list, tuple)) and len(v) == 2):
                raise ValueError(f"{what} {name}: a raw pan and tilt")
            return (_num(v[0], f"{what} {name} pan", 0.0, 1.0), _num(v[1], f"{what} {name} tilt", 0.0, 1.0))
        pts = d.get("points") or {}
        if not isinstance(pts, dict) or any(k not in REF_POINTS[1:] for k in pts):
            raise ValueError(f"{what}: points are near and side")
        anchors = d.get("anchors") or []
        if not isinstance(anchors, list) or len(anchors) > ANCHORS_MAX \
                or any(not (isinstance(a, (list, tuple)) and len(a) == 4) for a in anchors):
            raise ValueError(f"{what}: anchors are up to {ANCHORS_MAX} confirmed spots, each x, y, pan, tilt")
        anchors = [(_num(a[0], f"{what} anchor x", 0.0, 100.0), _num(a[1], f"{what} anchor y", 0.0, 100.0),
                    _num(a[2], f"{what} anchor pan", 0.0, 1.0), _num(a[3], f"{what} anchor tilt", 0.0, 1.0))
                   for a in anchors]
        return cls(center=raw(d["center"], "center") if d.get("center") is not None else None,
                   points={k: raw(v, k) for k, v in pts.items()},
                   pan_invert=d.get("pan_invert") is True, tilt_invert=d.get("tilt_invert") is True,
                   swap=d.get("swap") is True,
                   pan_range=_num(d.get("pan_range", PAN_RANGE), f"{what} pan range", 90, 720),
                   tilt_range=_num(d.get("tilt_range", TILT_RANGE), f"{what} tilt range", 45, 360),
                   anchors=anchors)


def set_calibration_defaults(cal: dict) -> bool:
    """The rig block's calibration defaults (settings_contract rig.calibration); True if changed.
    A head with its own saved ranges keeps them; every other head and the guessed model use these."""
    global PAN_RANGE, TILT_RANGE, TILT_DOWN_AT_CENTER
    new = (float(cal["pan_range"]), float(cal["tilt_range"]), float(cal["tilt_down"]))
    if new == (PAN_RANGE, TILT_RANGE, TILT_DOWN_AT_CENTER):
        return False
    PAN_RANGE, TILT_RANGE, TILT_DOWN_AT_CENTER = new
    return True


@dataclass
class Spot:
    x: float
    y: float
    z: float = 0.0
    facing: Optional[float] = None   # degrees; None = face the dance floor
    pan_trim: float = 0.0
    tilt_trim: float = 0.0
    pan_invert: bool = False         # the bar hangs the other way round: pan turns the other way
    cal: list = field(default_factory=lambda: [HeadCal(), HeadCal()])   # each head's calibration (1.12.1)
    out: bool = False                # lost or not set up at this venue tonight (BL #11766): the show closes the gap
    # How the room picture draws the light, degrees like facing; None = square to its facing (Llano BL #12454, his
    # 11-14 9:42 PM video at 0:40: "see how it's caddy cornered ... maybe we have a way to rotate it"). The drawing
    # only: nothing that aims reads it (the heads aim from facing and the line-up).
    drawn: Optional[float] = None


@dataclass
class Rect:
    x: float
    y: float
    w: float
    d: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.d / 2


@dataclass
class Zone(Rect):
    """A room element (BL #12344): a stage, a table area or a no-beam zone, top-down in meters."""
    kind: str = "nobeam"
    label: str = ""

    def has(self, x: float, y: float) -> bool:
        return self.x - 1e-9 <= x <= self.x + self.w + 1e-9 and self.y - 1e-9 <= y <= self.y + self.d + 1e-9

    def to_dict(self) -> dict:
        out = {"kind": self.kind, "x": self.x, "y": self.y, "w": self.w, "d": self.d}
        if self.label:
            out["label"] = self.label
        return out


@dataclass
class Limits(Rect):
    """How far the moving heads go at this venue (PM #23796): a box on the room plan, top-down in meters.
    `over`: the far edge is where the highest beam passes over heads (HEAD_CLEAR), else where it lands."""
    over: bool = True

    def to_dict(self) -> dict:
        out = {"x": round(self.x, 3), "y": round(self.y, 3), "w": round(self.w, 3), "d": round(self.d, 3)}
        if not self.over:
            out["over"] = False
        return out


@dataclass
class Layout:
    name: str
    label: str
    room: tuple[float, float, float]           # width, depth, ceiling height
    booth: Rect
    floor: Rect
    spots: dict[str, Spot] = field(default_factory=dict)
    preset: bool = False
    open: bool = False                         # no walls or ceiling (outdoors, an open tent)
    plan: dict = field(default_factory=dict)   # where each light was planned to stand (BL #11766): id -> x, y, z, facing
    zones: list = field(default_factory=list)  # room elements (BL #12344): Zone, a stage, tables or a no-beam zone
    limits: Optional[Limits] = None            # how far the moving heads go here (PM #23796); None = anywhere in front
    _memo: dict = field(default_factory=dict, repr=False, compare=False)   # anchor misses per head, by inputs

    # --- geometry ----------------------------------------------------------------------

    def facing(self, fid: str) -> float:
        s = self.spots[fid]
        if s.facing is not None:
            return s.facing
        return math.degrees(math.atan2(self.floor.cx - s.x, self.floor.cy - s.y))

    def heads(self, bar: int) -> list[tuple[float, float, float]]:
        """World position of a GigBAR's two heads: head 1 (channels 24-29) on the bar's own left as
        it faces out, the RIGHT end as you face the bar from the dance floor (1.16.0)."""
        s = self.spots[f"bar{bar}"]
        f = math.radians(self.facing(f"bar{bar}"))
        # Facing vector (sin f, cos f); seen from above, the bar's own left-hand side is (cos f, -sin f).
        lx, ly = math.cos(f), -math.sin(f)
        h = HEAD_SPACING / 2
        return [(s.x + lx * h, s.y + ly * h, s.z), (s.x - lx * h, s.y - ly * h, s.z)]

    def all_heads(self) -> list[tuple[int, int, tuple[float, float, float]]]:
        return [(b, i, p) for b in (1, 2) for i, p in enumerate(self.heads(b))]

    # --- calibration (1.12.1) --------------------------------------------------------------

    def head_index(self, bar: int, head: tuple[float, float, float]) -> int:
        """Which of a bar's heads sits at `head` (callers that only know the position)."""
        hs = self.heads(bar)
        return min(range(len(hs)), key=lambda m: sum((a - b) ** 2 for a, b in zip(hs[m], head)))

    def ref_target(self, name: str) -> tuple[float, float, float]:
        fl = self.floor
        return {"center": (fl.cx, fl.cy, 0.0), "near": (fl.cx, fl.y, 0.0), "side": (fl.x, fl.cy, 0.0)}[name]

    def cal(self, bar: int, m: int) -> Optional[HeadCal]:
        """A head's calibration, or None while it has no center (the guessed model applies)."""
        c = self.spots[f"bar{bar}"].cal[m]
        return self.partner_cal(bar, m, self.facing_cal(bar, m, self.side_cal(bar, m, c))) if c.center else None

    def side_cal(self, bar: int, m: int, c: HeadCal) -> HeadCal:
        """The same calibration, its tilt turning the way that puts straight down at the fixture's
        (Which side of down, 1.16.7): a center with no dots says where the head points, not which way
        its tilt turns, so of the two directions the one whose straight down (`down_tilt`) is nearer
        TILT_DOWN_AT_CENTER is the head's. A head with dots keeps its own (the fit measured it)."""
        if not c.center or c.points:
            return c
        _, oc = self._center_angles(bar, m)
        other = HeadCal(c.center, {}, c.pan_invert, not c.tilt_invert, c.swap, c.pan_range, c.tilt_range, list(c.anchors))
        if abs(other.down_tilt(oc) - TILT_DOWN_AT_CENTER) < abs(c.down_tilt(oc) - TILT_DOWN_AT_CENTER):
            return other
        return c

    def rest_pose(self) -> tuple[float, float]:
        """Raw (pan, tilt) every head rests at (Rest on the facing side, 1.16.7): straight ahead and
        level (HOME_POSE on the middle twin, `rest_pan`), turned round to the side the rig's calibrated
        heads face their spots from (`facing_pose`); the same beam either way."""
        return self.facing_pose(rest_pan(PAN_RANGE), HOME_POSE[1])

    def partner_cal(self, bar: int, m: int, c: HeadCal) -> HeadCal:
        """The same calibration, its pan turning the way its bar partner's does (One chassis, 1.16.6,
        his 11-10 report: after he re-set head 4's center it lined up, but panned right while head 3
        panned left). A bar's two heads are the same motor in one housing, so pan can't turn opposite
        ways on one bar; a center alone (Set center, a nudge) measures where the head points, not which
        way it turns, so `pan_invert` was whatever an older line-up left (his: from a center saved
        turned round). A head with dots keeps its own (the fit measured it). When neither head of the
        bar has dots and they disagree, the other bar's calibrated heads settle it if they agree with
        each other; with nothing to go on, each keeps its own. Both read facing the rig's way."""
        if not c.center or c.points:
            return c
        o = self.spots[f"bar{bar}"].cal[1 - m]
        if not o.center:
            return c
        o = self.facing_cal(bar, 1 - m, self.side_cal(bar, 1 - m, o))
        if o.pan_invert == c.pan_invert:
            return c
        if not o.points:
            other = [self.facing_cal(3 - bar, k, self.side_cal(3 - bar, k, x)).pan_invert
                     for k, x in enumerate(self.spots[f"bar{3 - bar}"].cal) if x.center]
            if not other or len(set(other)) > 1 or other[0] != o.pan_invert:
                return c
        return HeadCal(c.center, dict(c.points), o.pan_invert, c.tilt_invert, c.swap, c.pan_range, c.tilt_range,
                       list(c.anchors))

    def cal_problem(self, bar: int, m: int) -> Optional[str]:
        """Why a head's saved center can't be used (Facing the spot, 1.16.4), in plain words, or None:
        it still faces the other way from the rig's other heads after `facing_cal` (it can't reach the
        center dot their way round), or the straight down it implies is more than CAL_DOWN_SLACK
        degrees off the fixture's (manual: tilt 0.5), a pose that was never on the dot."""
        c = self.cal(bar, m)
        if c is None:
            return None
        _, oc = self._center_angles(bar, m)
        side = self._tilt_side()
        if side and (-1 if c.tilt_invert else 1) != side:
            return "its saved line-up has it turned round the other way from the other heads"
        if abs(c.down_tilt(oc) - TILT_DOWN_AT_CENTER) * c.tilt_range > CAL_DOWN_SLACK:
            return "its saved line-up doesn't match how the head tilts"
        return None

    def facing_pose(self, pan: float, tilt: float) -> tuple[float, float]:
        """A raw pose turned round to the rig's side (`_tilt_side`) if it is on the other: pan half a
        turn (the twin nearest DMX middle), tilt mirrored about straight down; the same beam. For a head
        aimed by the guess beside calibrated heads (Line up my lights, `cal_problem`)."""
        side = self._tilt_side()
        if not side or (tilt - TILT_DOWN_AT_CENTER) * side >= 0:
            return pan, tilt
        twins = [pan + k * 180.0 / PAN_RANGE for k in (-3, -1, 1, 3) if 0.0 <= pan + k * 180.0 / PAN_RANGE <= 1.0]
        mirrored = 2 * TILT_DOWN_AT_CENTER - tilt
        if not twins or not 0.0 <= mirrored <= 1.0:
            return pan, tilt
        return min(twins, key=lambda t: abs(t - 0.5)), mirrored

    def _tilt_side(self) -> int:
        """Which way the rig's calibrated heads tilt toward their center dots: +1 (the tilt value rises
        toward it), -1 (falls toward it), 0 when they don't clearly agree. Read from the saved
        calibrations themselves (`tilt_invert`), most heads winning."""
        votes = [(-1 if self.side_cal(b, m, c).tilt_invert else 1)
                 for b in (1, 2) for m, c in enumerate(self.spots[f"bar{b}"].cal) if c.center]
        total = sum(votes)
        return (total > 0) - (total < 0) if len(votes) >= 2 else 0

    def facing_cal(self, bar: int, m: int, c: HeadCal) -> HeadCal:
        """The same calibration, turned to face its dots the way the rig's other heads do (Facing the
        spot, 1.16.4, his 11-09 report: after Line up my lights head 4 sat backwards and didn't turn
        with the others). A head reaches the center dot two ways: turned toward it and tilted down to
        it, or turned 180 the other way and tilted over the top; the floor can't tell them apart, so a
        fit's tie or a nudge can save either, and a head saved the other way from the rest has its
        tilt turning the other way (`tilt_invert`). Such a calibration is turned round: pan half a turn
        (on the twin nearest DMX middle), tilt mirrored about straight down, tilt turning the rig's way.
        Every pose points exactly where it did; aims, the front clamp and the forward clamp then agree
        with the other heads on which side is the front. Kept as is when the rig's heads don't clearly
        agree (`_tilt_side`), or the turned pose is out of the motors' range."""
        side = self._tilt_side()
        st = -1 if c.tilt_invert else 1
        if not c.center or not side or st == side:
            return c
        _, oc = self._center_angles(bar, m)
        ip, it = (1, 0) if c.swap else (0, 1)
        center = list(c.center)
        tilt = center[it] - 2.0 * st * oc / c.tilt_range
        twins = [center[ip] + k * 180.0 / c.pan_range for k in (-3, -1, 1, 3)]
        twins = [t for t in twins if 0.0 <= t <= 1.0]
        if not (0.0 <= tilt <= 1.0) or not twins:
            return c
        center[ip], center[it] = min(twins, key=lambda t: abs(t - 0.5)), tilt
        # The dots are real poses and the turned model points them exactly where the old one did: kept.
        return HeadCal(tuple(center), dict(c.points), c.pan_invert, not c.tilt_invert, c.swap, c.pan_range, c.tilt_range,
                       list(c.anchors))

    def _center_angles(self, bar: int, m: int) -> tuple[float, float]:
        """The heading and the angle off straight down from a head to the floor's center dot."""
        o = self.heads(bar)[m]
        dx, dy, dz = (t - h for t, h in zip(self.ref_target("center"), o))
        return math.degrees(math.atan2(dx, dy)), math.degrees(math.atan2(math.hypot(dx, dy), -dz))

    def _cal_angles(self, bar: int, m: int, c: HeadCal, pan: float, tilt: float) -> tuple[float, float]:
        hc, oc = self._center_angles(bar, m)
        (pp, tt), (pc, tc) = ((tilt, pan), c.center[::-1]) if c.swap else ((pan, tilt), c.center)
        heading = hc + (-1 if c.pan_invert else 1) * (pp - pc) * c.pan_range
        off = oc + (-1 if c.tilt_invert else 1) * (tt - tc) * c.tilt_range
        return heading, off

    def _cal_aim(self, bar: int, m: int, c: HeadCal, target) -> tuple[float, float]:
        o = self.heads(bar)[m]
        dx, dy, dz = (t - h for t, h in zip(target, o))
        flat = math.hypot(dx, dy)
        hc, oc = self._center_angles(bar, m)
        hw = math.degrees(math.atan2(dx, dy)) if flat > 1e-9 else hc
        ow = math.degrees(math.atan2(flat, -dz))
        (pc, tc) = c.center[::-1] if c.swap else c.center
        sp, st = (-1 if c.pan_invert else 1), (-1 if c.tilt_invert else 1)
        best = None
        facing = self._tilt_side() != 0
        # A hung head reaches a point two ways: (heading, off) or (heading + 180, -off). Take the
        # one in range nearest the calibrated center, so a move between targets never swings round;
        # when the rig's heads agree which way faces a spot (Facing the spot, 1.16.4, `facing_cal`),
        # the facing way first (`off` >= 0: this calibration was turned to face its center dot).
        for h, off in ((hw, ow), (hw + 180.0, -ow)):
            for k in (-1, 0, 1):
                pp = pc + sp * ((h - hc + 180.0) % 360.0 - 180.0 + 360.0 * k) / c.pan_range
                tt = tc + st * (off - oc) / c.tilt_range
                back = facing and off < 0 and ow > 1.0
                cost = (max(0.0, -pp, pp - 1) + max(0.0, -tt, tt - 1)) * 100 + back * 10 \
                    + abs(pp - pc) + abs(tt - tc)
                if best is None or cost < best[0]:
                    best = (cost, _clamp(pp), _clamp(tt))
        _, pp, tt = best
        return (tt, pp) if c.swap else (pp, tt)

    def beam_of(self, bar: int, m: int, pan: float, tilt: float) -> tuple[float, float, float]:
        """Unit direction head m points for a pan/tilt, calibrated when it has a center. Near confirmed
        spots it inverts the anchors' pull (`aim`), so a confirmed pose is drawn landing on its spot."""
        c = self.cal(bar, m)
        if c is None:
            return self.beam(bar, self.heads(bar)[m], pan, tilt)
        misses = self._anchor_misses(bar, m, c)
        p, t = pan, tilt
        for _ in range(6 if misses else 0):   # the pull is smooth and small: a few rounds settle it
            k = self._anchor_pull(misses, self._cal_beam(bar, m, c, p, t))
            p, t = pan - k[0], tilt - k[1]
        return self._cal_beam(bar, m, c, p, t)

    def anchor_pulls(self, bar: int, m: int) -> list:
        """Head m's confirmed-spot pulls for a picture to draw with (`beam_of`): each usable anchor as
        [dx, dy, dz, pan, tilt], its unit direction from the head and its raw pull. Empty without a center.
        The room picture drew calibrated heads without them, so a head bent onto a confirmed spot far from
        the center showed its beam overshooting the spot (his 11-14 9:06 PM video, BL #12381)."""
        c = self.cal(bar, m)
        if c is None:
            return []
        return [[*map(float, a), float(r[0]), float(r[1])] for a, r in self._anchor_misses(bar, m, c)]

    def _cal_beam(self, bar: int, m: int, c: HeadCal, pan: float, tilt: float) -> tuple[float, float, float]:
        heading, off = (math.radians(a) for a in self._cal_angles(bar, m, c, pan, tilt))
        return (math.sin(off) * math.sin(heading), math.sin(off) * math.cos(heading), -math.cos(off))

    # --- confirmed spots (BL #11766) --------------------------------------------------------

    def _anchor_misses(self, bar: int, m: int, c: HeadCal) -> list:
        """Each usable anchor of head m: its direction from the head, and how far the model's pose for
        its spot sits from the pose he confirmed there (raw, pan on the nearest motor turn). An anchor
        more than ANCHOR_MAX off is a line-up the model can't believe (another way round, a moved bar):
        ignored here, named by `converge`. Cached per head on everything it reads."""
        if not c.anchors:
            return []
        s = self.spots[f"bar{bar}"]
        key = (bar, m, c.center, c.pan_invert, c.tilt_invert, c.swap, c.pan_range, c.tilt_range, tuple(c.anchors),
               s.x, s.y, s.z, self.facing(f"bar{bar}"), tuple(vars(self.floor).values()), self._tilt_side())
        hit = self._memo.get(key)   # the show and the page's server thread both aim: never check-then-read
        if hit is not None:
            return hit
        o = self.heads(bar)[m]
        i = 1 if c.swap else 0                                   # the channel that turns 540 degrees
        step = 360.0 / c.pan_range
        ranges = (c.tilt_range, c.pan_range) if c.swap else (c.pan_range, c.tilt_range)
        out = []
        _, oc = self._center_angles(bar, m)
        for x, y, pan, tilt in c.anchors:
            mp = self._cal_aim(bar, m, c, (x, y, 0.0))
            best = None
            # The pose as saved, and the same beam reached the other way round (half a pan turn, tilt
            # mirrored about this calibration's straight down): a calibration turned to face its spots
            # (`facing_cal`) aims the other way round from poses saved before it turned.
            for p_, t_ in ((pan, tilt), self._other_way(c, oc, pan, tilt)):
                r = [p_ - mp[0], t_ - mp[1]]          # both in channel order
                r[i] -= round(r[i] / step) * step
                size = max(abs(r[0]) * ranges[0], abs(r[1]) * ranges[1])
                if best is None or size < best[0]:
                    best = (size, r)
            if best[0] <= ANCHOR_MAX:
                out.append((_unit(o, (x, y, 0.0)), tuple(best[1])))
        if len(self._memo) > 64:
            self._memo.clear()
        self._memo[key] = out
        return out

    @staticmethod
    def _other_way(c: HeadCal, oc: float, pan: float, tilt: float) -> tuple[float, float]:
        """A raw pose (channel order) reaching the same beam the other way round under calibration c:
        the 540-degree motor half a turn on, the other mirrored about c's straight down."""
        ip, it = (1, 0) if c.swap else (0, 1)
        pose = [pan, tilt]
        pose[ip] += 180.0 / c.pan_range
        pose[it] = 2.0 * c.down_tilt(oc) - pose[it]
        return pose[0], pose[1]

    @staticmethod
    def _anchor_pull(misses: list, d) -> list:
        """The raw (pan, tilt) correction toward direction `d`: an anchor's miss in full at its own spot,
        blended by inverse square angle between anchors, and fading to nothing past ANCHOR_REACH."""
        num, den = [0.0, 0.0], 1.0 / ANCHOR_REACH ** 2
        for a, r in misses:
            ang = math.degrees(math.acos(max(-1.0, min(1.0, sum(p * q for p, q in zip(a, d))))))
            if ang < 1e-6:
                return list(r)
            w = 1.0 / ang ** 2
            num, den = [num[0] + w * r[0], num[1] + w * r[1]], den + w
        return [num[0] / den, num[1] / den]

    def anchored(self, bar: int, m: int, c: HeadCal, pose: tuple, target) -> tuple[float, float]:
        """A calibrated pose for `target` bent by head m's confirmed spots (`aim` does this)."""
        misses = self._anchor_misses(bar, m, c)
        if not misses:
            return pose
        k = self._anchor_pull(misses, _unit(self.heads(bar)[m], target))
        return _clamp(pose[0] + k[0]), _clamp(pose[1] + k[1])

    def spot_miss(self, bar: int, m: int, x: float, y: float, pan: float, tilt: float) -> Optional[float]:
        """How far (meters, on the floor) the head's model, anchors aside, lands a pose from the spot
        (x, y) it was confirmed on; None when that pose's beam never reaches the floor."""
        c = self.cal(bar, m)
        if c is None:
            return None
        o = self.heads(bar)[m]
        d = self._cal_beam(bar, m, c, pan, tilt)
        if d[2] > -1e-6:
            return None
        t = -o[2] / d[2]
        return math.dist((o[0] + d[0] * t, o[1] + d[1] * t), (x, y))

    def fit_head(self, bar: int, m: int) -> Optional[float]:
        """With a center and at least one more dot, set the signs and swap whose beams land
        nearest the dots; the worst miss in degrees, or None when there is nothing to fit."""
        c = self.spots[f"bar{bar}"].cal[m]
        if not c.center or not c.points:
            return None
        o = self.heads(bar)[m]

        def miss(cand: HeadCal) -> float:
            worst = 0.0
            for name, (pan, tilt) in cand.points.items():
                heading, off = (math.radians(a) for a in self._cal_angles(bar, m, cand, pan, tilt))
                d = (math.sin(off) * math.sin(heading), math.sin(off) * math.cos(heading), -math.cos(off))
                t = [a - b for a, b in zip(self.ref_target(name), o)]
                n = math.sqrt(sum(v * v for v in t)) or 1.0
                cosang = max(-1.0, min(1.0, sum(a * b / n for a, b in zip(d, t))))
                worst = max(worst, math.degrees(math.acos(cosang)))
            return worst
        cands = [HeadCal(c.center, c.points, pi, ti, sw, c.pan_range, c.tilt_range)
                 for sw in (False, True) for pi in (False, True) for ti in (False, True)]
        best = min(cands, key=miss)
        c.pan_invert, c.tilt_invert, c.swap = best.pan_invert, best.tilt_invert, best.swap
        return miss(best)

    def doctor_poses(self, bar: int, m: int) -> list[tuple[float, float]]:
        """The Light doctor's raw poses for head m (DOCTOR_PLUS), on the DMX step so the bytes he
        logs are the bytes the head got. Pan and tilt steps turn the beam the same angle."""
        fl, head = self.floor, self.heads(bar)[m]
        pc, tc = self.aim(bar, head, self.ref_target("center"), m)
        dist = math.dist(head, self.ref_target("center"))
        turn = math.degrees(math.atan2(min(fl.w, fl.d) / 2 * DOCTOR_REACH * 2, dist))
        c = self.cal(bar, m) or HeadCal()
        dp, dt = turn / c.pan_range, turn / c.tilt_range
        return [(round(_clamp(pc + i * dp) * 255) / 255, round(_clamp(tc + j * dt) * 255) / 255) for i, j in DOCTOR_PLUS]

    def fit_taps(self, bar: int, m: int, samples, combos=None, prefer=None) -> tuple[HeadCal, float]:
        """The Light doctor's fit: `samples` are (pan, tilt, (x, y)), a raw pose and where on the
        floor he tapped its beam. Tries every swap and turn direction, and for each the center
        (the raw pan/tilt on the floor's center dot) whose beams land nearest the taps. Returns
        the head's new calibration, ranges kept, and its worst miss in degrees."""
        if not samples:
            raise ValueError("tap at least one beam so Llano can work this head out")
        old = self.spots[f"bar{bar}"].cal[m]
        # Tap to aim (11-09): with fewer than DOCTOR_MIN_TAPS taps only the center is solved, the
        # turn directions and swap kept from the head's model (its saved calibration, else the guess:
        # pan turns as the bar's Mirror says, in the room (`_side`), tilt rises toward the front, no
        # swap), so one tap of a known pose places the head.
        if combos is not None:   # one spot (1.16.0): the turn directions its solve settled
            combos = list(combos)
        elif len(samples) >= DOCTOR_MIN_TAPS:
            combos = [(sw, sp, st) for sw in (False, True) for sp in (1, -1) for st in (1, -1)]
        elif old.center and not self.cal_problem(bar, m):   # a center that can't be used isn't a model to keep
            old = self.facing_cal(bar, m, self.side_cal(bar, m, old))
            combos = [(old.swap, -1 if old.pan_invert else 1, -1 if old.tilt_invert else 1)]
        else:
            combos = [(False, _guess_turn(self.spots[f"bar{bar}"]), 1)]
        o = self.heads(bar)[m]
        hc, oc = self._center_angles(bar, m)
        want = []
        for pan, tilt, (x, y) in samples:
            t = (x - o[0], y - o[1], -o[2])
            n = math.sqrt(sum(v * v for v in t)) or 1.0
            want.append((pan, tilt, tuple(v / n for v in t)))

        def errs(sw, sp, st, pc, tc):
            for pan, tilt, w in want:
                pp, tt = (tilt, pan) if sw else (pan, tilt)
                h = math.radians(hc + sp * (pp - pc) * old.pan_range)
                off = math.radians(oc + st * (tt - tc) * old.tilt_range)
                d = (math.sin(off) * math.sin(h), math.sin(off) * math.cos(h), -math.cos(off))
                yield math.degrees(math.acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(d, w))))))

        def cost(*a):
            return sum(e * e for e in errs(*a))
        fits = []
        for sw, sp, st in combos:
            # coarse over the whole range, then to the DMX step around the best
            # Pan's 540 degrees reach a heading twice, so a fit has twins 360 apart: refine
            # the best few coarse cells, not just one, and let the tie-break below choose.
            grid = [i / 50 for i in range(51)]
            coarse = sorted((cost(sw, sp, st, pc, tc), pc, tc) for pc in grid for tc in grid)
            near = lambda v, step: [min(1.0, max(0.0, v + i * step)) for i in range(-6, 7)]
            for c0 in coarse[:DOCTOR_SEEDS]:
                c1 = min(((cost(sw, sp, st, pc, tc), pc, tc) for pc in near(c0[1], 1 / 255) for tc in near(c0[2], 1 / 255)))
                c1 = min(((cost(sw, sp, st, pc, tc), pc, tc) for pc in near(c1[1], 1 / 2040) for tc in near(c1[2], 1 / 2040)))
                fits.append((c1[0], sw, sp, st, c1[1], c1[2]))
        # A head turned 180 in pan with its tilt the other side of straight down points the same
        # way: equal fits. Keep the one whose center is nearest today's aim, not the far end of tilt;
        # one spot (1.16.0) prefers the poses he nudged the head to, or the next aim spins it 360.
        top = min(f[0] for f in fits)
        guess = prefer or self.aim(bar, o, self.ref_target("center"), m)
        def gap(f):
            raw = (f[5], f[4]) if f[1] else (f[4], f[5])
            return abs(raw[0] - guess[0]) + abs(raw[1] - guess[1])
        _, sw, sp, st, pc, tc = min((f for f in fits if f[0] <= top * 1.05 + 0.05), key=gap)
        center = (round(tc, 5), round(pc, 5)) if sw else (round(pc, 5), round(tc, 5))
        cal = self.facing_cal(bar, m, HeadCal(center, {}, sp < 0, st < 0, sw, old.pan_range, old.tilt_range))
        return cal, max(errs(sw, sp, st, pc, tc))

    def converge(self, samples) -> dict:
        """One spot (1.16.0): `samples` are (bar, head, pan, tilt, (x, y)), each the raw pose he nudged
        a head to so its beam sits on the floor spot (x, y); two spots per head refine it. Per bar
        with both heads lined up, the facing and height whose straight-ahead model (HOME_POSE, every
        turn direction tried) lands both heads' poses nearest their spots are kept when they agree
        within CONVERGE_FIT_M; each head is then fitted to its own poses (fit_taps) with those turn
        directions, so the spot itself is exact. A bar that can't be solved keeps where the layout
        says it stands and still gets each head fitted. Changes the layout; returns what it found.

        Every spot stays put (BL #11766): each head keeps each spot it was lined up on as an anchor, so a
        second or third spot never moves the first. Where one head's spots disagree with each other by
        more than ANCHOR_WARN_M under any one model (a light moved, a pose not quite on its spot, a
        position measured wrong), the worst is named in `disagree` so he can check it."""
        by = {}
        # A head lined up turned the other way round (pan half a turn, tilt over the top) points its beam
        # exactly where the same head turned the rig's way would (BL #12381, the 11-14 report: once a head
        # was turned the opposite way, everything after it went wrong). Its pose is read as that
        # same beam on the rig's side (`facing_pose`) before anything is fitted, so it can't flip which
        # way that head's, its partner's, or the rig's tilt turns.
        for b, m, pan, tilt, (x, y) in samples:
            if b not in (1, 2) or m not in (0, 1):
                raise ValueError("bar must be 1 or 2 and head 0 or 1")
            pan, tilt = self.facing_pose(float(pan), float(tilt))
            by.setdefault(b, {}).setdefault(m, []).append((pan, tilt, (float(x), float(y))))
        # Spots lined up before (saved, the app reopened since) count as if lined up now: a new pose on the
        # same spot wins. Starting over is Clear line-up (clear_lineup), never a new spot.
        for b, heads in by.items():
            for m, rows in heads.items():
                new = {xy for *_, xy in rows}
                rows[:0] = [(p, t, (x, y)) for x, y, p, t in self.spots[f"bar{b}"].cal[m].anchors if (x, y) not in new]
        self.keep_plan()   # a bar this moves or turns can go back to plan
        # What each head had before (BL #12381): a line-up that worked is never swapped for one that can't
        # hold the spot he just lined up or that the app itself would refuse next time (`cal_problem`).
        before = {(b, m): (HeadCal.from_dict(self.spots[f"bar{b}"].cal[m].to_dict(), "cal")
                           if self.spots[f"bar{b}"].cal[m].center else None,
                           self.cal_problem(b, m) is None)
                  for b in by for m in (0, 1)}
        out = {"bars": {}}
        for b, heads in sorted(by.items()):
            s = self.spots[f"bar{b}"]
            was = {"facing": round(self.facing(f"bar{b}"), 1), "height": round(s.z, 2)}
            stood, cals = (s.x, s.y, s.z, s.facing), list(s.cal)
            # One spot never re-solves a bar whose two heads were both already lined up (BL #12381 follow-up):
            # one spot is four numbers for a facing, a height and four turn directions, so even a solve every
            # head plays back can be a different bar (his Nov 10 rig re-lined on one spot, poses 2 DMX steps
            # off: GigBAR 1 "solved" at 2.99 m, facing -0.8, every other aim up to 30 steps off). Such a bar
            # keeps where it stands; each head's center moves to the spot and keeps its turn directions
            # (fit_taps keeps a usable saved model's on one pose). A second spot, or a new bar, still solves.
            nspots = len({xy for rows in heads.values() for *_, xy in rows})
            lined = all(before[(b, m)][0] is not None and before[(b, m)][1] for m in (0, 1))
            solved = self._solve_bar(b, heads) if len(heads) == 2 and (nspots >= 2 or not lined) else None
            # A solve pinned on the height search's bound is no bar position (BL #12381, his 11-14 9:03 PM line-up on
            # 1.26.1: three spots "solved" GigBAR 2 at 3.0 m, his ceiling, and moved it 0.9 m toward the booth;
            # every spot still played back, so the soundness check passed). The best fit wanted a bar above the
            # ceiling: the poses disagree with every real bar, so it keeps where it stands like an unsolved bar.
            pinned = solved is not None and not self._height_inside(solved["height"])
            if pinned:
                solved = None
            rep = self._converge_bar(b, heads, solved, was)
            if pinned:
                rep.update(stayed=True, why="its spots only fit a bar hung at the ceiling or the floor, so it keeps "
                                            "the position shown and every spot you lined up is held exactly")
            if len(heads) == 2 and solved is None and lined and not pinned:
                rep.update(stayed=True, why="its heads were already lined up, so one spot moves their aim and "
                                            "keeps where the bar stands")
            if (rep["solved"] or "moved" in rep) and not self._bar_sound(b, heads):
                # The solve fit the poses with a model the heads can't play back (his 11-14 line-up: one spot
                # "solved" GigBAR 2 at 2.99 m, tilting the wrong way, so both heads then missed by 7-10 m and
                # the next Line up refused the line-up it had just saved). The bar stays where it stood and
                # each head is fitted to its own poses, the way an unsolved bar is.
                (s.x, s.y, s.z, s.facing), s.cal = stood, list(cals)   # each head refits from what it had
                rep = self._converge_bar(b, heads, None, was)
                rep["why"] = ("its heads only agreed on where it faces with a model they can't play back, so it "
                              "keeps the position shown; line up a second spot and Llano works it out")
                rep["stayed"] = True   # news, not his mistake: the laptop says it plainly, not in red
            for m, rows in sorted(heads.items()):
                prev, prev_ok = before[(b, m)]
                last = {xy: (p, t) for p, t, xy in rows}
                if prev is not None and prev_ok and (self.cal_problem(b, m) or self._holds(b, m, last) < len(last)):
                    s.cal[m] = prev   # the line-up that worked stays; this pose is named below as not held
                    rep.setdefault("kept", []).append(m)
            out["bars"][b] = rep
        out["held"], out["disagree"] = self._spot_report(by)
        return out

    def _converge_bar(self, b: int, heads: dict, solved: Optional[dict], was: dict) -> dict:
        """One bar of `converge`: apply its solve (or none) and fit each head to its own poses."""
        s = self.spots[f"bar{b}"]
        rep = {"was": was, "solved": False}
        nspots = len({xy for rows in heads.values() for *_, xy in rows})
        if solved and "x" in solved:   # its spots say the bar stands somewhere else: moved there, plan kept
            self.keep_plan()
            plan = self.planned(f"bar{b}")
            s.x, s.y = round(solved["x"], 2), round(solved["y"], 2)
            s.facing, s.z = round(solved["facing"], 1), round(solved["height"], 2)
            rep["moved"] = {"x": s.x, "y": s.y, "from_x": round(plan["x"], 2), "from_y": round(plan["y"], 2),
                            "by_m": round(math.hypot(s.x - plan["x"], s.y - plan["y"]), 2),
                            "fit_was_m": round(solved["fixed_rms_m"], 2)}
        if solved and solved["rms_m"] <= CONVERGE_FIT_M:
            s.facing, s.z = round(solved["facing"], 1), round(solved["height"], 2)
            rep.update(solved=True, facing=s.facing, height=s.z, rms_m=round(solved["rms_m"], 2))
        elif solved:
            rep.update(rms_m=round(solved["rms_m"], 2), facing=s.facing, height=s.z)
            # A code and its distances in meters, so the page says it in the room's unit (BL #12435); `why`
            # stays plain words with no unit for a reader that only has it.
            off = round(solved["rms_m"], 2)
            if nspots < 2:
                rep.update(why_code="one_spot_apart", off_m=off,
                           why="its heads land apart on this spot, so one spot is not enough to tell where the bar "
                               "faces; line up a second spot and Llano holds both")
            elif "moved" in rep:
                rep.update(why_code="moved_spots_differ", off_m=off, moved_m=rep["moved"]["by_m"],
                           why="its spots put it away from the plan, so it was moved there (Back to plan undoes "
                               "it); they still differ a little, and every spot you lined up is held exactly")
            else:
                rep.update(why_code="spots_differ", off_m=off, spots=nspots,
                           why=f"no one bar position fits all {nspots} spots, so the bar keeps the position shown "
                               "and every spot you lined up is held exactly")
        else:
            rep["why"] = "line up both heads of the bar to work out where it faces and how high it hangs"
        rep["heads"] = {}
        for m, rows in sorted(heads.items()):
            combos = [(False, solved["turn"][m][0], solved["turn"][m][1])] if rep["solved"] else \
                None if len(rows) < 2 else [(False, sp, st) for sp in (1, -1) for st in (1, -1)]
            # the twin nearest the poses he used: the spot sits at about the floor's center pose
            prefer = (sum(r[0] for r in rows) / len(rows), sum(r[1] for r in rows) / len(rows))
            last = {xy: (p, t) for p, t, xy in rows}        # one anchor per spot: the newest pose on it
            anchors = [(x, y, p, t) for (x, y), (p, t) in list(last.items())[-ANCHORS_MAX:]]
            cal, miss = self.fit_taps(b, m, [(p, t, xy) for p, t, xy in rows], combos=combos, prefer=prefer)
            cal.anchors, s.cal[m] = anchors, cal
            # One pose far off its spot drags the whole fit and costs the good spots their hold: with
            # three or more spots, refit leaving each out in turn and keep the fit that holds the most.
            held = self._holds(b, m, last)
            if len(last) >= 3 and held < len(last):
                for drop in list(last):
                    c2, m2 = self.fit_taps(b, m, [(p, t, xy) for p, t, xy in rows if xy != drop], combos=combos, prefer=prefer)
                    c2.anchors, s.cal[m] = anchors, c2
                    h2 = self._holds(b, m, last)
                    if h2 > held:
                        cal, miss, held = c2, m2, h2
                s.cal[m] = cal
            rep["heads"][m] = {"miss_deg": round(miss, 1), "spots": len(rows)}
        return rep

    def _bar_sound(self, b: int, heads: dict) -> bool:
        """Every head of the bar plays back every spot it was lined up on, and none has a saved center the
        app would refuse (`cal_problem`): a solve that leaves less than that is not kept (BL #12381)."""
        for m, rows in heads.items():
            last = {xy: (p, t) for p, t, xy in rows}
            if self.cal_problem(b, m) or self._holds(b, m, last) < len(last):
                return False
        return True

    def _spot_report(self, by: dict) -> tuple[list, list]:
        """Per confirmed spot and head: how far the model alone lands his pose from the spot, and whether
        the aim at the spot now plays his pose back to the DMX step (`held`). `disagree` names a spot only
        when it stands out: the worst spot (past ANCHOR_WARN_M) on most of the heads that saw it, or any
        spot a head couldn't hold. Misses spread evenly over the spots name nothing (no one spot is off)."""
        held, worst_of = [], {}
        seen = {}
        for b, heads in sorted(by.items()):
            for m, rows in sorted(heads.items()):
                last = {xy: (p, t) for p, t, xy in rows}
                worst = None
                for (x, y), (p, t) in last.items():
                    miss = self.spot_miss(b, m, x, y, p, t)
                    aim = self.aim(b, self.heads(b)[m], (x, y, 0.0), m)
                    ok = all(round(a * 255) == round(v * 255) for a, v in zip(aim, (p, t))) or self._same_beam(b, m, aim, (p, t))
                    row = {"bar": b, "head": m + 1, "x": round(x, 2), "y": round(y, 2),
                           "miss_m": None if miss is None else round(miss, 2), "held": ok}
                    held.append(row)
                    seen[(x, y)] = seen.get((x, y), 0) + 1
                    if (miss is None or miss > ANCHOR_WARN_M or not ok) and \
                            (worst is None or (miss or 99) > (worst["miss_m"] or 99)):
                        worst = row
                if worst and len(last) > 1:
                    worst_of[(b, m)] = worst
        votes = {}
        for r in worst_of.values():
            votes.setdefault((r["x"], r["y"]), []).append(r)
        bad = [r for r in held if not r["held"]]
        for xy, rows in votes.items():
            if len(rows) * 2 > seen.get(xy, 0):
                bad += [r for r in rows if r["held"]]
        bad.sort(key=lambda r: (r["held"], -(r["miss_m"] or 99)))
        return held, bad

    def _holds(self, bar: int, m: int, last: dict) -> int:
        """How many of head m's confirmed spots its aim plays back to the DMX step (or the same beam)."""
        n = 0
        for (x, y), (p, t) in last.items():
            aim = self.aim(bar, self.heads(bar)[m], (x, y, 0.0), m)
            n += all(round(a * 255) == round(v * 255) for a, v in zip(aim, (p, t))) or self._same_beam(bar, m, aim, (p, t))
        return n

    def _same_beam(self, bar: int, m: int, a, b) -> bool:
        """Two raw poses that point head m the same way (one motor turn apart), to a DMX step."""
        da, db = self.beam_of(bar, m, *a), self.beam_of(bar, m, *b)
        return math.degrees(math.acos(max(-1.0, min(1.0, sum(p * q for p, q in zip(da, db)))))) < 0.5

    def _height_inside(self, z: float) -> bool:
        """A solved bar height clear of `_solve_bar`'s search bounds (0.3 m and the ceiling, at most 12 m)."""
        return 0.3 + BOUND_M < z < min(self.room[2], 12.0) - BOUND_M

    def _solve_bar(self, bar: int, heads: dict) -> Optional[dict]:
        """The facing (degrees) and height (meters) of a bar, and each head's turn directions, that
        land its heads' poses nearest their spots on the floor under the straight-ahead model:
        heading = facing + pan sign * (pan - home) * range, angle off straight down = 90 + tilt sign
        * (tilt - home) * range. A coarse search, then finer around the best."""
        s, (_, _, ceiling) = self.spots[f"bar{bar}"], self.room
        auto = math.degrees(math.atan2(self.floor.cx - s.x, self.floor.cy - s.y))
        hp, ht = HOME_POSE

        def land(f, z, m, sp, st, pan, tilt, bx=None, by=None):
            fr = math.radians(f)
            lx, ly = math.cos(fr), -math.sin(fr)
            k = (1, -1)[m] * HEAD_SPACING / 2
            hx, hy = (s.x if bx is None else bx) + lx * k, (s.y if by is None else by) + ly * k
            h = math.radians(f + sp * (pan - hp) * PAN_RANGE)
            o = math.radians(90.0 + st * (tilt - ht) * TILT_RANGE)
            dz = -math.cos(o)
            if dz > -0.05:   # level or above: never reaches the floor
                return None
            t = z / -dz
            return hx + math.sin(o) * math.sin(h) * t, hy + math.sin(o) * math.cos(h) * t

        def cost(f, z, turn, bx=None, by=None, cap=MOVE_CAP):
            # each pose's pull is capped (MOVE_CAP): one slipped pose can't drag the facing, height or spot
            err, n = 0.0, 0
            for m, rows in heads.items():
                for pan, tilt, (x, y) in rows:
                    p = land(f, z, m, *turn[m], pan, tilt, bx, by)
                    err += 100.0 if p is None else min(cap, (p[0] - x) ** 2 + (p[1] - y) ** 2)
                    n += 1
            return err / max(1, n)
        top = min(ceiling, 12.0)
        best = None
        signs = [(sp, st) for sp in (1, -1) for st in (1, -1)]
        for t0 in signs:
            for t1 in signs:
                turn = {0: t0, 1: t1}
                c = min((cost(auto + df, z, turn), auto + df, z)
                        for df in range(-int(CONVERGE_TURN), int(CONVERGE_TURN) + 1, 3)
                        for z in [0.6 + 0.2 * i for i in range(int((top - 0.6) / 0.2) + 1)])
                if best is None or c[0] < best[0]:
                    best = (*c, turn)
        _, f, z, turn = best
        for step_f, step_z in ((1.0, 0.05), (0.2, 0.01)):
            _, f, z = min((cost(f + i * step_f, z + j * step_z, turn), f + i * step_f, z + j * step_z)
                          for i in range(-4, 5) for j in range(-4, 5)
                          if 0.3 <= z + j * step_z <= top and abs(f + i * step_f - auto) <= CONVERGE_TURN)
        out = {"facing": (f + 180.0) % 360.0 - 180.0, "height": z, "turn": turn,
               "rms_m": math.sqrt(cost(f, z, turn, cap=math.inf))}
        # Where the bar really stands (BL #11766): with three or more spots on each head the poses also
        # say where the bar hangs, so x and y join facing and height in a pattern search from the solve
        # above (same turn directions). Kept only when it fits clearly better (MOVE_BETTER) by a move he
        # would notice (MOVE_MIN_M); converge applies it and the plan stays for Back to plan.
        if all(len({xy for *_, xy in rows}) >= 3 for rows in heads.values()):
            (w, d, _), bx, by = self.room, s.x, s.y
            best_c = cost(f, z, turn, bx, by)
            for sxy, sf, sz in ((0.4, 4.0, 0.2), (0.2, 2.0, 0.1), (0.1, 1.0, 0.05), (0.05, 0.5, 0.02), (0.02, 0.2, 0.01)):
                moved = True
                while moved:
                    moved = False
                    for dx, dy, df, dz in ((sxy, 0, 0, 0), (-sxy, 0, 0, 0), (0, sxy, 0, 0), (0, -sxy, 0, 0),
                                           (0, 0, sf, 0), (0, 0, -sf, 0), (0, 0, 0, sz), (0, 0, 0, -sz)):
                        cand = (bx + dx, by + dy, f + df, z + dz)
                        if not (0 <= cand[0] <= w and 0 <= cand[1] <= d and 0.3 <= cand[3] <= top
                                and abs(cand[2] - auto) <= CONVERGE_TURN and math.hypot(cand[0] - s.x, cand[1] - s.y) <= MOVE_MAX_M):
                            continue
                        c = cost(cand[2], cand[3], turn, cand[0], cand[1])
                        if c < best_c - 1e-9:
                            best_c, (bx, by, f2, z2), moved = c, cand, True
                            f, z = f2, z2
            rms, fixed = math.sqrt(best_c), math.sqrt(cost(out["facing"], out["height"], turn))
            if rms <= fixed * MOVE_BETTER and math.hypot(bx - s.x, by - s.y) >= MOVE_MIN_M:
                out.update(x=bx, y=by, facing=(f + 180.0) % 360.0 - 180.0, height=z,
                           rms_m=math.sqrt(cost(f, z, turn, bx, by, cap=math.inf)), fixed_rms_m=out["rms_m"])
        return out

    def flip_pan(self, bar: int) -> None:
        """The Mirror button: a bar's heads turn the other way. A bar with no calibrated head flips
        the guessed model's pan direction (aim re-solves every target from the heads' home
        headings, so nothing doubles). Otherwise each head turns round where it lands on the
        dance floor's center (a head without a center gets one from today's aim first); a head with
        measured dots is left alone: the fit already knows which way it turns."""
        s = self.spots[f"bar{bar}"]
        if not any(c.center for c in s.cal):   # the guessed model: only the way pan turns is wrong
            s.pan_invert = not s.pan_invert
            return
        for m in range(2):
            c = s.cal[m]
            if c.points:   # measured dots decide which way it turns (fit_head); a flip would undo them
                continue
            if not c.center:
                c.center, c.pan_invert = self.aim(bar, self.heads(bar)[m], self.ref_target("center"), m), _guess_turn(s) < 0
            c.pan_invert = not c.pan_invert

    def aim(self, bar: int, head: tuple[float, float, float], target: tuple[float, float, float],
            m: Optional[int] = None) -> tuple[float, float]:
        """Pan/tilt (0..1) that points a head at a room point. A point above the head is out of
        reach of a hung head: it gets the level beam toward it, the highest the head goes."""
        m = self.head_index(bar, head) if m is None else m
        c = self.cal(bar, m)
        if c is not None:
            return self.anchored(bar, m, c, self._cal_aim(bar, m, c, target), target)
        s = self.spots[f"bar{bar}"]
        dx, dy, dz = (t - h for t, h in zip(target, head))
        flat = math.hypot(dx, dy)
        # Straight down ("down" at the line-up check) has no heading: keep the bar's facing.
        world = math.degrees(math.atan2(dx, dy)) if flat > 1e-9 else self.facing(f"bar{bar}")
        # Off the bar's facing first (a target in front is within 90), then the trim: every
        # target of a bar lands on the same side of the pan range, so a move between two of them
        # never swings round through the back (a bar trimmed 180 split them before 1.9.0).
        # The head's home and the bar's trim pick ONE turn for the bar's front (base), so every target
        # in front lands on the same side of the pan range whatever the trim (HEAD_HOME, 11-08).
        base = (-s.pan_trim - _home(m) + 180.0) % 360.0 - 180.0
        rel = _side((world - self.facing(f"bar{bar}") + 180.0) % 360.0 - 180.0) + base
        if abs(rel) > PAN_RANGE / 2:
            rel -= math.copysign(360.0, rel)
        if _bar_turn(s) < 0:
            rel = -rel
        off = math.degrees(math.atan2(flat, -dz)) - s.tilt_trim   # degrees off straight down
        return (_clamp(0.5 + rel / PAN_RANGE), _clamp(TILT_DOWN_AT_CENTER + off / TILT_RANGE))

    def forward(self, bar: int, pan: float, m: Optional[int] = None) -> float:
        """The pan nearest `pan` that keeps the beam within FORWARD_MAX degrees of the bar's
        facing, so a head never turns round to the wall behind it. Works in the room, not in
        raw pan: a bar trimmed 180 degrees at the line-up check still faces the dance floor."""
        c = self.cal(bar, m) if m is not None else None
        if c is not None:
            if c.swap:   # the pan channel tilts this head: front() keeps it in front
                return pan
            hc, _ = self._center_angles(bar, m)
            sp = -1 if c.pan_invert else 1
            rel = (hc + sp * (pan - c.center[0]) * c.pan_range - self.facing(f"bar{bar}") + 180.0) % 360.0 - 180.0
            if abs(rel) <= FORWARD_MAX:
                return pan
            fix = max(-FORWARD_MAX, min(FORWARD_MAX, rel)) - rel
            return _clamp(pan + sp * fix / c.pan_range)
        s = self.spots[f"bar{bar}"]
        sign = float(_bar_turn(s))
        turn = (pan - 0.5) * PAN_RANGE
        home = s.pan_trim + _home(m)
        rel = (home + sign * turn + 180.0) % 360.0 - 180.0
        if abs(rel) <= FORWARD_MAX:
            return pan
        rel = max(-FORWARD_MAX, min(FORWARD_MAX, rel))
        want = sign * (rel - home)
        # The same heading one turn either way: take the one nearest where the head already is.
        want = min((want + k * 360.0 for k in (-1, 0, 1)), key=lambda t: abs(t - turn))
        return _clamp(0.5 + want / PAN_RANGE)

    def front(self, bar: int, tilt: float, m: Optional[int] = None) -> float:
        """The tilt nearest `tilt` that keeps the beam on the pan's front side of straight down.
        Below it a hung head tilts toward the back, so a move dipping under straight down (a
        circle round the booth) would flick the beam behind the bar."""
        c = self.cal(bar, m) if m is not None else None
        if c is not None:
            if c.swap:
                return tilt
            _, oc = self._center_angles(bar, m)
            st = -1 if c.tilt_invert else 1
            down = c.center[1] - st * oc / c.tilt_range    # the raw tilt of straight down
            return _clamp(max(tilt, down) if st > 0 else min(tilt, down))
        return max(tilt, _clamp(TILT_DOWN_AT_CENTER - self.spots[f"bar{bar}"].tilt_trim / TILT_RANGE))

    def beam(self, bar: int, head: tuple[float, float, float], pan: float, tilt: float,
             m: Optional[int] = None) -> tuple[float, float, float]:
        """Unit direction a head points for a pan/tilt; the inverse of aim()."""
        m = self.head_index(bar, head) if m is None else m
        if self.cal(bar, m) is not None:
            return self.beam_of(bar, m, pan, tilt)
        s = self.spots[f"bar{bar}"]
        turn = (pan - 0.5) * PAN_RANGE
        world = math.radians(self.facing(f"bar{bar}") + _side(s.pan_trim + _home(m) + _bar_turn(s) * turn))
        off = math.radians((tilt - TILT_DOWN_AT_CENTER) * TILT_RANGE + s.tilt_trim)
        return (math.sin(off) * math.sin(world), math.sin(off) * math.cos(world), -math.cos(off))

    # --- what the show reads -----------------------------------------------------------

    def targets(self) -> dict[str, list[tuple[float, float, float]]]:
        """Each named position as one room point per head (bar 1 heads, then bar 2 heads)."""
        fl, (_, d, _) = self.floor, self.room
        heads = self.all_heads()
        # Heads ranked left to right by where they sit, so "fan" and "cross" mean the room.
        rank = {k: r for r, k in enumerate(sorted(range(len(heads)), key=lambda k: heads[k][2][0]))}
        n = len(heads)

        def across(fracs, y, z):
            return [(fl.x + fl.w * fracs[rank[k]], y, z) for k in range(n)]

        spread = [0.2 + 0.6 * r / (n - 1) for r in range(n)]

        def high(p):
            # As high as safe: over the dancers' heads to the back of the room, or the far edge
            # of the floor for a bar hung lower than that.
            # With table areas or a no-beam zone in the room (BL #12344) it stops at the floor's far edge:
            # a beam to the back wall would cross the dinner tables.
            if p[2] >= HEAD_CLEAR + 0.1 and not self.beam_free():
                return (p[0], d, HEAD_CLEAR)
            return (min(fl.x + fl.w, max(fl.x, p[0])) if self.beam_free() else p[0], fl.y + fl.d, 0.0)
        base = {
            "home": [(fl.cx, fl.cy, 1.0)] * n,
            # The DJ, lit from the dance floor side: just in front of the booth at chest height.
            # The booth's middle (before 1.9.0) sits level with bars that flank it, so the spots
            # ran sideways along the wall behind the bars.
            "booth": [(self.booth.cx, min(d, self.booth.y + self.booth.d + BOOTH_FRONT), 1.2)] * n,
            "ceiling": [high(p) for _, _, p in heads],
            # the arrival line-up check's known spots (Show Designer, 1.7.0)
            "center": [(fl.cx, fl.cy, 0.0)] * n,
            "down": [(p[0], p[1], 0.0) for _, _, p in heads],
        }
        if wide_moves():
            return {**base, **self._wide(heads, rank, across)}
        return {
            **base,
            "crowd": across(spread, fl.cy, 0.0),
            "fan": across([r / (n - 1) for r in range(n)], fl.y + fl.d, 0.0),
            "cross": across([1 - r / (n - 1) for r in range(n)], fl.y + fl.d * 0.7, 0.0),
            "sweep_left": across([0.05 + 0.1 * r / (n - 1) for r in range(n)], fl.cy, 0.0),
            "sweep_right": across([0.85 + 0.1 * r / (n - 1) for r in range(n)], fl.cy, 0.0),
        }

    def _wide(self, heads, rank, across) -> dict:
        """The whole room (Llano PM #23789, his 11-15 report: the heads "always point down and stay in a
        small area close to the bars"). Until 1.35 every move but "ceiling" aimed at a floor point inside
        the dance floor, in his Stage room a 6.1 x 6.7 m patch whose near edge is 0.6 m from the bars, so
        every beam sat 50-70 degrees below level and nothing reached a wall. His line-up was not the cause
        (its three spots agree with the manual's 180-degree tilt within about 2 degrees). Now:
        "crowd" spans the floor's whole width; "cross" crosses to the floor's far corners; "fan" fans the
        beams out over the crowd onto the side and back walls at HEAD_CLEAR; "sweep_left" / "sweep_right"
        are the left and right walls over the crowd. A wall beam passes over the dancers' heads and is never
        parked at eye level. With a table area or no-beam zone in the room, or a bar hung too low to clear
        heads, a wall target falls back to the dance floor's edge in the same direction (as "ceiling" does).
        Kill switch: LLANO_LIGHTS_WIDE_MOVES=0 (1.34's floor-only positions)."""
        fl, (w, d, _) = self.floor, self.room
        n = len(heads)
        low = min(p[2] for _, _, p in heads) < HEAD_CLEAR + 0.1
        y0 = min(d, max(fl.cy, max(p[1] for _, _, p in heads) + 1.0))   # walls start in front of the bars
        side = max(0.0, d - y0)
        total = 2 * side + w

        def wall(u):
            # u 0..1 along the left wall (front to back), the back wall (left to right), the right wall (back to front)
            s = max(0.0, min(1.0, u)) * total
            if s <= side:
                x, y = 0.0, y0 + s
            elif s <= side + w:
                x, y = s - side, d
            else:
                x, y = w, d - (s - side - w)
            if low or self.beam_free():
                return (min(fl.x + fl.w, max(fl.x, x)), min(fl.y + fl.d, max(fl.y, y)), 0.0)
            return (x, y, HEAD_CLEAR)

        def walls(us):
            return [wall(us[rank[k]]) for k in range(n)]

        step = [r / (n - 1) for r in range(n)]
        return {
            "crowd": across([0.08 + 0.84 * r for r in step], fl.cy, 0.0),
            "cross": across([0.95 - 0.9 * r for r in step], fl.y + fl.d, 0.0),
            "fan": walls([0.1 + 0.8 * r for r in step]),
            "sweep_left": walls([0.1 + 0.25 * r for r in step]),
            "sweep_right": walls([0.65 + 0.25 * r for r in step]),
        }

    @staticmethod
    def spot_target(x: float, y: float, head: tuple) -> tuple[float, float, float]:
        """Where a spotlight on someone standing at (x, y) aims (Llano PM #23789): at chest/face height
        (spot_height), not their feet, so the beam lands on the person and not on the floor behind
        them; never within half a meter of the head's own height (a bar hung low aims lower)."""
        return (x, y, max(0.0, min(spot_height(), head[2] - 0.5)))

    def beam_free(self) -> list:
        """The table areas and no-beam zones the moving looks keep out of (BL #12344)."""
        return [z for z in self.zones if z.kind in BEAM_FREE]

    def keep_out(self, target: tuple[float, float, float]) -> tuple[float, float, float]:
        """A target the moving looks may use: one landing in a table area or a no-beam zone (below
        HEAD_CLEAR, where people sit) is pulled to the nearest point of the dance floor; any other is kept."""
        x, y, z = target
        if z >= HEAD_CLEAR or not any(zn.has(x, y) for zn in self.beam_free()):
            return target
        fl = self.floor
        return (min(fl.x + fl.w, max(fl.x, x)), min(fl.y + fl.d, max(fl.y, y)), z)

    def positions(self) -> dict[str, list[tuple[float, float]]]:
        """Named positions as pan/tilt per head, in the shape LooksEngine.positions takes. Every target
        keeps out of the table areas and no-beam zones (`keep_out`, BL #12344); "down" and the line-up's
        "center" are on the floor or under the bar, so they never move."""
        heads = self.all_heads()
        return {name: [self.aim(b, p, self.keep_out(t), i) for (b, i, p), t in zip(heads, pts)]
                for name, pts in self.targets().items()}

    # --- how far the heads go (PM #23796) ------------------------------------------------

    def far_z(self, bar: int = 1, m: int = 0) -> float:
        """The height the box's far edge is read at: over the heads (HEAD_CLEAR) when every GigBAR set up here hangs
        high enough, else on the floor. One rule for the whole rig, the same one Line up's Highest step aims at."""
        if self.limits is None or not self.limits.over:
            return 0.0
        bars = [self.spots[f"bar{b}"] for b in (1, 2) if not self.spots[f"bar{b}"].out] or [self.spots["bar1"]]
        return HEAD_CLEAR if all(s.z >= HEAD_CLEAR + 0.1 for s in bars) else 0.0

    def limit_points(self, bar: int, m: int) -> list:
        """Room points round the box's edges this head is aimed at to read its raw range."""
        lim, n = self.limits, LIMIT_SAMPLES
        xs = [lim.x + lim.w * i / n for i in range(n + 1)]
        ys = [lim.y + lim.d * i / n for i in range(n + 1)]
        far = self.far_z()
        return ([(x, lim.y, 0.0) for x in xs] + [(lim.x, y, 0.0) for y in ys]
                + [(lim.x + lim.w, y, 0.0) for y in ys] + [(x, lim.y + lim.d, far) for x in xs])

    def head_box(self, bar: int, m: int) -> Optional[tuple]:
        """The raw (pan lo, pan hi, tilt lo, tilt hi) round this head's beams inside the box, or None. A rectangle
        in raw pan and tilt is wider than the box at its corners (the widest pan and the highest tilt together
        point past a side edge), so the tilt that is allowed also depends on the pan (`tilt_curve`)."""
        if self.limits is None:
            return None
        h = self.heads(bar)[m]
        poses = [self.aim(bar, h, t, m) for t in self.limit_points(bar, m)]
        pans, tilts = [p for p, _ in poses], [t for _, t in poses]
        return min(pans), max(pans), min(tilts), max(tilts)

    def tilt_curve(self, bar: int, m: int) -> list:
        """(raw pan, tilt lo, tilt hi) by pan, sorted: for each heading across the box as seen from this head, the
        tilt where its beam comes into the box on the floor and where it leaves it (on the far edge read at far_z,
        on a side edge on the floor). [] when the head stands over the box (every heading crosses it)."""
        lim, (hx, hy, _) = self.limits, self.heads(bar)[m]
        x0, x1, y0, y1 = lim.x, lim.x + lim.w, lim.y, lim.y + lim.d
        if x0 <= hx <= x1 and y0 <= hy <= y1:
            return []
        corners = [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]
        angs = [math.atan2(cx - hx, cy - hy) for cx, cy in corners]
        mid = math.atan2((x0 + x1) / 2 - hx, (y0 + y1) / 2 - hy)
        rel = [((a - mid + math.pi) % (2 * math.pi)) - math.pi for a in angs]
        lo_a, hi_a, far, h = min(rel), max(rel), self.far_z(), self.heads(bar)[m]
        out = []
        for i in range(LIMIT_CURVE + 1):
            a = mid + lo_a + (hi_a - lo_a) * i / LIMIT_CURVE
            dx, dy = math.sin(a), math.cos(a)
            t_in, t_out = -math.inf, math.inf
            for o, d, lo, hi in ((hx, dx, x0, x1), (hy, dy, y0, y1)):
                if abs(d) < 1e-12:
                    if not lo <= o <= hi:
                        t_in, t_out = 1.0, 0.0
                    continue
                ta, tb = sorted(((lo - o) / d, (hi - o) / d))
                t_in, t_out = max(t_in, ta), min(t_out, tb)
            if t_out <= max(t_in, 0.0) + 1e-9:
                continue
            ex, ey = hx + dx * t_out, hy + dy * t_out
            ix, iy = hx + dx * max(t_in, 0.0), hy + dy * max(t_in, 0.0)
            pan, t_hi = self.aim(bar, h, (ex, ey, far if abs(ey - y1) < 1e-6 else 0.0), m)
            _, t_lo = self.aim(bar, h, (ix, iy, 0.0), m)
            out.append((pan, min(t_lo, t_hi), max(t_lo, t_hi)))
        return sorted(out)

    def head_reach(self, bar: int, m: int, positions: Optional[dict] = None) -> tuple:
        """The raw (pan lo, pan hi, tilt lo, tilt hi) the show reaches with this head: every named position the
        moves travel between (not the line-up's "down" and "center"), widened by a figure's swing round them."""
        k = (bar - 1) * 2 + m
        pos = positions if positions is not None else self.positions()
        poses = [pts[k] for name, pts in pos.items() if name not in ("down", "center") and k < len(pts)]
        pans, tilts = [p for p, _ in poses], [t for _, t in poses]
        sp, st = FIGURE_SWING
        return (_clamp(min(pans) - sp), _clamp(max(pans) + sp), _clamp(min(tilts) - st), _clamp(max(tilts) + st))

    def limit_maps(self) -> list:
        """Per head (bar 1's two, then bar 2's): {"pan": axis, "tilt": axis, "reach": (tilt lo, hi), "curve": [...]}
        squeezing the show's reach into the box (`squeeze_pose`, `hold_pose`); [] with no box. Worked out when the
        layout is put to use (looks.LooksEngine.apply_venue), never per frame."""
        if self.limits is None:
            return []
        pos = self.positions()
        out = []
        for b, m, _ in self.all_heads():
            box, reach = self.head_box(b, m), self.head_reach(b, m, pos)
            c = self.spots[f"bar{b}"].cal[m]
            curve = [] if c.center and c.swap else self.tilt_curve(b, m)   # a swapped head keeps the rectangle
            out.append({"pan": _squeeze(reach[0], reach[1], box[0], box[1]),
                        "tilt": _squeeze(reach[2], reach[3], box[2], box[3]),
                        "reach": (reach[2], reach[3]), "curve": curve})
        return out

    def floor_into_box(self, x: float, y: float) -> tuple:
        """A floor point a roaming spotlight passes through, squeezed from the dance floor into the box (a spot
        roams inside it the way it roamed the floor, smaller), so every head still meets on one point."""
        if self.limits is None:
            return x, y
        fl, lim = self.floor, self.limits
        return (squeeze(_squeeze(fl.x, fl.x + fl.w, lim.x, lim.x + lim.w), x),
                squeeze(_squeeze(fl.y, fl.y + fl.d, lim.y, lim.y + lim.d), y))

    def order(self, group: str, n: "int | None" = None) -> list[float]:
        """0..1 chase offset per fixture of a group, from where each one sits left to right.

        Matches the evenly spaced i/n offsets the looks use without a venue, so a row of
        lights chases the same way; lights bunched together pulse together. n: only the
        first n of the group are set up tonight (the rig picker, 1.13.0)."""
        ids = [f for f in FIXTURE_IDS if f.startswith(group)][:n]
        if not ids:
            return []
        # A light marked out (lost, BL #11766) gets 0 and the rest chase as a row without it.
        here = [f for f in ids if not self.spots[f].out] or ids
        xs = [self.spots[f].x for f in here]
        lo, hi = min(xs), max(xs)
        if hi - lo < 1e-6:
            at = {f: i / len(here) for i, f in enumerate(here)}
        else:
            at = {f: (self.spots[f].x - lo) / (hi - lo) * (len(here) - 1) / len(here) for f in here}
        return [at.get(f, 0.0) for f in ids]

    def sides(self, group: str, n: "int | None" = None) -> list[float]:
        """0 for a light left of the dance floor's middle, 0.5 for one on the right."""
        ids = [f for f in FIXTURE_IDS if f.startswith(group)][:n]
        if not ids:
            return []
        here = [f for f in ids if not self.spots[f].out] or ids   # a light marked out doesn't count (BL #11766)
        side = {f: 0.0 if self.spots[f].x < self.floor.cx else 0.5 for f in here}
        if len(set(side.values())) < 2:  # all on one side: alternate by position instead
            side = {f: (r % 2) / 2 for r, f in enumerate(sorted(here, key=lambda f: self.spots[f].x))}
        return [side.get(f, 0.0) for f in ids]

    # --- where each light really stands (BL #11766) ------------------------------------------

    def reference(self) -> tuple[float, float]:
        """The fixed point every measurement is taken from: the DJ booth's center, seen from above."""
        return self.booth.cx, self.booth.cy

    def planned(self, fid: str) -> dict:
        """Where a light was planned to stand: the layout's plan, else where it stands now."""
        s = self.spots[fid]
        return dict(self.plan.get(fid) or {"x": s.x, "y": s.y, "z": s.z, "facing": s.facing})

    def measurements(self) -> list[dict]:
        """Each light as he would measure it with a tape at the venue, from the booth's center: `right`
        meters to the right (+) or left (-) as the top view draws it (house left = small x); `out` meters
        toward the back of the room; `distance` the straight line; `height` above the floor; `facing` in
        degrees (0 = straight out from the booth wall, the floor's middle when not set); `spacing` to the
        nearest other light of its kind; `moved` how far it now stands from the plan."""
        rx, ry = self.reference()
        out = []
        for kind in ("bar", "tetra", "stick"):
            ids = [f for f in FIXTURE_IDS if f.startswith(kind)]
            for fid in ids:
                s, p = self.spots[fid], self.planned(fid)
                near = min((math.hypot(self.spots[o].x - s.x, self.spots[o].y - s.y) for o in ids if o != fid), default=None)
                out.append({"id": fid, "right": round(s.x - rx, 2), "out": round(s.y - ry, 2),
                            "distance": round(math.hypot(s.x - rx, s.y - ry), 2), "height": round(s.z, 2),
                            "facing": round(self.facing(fid), 1), "set_facing": s.facing is not None,
                            "spacing": None if near is None else round(near, 2),
                            "moved": round(math.hypot(s.x - p["x"], s.y - p["y"]), 2), "is_out": s.out})
        order = {f: i for i, f in enumerate(FIXTURE_IDS)}
        return sorted(out, key=lambda r: order[r["id"]])

    def keep_plan(self) -> None:
        """Snapshot today's positions as the plan, once: the first edit at a venue keeps what was planned."""
        if not self.plan:
            self.plan = {fid: {"x": s.x, "y": s.y, "z": s.z, "facing": s.facing} for fid, s in self.spots.items()}

    def set_position(self, fid: str, right: Optional[float] = None, out: Optional[float] = None,
                     height: Optional[float] = None, facing: "float | str | None" = None) -> None:
        """Move one light to where it really stands, in the measurements' terms (`measurements`). The plan
        is kept first. facing "auto" goes back to facing the dance floor. A light's line-up stays: it
        measured where the head points, which is still true if only the numbers were wrong; Clear line-up
        on the phone starts a bar over when the bar itself moved."""
        if fid not in self.spots:
            raise ValueError(f"no light named {fid}")
        self.keep_plan()
        s, (rx, ry), (w, d, h) = self.spots[fid], self.reference(), self.room
        if right is not None:
            s.x = _num(rx + right, f"{fid} position across the room", 0.0, w)
        if out is not None:
            s.y = _num(ry + out, f"{fid} position out from the booth", 0.0, d)
        if height is not None:
            s.z = _num(height, f"{fid} height", 0.0, h)
        if facing == "auto":
            s.facing = None
        elif facing is not None:
            s.facing = _num(facing, f"{fid} facing", -720, 720)

    def reset_to_plan(self, fid: Optional[str] = None) -> None:
        """Every light (or one) back where the plan has it, back in the show; line-ups are kept."""
        for f in ([fid] if fid else list(self.spots)):
            if f not in self.spots:
                raise ValueError(f"no light named {f}")
            p, s = self.planned(f), self.spots[f]
            s.x, s.y, s.z, s.facing, s.out = p["x"], p["y"], p["z"], p.get("facing"), False

    def number_ids(self, kind: str) -> list[str]:
        """This layout's lights of one kind (tetra, stick) in number order: tetra1, tetra2, ..."""
        if kind not in NUMBER_KINDS:
            raise ValueError(f"kind must be one of {', '.join(NUMBER_KINDS)}")
        ids = [f for f in self.spots if f.startswith(kind) and f[len(kind):].isdigit()]
        return sorted(ids, key=lambda f: int(f[len(kind):]))

    def number_side(self, kind: str) -> str:
        """Which end light 1 of a kind stands at, seen the way the room picture draws it: "right" when
        light 1 is further right than the last one, "left" when further left, "" when they line up
        front to back (or there are fewer than two), so no side can be read."""
        ids = self.number_ids(kind)
        if len(ids) < 2:
            return ""
        first, last = self.spots[ids[0]].x, self.spots[ids[-1]].x
        return "" if abs(first - last) < 0.05 else ("right" if first > last else "left")

    def renumber(self, kind: str) -> None:
        """Flip the numbers of one kind (BL #12378): the spots stay put, which light is 1, 2, 3 reverses,
        so each light's address follows its number to the other end. The plan reverses with it."""
        ids = self.number_ids(kind)
        if len(ids) < 2:
            return
        spots = [self.spots[f] for f in ids]
        plan = [self.plan.get(f) for f in ids]
        for f, s, p in zip(ids, reversed(spots), reversed(plan)):
            self.spots[f] = s
            if self.plan:
                if p is None:
                    self.plan.pop(f, None)
                else:
                    self.plan[f] = p
        self._memo.clear()

    def clear_lineup(self, bar: int) -> None:
        """A GigBAR's line-up forgotten (a spare swapped in, the bar moved): its heads go back to the guess."""
        if bar not in (1, 2):
            raise ValueError("bar must be 1 or 2")
        s = self.spots[f"bar{bar}"]
        s.cal, s.pan_trim, s.tilt_trim, s.pan_invert = [HeadCal(), HeadCal()], 0.0, 0.0, False

    def carry_lineup(self, src: "Layout", bars=(1, 2)) -> list:
        """Each head's line-up from `src` carried onto this layout's bars (Llano BL #12400, his 11-14 9:47 PM
        video on 1.26.4: Draw my room redrew his room with the GigBARs on the stage corners and no line-up, so
        every head fell back to the guess, which points head 1 of each bar half a turn the wrong way on his rig,
        and Line up my lights then aimed them backwards; the guess has done that since 1.14.3, his line-up hid
        it). A line-up is how the real head turns on its bar: which raw pose points it where, seen from the bar.
        The bar keeps that when it moves, so each head's center becomes the raw pose that, seen from the bar
        the same way round, points at this layout's floor center: same turn directions, same swap, same
        ranges. The old room's spots (anchors) are that room's and stay behind: a one-spot line-up here then
        moves the center onto the spot and keeps the turn directions (`converge`). A head already lined up
        here, a source head with no line-up, or a carried center the app would refuse (`cal_problem`) keeps
        what it had. Returns the (bar, head) pairs carried."""
        carried = []
        for b in bars:
            f0, f1 = src.facing(f"bar{b}"), self.facing(f"bar{b}")
            for m in (0, 1):
                c = src.cal(b, m)
                if c is None or self.spots[f"bar{b}"].cal[m].center:
                    continue
                o = self.heads(b)[m]
                dx, dy, dz = (t - h for t, h in zip(self.ref_target("center"), o))
                heading = math.degrees(math.atan2(dx, dy)) - f1 + f0      # the same way round from the bar, in src
                off = math.degrees(math.atan2(math.hypot(dx, dy), -dz))
                hc, oc = src._center_angles(b, m)
                (pc, tc) = c.center[::-1] if c.swap else c.center
                sp, st = (-1 if c.pan_invert else 1), (-1 if c.tilt_invert else 1)
                pp = mid_twin(pc + sp * ((heading - hc + 180.0) % 360.0 - 180.0) / c.pan_range, 360.0 / c.pan_range)
                tt = tc + st * (off - oc) / c.tilt_range
                if not (0.0 <= pp <= 1.0 and 0.0 <= tt <= 1.0):
                    continue
                self.spots[f"bar{b}"].cal[m] = HeadCal((tt, pp) if c.swap else (pp, tt), {}, c.pan_invert, c.tilt_invert,
                                                       c.swap, c.pan_range, c.tilt_range, [])
                carried.append((b, m))
            for m in (0, 1):   # read both heads of the bar before keeping either (partner_cal reads its partner)
                if (b, m) in carried and self.cal_problem(b, m):
                    self.spots[f"bar{b}"].cal[m] = HeadCal()
                    carried.remove((b, m))
        self._memo.clear()
        return carried

    # --- storage -----------------------------------------------------------------------

    def to_dict(self) -> dict:
        w, d, h = self.room
        out = {
            "name": self.name, "label": self.label, "preset": self.preset,
            "room": {"w": w, "d": d, "h": h},
            "booth": vars(self.booth).copy(), "floor": vars(self.floor).copy(),
            # pan_invert only when set, so a layout saved before 1.7.0 reads back unchanged
            "fixtures": {fid: self._spot_dict(s, self._drawn_cal(fid, s)) for fid, s in self.spots.items()},
        }
        if self.open:
            out["open"] = True
        if self.zones:   # only once he adds a stage, tables or a no-beam zone, so older layouts read back unchanged
            out["zones"] = [z.to_dict() for z in self.zones]
        if self.limits is not None:   # only once he sets how far the heads go (PM #23796)
            out["limits"] = self.limits.to_dict()
        if self.plan:   # only once he has moved a light at a venue, so older layouts read back unchanged
            out["plan"] = {fid: {k: v for k, v in p.items() if v is not None} for fid, p in self.plan.items()}
        return out

    def _drawn_cal(self, fid: str, s: Spot) -> list:
        """Each head's calibration as the heads are really driven (`cal`: turned to the rig's side, tilting
        the way its straight down says, panning with its partner), so every picture that draws from a saved
        or sent layout draws what the real head does (BL #12381, his 11-14 photos: the room picture showed
        GigBAR 2 aiming out at the floor while the real heads pointed down; the picture read the raw saved
        "tilt turns the other way" the heads no longer used). The same model saved again reads back the same."""
        m = re.fullmatch(r"bar([12])", fid)
        if not m:
            return list(s.cal)
        out = []
        for k, c in enumerate(s.cal):
            try:
                use = self.cal(int(m.group(1)), k) if c.center else None
            except Exception:  # noqa: BLE001 -- a head the model can't read is saved as it was
                use = None
            out.append(c if use is None else HeadCal(use.center, dict(c.points), use.pan_invert, use.tilt_invert,
                                                     use.swap, c.pan_range, c.tilt_range, list(c.anchors)))
        return out

    @staticmethod
    def _spot_dict(s: Spot, cals: Optional[list] = None) -> dict:
        out = {k: v for k, v in vars(s).items() if k != "cal" and v is not None and (k not in ("pan_invert", "out") or v)}
        cal = [c.to_dict() for c in (s.cal if cals is None else cals)]
        if any(cal):   # only once a head is calibrated, so older layouts read back unchanged
            out["cal"] = cal
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "Layout":
        """Build and check a layout; raises ValueError with a plain reason when it is wrong."""
        if not isinstance(data, dict):
            raise ValueError("a layout is a JSON object")
        room = data.get("room")
        if not isinstance(room, dict):
            raise ValueError("room missing")
        w, d, h = (_num(room.get(k), f"room {k}", 2.0, 100.0) for k in ("w", "d", "h"))
        booth, floor = (_rect(data.get(k), k, w, d) for k in ("booth", "floor"))
        fixtures = data.get("fixtures")
        if not isinstance(fixtures, dict):
            raise ValueError("fixtures missing")
        missing = [f for f in FIXTURE_IDS if f not in fixtures]
        if missing:
            raise ValueError(f"every light needs a spot; missing {', '.join(missing)}")
        spots = {}
        for fid in FIXTURE_IDS:
            f = fixtures[fid]
            if not isinstance(f, dict):
                raise ValueError(f"{fid}: spot must be an object")
            facing = f.get("facing")
            spots[fid] = Spot(
                x=_num(f.get("x"), f"{fid} x", 0.0, w), y=_num(f.get("y"), f"{fid} y", 0.0, d),
                z=_num(f.get("z", 0.0), f"{fid} height", 0.0, h),
                facing=None if facing is None else _num(facing, f"{fid} facing", -720, 720),
                pan_trim=_num(f.get("pan_trim", 0.0), f"{fid} pan trim", -270, 270),
                tilt_trim=_num(f.get("tilt_trim", 0.0), f"{fid} tilt trim", -90, 90),
                pan_invert=f.get("pan_invert") is True,
                cal=_cals(f.get("cal"), fid), out=f.get("out") is True,
                drawn=None if f.get("drawn") is None else _num(f.get("drawn"), f"{fid} drawn turn", -720, 720))
        name = slug(str(data.get("name") or data.get("label") or "my-layout"))
        label = str(data.get("label") or name)[:80]
        lay = cls(name, label, (w, d, h), booth, floor, spots, preset=bool(data.get("preset")),
                  open=data.get("open") is True, plan=_plan(data.get("plan"), w, d, h), zones=_zones(data.get("zones"), w, d),
                  limits=_limits(data.get("limits"), w, d))
        for b in (1, 2):   # two or more dots on a head: its signs and swap follow from them
            for m in range(2):
                lay.fit_head(b, m)
                lay.spots[f"bar{b}"].cal[m] = lay.facing_cal(b, m, lay.spots[f"bar{b}"].cal[m])
        fixed = {(b, m): lay.partner_cal(b, m, lay.spots[f"bar{b}"].cal[m]) for b in (1, 2) for m in range(2)}
        for (b, m), c in fixed.items():   # read every head before changing any (One chassis, above)
            lay.spots[f"bar{b}"].cal[m] = c
        return lay


def _side(a: float) -> float:
    """An angle off the bar's facing in the guessed model's frame, in the room (and back): that frame
    was written mirrored left-right (1.16.0, `heads`), so its angles turn the other way."""
    return -a


def _bar_turn(s: "Spot") -> int:
    """Which way the guessed model's heading turns as raw pan rises, in its mirrored frame: the fixture's
    (GUESS_TURN), the other way on a bar flipped at the line-up check (`pan_invert`)."""
    return -GUESS_TURN if s.pan_invert else GUESS_TURN


def _guess_turn(s: "Spot") -> int:
    """Which way the guessed model's heading turns in the room as raw pan rises: +1 or -1."""
    return int(_side(float(_bar_turn(s))))


def _home(m: Optional[int]) -> float:
    """Where head m points at pan 0.5, degrees off its bar's facing (HEAD_HOME); 0 when unknown."""
    return HEAD_HOME[m] if m in (0, 1) else 0.0


def _plan(v, w: float, d: float, h: float) -> dict:
    """A layout's plan (BL #11766): where each light was meant to stand, kept for Reset to plan."""
    if v is None:
        return {}
    if not isinstance(v, dict) or any(k not in FIXTURE_IDS or not isinstance(p, dict) for k, p in v.items()):
        raise ValueError("plan holds a spot per light id")
    out = {}
    for fid, p in v.items():
        facing = p.get("facing")
        out[fid] = {"x": _num(p.get("x"), f"{fid} planned x", 0.0, w), "y": _num(p.get("y"), f"{fid} planned y", 0.0, d),
                    "z": _num(p.get("z", 0.0), f"{fid} planned height", 0.0, h),
                    "facing": None if facing is None else _num(facing, f"{fid} planned facing", -720, 720)}
    return out


def _zones(v, w: float, d: float) -> list:
    """The room elements, checked (BL #12344); none when the layout has none."""
    if v is None:
        return []
    if not isinstance(v, list):
        raise ValueError("zones must be a list")
    if len(v) > ZONES_MAX:
        raise ValueError(f"at most {ZONES_MAX} room elements")
    out = []
    for i, z in enumerate(v):
        if not isinstance(z, dict) or z.get("kind") not in ZONE_KINDS:
            raise ValueError(f"room element {i + 1} must be a stage, tables or a no-beam zone")
        what = ZONE_KINDS[z["kind"]].lower()
        r = _rect(z, what, w, d)
        out.append(Zone(r.x, r.y, r.w, r.d, z["kind"], str(z.get("label") or "")[:40]))
    return out


def _limits(v, w: float, d: float) -> Optional[Limits]:
    """How far the heads go (PM #23796), checked; None when the layout has no box."""
    if v is None:
        return None
    r = _rect(v, "the head limits", w, d)
    if r.w < LIMIT_MIN_M or r.d < LIMIT_MIN_M:
        raise ValueError(f"the head limits are at least {LIMIT_MIN_M} m wide and deep")
    return Limits(r.x, r.y, r.w, r.d, over=v.get("over") is not False)


def _squeeze(nlo: float, nhi: float, lo: float, hi: float) -> tuple:
    """(a, b, lo, hi): an axis of the show's reach nlo..nhi squeezed into the box's lo..hi. Inside already: as it
    is. Overlapping by at least half: onto the overlap, so the moves keep their place and shrink. Barely
    overlapping or outside: onto the whole box. Either way the ends land on distinct places, never one edge."""
    if lo <= nlo and nhi <= hi or nhi - nlo < 1e-6:
        return (1.0, 0.0, lo, hi)
    tlo, thi = max(nlo, lo), min(nhi, hi)
    if thi - tlo < 0.5 * min(nhi - nlo, hi - lo):
        tlo, thi = lo, hi
    a = (thi - tlo) / (nhi - nlo)
    return (a, tlo - a * nlo, lo, hi)


def squeeze(axis: tuple, x: float) -> float:
    """One raw value through an axis of limit_maps."""
    a, b, lo, hi = axis
    return min(hi, max(lo, a * x + b))


def _tilt_band(mp: dict, pan: float) -> Optional[tuple]:
    """The (tilt lo, tilt hi) the box allows at this raw pan, from the head's curve (None without one)."""
    cv = mp.get("curve") or []
    if not cv:
        return None
    if pan <= cv[0][0]:
        return cv[0][1], cv[0][2]
    if pan >= cv[-1][0]:
        return cv[-1][1], cv[-1][2]
    for (p0, l0, h0), (p1, l1, h1) in zip(cv, cv[1:]):
        if p0 <= pan <= p1:
            k = 0.0 if p1 - p0 < 1e-12 else (pan - p0) / (p1 - p0)
            return l0 + (l1 - l0) * k, h0 + (h1 - h0) * k
    return cv[-1][1], cv[-1][2]


def squeeze_pose(mp: dict, pan: float, tilt: float) -> tuple:
    """A show pose squeezed into the box: pan by its axis, then tilt from the show's reach into the band the box
    allows at that pan (so a beam turned to the side tilts less high), never parked on one edge."""
    pan = squeeze(mp["pan"], pan)
    band = _tilt_band(mp, pan)
    if band is None:
        return pan, squeeze(mp["tilt"], tilt)
    return pan, squeeze(_squeeze(mp["reach"][0], mp["reach"][1], band[0], band[1]), tilt)


def hold_pose(mp: dict, pan: float, tilt: float) -> tuple:
    """A pose he steers (Follow someone, a spotlight) held at the box's edge, never squeezed."""
    _, _, plo, phi = mp["pan"]
    pan = min(phi, max(plo, pan))
    band = _tilt_band(mp, pan)
    lo, hi = band if band is not None else mp["tilt"][2:]
    return pan, min(hi, max(lo, tilt))


def _cals(v, fid: str) -> list:
    if v is None:
        return [HeadCal(), HeadCal()]
    if not fid.startswith("bar") or not isinstance(v, list) or len(v) != 2:
        raise ValueError(f"{fid}: calibration is one entry per head of a GigBAR")
    return [HeadCal.from_dict(c, f"{fid} head {m + 1}") for m, c in enumerate(v)]


def mid_twin(pan: float, step: float, near: float = 0.5) -> float:
    """The raw pan reaching the same heading as `pan` (one motor turn, `step` = 360 / pan range,
    either way) inside 0..1 and nearest `near`: DMX middle unless named (Middle twin, 1.16.4)."""
    twins = [pan + k * step for k in range(-2, 3) if -1e-9 <= pan + k * step <= 1 + 1e-9]
    return _clamp(min(twins, key=lambda t: abs(t - near))) if twins else pan


def rest_pan(pan_range: float) -> float:
    """Raw pan of straight ahead on the twin nearest DMX middle (Middle twin, 1.16.4): his heads face
    straight ahead at pan 0 (HOME_POSE), and one motor turn on, at 360 / pan range, the same way."""
    return mid_twin(HOME_POSE[0], 360.0 / pan_range)


def wide_moves() -> bool:
    """The named moves use the whole room (Layout._wide). LLANO_LIGHTS_WIDE_MOVES=0 puts back 1.34's
    floor-only positions without a build."""
    return (os.environ.get("LLANO_LIGHTS_WIDE_MOVES") or "").strip().lower() not in ("0", "off", "false", "no")


def spot_height() -> float:
    """Meters above the floor a spotlight aims at (SPOT_HEIGHT, a person's chest/face). LLANO_LIGHTS_SPOT_HEIGHT
    tunes it on the rig without a build; 0 is 1.34's spot on the floor. Kept between 0 and 2 m."""
    try:
        v = float(os.environ.get("LLANO_LIGHTS_SPOT_HEIGHT") or SPOT_HEIGHT)
    except ValueError:
        return SPOT_HEIGHT
    return max(0.0, min(2.0, v)) if math.isfinite(v) else SPOT_HEIGHT


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _unit(o, target) -> tuple:
    t = [a - b for a, b in zip(target, o)]
    n = math.sqrt(sum(v * v for v in t)) or 1.0
    return tuple(v / n for v in t)


def _num(v, what: str, lo: float, hi: float) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"{what} must be a number")
    if not lo <= v <= hi:
        raise ValueError(f"{what} must be between {lo:g} and {hi:g} (got {v:g})")
    return float(v)


def _rect(v, what: str, w: float, d: float) -> Rect:
    if not isinstance(v, dict):
        raise ValueError(f"{what} missing")
    r = Rect(_num(v.get("x"), f"{what} x", 0, w), _num(v.get("y"), f"{what} y", 0, d),
             _num(v.get("w"), f"{what} width", 0.5, w), _num(v.get("d"), f"{what} depth", 0.5, d))
    if r.x + r.w > w + 1e-6 or r.y + r.d > d + 1e-6:
        raise ValueError(f"{what} runs past the room's walls")
    return r


WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(10)), *(f"lpt{i}" for i in range(10))}


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]
    if s in WINDOWS_RESERVED:  # a file named con.json can't be made on Windows
        s = f"{s}-layout"
    return s or "my-layout"


# --- numbering (BL #12396) ---------------------------------------------------------------

NUMBER_KINDS = ("tetra", "stick")
NUMBER_SIDES = ("left", "right")


def numbered(lay: Layout, numbering: Optional[dict]) -> Layout:
    """`lay` with each kind's light 1 at the end the rig says (`rig.numbering`, {"tetra": "right"}),
    changed in place and returned. A kind with no side, or whose side can't be read from the room
    (lights in a line front to back), is left as drawn; asking twice changes nothing more."""
    for kind in NUMBER_KINDS:
        want = (numbering or {}).get(kind)
        have = lay.number_side(kind)
        if want in NUMBER_SIDES and have and have != want:
            lay.renumber(kind)
    return lay


def rig_numbering() -> dict:
    """The rig's numbering from the show settings in use, {"tetra": "left"|"right", "stick": ...}."""
    from . import show_settings  # noqa: PLC0415 -- the settings module, kept out of the pure geometry imports
    v = (show_settings.current().get("rig") or {}).get("numbering")
    return dict(v) if isinstance(v, dict) else {}


# --- presets ---------------------------------------------------------------------------

def _preset(name, label, room, booth, floor, bars, tetras, sticks, open=False) -> Layout:
    spots = {f"bar{i + 1}": Spot(x, y, 2.4) for i, (x, y) in enumerate(bars)}
    spots.update({f"tetra{i + 1}": Spot(x, y, 0.1) for i, (x, y) in enumerate(tetras)})
    spots.update({f"stick{i + 1}": Spot(x, y, 0.0) for i, (x, y) in enumerate(sticks)})
    return Layout(name, label, room, Rect(*booth), Rect(*floor), spots, preset=True, open=open)


def presets(numbering: Optional[dict] = None) -> dict[str, Layout]:
    """The ready-made rooms, each with its Tetras and sticks numbered from the end `numbering` says
    (`rig.numbering`; None = as drawn, light 1 on the left)."""
    small = (8.0, 10.0, 3.0)
    hall = (16.0, 24.0, 5.0)
    out = [
        _preset("small-room-front", "Small room: GigBARs flank the booth, Tetras across the front",
                small, (3.0, 0.3, 2.0, 1.0), (1.5, 2.5, 5.0, 5.0),
                bars=[(2.3, 0.8), (5.7, 0.8)],
                tetras=[(1.5 + i * 1.0, 1.7) for i in range(6)],
                sticks=[(1.5, 2.5), (6.5, 2.5), (1.5, 7.5), (6.5, 7.5)]),
        _preset("small-room-walls", "Small room: Tetras uplight the side walls, sticks on the floor corners",
                small, (3.0, 0.3, 2.0, 1.0), (1.5, 2.5, 5.0, 5.0),
                bars=[(2.3, 0.8), (5.7, 0.8)],
                tetras=[(0.25, 2.5), (0.25, 5.0), (0.25, 7.5), (7.75, 2.5), (7.75, 5.0), (7.75, 7.5)],
                sticks=[(1.5, 2.5), (6.5, 2.5), (1.5, 7.5), (6.5, 7.5)]),
        _preset("wedding-hall-walls", "Wedding hall: Tetras uplight the walls, sticks on the floor corners",
                hall, (6.5, 0.5, 3.0, 1.5), (4.0, 3.5, 8.0, 8.0),
                bars=[(5.2, 1.3), (10.8, 1.3)],
                tetras=[(0.3, 6.0), (0.3, 12.0), (0.3, 18.0), (15.7, 6.0), (15.7, 12.0), (15.7, 18.0)],
                sticks=[(4.0, 3.5), (12.0, 3.5), (4.0, 11.5), (12.0, 11.5)]),
        _preset("wedding-hall-front", "Wedding hall: everything framing the booth and dance floor",
                hall, (6.5, 0.5, 3.0, 1.5), (4.0, 3.5, 8.0, 8.0),
                bars=[(5.2, 1.3), (10.8, 1.3)],
                tetras=[(4.0 + i * 1.6, 2.8) for i in range(6)],
                sticks=[(4.0, 3.5), (12.0, 3.5), (4.0, 11.5), (12.0, 11.5)]),
        # His recording, 3:14: a lawn, a patio or an open tent. No walls to uplight, so the
        # Tetras ring the dance floor.
        _preset("open-space", "Open space or outdoors: no walls, everything around the dance floor",
                (14.0, 14.0, 4.0), (5.5, 0.5, 3.0, 1.5), (3.0, 3.5, 8.0, 8.0),
                bars=[(4.7, 1.3), (9.3, 1.3)],
                tetras=[(3.0, 4.0), (3.0, 7.5), (3.0, 11.0), (11.0, 4.0), (11.0, 7.5), (11.0, 11.0)],
                sticks=[(3.0, 3.5), (11.0, 3.5), (3.0, 11.5), (11.0, 11.5)], open=True),
    ]
    # His wedding (BL #12344): a 20 ft stage, a 22 ft deep floor, the bars 8 ft up on a 2 ft stage.
    stage = stage_layout(20 * FT, 22 * FT, 10 * FT)
    stage.preset = True
    out.append(stage)
    return {p.name: numbered(p, numbering) for p in out}


def stage_layout(stage_w: float, floor_d: float, bar_h: float, *, stage_d: float = 8 * FT,
                 floor_w: Optional[float] = None, name: str = "stage",
                 label: str = "Stage: GigBARs on the stage's front corners, turned in to the dance floor",
                 numbering: Optional[dict] = None) -> Layout:
    """A whole room from three numbers he can measure at the venue (BL #12344), in meters: the stage's
    width, the dance floor's depth out from the stage, and how high each GigBAR's T-bar is above the dance
    floor (its stand plus the stage). The stage sits against the front wall with the booth in its middle,
    the dance floor in front of it as wide as the stage (or `floor_w`), and the bars on the stage's front
    corners STAGE_INSET in from each edge, facing the floor's middle (facing None). Tetras along the stage's
    back, sticks on the floor's corners, room left round it for the tables, each kind numbered from the
    end `numbering` says (BL #12396). Raises ValueError in plain words when a number is off."""
    stage_w = _num(stage_w, "stage width", 2 * STAGE_INSET + 1.0, 30.0)
    floor_d = _num(floor_d, "dance floor depth", 2.0, 30.0)
    bar_h = _num(bar_h, "GigBAR height", 1.0, 6.0)
    stage_d = _num(stage_d, "stage depth", 1.5, 10.0)
    floor_w = stage_w if floor_w is None else _num(floor_w, "dance floor width", 2.0, 30.0)
    side, back = 3.0, 4.0                       # room for tables round the floor
    w = round(max(stage_w, floor_w) + 2 * side, 2)
    d = round(stage_d + floor_d + back, 2)
    h = round(max(5.0, bar_h + 0.5), 2)
    sx, fx = (w - stage_w) / 2, (w - floor_w) / 2
    bw = min(2.0, stage_w - 2 * STAGE_INSET - 0.4)
    booth = Rect(round(w / 2 - bw / 2, 2), round(max(0.2, stage_d / 2 - 0.5), 2), round(bw, 2), 1.0)
    floor = Rect(round(fx, 2), round(stage_d, 2), round(floor_w, 2), round(floor_d, 2))
    by = round(stage_d - STAGE_INSET, 2)
    spots = {"bar1": Spot(round(sx + STAGE_INSET, 2), by, bar_h), "bar2": Spot(round(sx + stage_w - STAGE_INSET, 2), by, bar_h)}
    for i in range(6):   # along the back of the stage, uplighting the wall behind the booth
        spots[f"tetra{i + 1}"] = Spot(round(sx + stage_w * (i + 0.5) / 6, 2), 0.3, 0.1)
    corners = [(fx, stage_d), (fx + floor_w, stage_d), (fx, stage_d + floor_d), (fx + floor_w, stage_d + floor_d)]
    for i, (x, y) in enumerate(corners):
        spots[f"stick{i + 1}"] = Spot(round(x, 2), round(y, 2), 0.0)
    stage = Zone(round(sx, 2), 0.0, round(stage_w, 2), round(stage_d, 2), "stage", "Stage")
    return numbered(Layout(name, label, (w, d, h), booth, floor, spots, zones=[stage]), numbering)


# --- saved layouts and the one in use ----------------------------------------------------

def default_dir() -> Path:
    return Path.home() / ".gigbar_lights"


def has_lineup(layout: Layout, bar: Optional[int] = None) -> bool:
    """Whether any head (of one bar, or of either) has a saved line-up center."""
    return any(c.center for b in ((bar,) if bar else (1, 2)) for c in layout.spots[f"bar{b}"].cal)


def keep_lineup(new: Layout, old: Layout, cleared=()) -> list:
    """Each bar lined up in `old` that comes in `new` with no line-up at all gets old's back (PM #23745), unless
    `cleared` names it. A bar standing where it stood takes the line-up as saved, its spots included; a bar
    moved takes it carried with the bar (`carry_lineup`). Returns the bars kept."""
    kept = []
    for b in (1, 2):
        if b in cleared or has_lineup(new, b) or not has_lineup(old, b):
            continue
        s, o = new.spots[f"bar{b}"], old.spots[f"bar{b}"]
        if (s.x, s.y, s.z, new.facing(f"bar{b}")) == (o.x, o.y, o.z, old.facing(f"bar{b}")):
            s.cal = [HeadCal.from_dict(c.to_dict(), f"bar{b}") if c.center else HeadCal() for c in o.cal]
            s.pan_trim, s.tilt_trim, s.pan_invert = o.pan_trim, o.tilt_trim, o.pan_invert
            new._memo.clear()
        else:
            new.carry_lineup(old, bars=(b,))
        if has_lineup(new, b):
            kept.append(b)
    return kept


class LayoutStore:
    """Presets plus his saved layouts (one JSON file each) and which one is in use."""

    def __init__(self, root: Optional[Path] = None, numbering=None):
        self.root = Path(root) if root else default_dir()
        self.dir = self.root / "layouts"
        # the rig's numbering the presets are drawn with (BL #12396): a callable, read fresh each time
        self.numbering = numbering or rig_numbering

    def _files(self) -> dict[str, tuple[Path, Layout]]:
        """Each saved layout by name, with the file it came from (a hand-copied file's name can differ)."""
        out = {}
        if self.dir.is_dir():
            for p in sorted(self.dir.glob("*.json")):
                try:
                    lay = Layout.from_dict(json.loads(p.read_text(encoding="utf-8")))
                except Exception:  # noqa: BLE001 -- ok: a hand-broken file is skipped, never fatal at launch
                    continue
                lay.preset = False
                out[lay.name] = (p, lay)
        return out

    def saved(self) -> dict[str, Layout]:
        return {n: lay for n, (_, lay) in self._files().items()}

    def all(self) -> dict[str, Layout]:
        return {**presets(self.numbering()), **self.saved()}

    def get(self, name: str) -> Optional[Layout]:
        return self.all().get(name)

    # --- his line-up is never dropped by surprise (PM #23745) ---------------------------------
    # His 11-14 9:42 PM video: Draw my room threw his line-up away, and with no line-up the guess turned head 1
    # of each bar to the wall. Every save of a layout he already lined up keeps that line-up unless he cleared
    # it himself (`cleared`), and the newest line-up he saved is kept apart (lineup_lastgood.json) so Bring
    # back my line-up can put it on any room, whatever path lost it (an update, a sync, a new room, a switch).

    @property
    def lastgood_file(self) -> Path:
        return self.root / "lineup_lastgood.json"

    def remember_lineup(self, layout: Layout) -> bool:
        """Keep this layout's line-up as the last good one, when it has one. Never raises: a full disk loses
        only the spare copy, never the save it rides along with."""
        if not has_lineup(layout):
            return False
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = self.lastgood_file.with_name(self.lastgood_file.name + ".tmp")
            tmp.write_text(json.dumps({"layout": layout.to_dict(), "label": layout.label,
                                       "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, indent=1),
                           encoding="utf-8")
            tmp.replace(self.lastgood_file)
            return True
        except OSError:  # ok: the spare copy is a convenience; the layout file itself was written
            return False

    def last_lineup(self) -> Optional[tuple[Layout, str]]:
        """(the last layout saved with a line-up, when it was saved) or None. Falls back to any saved layout with a
        line-up, so a laptop updated from before 1.31.1 (no spare copy yet) still finds his."""
        try:
            d = json.loads(self.lastgood_file.read_text(encoding="utf-8"))
            lay = Layout.from_dict(d["layout"])
            if has_lineup(lay):
                return lay, str(d.get("at") or "")
        except (OSError, ValueError, KeyError, TypeError):  # ok: no spare copy yet, or a hand-broken one
            pass
        for lay in self.saved().values():
            if has_lineup(lay):
                return lay, ""
        return None

    def save(self, layout: Layout, cleared=()) -> Layout:
        """Save as his own layout under its label. A preset is never overwritten. A bar he lined up in the copy
        saved under this name keeps its line-up when the new copy comes without one, unless `cleared` names
        the bar (Clear line-up); `layout.kept_lineup` lists the bars kept that way."""
        layout.kept_lineup = []
        ps = presets()
        if layout.name in ps:
            from_label = slug(layout.label)
            layout.name = from_label if from_label not in ps else f"{layout.name}-mine"
        layout.preset = False
        self.dir.mkdir(parents=True, exist_ok=True)
        # Two labels can share a file name ("Hall A" / "hall-a", non-Latin names): never
        # overwrite a different saved layout, number this one instead.
        base, n = layout.name, 2
        while True:
            existing = self.saved().get(layout.name)
            if existing is None or existing.label == layout.label:
                break
            layout.name, n = f"{base}-{n}", n + 1
        if existing is not None:
            layout.kept_lineup = keep_lineup(layout, existing, cleared)
        tmp = self.dir / f"{layout.name}.json.tmp"
        tmp.write_text(json.dumps(layout.to_dict(), indent=1), encoding="utf-8")
        tmp.replace(self.dir / f"{layout.name}.json")
        self.remember_lineup(layout)
        return layout

    def _own(self, name: str) -> tuple[Path, Layout]:
        """One of his saved venues by name, with its file; a preset or an unknown name is refused in plain words."""
        files = self._files()
        if name in presets() and name not in files:
            raise ValueError("that's a ready-made room: save your own copy to rename or delete it")
        if name not in files:
            raise ValueError(f"no saved venue named {name}")
        return files[name]

    def rename(self, name: str, label: str) -> Layout:
        """Give one of his saved venues a new name (BL #12380). Only the name he sees changes: the file
        and the key Llano syncs it under stay, so the show, its line-up and llano.app keep the same venue."""
        path, lay = self._own(name)
        label = " ".join(str(label or "").split())
        if not label:
            raise ValueError("type a name for the venue")
        if len(label) > 80:
            raise ValueError("keep the venue's name to 80 letters or fewer")
        clash = [l.label for n, l in self.saved().items() if n != name and l.label.casefold() == label.casefold()]
        if clash:
            raise ValueError(f"you already have a venue called {clash[0]}")
        lay.label = label
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(lay.to_dict(), indent=1), encoding="utf-8")
        tmp.replace(path)
        return lay

    def delete(self, name: str) -> None:
        """Take one of his saved venues off the list (BL #12380). The file is set aside as
        <name>.json.removed, never erased, the same as a venue deleted on llano.app. The venue the
        show aims from can't be deleted: he picks another first, so a show never re-aims by surprise."""
        path, _ = self._own(name)
        if name == self.current_name():
            raise ValueError("the show is aiming from this venue: use another one first, then delete it")
        path.replace(path.with_name(path.name + ".removed"))

    def current_name(self) -> str:
        try:
            name = json.loads((self.root / "venue.json").read_text(encoding="utf-8")).get("current")
        except (OSError, ValueError, AttributeError):  # ok: nothing chosen yet = the default
            name = None
        return name if isinstance(name, str) and name in self.all() else DEFAULT_LAYOUT

    def current(self) -> Layout:
        return self.all()[self.current_name()]

    def use(self, name: str) -> Layout:
        lay = self.get(name)
        if lay is None:
            raise ValueError(f"no layout named {name}")
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "venue.json").write_text(json.dumps({"current": name}), encoding="utf-8")
        return lay
