"""1.16.7: his 11-09 recording 20261109_201341 (heads 1-4 left to right from the dance floor).
Head 4 had been nudged onto the center dot from the low side of straight down (tilt 49) while its model
kept the high side's tilt direction: Straight down pointed it out into the room, Middle of the floor
aimed it behind the bar, and the picture tilted the other way from the head while he nudged it. And
Line up my lights turned heads 1-3 half a turn and swung them through straight down every time it
started, while head 4 barely moved: rest sat on the other side of straight down from their centers.
"""
from __future__ import annotations

import math

from tools.gigbar_lights.show import Show
from tools.gigbar_lights.venue import Layout, LayoutStore, rest_pan

OLD_HEAD4 = {"center": [0.62735, 0.19216], "pan_invert": True}   # his saved head 4 during the recording


def _his(tmp_path, head4: dict = OLD_HEAD4) -> Layout:
    d = LayoutStore(tmp_path / "p").current().to_dict()
    d["fixtures"]["bar1"]["cal"] = [{"center": [0.34098, 0.84686]}, {"center": [0.38431, 0.86676]}]
    d["fixtures"]["bar2"]["cal"] = [head4, {"center": [0.32245, 0.86382]}]
    return Layout.from_dict(d)


def _b(v: float) -> int:
    return round(v * 255)


def test_a_center_saved_below_straight_down_tilts_the_way_the_head_does(tmp_path):
    lay = _his(tmp_path)
    assert lay.cal_problem(2, 0) is None
    pos = lay.positions()
    k4 = [k for k, (b, m, _) in enumerate(lay.all_heads()) if (b, m) == (2, 0)][0]
    k3 = [k for k, (b, m, _) in enumerate(lay.all_heads()) if (b, m) == (2, 1)][0]
    # Straight down is the fixture's (tilt 128), not level out into the room (it was tilt 0).
    assert abs(_b(pos["down"][k4][1]) - 128) <= 12
    # Middle of the floor: on the same side as head 3, not behind the bar.
    assert abs(_b(pos["center"][k4][0]) - _b(pos["center"][k3][0])) <= 20
    assert abs(_b(pos["center"][k4][1]) - _b(pos["center"][k3][1])) <= 20
    # His hand re-line-up after the recording landed head 4 at (74, 208); the old center now says the same.
    c = lay.cal(2, 0)
    assert abs(_b(c.center[0]) - 74) <= 3 and abs(_b(c.center[1]) - 208) <= 20


def test_the_picture_tilts_the_way_the_nudged_head_does(tmp_path):
    lay = _his(tmp_path)
    pan, tilt = OLD_HEAD4["center"]

    def off(t: float) -> float:   # degrees off straight down the picture draws
        return math.degrees(math.acos(-lay.beam_of(2, 0, pan, t)[2]))
    # On the low side of straight down (tilt < 0.5) raising the tilt brings the beam toward straight down.
    assert off(tilt + 10 / 255) < off(tilt)


def test_rest_is_on_the_side_the_heads_face_their_spots_from(tmp_path):
    lay = _his(tmp_path)
    pan, tilt = lay.rest_pose()
    assert abs(_b(pan) - _b(rest_pan(540.0) - 1 / 3)) <= 1 and tilt == 1.0
    # A rig with no line-up keeps every earlier version's rest.
    assert LayoutStore(tmp_path / "q").current().rest_pose() == (rest_pan(540.0), 0.0)


def test_line_up_my_lights_starts_without_spinning(tmp_path):
    lay = _his(tmp_path)
    show = Show(analyze=False)
    show.set_venue(lay)
    show.looks.overrides.lineup = (0, "center")
    first = None
    travel = {}
    now = 1000.0
    for _ in range(160):   # 4 s at 40 Hz
        show.render(now)
        cur = {k: (ax[0].pos, ax[1].pos) for k, ax in show.glide._heads.items()}
        if first is None:
            first = {k: show.glide.rest_pose() for k in cur}
        for k, (p, t) in cur.items():
            tr = travel.setdefault(k, [0.0, 0.0, cur[k]])
            tr[0] += abs(p - tr[2][0]); tr[1] += abs(t - tr[2][1]); tr[2] = (p, t)
        now += 0.025
    for k, (pan_moved, tilt_moved, _) in travel.items():
        # was ~85 pan steps (half a turn) and ~216 tilt steps through straight down for heads 1-3
        assert _b(pan_moved) <= 25 and _b(tilt_moved) <= 70, (k, _b(pan_moved), _b(tilt_moved))


def test_stop_parks_at_the_layout_rest(tmp_path):
    lay = _his(tmp_path)
    show = Show(analyze=False)
    show.set_venue(lay)
    show.looks.overrides.lineup = (0, "center")
    now = 1000.0
    for _ in range(80):
        show.render(now); now += 0.025
    show.looks.overrides.lineup = None
    for _ in range(200):
        show.park(now); now += 0.025
        if show.glide.parked():
            break
    assert show.glide.parked()
    assert show.glide.parked(lay.rest_pose())


def test_heads_hold_their_aim_through_the_dark(tmp_path):
    """Hold through the dark (his clip 20261109_190016): the dark beat before a drop and a silence
    parked every head at pan/tilt 0.5, so each swung toward straight down and back as the drop hit."""
    from tools.gigbar_lights import demo_songs
    lay = _his(tmp_path, {"center": [0.2902, 0.81569]})
    dark = travel = 0
    for song in demo_songs.load():
        show = Show(analyze=False)
        show.set_venue(lay)
        feed = demo_songs.SongFeed(show, song, None)
        now, due, prev = 1000.0, 1000.0, None
        while now < 1180 and dark < 40:
            feed(now)
            if now >= due:
                show.render(now)
                due += 0.025
                heads = [m for b in show.rig.bars for m in b.movers]
                cur = [(m.pan * 255, m.tilt * 255) for m in heads]
                if prev and all(m.dim == 0 for m in heads):
                    dark += 1
                    travel += sum(abs(a - c) + abs(b - d) for (a, b), (c, d) in zip(cur, prev))
                prev = cur
            now += 512 / 44100
    assert dark >= 20
    assert travel <= 1.0, travel   # was thousands of DMX steps on his layout
