"""1.16.4: his 11-09 reports on 1.16.3 with real lights (heads numbered 1-4 left to right from the floor).

1. Heads 1 and 4 glide, heads 2 and 3 still step: a head pulled along by Together moved as soon as it
   was half a DMX step behind, so a slow head hopped one step at a time. Now only when its byte would
   change by 2 or more.
2. Head 4 spins about a full turn at power-up and going to rest, and sounds like it hits a hard stop:
   its saved center sat on the pan twin near the end of the 540 degree range while rest was pan 0 at
   the other end. Now a saved center sits on the twin nearest DMX middle, rest is straight ahead on
   the twin nearest middle, and Stop's last frame keeps the heads where they parked.
3. After Line up my lights head 4 sat backwards: a head reaches a floor spot turned toward it or turned
   round and tilted over, and his was saved the other way round from the other three. Now it is
   turned to face its spots the way the rig's other heads do, every beam pointing where it did.
"""
from __future__ import annotations

import math
import random

import pytest

from tools.gigbar_lights import __main__ as gl, demo_songs, venue
from tools.gigbar_lights.show import Show
from tools.gigbar_lights.venue import HeadCal, Layout, LayoutStore, mid_twin, rest_pan
from test_light_doctor_11615 import preview  # noqa: F401  (the app fixture)


@pytest.fixture(autouse=True)
def _slow_legs(monkeypatch):
    """These pin how the glide moves a head that crawls (No crawling, Together, Arrive together, Pan in slides),
    which still governs every move under its crawl line. Fluid travel (Llano BL #12400) now runs a slow glide or
    sweep above that line, so the slow legs these build are made with it off; test_heads_face_and_flow_12400.py
    pins the fluid legs."""
    monkeypatch.setenv("LLANO_LIGHTS_FLUID_TRAVEL", "0")

TWIN = 360.0 / 540.0
HB = (23, 24, 29, 30, 63, 64, 69, 70)   # every head's pan and tilt bytes, default rig


def _fitted(tmp_path) -> Layout:
    """The default room with every head calibrated exactly from the guessed model (Light doctor taps)."""
    lay = LayoutStore(tmp_path / "profile").current()
    for b in (1, 2):
        for m in (0, 1):
            o, samples = lay.heads(b)[m], []
            for p, t in lay.doctor_poses(b, m):
                d = lay.beam(b, o, p, t, m)
                if d[2] < -0.05:
                    k = -o[2] / d[2]
                    samples.append((p, t, (o[0] + d[0] * k, o[1] + d[1] * k)))
            lay.spots[f"bar{b}"].cal[m], _ = lay.fit_taps(b, m, samples)
    return lay


def _dirs(lay, b, m, c, poses):
    out = []
    for p, t in poses:
        h, o = (math.radians(a) for a in lay._cal_angles(b, m, c, p, t))
        out.append((math.sin(o) * math.sin(h), math.sin(o) * math.cos(h), -math.cos(o)))
    return out


def test_slow_inner_heads_make_no_lone_one_step_ticks(tmp_path):
    for song_id in ("groove", "drop", "slow"):
        song = next(s for s in demo_songs.load() if s.id == song_id)
        show = Show(analyze=False)
        show.set_venue(LayoutStore(tmp_path / song_id).current())
        feed = demo_songs.SongFeed(show, song, None)
        now, due, rows = 1000.0, 1000.0, []
        while now < 1060.0:
            feed(now)
            if now >= due:
                u = show.render(now)
                rows.append([u[i] for i in HB])
                due += 0.025
            now += 512 / 44100
        for k in range(len(HB)):
            v = [r[k] for r in rows]
            lone = sum(1 for i in range(2, len(v) - 1)
                       if abs(v[i] - v[i - 1]) == 1 and v[i - 1] == v[i - 2] and v[i + 1] == v[i])
            assert lone == 0, (song_id, HB[k], lone)


def test_a_center_saved_a_turn_up_sits_on_the_twin_nearest_middle_and_points_the_same_way(tmp_path):
    assert mid_twin(0.95, TWIN) == 0.95 - TWIN and mid_twin(0.03, TWIN) == 0.03 + TWIN
    assert rest_pan(540.0) == TWIN
    lay = _fitted(tmp_path)
    c = lay.spots["bar2"].cal[0]
    high = HeadCal.from_dict({**c.to_dict(), "center": [mid_twin(c.center[0], TWIN) + (TWIN if c.center[0] < 1 / 3 else -TWIN), c.center[1]]}, "x")
    assert high.center == c.center   # whichever way he nudged it, the same twin is kept
    swapped = HeadCal.from_dict({"center": [0.4, 0.97], "swap": True}, "x")   # the pan motor is the second channel
    assert swapped.center == (0.4, mid_twin(0.97, TWIN))


def test_every_aim_of_a_head_saved_near_its_end_stop_stays_well_inside_the_range(tmp_path):
    lay = _fitted(tmp_path)
    d = lay.to_dict()
    c = d["fixtures"]["bar2"]["cal"][0]
    c["center"] = [max((v for v in (c["center"][0] - TWIN, c["center"][0], c["center"][0] + TWIN) if 0 <= v <= 1),
                       key=lambda v: abs(v - 0.5)), c["center"][1]]   # saved on the twin by an end stop
    lay = Layout.from_dict(d)
    fl, pans = lay.floor, []
    for i in range(21):
        for j in range(21):
            target = (fl.x + fl.w * i / 20, fl.y + fl.d * j / 20, 0.0)
            pans.append(lay.aim(2, lay.heads(2)[0], target, 0)[0])
    assert 0.15 < min(pans) and max(pans) < 0.85
    # neighbouring spots never pick a different motor turn (no 360 swing as a spot sweeps the floor)
    assert max(abs(a - b) for a, b in zip(pans, pans[1:]) if abs(a - b) > 0) < 0.2


