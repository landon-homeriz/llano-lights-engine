"""Center all lands every GigBAR head on the floor in front of its bar before any calibration
(his 11-08 photos on 1.14.0, "Middle of the dance floor": the right heads hit the door and the
wardrobe to his right, the left heads turned back to the wall behind the bars). Pan 0.5 points
each head out along the bar toward its own end (venue.HEAD_HOME), not out of the bar's front."""
from __future__ import annotations

import copy
import math

import pytest

from tools.gigbar_lights import venue
from tools.gigbar_lights.venue import HeadCal, Layout, presets


def his_layout() -> Layout:
    return copy.deepcopy(presets()["small-room-front"])


def land(lay: Layout, bar: int, m: int, pan: float, tilt: float):
    """Where head m's beam meets the floor (None if it never comes down)."""
    o = lay.heads(bar)[m]
    d = lay.beam(bar, o, pan, tilt, m)
    if d[2] >= -1e-6:
        return None
    t = -o[2] / d[2]
    return (o[0] + d[0] * t, o[1] + d[1] * t)


@pytest.mark.parametrize("name", sorted(presets()))
def test_center_all_lands_every_head_on_the_center_dot(name):
    lay = copy.deepcopy(presets()[name])
    cx, cy, _ = lay.ref_target("center")
    for b, m, head in lay.all_heads():
        pan, tilt = lay.aim(b, head, (cx, cy, 0.0), m)
        assert lay.forward(b, pan, m) == pytest.approx(pan)   # the guard leaves it alone
        x, y = land(lay, b, m, pan, tilt)
        assert math.hypot(x - cx, y - cy) < 0.01, (name, b, m)
        assert y > lay.heads(b)[m][1]   # in front of the bar, never behind it


def test_both_heads_reach_the_floor_from_the_same_side_of_the_range():
    """1.31.1 (PM #23745): the two heads on a bar are mounted the same way, not mirrored. His four heads lined up on
    the real rig (11-14) each meet the floor's middle near raw pan 0.33, head 1 and head 2 alike; the 1.14.0 guess
    had head 1 mirrored, which sent it half a turn away (0.68) to the wall when no line-up was saved."""
    lay = his_layout()
    cx, cy, _ = lay.ref_target("center")
    for b in (1, 2):
        p0, _ = lay.aim(b, lay.heads(b)[0], (cx, cy, 0.0), 0)
        p1, _ = lay.aim(b, lay.heads(b)[1], (cx, cy, 0.0), 1)
        assert 0.2 < p0 < 0.5 and 0.2 < p1 < 0.5, (b, p0, p1)
        assert abs(p0 - p1) < 0.1   # the same turn, give or take where each head sits on the bar


def test_pan_half_points_both_heads_the_same_way_along_the_bar():
    """At pan 0.5 (270 degrees on from straight ahead at pan 0) both heads point out along the bar the same way,
    as his lined-up heads do; the 1.14.0 reading of his 11-08 photos (each to its own end) was the mirrored guess."""
    lay = his_layout()
    for b in (1, 2):
        f = math.radians(lay.facing(f"bar{b}"))
        own_left = (math.cos(f), -math.sin(f))   # seen from above, the bar's own left as it faces out (1.16.0)
        for m in (0, 1):
            d = lay.beam(b, lay.heads(b)[m], 0.5, 0.84, m)
            along = d[0] * own_left[0] + d[1] * own_left[1]
            assert along > 0.8, (b, m)


def test_mirror_on_an_uncalibrated_bar_flips_the_turn_and_still_finds_the_dot():
    lay = his_layout()
    cx, cy, _ = lay.ref_target("center")
    before = [lay.aim(1, h, (cx, cy, 0.0), m) for m, h in enumerate(lay.heads(1))]
    lay.flip_pan(1)
    s = lay.spots["bar1"]
    assert s.pan_invert and not any(c.center for c in s.cal)   # no guessed center frozen in
    after = [lay.aim(1, h, (cx, cy, 0.0), m) for m, h in enumerate(lay.heads(1))]
    for (pb, _), (pa, _) in zip(before, after):
        assert pa == pytest.approx(1.0 - pb, abs=1e-6)   # the same quarter turn, the other way
    for m, (pan, tilt) in enumerate(after):
        x, y = land(lay, 1, m, pan, tilt)
        assert math.hypot(x - cx, y - cy) < 0.01


def test_a_calibrated_head_keeps_its_own_center():
    """Set center replaces the guess: HEAD_HOME never moves a calibrated head."""
    lay = his_layout()
    cx, cy, _ = lay.ref_target("center")
    lay.spots["bar2"].cal[1] = HeadCal(center=(0.31, 0.77))
    assert lay.aim(2, lay.heads(2)[1], (cx, cy, 0.0), 1) == pytest.approx((0.31, 0.77), abs=1e-6)


def test_line_up_center_uses_the_saved_calibration():
    """Center all aims through the layout's targets, so a saved center is what the head gets."""
    lay = his_layout()
    lay.spots["bar1"].cal[0] = HeadCal(center=(0.62, 0.71))
    heads = lay.all_heads()
    center = dict(zip([(b, m) for b, m, _ in heads], lay.positions()["center"]))
    assert center[(1, 0)] == pytest.approx((0.62, 0.71), abs=1e-6)
    pan, tilt = lay.aim(1, lay.heads(1)[0], lay.ref_target("center"), 0)
    assert (pan, tilt) == pytest.approx((0.62, 0.71), abs=1e-6)
