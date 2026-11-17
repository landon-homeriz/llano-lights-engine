"""Smooth head motion: every GigBAR head glides to where the show aims it instead of jumping.

The 11-09 report (no smooth panning yet): a section change, a new look, a
snap or a beat-clock correction moved a head's pan/tilt target in one frame, and the head crossed
the room at full motor speed. The fixture has no speed or smoothing channel (manual Rev. 4 pp.12-13:
the SYS menu is IR, FOOT, PanReverse, TiltReverse, RESET; 35CH has no fine or speed channel), so the
glide happens here, frame by frame, before the DMX goes out.

Each axis follows its target with a speed and an acceleration limit, in degrees so pan (540) and
tilt (180) move alike. A target already moving within the limits (a sweep, a circle, a glide) is
fed forward and tracked frame for frame; a jump becomes an ease-in, ease-out move of about a
quarter second for a typical section change. A "snap" move keeps its bite with 4x the acceleration.

No crawling (the 11-09 report on 1.15.0.3: still choppy): a GigBAR head takes one
8-bit pan and tilt (2.1 and 0.7 degrees a step; no fine or speed channel), and its motor jumps each
step at full speed. A slow move (a verse glide, a rise across a build) changed the pan byte only 2
or 3 times a second, so the head ticked across the room. Now a target moving slower than CRAWL_STEPS
steps a second is not tracked step by step: the head holds still until the target is GATE_STEPS
steps away, then makes one short eased move onto it (several steps in a row, which the motor runs
as one motion) and holds again. Fast moves and figures track as before.

Together (1.16.3, the 11-09 demo video: the heads stepped one at a time, left light then right light):
each axis used to wait for its own gate, and the two heads of a bar aim from 0.4 m apart, so their
targets differ and they reached the gate on different frames: left tilt moved, then right tilt, then
left pan. Now on the frame one slow axis starts its short move, every other slow axis 2 DMX steps
or more behind starts too, so the heads (and pan and tilt) move together. (1.16.4, his 11-09 real-lights
report "heads 2 and 3 still step": half a step behind dragged the slow inner heads into a move of one
step at a time, so they ticked; 2 steps is a short eased move, and lone 1-step ticks in Demo went
from 128 to 0.) The room picture
draws a second, ungated follower (`picture`): unrounded and continuous, it glides where the real heads
make short moves, and it never crosses the room ahead of them (it shares their speed limits).

Arrive together (1.16.5, the 11-10 real-lights report on 1.16.4: heads 2 and 3 still stepped,
1 and 4 were smooth): a look that moves every head on the same beat gives the inner heads, aimed closer
under the bars, a far smaller turn than the outer ones (Demo: outer pan 22 steps, inner pan 8 and tilt 5).
An eased move's time grows only with the square root of its size, so the outer heads swept over a
quarter second while the inner ones arrived in one 25 ms frame: a twitch. Now every axis that starts
a move on the same frame (its target held still, then jumped at least 2 steps) arrives with the
biggest such move: its speed and acceleration limits scale by its share of that move in degrees,
the same ease-in, ease-out shape stretched in time (`_sync`). The target's own motion is still fed
forward at full speed; only the catch-up is stretched, and it ends when the axis lands.

Pan in slides (1.16.9, the 11-10 real-lights report on 1.16.8: inner heads 2 and 3 still jittery
in some parts of the show and smooth in others; outer heads 1 and 4 always fluid): a slow look
turns the inner heads farther in pan than the outer ones (his saved booth-to-crowd glide: 29 pan steps
against 17), and a pan step is 2.1 degrees against tilt's 0.7, so they made about twice the pan hops
(40 a minute against 26-32), each a 3-step jump of up to 7.5 degrees of beam, and a tilt hop dragged
their pan along 2 steps at a time. Both 1-step pan ticks (1.15) and 3-step pan hops have read as jerky:
slow pan on this fixture can only step. Now a slow pan, outside a figure, holds until it is
PAN_GATE_STEPS behind its moving target, then slides there with SLIDE_DEG_S2 (6 steps over about 5
frames), and only another pan's slide takes it along (Together, per axis), so all four heads pan on the
same frames the same number of times (his layout, every slow look; Demo's bar partners: 0 turns and
0 lone starts, from 6 and 48). Once the target stops, the gate is GATE_STEPS again, so a head settles
on its aim. A pan under PAN_GATE_STEPS across (a small crowd-to-fan sweep) rides on tilt. Figures
(circle, eight, line) keep GATE_STEPS and their shape. Kill switch: LLANO_LIGHTS_PAN_SLIDES=0 is
1.16.8 byte for byte.

Line-up and calibration poses (1.16.0, his 11-09 report: after Done, GigBAR 2's right head stopped
a quarter turn off while Llano had sent all four heads the same zero pan and tilt): until 1.16.0 they
landed raw, so Center all, a Light doctor pose and the rest pose at Stop slammed a head up to 540
degrees at full motor speed, the way a stepper skips and then sits off by what it skipped. Now a
jump glides there calmly (`calm`); a nudge of a few DMX steps still lands at once, so he sees each
press. `park` glides every head home to straight ahead, tilt 0, before the rig goes dark.

Middle twin (1.16.4, the 11-09 report on 1.16.3: head 4 spun about a full turn at power-up and going
to rest, and seemed to hit a hard stop): pan turns 540 degrees (manual Rev. 4 specs: 540/180
over DMX 0..255), so any heading below the head is reached at two raw pans one motor turn (360 / 540
= 0.667) apart. Head 4's saved center sat on the upper twin (show aims at bytes 224-252) while rest
was pan 0 at the bottom end: every park, every fresh line-up and the all-zero frame after Stop turned
it about 500 degrees, and an aim past the top end flipped to the other twin mid show. Now a saved
center sits on the twin nearest DMX middle (venue.HeadCal), so the show's aims stay well inside the
range whichever way he nudged it, and rest is straight ahead on the twin nearest middle
(venue.rest_pan: pan 0.667, byte 170), never pan 0 against the end stop: a head parks the short way.
"""
from __future__ import annotations