def test_stop_parks_every_head_the_short_way_and_leaves_it_there(tmp_path):
    lay = _fitted(tmp_path)
    show = Show(analyze=False)
    show.set_venue(lay)
    show.looks.overrides.lineup = (0, "center")
    t = 0.0
    for _ in range(160):
        show.render(t)
        t += 0.025
    sent = []

    class Out:
        def send(self, u):
            sent.append(bytes(u))
    clock = [t]
    n = gl.park(show, Out(), clock=lambda: clock[0], sleep=lambda dt: clock.__setitem__(0, clock[0] + dt))
    rest = lay.rest_pose()   # straight ahead, held the way round his heads face their spots (1.16.7)
    assert show.glide.parked(rest) and show.glide.parked()
    pans = [f[63] for f in sent]
    assert abs(pans[-1] - round(rest[0] * 255)) <= 1 and sum(abs(a - b) for a, b in zip(pans, pans[1:])) < 128
    final = show.park(clock[0])   # what _run_loop sends last: the parked frame, never all zero
    assert n and final[63] == sent[-1][63] and final[23] == sent[-1][23]


def test_a_head_saved_backwards_is_turned_round_to_face_its_spots_like_the_others(tmp_path):
    lay = _fitted(tmp_path)
    good = lay.spots["bar2"].cal[0]
    _, oc = lay._center_angles(2, 0)
    st = -1 if good.tilt_invert else 1
    back = HeadCal((mid_twin(good.center[0] + TWIN / 2 if good.center[0] < 0.5 else good.center[0] - TWIN / 2, TWIN),
                    good.center[1] - 2 * st * oc / 180.0), {}, good.pan_invert, not good.tilt_invert)
    random.seed(4)
    poses = [(random.random(), random.random()) for _ in range(200)]
    assert max(math.dist(a, b) for a, b in zip(_dirs(lay, 2, 0, back, poses), _dirs(lay, 2, 0, good, poses))) < 1e-9
    lay.spots["bar2"].cal[0] = back
    assert lay.cal(2, 0).tilt_invert == good.tilt_invert   # three heads agree: the fourth follows them
    assert lay.cal_problem(2, 0) is None
    spot = (lay.floor.cx, lay.floor.cy, 0.0)
    lay.spots["bar2"].cal[0] = good
    want = lay.aim(2, lay.heads(2)[0], spot, 0)
    lay.spots["bar2"].cal[0] = back
    got = lay.aim(2, lay.heads(2)[0], spot, 0)
    assert abs(got[0] - want[0]) < 2 / 255 and abs(got[1] - want[1]) < 2 / 255


def test_line_up_says_so_and_starts_from_the_guess_when_a_saved_center_cant_be_used(tmp_path):
    lay = _fitted(tmp_path)
    c = lay.spots["bar2"].cal[0]
    lay.spots["bar2"].cal[0] = HeadCal((c.center[0], c.center[1] - 0.25), {}, c.pan_invert, c.tilt_invert)   # 45 degrees off
    assert lay.cal_problem(2, 0) == "its saved line-up doesn't match how the head tilts"
    assert all(lay.cal_problem(b, m) is None for b, m in ((1, 0), (1, 1), (2, 1)))
    # its next Line up refits from the guess, not the bad center's turn directions
    spot = (lay.floor.cx, lay.floor.cy)
    guess = Layout.from_dict(lay.to_dict())
    guess.spots["bar2"].cal[0] = HeadCal()   # what Line up starts it from (gigbar_app spotaim)
    pose = lay.facing_pose(*guess.aim(2, guess.heads(2)[0], (*spot, 0.0), 0))
    cal, _ = lay.fit_taps(2, 0, [(*pose, spot)])
    assert venue.Layout.cal_problem(_with(lay, cal), 2, 0) is None


def _with(lay, cal):
    lay.spots["bar2"].cal[0] = cal
    return lay


def test_line_up_spot_names_a_center_it_cant_use_and_aims_that_head_by_the_guess(preview):
    from test_light_doctor_11615 import _post
    lay = preview.layout
    for b in (1, 2):   # three good heads, then head 4's center 45 degrees off how the head tilts
        for m in (0, 1):
            pose = lay.aim(b, lay.heads(b)[m], lay.ref_target("center"), m)
            lay.spots[f"bar{b}"].cal[m] = HeadCal(pose, {}, venue._guess_turn(lay.spots[f"bar{b}"]) < 0)
    c = lay.spots["bar2"].cal[0]
    lay.spots["bar2"].cal[0] = HeadCal((c.center[0], c.center[1] - 0.25), {}, c.pan_invert)
    spot = (lay.floor.cx, lay.floor.cy)
    code, body = _post(preview, {"action": "spotaim", "layout": lay.to_dict(), "target": {"x": spot[0], "y": spot[1]}})
    assert code == 200, body
    assert set(body["cal_problems"]) == {"2:0"}
    guess = Layout.from_dict(lay.to_dict())
    guess.spots["bar2"].cal[0] = HeadCal()
    want = guess.facing_pose(*guess.aim(2, guess.heads(2)[0], (*spot, 0.0), 0))
    assert body["poses"]["2:0"] == [round(v, 5) for v in want]
