"""Llano BL #12400: the 11-14 video on 1.26.4: after the update the heads were reversed again
and jerky again, pausing mid-sweep instead of sweeping fluidly.

1. Reversed. At 9:47 PM he pressed Draw my room with his stage numbers. It redrew the room with the GigBARs on the
   stage corners and no line-up, so every head fell back to the guessed model, which points head 1 of each bar
   half a turn the wrong way on his rig (pan 0.677 where his lined-up heads need about 0.33 for the middle of the
   floor); Line up my lights then aimed them at the wall. The guess has done that since 1.14.3; his saved line-up
   hid it. Now his line-up comes along (`Layout.carry_lineup`): each head turns on its bar the way he lined it up.
   His rooms: his_room_lined_up_12400.json (settings rev 80, the small room he lined up), his_stage_room_12400.json
   (rev 81, the Stage room he drew, saved with no line-up).

2. Jerky. The 1.16.9 smoothing never changed (the bytes a verse glide sends are the same from 1.16.9 to 1.27.0).
   A slow leg crawls under glide.CRAWL_STEPS, so the glide holds it and catches up in short moves: a stop every
   second or so half way across, more in the Stage room (bars higher, floor farther). Fluid travel (looks.py) runs
   such a leg at an even pace the glide tracks and rests at the ends. The DMX capture below is what the laptop
   sends the heads, 40 frames a second through the looks engine and the glide, during a verse.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.gigbar_lights import looks
from tools.gigbar_lights.glide import HeadGlide
from tools.gigbar_lights.looks import FIGURES, Frame, LooksEngine
from tools.gigbar_lights.rig import default_rig
from tools.gigbar_lights.show_script import Section
from tools.gigbar_lights.venue import FT, Layout, stage_layout

HERE = Path(__file__).parent
LINED = json.loads((HERE / "his_room_lined_up_12400.json").read_text())
STAGE = json.loads((HERE / "his_stage_room_12400.json").read_text())
HEADS = [(b, m) for b in (1, 2) for m in (0, 1)]


def _no_lineup(d: dict) -> dict:
    d = copy.deepcopy(d)
    for b in ("bar1", "bar2"):
        d["fixtures"][b].pop("cal", None)
    return d


def _center_aims(lay: Layout) -> dict:
    fl = lay.floor
    return {(b, m): lay.aim(b, lay.heads(b)[m], (fl.cx, fl.cy, 0.0), m) for b, m in HEADS}


def _lands_toward_center(lay: Layout, b: int, m: int) -> float:
    """Degrees between where head m's center aim points (seen from above) and the floor's center."""
    import math
    h, fl = lay.heads(b)[m], lay.floor
    p, t = lay.aim(b, h, (fl.cx, fl.cy, 0.0), m)
    d = lay.beam_of(b, m, p, t)
    want = math.degrees(math.atan2(fl.cx - h[0], fl.cy - h[1]))
    got = math.degrees(math.atan2(d[0], d[1]))
    return abs((got - want + 180) % 360 - 180)


# --- 1. the heads face the floor after Draw my room -----------------------------------------------

def test_without_a_lineup_the_guess_now_turns_every_head_like_his_lined_up_heads():
    # the finding, fixed in 1.31.1 (PM #23745): his lined-up heads sit near pan 0.33 for the floor's middle; until
    # 1.31.1 the guess sent head 1 of each bar about half a turn away (a 540-degree pan: 0.33 is 180 degrees)
    lined, guess = _center_aims(Layout.from_dict(LINED)), _center_aims(Layout.from_dict(_no_lineup(LINED)))
    for b, m in HEADS:
        assert abs(guess[(b, m)][0] - lined[(b, m)][0]) * 540 < 40, (b, m)


def test_carrying_his_lineup_onto_the_same_room_keeps_every_aim_within_a_few_steps():
    src, dst = Layout.from_dict(LINED), Layout.from_dict(_no_lineup(LINED))
    assert sorted(dst.carry_lineup(src)) == HEADS
    fl = src.floor
    for b, m in HEADS:
        for x, y in ((fl.cx, fl.cy), (fl.x + 0.5, fl.y + 0.5), (fl.x + fl.w - 0.5, fl.y + fl.d - 0.5)):
            a, c = src.aim(b, src.heads(b)[m], (x, y, 0.0), m), dst.aim(b, dst.heads(b)[m], (x, y, 0.0), m)
            # the old room's spots (anchors) stay behind, so the carried model can differ a little
            assert max(abs(a[0] - c[0]), abs(a[1] - c[1])) * 255 <= 6, (b, m, x, y, a, c)


@pytest.mark.parametrize("room", ["his Stage room", "Draw my room 20 x 22 at 10 ft"])
def test_his_lineup_carried_onto_the_stage_room_faces_every_head_at_the_floor(room):
    dst = Layout.from_dict(STAGE) if room == "his Stage room" else stage_layout(20 * FT, 22 * FT, 10 * FT)
    assert sorted(dst.carry_lineup(Layout.from_dict(LINED))) == HEADS
    for b, m in HEADS:
        assert dst.cal_problem(b, m) is None
        assert _lands_toward_center(dst, b, m) < 2.0, (b, m)
        # the pose the real head needs: near his lined-up center pans, never half a turn away
        p, _ = _center_aims(dst)[(b, m)]
        assert 0.2 < p < 0.5, (b, m, p)
    # saved and read back, the same aims (the laptop saves it, then reopens it)
    back = Layout.from_dict(dst.to_dict())
    assert _center_aims(back) == _center_aims(dst)


def test_the_carried_lineup_keeps_no_spots_from_the_old_room_and_one_spot_keeps_the_turn_directions():
    dst = Layout.from_dict(STAGE)
    dst.carry_lineup(Layout.from_dict(LINED))
    assert all(not dst.spots[f"bar{b}"].cal[m].anchors for b, m in HEADS)
    before = {(b, m): (dst.cal(b, m).pan_invert, dst.cal(b, m).tilt_invert) for b, m in HEADS}
    fl = dst.floor
    spot = (fl.cx, fl.cy + 1.0)
    samples = [(b, m, *dst.aim(b, dst.heads(b)[m], (*spot, 0.0), m), spot) for b, m in HEADS]
    dst.converge(samples)
    assert {(b, m): (dst.cal(b, m).pan_invert, dst.cal(b, m).tilt_invert) for b, m in HEADS} == before
    assert all(_lands_toward_center(dst, b, m) < 3.0 for b, m in HEADS)


def test_a_room_already_lined_up_is_never_overwritten():
    dst = Layout.from_dict(LINED)
    was = [dst.spots[f"bar{b}"].cal[m].to_dict() for b, m in HEADS]
    assert dst.carry_lineup(Layout.from_dict(_no_lineup(LINED))) == []
    assert dst.carry_lineup(Layout.from_dict(LINED)) == []
    assert [dst.spots[f"bar{b}"].cal[m].to_dict() for b, m in HEADS] == was


class _Req:
    def __init__(self, body: dict):
        import io
        raw = json.dumps(body).encode()
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = io.BytesIO(raw)


def _app():
    import sys
    sys.path.insert(0, str(HERE.parents[1] / "tools/gigbar_lights/windows/src"))
    import gigbar_app
    return gigbar_app


@pytest.mark.parametrize("from_room", ["playing now", "saved, another room playing"])
def test_draw_my_room_on_the_laptop_brings_his_lineup_along(tmp_path, from_room):
    # the 9:47 PM press: his lined-up room in use, then Stage setup with his three numbers
    from tools.gigbar_lights.venue import LayoutStore
    store = LayoutStore(tmp_path)
    store.save(Layout.from_dict(LINED))
    store.use(LINED["name"] if from_room == "playing now" else "small-room-front")
    pv = _app().Preview("", store)
    try:
        code, out = pv.layout_post(_Req({"action": "stage", "stage_w": 20 * FT, "floor_d": 22 * FT, "bar_h": 10 * FT}))
        assert code == 200 and out["carried"] == 4, out.get("error")
        for b, m in HEADS:
            assert _lands_toward_center(pv.layout, b, m) < 2.0, (b, m)
        assert all(c.get("center") for b in ("bar1", "bar2") for c in out["layout"]["fixtures"][b]["cal"])
    finally:
        pv.close()


def test_draw_my_room_with_no_lineup_anywhere_draws_the_room_as_before(tmp_path):
    from tools.gigbar_lights.venue import LayoutStore
    pv = _app().Preview("", LayoutStore(tmp_path))
    try:
        code, out = pv.layout_post(_Req({"action": "stage", "stage_w": 20 * FT, "floor_d": 22 * FT, "bar_h": 10 * FT}))
        assert code == 200 and out["carried"] == 0
        assert out["layout"] == _app().layout_payload(stage_layout(20 * FT, 22 * FT, 10 * FT))
    finally:
        pv.close()


# --- 2. the heads sweep without stopping half way ---------------------------------------------------

def _capture(layout: dict, kind: str = "verse", secs: float = 40.0, bpm: float = 124.0, move=None):
    """What the laptop sends the four heads, 40 frames a second: the looks engine, then the glide (show.render's
    order). Returns the targets the engine asked for and the DMX bytes per frame, (pan, tilt) per head."""
    eng, rig, g = LooksEngine(), default_rig(), HeadGlide()
    eng.apply_venue(Layout.from_dict(layout))
    sec = Section(kind, 0, 100000, 1.0)
    raw, out = [], []
    for i in range(int(secs * 40)):
        now = i / 40
        f = Frame(now * bpm / 60, bpm, True, level=0.6, section=sec, track_key=7, now=now)
        if move:
            eng._move(f, rig, move, 0.0)
        else:
            eng.render(f, rig)
        raw.append([(h.pan, h.tilt) for bar in rig.bars for h in bar.movers])
        g.apply(rig, now, snap=eng.move_shape == "snap", figure=eng.move_shape in FIGURES)
        out.append([(round(h.pan * 255), round(h.tilt * 255)) for bar in rig.bars for h in bar.movers])
    return raw[80:], out[80:]


def _mid_sweep_stops(out: list, k: int, frames: int = 8) -> list:
    """Runs of `frames` or more (0.2 s) where head k's pan and tilt bytes both stand still while it is between
    the two ends of its sweep (not resting at an end, which Fluid travel does on purpose)."""
    tilt = [o[k][1] for o in out]
    pan = [o[k][0] for o in out]
    lo, hi = min(tilt), max(tilt)
    stops, run = [], 0
    for i in range(1, len(out)):
        if pan[i] == pan[i - 1] and tilt[i] == tilt[i - 1] and lo + 2 < tilt[i] < hi - 2:
            run += 1
        else:
            if run >= frames:
                stops.append((i - run, run))
            run = 0
    return stops


@pytest.mark.parametrize("room", ["small room lined up", "Stage room, line-up carried"])
def test_a_verse_sweep_sends_pan_and_tilt_that_never_stop_half_way(room):
    if room == "small room lined up":
        layout = LINED
    else:
        dst = Layout.from_dict(STAGE)
        dst.carry_lineup(Layout.from_dict(LINED))
        layout = dst.to_dict()
    _, out = _capture(layout)
    for k in range(4):
        assert not _mid_sweep_stops(out, k), (room, k + 1, _mid_sweep_stops(out, k)[:5])
        tilt = [o[k][1] for o in out]
        assert max(tilt) - min(tilt) >= 8   # it really sweeps: the test can't pass on a head held still


def test_the_kill_switch_brings_back_the_stops(monkeypatch):
    # the regression guard's teeth: without Fluid travel the same verse stops half way, as 1.27.0 did
    monkeypatch.setenv("LLANO_LIGHTS_FLUID_TRAVEL", "0")
    _, out = _capture(LINED)
    assert any(_mid_sweep_stops(out, k) for k in range(4))


def test_every_head_starts_each_leg_together_and_its_beam_travels_in_one_run():
    # his saved glide (booth to crowd, 32 beats): each head's beam moves as one run per leg, never a string of
    # hops; a smaller axis may land in a couple of short moves while the other carries the beam
    mv = {"shape": "glide", "from": "booth", "to": "crowd", "size": 0.5, "beats": 32, "spread": "mirror"}
    _, out = _capture(LINED, move=mv, secs=64.0)
    starts = []
    for k in range(4):
        ch = [i for i in range(1, len(out)) if out[i][k] != out[i - 1][k]]
        runs = [c for j, c in enumerate(ch) if j == 0 or c - ch[j - 1] > 6]   # a new run after 0.15 s still
        assert len(runs) <= 5, (k + 1, runs)   # 62 s of 32-beat legs at 124 BPM: 4 legs, one run each
        starts.append(runs[0])
    assert max(starts) - min(starts) <= 4, starts   # all heads set off within a tenth of a second


@pytest.mark.parametrize("shape", ["glide", "sweep"])
def test_fluid_travel_keeps_both_ends_and_the_beats(shape):
    # the same two spots, reached on the same beats: only how the head gets between them changes
    pa, pb = (0.4, 0.6), (0.5, 0.9)
    eng = LooksEngine()
    eng.positions = {"home": [pa, pa], "a": [pa, pa], "b": [pb, pb]}
    mv = {"shape": shape, "from": "a", "to": "b", "size": 0.5, "beats": 16, "spread": "parallel"}
    ends = (0.0, 16.0) if shape == "glide" else (-8.0, 8.0)
    for q in (1.0, 0.2):
        got = [eng._head(mv, 0, beat, 0.0, q=q) for beat in ends]
        assert got[0] == pytest.approx(pa) and got[1] == pytest.approx(pb), (shape, q, got)


def test_a_leg_already_fast_plays_byte_for_byte_as_before(monkeypatch):
    mv = {"shape": "sweep", "from": "booth", "to": "fan", "size": 0.5, "beats": 4, "spread": "mirror"}
    new = _capture(LINED, move=mv, secs=10.0)[1]
    monkeypatch.setenv("LLANO_LIGHTS_FLUID_TRAVEL", "0")
    assert _capture(LINED, move=mv, secs=10.0)[1] == new