import math
import os
from typing import Optional

from .venue import rest_pan

MAX_DEG_S = 720.0        # top speed while gliding, degrees a second
MAX_DEG_S2 = 4800.0      # acceleration: a 108-degree jump takes about 0.3 s
SNAP_ACCEL = 4.0         # a snap move accelerates this much harder
MAX_GAP_S = 0.25         # a longer gap between frames (stall, first frame): land at once
CRAWL_STEPS = 12.0       # a target slower than this many DMX steps a second would tick: hold-and-move
GATE_STEPS = 3.0         # ...moving once it is this many steps away
PAN_GATE_STEPS = 6.0     # Pan in slides: a slow pan (not in a figure) waits until it is this many steps behind
STILL_STEPS = 0.1        # ...while its target moves faster than this many steps a second (else GATE_STEPS: settle)
SLIDE_DEG_S2 = 1800.0    # ...then slides there this gently: 6 steps over ~5 frames, at most 2 a frame


def pan_slides() -> bool:
    """Pan in slides (1.16.9, above) unless LLANO_LIGHTS_PAN_SLIDES=0 (1.16.8's 3-step pan hops)."""
    return (os.environ.get("LLANO_LIGHTS_PAN_SLIDES") or "1").strip().lower() not in {"0", "off", "false", "no"}
SYNC_MIN_STEPS = 80.0    # Arrive together: a stretched move still peaks at 2 DMX steps a frame or faster
CALM_DEG_S = 360.0       # line-up, calibration and parking: half the show's top speed
CALM_DEG_S2 = 1800.0
NUDGE_STEPS = 3          # a change this many DMX steps or less lands at once (his arrow presses)
PARK_MAX_S = 2.5         # parking never holds Stop up longer than this
CALM_FRAME_S = 0.025     # a calm run's first frame (or one after a stall) steps as one 40 Hz frame


