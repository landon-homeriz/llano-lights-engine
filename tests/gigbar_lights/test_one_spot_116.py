"""Line up my lights on one spot (1.16.0, Llano PM #22505).

He picks a spot, every head is sent there, and he nudges each head until all the beams sit on it.
Each head's pose then says where its bar faces and how high it hangs, because the heads face
straight ahead at pan 0, tilt 0 (his fact, and where Stop leaves them). After that, any other spot
is reached from the model, not from more taps.
"""
import math

import pytest

from tools.gigbar_lights import venue
from tools.gigbar_lights.venue import HEAD_SPACING, HOME_POSE, PAN_RANGE, TILT_RANGE, mid_twin, presets


class RealBar:
    """A bar as it really hangs: its facing, height and each head's turn directions, with the
    straight-ahead pose at HOME_POSE. Tells which raw pose puts a head's beam on a floor spot."""

    def __init__(self, lay, bar, facing, height, turn):
        self.s, self.facing, self.height, self.turn = lay.spots[f"bar{bar}"], facing, height, turn

    def head(self, m):
        f = math.radians(self.facing)
        k = (1, -1)[m] * HEAD_SPACING / 2   # head 1 on the bar's own left: his right from the floor
        return self.s.x + math.cos(f) * k, self.s.y - math.sin(f) * k, self.height

    def pose(self, m, x, y):
        hx, hy, z = self.head(m)
        sp, st = self.turn[m]
        heading = math.degrees(math.atan2(x - hx, y - hy))
        off = math.degrees(math.atan2(math.hypot(x - hx, y - hy), z))
        tilt = HOME_POSE[1] + (off - 90.0) / (st * TILT_RANGE)
        for k in range(-2, 3):
            pan = HOME_POSE[0] + ((heading - self.facing) + 360.0 * k) / (sp * PAN_RANGE)
            if 0.0 <= pan <= 1.0:
                return round(pan * 255) / 255, round(tilt * 255) / 255
        raise AssertionError("out of reach")

    def lands(self, m, pan, tilt):
        hx, hy, z = self.head(m)
        sp, st = self.turn[m]
        h = math.radians(self.facing + sp * (pan - HOME_POSE[0]) * PAN_RANGE)
        o = math.radians(90.0 + st * (tilt - HOME_POSE[1]) * TILT_RANGE)
        t = z / math.cos(o)
        return hx + math.sin(o) * math.sin(h) * t, hy + math.sin(o) * math.cos(h) * t


# The two heads of a bar turn opposite ways (mounted mirrored); tilt rises from level toward down.
MIRRORED = {0: (-1, -1), 1: (1, -1)}


def _rig(lay):
    auto2 = lay.facing("bar2")
    auto1 = lay.facing("bar1")
    return {1: RealBar(lay, 1, auto1 - 9.0, 2.75, MIRRORED), 2: RealBar(lay, 2, auto2 + 12.0, 2.1, {0: (1, -1), 1: (-1, -1)})}


@pytest.mark.parametrize("name", ["small-room-front", "wedding-hall-front"])
def test_one_spot_works_out_each_bars_facing_and_height_and_every_other_spot_follows(name):
    lay = presets()[name]
    real = _rig(lay)
    spot = (lay.floor.cx, lay.floor.cy)
    samples = [(b, m, *real[b].pose(m, *spot), spot) for b in (1, 2) for m in (0, 1)]
    found = lay.converge(samples)
    for b in (1, 2):
        rep = found["bars"][b]
        assert rep["solved"], rep
        assert rep["facing"] == pytest.approx(real[b].facing, abs=1.5)
        assert rep["height"] == pytest.approx(real[b].height, abs=0.08)
    # Back on the spot it lands on the pose he nudged it to, on the pan twin nearest DMX middle (1.16.4,
    # his ruling: whichever way he nudged, the head works away from its end stops).
    for b, m, pan, tilt, _ in samples:
        assert lay.aim(b, lay.heads(b)[m], (*spot, 0.0), m) == pytest.approx((mid_twin(pan, 360 / 540), tilt), abs=2 / 255)
    # Every head lands on the spot it was lined up on, and on spots it never saw.
    fl = lay.floor
    for target in [spot, (fl.x + 0.5, fl.y + 0.5), (fl.x + fl.w - 0.5, fl.y + fl.d * 0.8), (fl.cx, fl.y)]:
        for b in (1, 2):
            for m in (0, 1):
                pan, tilt = lay.aim(b, lay.heads(b)[m], (*target, 0.0), m)
                x, y = real[b].lands(m, pan, tilt)
                hx, hy, _ = real[b].head(m)
                # within a DMX step: one is about 2 degrees of pan, so 3% of the throw
                throw = math.hypot(target[0] - hx, target[1] - hy)
                assert math.hypot(x - target[0], y - target[1]) < max(0.2, 0.03 * throw), (name, target, b, m)


def test_a_second_spot_refines_it():
    lay = presets()["small-room-front"]
    real = _rig(lay)
    a, b2 = (lay.floor.cx, lay.floor.cy), (lay.floor.x + 1.0, lay.floor.y + 1.0)
    samples = [(b, m, *real[b].pose(m, *p), p) for p in (a, b2) for b in (1, 2) for m in (0, 1)]
    found = lay.converge(samples)
    assert all(found["bars"][b]["solved"] for b in (1, 2))
    assert all(h["spots"] == 2 and h["miss_deg"] < 1.5 for b in (1, 2) for h in found["bars"][b]["heads"].values())


def test_one_head_alone_is_still_placed_on_the_spot_but_the_bar_is_left_where_it_stands():
    lay = presets()["small-room-front"]
    real = _rig(lay)
    spot = (lay.floor.cx, lay.floor.cy)
    before = (lay.facing("bar2"), lay.spots["bar2"].z)
    found = lay.converge([(2, 0, *real[2].pose(0, *spot), spot)])
    assert not found["bars"][2]["solved"] and "both heads" in found["bars"][2]["why"]
    assert (lay.facing("bar2"), lay.spots["bar2"].z) == before
    assert lay.spots["bar2"].cal[0].center is not None


def test_one_spot_survives_saving():
    lay = presets()["small-room-front"]
    real = _rig(lay)
    spot = (lay.floor.cx, lay.floor.cy)
    lay.converge([(b, m, *real[b].pose(m, *spot), spot) for b in (1, 2) for m in (0, 1)])
    back = venue.Layout.from_dict(lay.to_dict())
    for b in (1, 2):
        assert back.facing(f"bar{b}") == pytest.approx(lay.facing(f"bar{b}"))
        assert back.spots[f"bar{b}"].z == lay.spots[f"bar{b}"].z
        for m in (0, 1):
            assert back.aim(b, back.heads(b)[m], (2.0, 4.0, 0.0), m) == pytest.approx(lay.aim(b, lay.heads(b)[m], (2.0, 4.0, 0.0), m))
