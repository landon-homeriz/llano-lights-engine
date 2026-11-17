"""The moving heads use the whole room, and a spotlight lands on the person, bright (Llano PM #23789).

The 11-15 report on the Stage room (stage-tetra-1-on-the-right): the heads always pointed down and stayed in a
small area close to the bars, and the follow-me spotlight is too dim and lands on the floor. Every named
move but "ceiling" aimed at a floor point inside the 6.1 x 6.7 m dance floor; now "fan" and the sweeps reach
the side and back walls over the crowd, "crowd" spans the floor's whole width and "cross" its far corners,
Follow someone aims at chest/face height (a roaming Spotlight look stays on the floor:
nobody is under it), and a Spotlight look runs its heads at full with the wash dipped.
"""
import json
import math
from pathlib import Path

import pytest

from tools.gigbar_lights import moments, settings_contract as contract, studio, venue
from tools.gigbar_lights.looks import Frame, LooksEngine
from tools.gigbar_lights.rig import default_rig
from tools.gigbar_lights.show_script import Section
from tools.gigbar_lights.venue import Layout, Zone

HERE = Path(__file__).parent
STAGE = json.loads((HERE / "his_stage_room_12400.json").read_text())


def _land(lay, b, m, pan, tilt):
    """Where a head's beam first meets the room (a wall, the floor or the ceiling)."""
    o = lay.heads(b)[m]
    d = lay.beam(b, o, pan, tilt, m)
    w, dd, h = lay.room
    best = None
    for ax, lim in ((0, 0.0), (0, w), (1, 0.0), (1, dd), (2, 0.0), (2, h)):
        if abs(d[ax]) < 1e-9:
            continue
        t = (lim - o[ax]) / d[ax]
        p = [o[i] + t * d[i] for i in range(3)]
        if t > 1e-6 and all(-1e-6 <= p[i] <= (w, dd, h)[i] + 1e-6 for i in range(3)) and (best is None or t < best[0]):
            best = (t, p)
    return best[1]


def _landings(lay, name):
    pos = lay.positions()[name]
    return [_land(lay, b, m, *pt) for (b, m, _), pt in zip(lay.all_heads(), pos)]


def test_fan_reaches_the_side_and_back_walls_over_the_crowd():
    lay = Layout.from_dict(STAGE)
    w, d, _ = lay.room
    hits = _landings(lay, "fan")
    on_wall = [p for p in hits if p[0] < 0.05 or p[0] > w - 0.05 or p[1] > d - 0.05]
    assert len(on_wall) == 4, hits
    assert all(p[2] >= venue.HEAD_CLEAR - 0.05 for p in hits), "a wall beam passes over the dancers' heads"
    assert min(p[0] for p in hits) < 0.05 and max(p[0] for p in hits) > w - 0.05, "left wall to right wall"


def test_the_sweeps_reach_the_left_and_right_walls():
    lay = Layout.from_dict(STAGE)
    w = lay.room[0]
    left, right = _landings(lay, "sweep_left"), _landings(lay, "sweep_right")
    assert all(p[0] < w / 3 for p in left) and all(p[0] > 2 * w / 3 for p in right)


def test_crowd_spans_the_floor_and_cross_reaches_its_far_corners():
    lay = Layout.from_dict(STAGE)
    fl = lay.floor
    crowd = [p[0] for p in lay.targets()["crowd"]]
    assert max(crowd) - min(crowd) > 0.8 * fl.w        # before: 0.6 of the floor's width
    cross = lay.targets()["cross"]
    assert all(p[1] == pytest.approx(fl.y + fl.d) for p in cross)


def test_the_moves_swing_much_wider_than_before(monkeypatch):
    def spread(name_a, name_b):
        lay = Layout.from_dict(STAGE)
        pos = lay.positions()
        return max(abs(a[1] - b[1]) for a, b in zip(pos[name_a], pos[name_b]))
    wide = spread("crowd", "fan")
    monkeypatch.setenv("LLANO_LIGHTS_WIDE_MOVES", "0")
    old = spread("crowd", "fan")
    assert wide > 2 * old, (wide, old)   # the verse's glide tilts more than twice as far


def test_the_kill_switch_puts_back_the_floor_only_moves(monkeypatch):
    monkeypatch.setenv("LLANO_LIGHTS_WIDE_MOVES", "0")
    lay = Layout.from_dict(STAGE)
    assert all(p[2] == 0.0 for p in lay.targets()["fan"])


