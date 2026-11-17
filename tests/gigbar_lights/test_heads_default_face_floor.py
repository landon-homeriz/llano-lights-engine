"""Movers start facing the dance floor with no line-up (PM #23745, the 11-14 video: the
lights pointed backwards).

A room with no line-up aims every head with the guessed model of a Chauvet GigBAR Move. Until 1.31.1 that model
had both heads turning the wrong way as raw pan rises, and head 1's home half a turn off, so head 1 of each bar
was sent about 180 degrees from the floor (1.14.3 to 1.31.0). His saved line-up hid it until Draw my room drew
a room without one.

The real fixture, as his four lined-up heads show it (his_room_lined_up_12400.json, lined up on the real rig):
both heads on a bar are the same, not mirrored. At raw pan 0, tilt 0 each looks straight ahead and level; raw
pan rising turns it clockwise seen from above; tilt above 0.5 leans toward the heading. These tests read the
fixture from his line-up and check the guess against it in rooms that are NOT his: nothing here is his venue's
numbers, and the code holds none (venue.HEAD_HOME, venue.GUESS_TURN).
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

from tools.gigbar_lights import venue
from tools.gigbar_lights.glide import HeadGlide
from tools.gigbar_lights.looks import FIGURES, Frame, LooksEngine
from tools.gigbar_lights.rig import default_rig
from tools.gigbar_lights.show_script import Section
from tools.gigbar_lights.venue import FT, Layout, stage_layout

HERE = Path(__file__).parent
LINED = json.loads((HERE / "his_room_lined_up_12400.json").read_text())
HEADS = [(b, m) for b in (1, 2) for m in (0, 1)]


def _no_lineup(d: dict) -> dict:
    d = copy.deepcopy(d)
    for b in ("bar1", "bar2"):
        d["fixtures"][b].pop("cal", None)
    return d


def _side_wall_room() -> dict:
    """A room unlike his: the GigBARs on the left wall, turned 90 degrees, the floor to their right."""
    d = stage_layout(24 * FT, 20 * FT, 9 * FT).to_dict()
    d["name"], d["label"] = "side-wall", "Side wall test room"
    fl = d["floor"]
    d["fixtures"]["bar1"].update(x=0.6, y=fl["y"] + 1.0, facing=90.0)
    d["fixtures"]["bar2"].update(x=0.6, y=fl["y"] + fl["d"] - 1.0, facing=90.0)
    return d


ROOMS = {
    "Draw my room 20 x 22 at 10 ft": lambda: stage_layout(20 * FT, 22 * FT, 10 * FT).to_dict(),
    "Draw my room 30 x 16 at 8 ft": lambda: stage_layout(30 * FT, 16 * FT, 8 * FT).to_dict(),
    "Draw my room 14 x 30 at 12 ft": lambda: stage_layout(14 * FT, 30 * FT, 12 * FT).to_dict(),
    "side wall, bars turned 90": _side_wall_room,
    **{f"preset {n}": (lambda lay=lay: lay.to_dict()) for n, lay in venue.presets().items()},
}


def _real(fresh: dict) -> Layout:
    """The real fixture in this room: his line-up (how each real head turns on its bar) carried onto it."""
    real = Layout.from_dict(_no_lineup(fresh))
    assert sorted(real.carry_lineup(Layout.from_dict(LINED))) == HEADS
    return real


def _off_floor(real: Layout, b: int, m: int, pan: float, tilt: float) -> float:
    """Degrees, seen from above, between where the REAL head points for this pose and the floor's middle."""
    h, fl = real.heads(b)[m], real.floor
    d = real.beam_of(b, m, pan, tilt)
    want = math.degrees(math.atan2(fl.cx - h[0], fl.cy - h[1]))
    return abs((math.degrees(math.atan2(d[0], d[1])) - want + 180) % 360 - 180)


def _miss_3d(real: Layout, b: int, m: int, pan: float, tilt: float, target) -> float:
    """Degrees between where the REAL head points for this pose and the target, in the room (tilt included)."""
    d, h = real.beam_of(b, m, pan, tilt), real.heads(b)[m]
    w = [a - c for a, c in zip(target, h)]
    n = math.sqrt(sum(v * v for v in w))
    return math.degrees(math.acos(max(-1.0, min(1.0, sum(a * c / n for a, c in zip(d, w))))))