class _Axis:
    __slots__ = ("pos", "vel", "target", "tv", "resting", "gate", "slow", "starting", "ff", "dx", "jump", "scale",
                 "slide", "sliding", "steps")

    def __init__(self, x: float, gate: bool = True):
        self.pos, self.vel, self.target, self.tv, self.resting = x, 0.0, x, 0.0, True
        self.gate, self.slow, self.starting, self.ff = gate, False, False, 0.0
        self.dx, self.jump, self.scale = 0.0, False, 1.0   # Arrive together (above)
        self.slide = 0.0   # Pan in slides (above): the gate while the target moves, 0 = GATE_STEPS
        self.sliding = False   # this move is a slide (Pan in slides): gentler acceleration until it lands
        self.steps = GATE_STEPS   # the hold-and-move gate in DMX steps (a steered spot follows closer, apply)

    def aim(self, target: float, dt: float, vmax: float) -> bool:
        """Take this frame's target; True while it holds still (a slow target not yet GATE_STEPS
        away, No crawling above). The target's own motion is fed forward when it is feasible
        (|speed| <= vmax); a bigger change is a jump and feeds nothing forward."""
        tv = (target - self.target) / dt
        dx = target - self.target
        # A move starts: the target held still last frame, then jumped (Arrive together, above).
        self.jump = abs(dx) >= 2.0 / 255.0 and abs(self.dx) < 0.5 / 255.0
        self.dx = dx
        self.target = target
        if abs(tv) > vmax or self.jump:   # a jump from still is a move to make, not a speed to follow
            tv = 0.0
        self.ff = tv   # this frame's feasible target speed, fed forward by `move`
        # The target's speed over the last few frames: one frame's change is a whole DMX step or none.
        self.tv += (tv - self.tv) * min(1.0, dt / 0.2)
        self.slow = self.gate and abs(self.tv) < CRAWL_STEPS / 255.0
        gate = self.slide if self.slide and abs(self.tv) > STILL_STEPS / 255.0 else self.steps
        hold = self.slow and self.resting and abs(target - self.pos) < gate / 255.0
        self.starting = self.slow and self.resting and not hold   # its short move begins this frame
        return hold

    def due(self) -> bool:
        """Holding, but far enough behind that moving would change its DMX byte (Together, above)."""
        return abs(round(self.target * 255) - round(self.pos * 255)) >= 2

    def move(self, dt: float, vmax: float, amax: float) -> float:
        """One frame toward the target taken by `aim`."""
        target, tv = self.target, (0.0 if self.slow else self.ff)
        err = target - self.pos
        self.resting = False
        vmax, amax = vmax * self.scale, amax * self.scale   # Arrive together: the catch-up, stretched
        self.sliding = self.sliding and self.slow   # a target fast again is tracked at full pace
        if self.sliding:
            amax *= SLIDE_DEG_S2 / MAX_DEG_S2
        # The speed that still stops on the target (v^2 = 2 a d), plus the target's own speed.
        want = math.copysign(min(vmax, math.sqrt(2.0 * amax * abs(err))), err) + tv
        want = max(-vmax - abs(tv), min(vmax + abs(tv), want))
        dv = max(-amax * dt, min(amax * dt, want - self.vel))
        self.vel += dv
        nxt = self.pos + self.vel * dt
        # Never step past the target in one frame (that is what rings).
        if (target - self.pos) * (target - nxt) < 0 or abs(target - nxt) < 1e-6:
            nxt, self.vel = target, tv
            self.resting = tv == 0.0
            self.scale = 1.0
            self.sliding = self.sliding and not self.resting
        self.pos = nxt
        return nxt

    def step(self, target: float, dt: float, vmax: float, amax: float) -> float:
        """One frame toward `target` (raw 0..1) on its own (no other axis to move with)."""
        return self.pos if self.aim(target, dt, vmax) else self.move(dt, vmax, amax)

    def land(self, x: float) -> None:
        self.pos, self.vel, self.target, self.tv, self.resting = x, 0.0, x, 0.0, True
        self.scale, self.sliding = 1.0, False


def _sync(axes) -> None:
    """Arrive together (above): (axis, its degrees per raw unit, its acceleration) triples; every axis
    starting a move this frame scales its limits by its move's share of the biggest one, so all of
    them land on one frame, but never so far that its peak speed drops under SYNC_MIN_STEPS a second
    (a short move stretched further crawls one step at a time, the tick No crawling removed)."""
    starts = [(a, abs(a.target - a.pos), deg, acc) for a, deg, acc in axes if a.jump]
    lead = max((err * deg for _, err, deg, _ in starts), default=0.0)
    for a, err, deg, acc in starts:
        floor = (SYNC_MIN_STEPS / 255.0) ** 2 / (acc * err) if err > 0 else 1.0   # peak v = sqrt(a s d)
        a.scale = min(1.0, max(err * deg / lead, floor)) if lead > 0 else 1.0