def test_a_table_area_keeps_wall_beams_on_the_dance_floor():
    lay = Layout.from_dict(STAGE)
    lay.zones.append(Zone(0.0, 9.5, 12.1, 3.0, "tables", "Tables"))
    fl = lay.floor
    for p in lay.targets()["fan"] + lay.targets()["sweep_left"]:
        assert p[2] == 0.0 and fl.x <= p[0] <= fl.x + fl.w and fl.y <= p[1] <= fl.y + fl.d, p


def test_a_bar_hung_too_low_to_clear_heads_keeps_wall_beams_on_the_floor():
    low = json.loads(json.dumps(STAGE))
    for b in ("bar1", "bar2"):
        low["fixtures"][b]["z"] = 1.9
    lay = Layout.from_dict(low)
    assert all(p[2] == 0.0 for p in lay.targets()["fan"])


def test_the_named_moves_never_turn_a_head_round_behind_its_bar():
    lay = Layout.from_dict(STAGE)
    for name in ("crowd", "fan", "cross", "sweep_left", "sweep_right"):
        for (b, m, _), (pan, tilt) in zip(lay.all_heads(), lay.positions()[name]):
            assert lay.forward(b, pan, m) == pytest.approx(pan), (name, b, m)
            assert 0.5 <= tilt <= 1.0


# --- the spotlight ---------------------------------------------------------------------------------

def test_a_spotlight_aims_at_chest_height_not_the_floor(monkeypatch):
    lay = Layout.from_dict(STAGE)
    head = lay.heads(1)[0]
    assert lay.spot_target(6.0, 6.0, head) == (6.0, 6.0, 1.5)
    assert lay.spot_target(6.0, 6.0, (0.0, 0.0, 1.7))[2] == pytest.approx(1.2)   # a low bar aims lower
    monkeypatch.setenv("LLANO_LIGHTS_SPOT_HEIGHT", "0")
    assert lay.spot_target(6.0, 6.0, head)[2] == 0.0                            # kill switch: the floor


def _spot_frame(cfg, lay):
    eng = LooksEngine(settings=cfg)
    eng.apply_venue(lay)
    rig = default_rig()
    eng.render(Frame(5.0, 124.0, True, level=0.6, section=Section("verse", 0, 256, 0.6), track_key=7), rig)
    return rig


def test_the_spotlight_look_runs_its_heads_at_full_open_white_and_dips_the_wash(monkeypatch):
    lay = Layout.from_dict(STAGE)
    cfg = contract.normalize({**contract.defaults(), **moments.style("spotlight")})
    rig = _spot_frame(cfg, lay)
    heads = [h for bar in rig.bars for h in bar.movers]
    assert all(h.dim == pytest.approx(1.0) and h.color == 0 and h.gobo == 0 and h.strobe == 0 for h in heads)
    tetra = max(t.dim for t in rig.tetras)
    monkeypatch.setenv("LLANO_LIGHTS_SPOT_BRIGHT", "0")
    old = _spot_frame(cfg, lay)
    assert all(h.dim == pytest.approx(0.6) for bar in old.bars for h in bar.movers)
    assert tetra == pytest.approx(max(t.dim for t in old.tetras) * 0.5)


def _meet(lay, rig, z):
    pts = []
    for b, bar in enumerate(rig.bars):
        for m, h in enumerate(bar.movers):
            o = lay.heads(b + 1)[m]
            d = lay.beam(b + 1, o, h.pan, h.tilt, m)
            t = (z - o[2]) / d[2]
            pts.append((o[0] + d[0] * t, o[1] + d[1] * t))
    cx, cy = sum(p[0] for p in pts) / 4, sum(p[1] for p in pts) / 4
    return max(math.hypot(x - cx, y - cy) for x, y in pts)


def test_the_roaming_spotlight_look_still_meets_on_the_floor():
    """Nobody is under a spot that roams by itself: at chest height its beams would cross the room at face height."""
    lay = Layout.from_dict(STAGE)
    cfg = contract.normalize({**contract.defaults(), **moments.style("spotlight")})
    assert _meet(lay, _spot_frame(cfg, lay), 0.0) < 0.25


# Follow someone at chest height through his layout: test_studio_engine.test_spots_take_the_heads_dim_the_room_and_meet_on_the_floor


def test_follow_someone_dips_the_room_further_by_default():
    assert studio.Studio().spots["room"] == pytest.approx(0.2)