def test_the_guess_turns_each_head_the_way_his_real_heads_turn():
    # his four lined-up heads are the fixture's own record; the guess on the same bars, across the pan range,
    # now points where each real head points (within the few degrees each head sits off on its own bar)
    real, guess = Layout.from_dict(LINED), Layout.from_dict(_no_lineup(LINED))
    for b, m in HEADS:
        for pan in (0.2, 0.3, 0.4, 0.5, 0.6):
            r, g = real.beam_of(b, m, pan, 0.8), guess.beam_of(b, m, pan, 0.8)
            hr, hg = (math.degrees(math.atan2(v[0], v[1])) for v in (r, g))
            assert abs((hr - hg + 180) % 360 - 180) < 25, (b, m, pan, hr, hg)


@pytest.mark.parametrize("room", list(ROOMS))
def test_with_no_lineup_every_head_aims_at_the_floor_in_any_room(room):
    fresh = ROOMS[room]()
    lay, real = Layout.from_dict(_no_lineup(fresh)), _real(fresh)
    fl = lay.floor
    for b, m in HEADS:
        p, t = lay.aim(b, lay.heads(b)[m], (fl.cx, fl.cy, 0.0), m)
        assert _off_floor(real, b, m, p, t) < 25, (room, b, m, p, t)
        assert _miss_3d(real, b, m, p, t, (fl.cx, fl.cy, 0.0)) < 25, (room, b, m, p, t)   # down at it, not at a wall


def _capture(layout: dict, secs: float = 30.0, bpm: float = 124.0) -> list:
    """What the laptop sends the four heads during a verse, 40 frames a second (looks engine, then the glide)."""
    eng, rig, g = LooksEngine(), default_rig(), HeadGlide()
    eng.apply_venue(Layout.from_dict(layout))
    sec = Section("verse", 0, 100000, 1.0)
    out = []
    for i in range(int(secs * 40)):
        now = i / 40
        eng.render(Frame(now * bpm / 60, bpm, True, level=0.6, section=sec, track_key=7, now=now), rig)
        g.apply(rig, now, snap=eng.move_shape == "snap", figure=eng.move_shape in FIGURES)
        out.append([(round(h.pan * 255), round(h.tilt * 255)) for bar in rig.bars for h in bar.movers])
    return out[80:]


@pytest.mark.parametrize("room", ["Draw my room 20 x 22 at 10 ft", "side wall, bars turned 90"])
def test_the_bytes_a_fresh_room_sends_keep_every_head_in_front_of_its_bar(room):
    # the captured DMX of a verse in a room nobody lined up, read through the real heads: every frame of every
    # head lands in front of its bar, toward the floor (before 1.31.1 head 1 of each bar faced the wall)
    fresh = ROOMS[room]()
    real, frames = _real(fresh), _capture(_no_lineup(fresh))
    for k, (b, m) in enumerate(HEADS):
        worst = max(_off_floor(real, b, m, f[k][0] / 255, f[k][1] / 255) for f in frames)
        assert worst < 90, (room, b, m, worst)
        pans = {f[k][0] for f in frames}
        assert len(pans) > 3   # the head really moves: a still head can't pass this


def test_line_up_my_lights_starts_from_poses_that_face_the_floor():
    # Line up my lights' first aim on a fresh room is the guess at the floor's middle: every head starts there
    fresh = ROOMS["Draw my room 20 x 22 at 10 ft"]()
    lay, real = Layout.from_dict(_no_lineup(fresh)), _real(fresh)
    for b, m in HEADS:
        p, t = lay.aim(b, lay.heads(b)[m], lay.ref_target("center"), m)
        assert _off_floor(real, b, m, p, t) < 25, (b, m)
        # the same side of the range as his real line-ups (near 0.33, never half a turn away near 0.67)
        assert 0.2 < p < 0.5, (b, m, p)