class HeadGlide:
    """Per-head followers, keyed by (bar, head). `apply` moves the rig's heads in place."""

    def __init__(self, pan_range: float = 540.0, tilt_range: float = 180.0):
        self.pan_range, self.tilt_range = pan_range, tilt_range
        self.rest: Optional[tuple] = None   # raw (pan, tilt) heads rest at (venue.Layout.rest_pose), None = rest_pan, 0
        self._heads: dict = {}
        self._pic: dict = {}      # the room picture's ungated twins of _heads (picture)
        self._last: Optional[float] = None

    def apply(self, rig, now: float, smooth: bool = True, snap: bool = False, calm: bool = False,
              figure: bool = False, follow: float = 0.0) -> None:
        """`follow` (1.20.0, the Light studio's steered spots): the hold-and-move gate in DMX steps
        while he steers a spot, smaller than GATE_STEPS so the beam stays close behind the point he
        moves, and no pan slides (a slide waits 6 steps, a visible lag behind a person). 0 = the
        show's own gates, as before."""
        dt = None if self._last is None else now - self._last
        self._last = now
        if calm and smooth and (dt is None or dt <= 0 or dt > MAX_GAP_S):
            dt = CALM_FRAME_S   # a new line-up run glides from home too, never lands in one frame
        land = not smooth or dt is None or dt <= 0 or dt > MAX_GAP_S
        k = SNAP_ACCEL if snap else 1.0
        vmax, amax = (CALM_DEG_S, CALM_DEG_S2) if calm else (MAX_DEG_S, MAX_DEG_S2)
        slides = pan_slides()
        moving = []   # (axis, head, "pan"/"tilt", vmax, amax, holding this frame, degrees per raw unit)
        pics = []     # (picture axis, vmax, amax, degrees per raw unit)
        for b, bar in enumerate(rig.bars):
            for m, head in enumerate(bar.movers):
                ax = self._heads.get((b, m))
                if ax is None:
                    # A calm run (line-up, calibration, park) starts where the heads rest: straight
                    # ahead and level, where Stop leaves them (review 1.16.0). Straight ahead on the pan
                    # twin nearest DMX middle (1.16.4, Middle twin above): from pan 0 the first frame
                    # sent pan 0 and the glide then turned a head a full turn back up to its aims.
                    # Turned to the side the rig faces its spots from (1.16.7, venue.Layout.rest_pose).
                    start = self.rest_pose() if calm else (head.pan, head.tilt)
                    ax = self._heads[(b, m)] = (_Axis(start[0]), _Axis(start[1]))
                    self._pic[(b, m)] = (_Axis(start[0], gate=False), _Axis(start[1], gate=False))
                pic = self._pic[(b, m)]
                # Pan in slides, never in a figure (a circle or an eight keeps its shape) nor a line-up
                # (a held arrow keeps its pace): GATE_STEPS there
                ax[0].slide = PAN_GATE_STEPS if slides and not figure and not calm and not follow else 0.0
                ax[0].steps = ax[1].steps = follow or GATE_STEPS
                if land:
                    for a in (*ax, *pic):
                        a.land(head.pan if a in (ax[0], pic[0]) else head.tilt)
                    continue
                if calm and all(abs(a.pos - v) <= NUDGE_STEPS / 255 + 1e-9 and abs(a.vel) < 1e-6
                                for a, v in ((ax[0], head.pan), (ax[1], head.tilt))):
                    for a in (*ax, *pic):   # a nudge: he sees the raw value land
                        a.land(head.pan if a in (ax[0], pic[0]) else head.tilt)
                    continue
                for i, (attr, rng) in enumerate((("pan", self.pan_range), ("tilt", self.tilt_range))):
                    v, a = vmax / rng, k * amax / rng
                    pic[i].aim(getattr(head, attr), dt, v)
                    pics.append((pic[i], v, a, rng))
                    moving.append((ax[i], head, attr, v, a, ax[i].aim(getattr(head, attr), dt, v), rng))
        if not calm:   # a line-up keeps its own pace per head; a nudge lands at once
            _sync([(a, rng, acc) for a, _, _, _, acc, _, rng in moving])
            _sync([(a, rng, acc) for a, _, acc, rng in pics])
        for a, v, acc, _ in pics:
            a.move(dt, v, acc)
        # Together (above): one slow axis starting its short move takes every due one with it.
        # Only on the frame a move starts: a dragged axis then finishes its own move, never re-dragged.
        together = any(a.starting for a, *_ in moving)
        # Pan in slides: a sliding pan is taken along only by another pan's slide, never by a tilt hop
        # (a tilt every few seconds would drag it 2 steps at a time, the hop this replaces).
        pans = any(a.starting for a, _, attr, *_ in moving if attr == "pan")
        drag = lambda a, attr: a.due() and (pans if attr == "pan" and a.slide else together)
        if not calm:   # Pan in slides: a slow pan starting from rest (its gate or Together) slides there
            for a, _, attr, _, _, hold, _ in moving:
                if a.slide and a.resting and a.slow and not a.jump and (not hold or drag(a, attr)):
                    a.sliding = True
        for a, head, attr, v, acc, hold, _ in moving:
            if hold and not drag(a, attr):
                setattr(head, attr, a.pos)
            else:
                setattr(head, attr, a.move(dt, v, acc))

    def picture(self) -> dict:
        """Where the room picture draws each head, (bar, head) -> (pan, tilt) raw 0..1: the glide
        without the hold-and-move gate, unrounded, so a slow move is a continuous sweep on screen."""
        return {key: (p[0].pos, p[1].pos) for key, p in self._pic.items()}

    def rest_pose(self) -> tuple:
        """Raw (pan, tilt) of rest: the layout's (`rest`), else straight ahead on the middle twin, tilt 0."""
        return self.rest if self.rest is not None else (rest_pan(self.pan_range), 0.0)

    def parked(self, pose=None) -> bool:
        """Every head home at `pose` (raw pan, tilt; a bare pan means tilt 0; None = `rest_pose`),
        or never moved (nothing to park)."""
        pan, tilt = self.rest_pose() if pose is None else (pose, 0.0) if isinstance(pose, (int, float)) else pose
        return all(abs(ax[0].pos - pan) < 0.5 / 255 and abs(ax[1].pos - tilt) < 0.5 / 255 for ax in self._heads.values())
