"""1.16.5: the 11-10 real-lights report on 1.16.4 (heads 2 and 3 still stepped, 1 and 4 were smooth;
heads numbered 1-4 left to right from the floor).

A look that moves every head on the same beat gives the inner heads a far smaller turn than the outer
ones, and an eased move's time grows only with the square root of its size: the outer heads swept over
a few frames while the inner ones landed in one, a twitch, and the inner pan overshot one step and came
back (the jump frame was fed forward as if the target were moving). Now heads that start a move on the
same frame arrive on the same frame (glide `Arrive together`), and a jump from still feeds nothing forward.
"""
from __future__ import annotations

from tools.gigbar_lights import demo_songs
from tools.gigbar_lights.glide import HeadGlide
from tools.gigbar_lights.rig import default_rig
from tools.gigbar_lights.show import Show
from tools.gigbar_lights.venue import LayoutStore

DT = 1 / 40
HB = (23, 24, 29, 30, 63, 64, 69, 70)


def _beat_move(small: float, big: float):
    """Two heads held still, then on one frame head A jumps `big` raw and head B `small`; bytes out."""
    rig, g, out = default_rig(), HeadGlide(), []
    a, b = rig.bars[0].movers[0], rig.bars[1].movers[1]
    for i in range(40):
        jump = i >= 5
        a.pan, a.tilt = 0.4 + (big if jump else 0.0), 0.8
        b.pan, b.tilt = 0.4 + (small if jump else 0.0), 0.8 - (small if jump else 0.0)
        g.apply(rig, i * DT)
        out.append((round(a.pan * 255), round(b.pan * 255), round(b.tilt * 255)))
    return out


def test_heads_that_start_together_land_together():
    out = _beat_move(small=6 / 255, big=22 / 255)
    landed = [next(i for i in range(5, 40) if all(o[k] == out[-1][k] for o in out[i:])) for k in range(3)]
    # The small moves arrive with the big one (within 2 frames: SYNC_MIN_STEPS keeps them from crawling),
    # and none of them in a single frame.
    assert max(landed) - min(landed) <= 2, landed
    assert min(landed) - 5 >= 2, landed


def _show_frames(n: int) -> list:
    """Frame times the way Show renders: 40 Hz due times met on 512-sample audio blocks (23 or 35 ms apart)."""
    ts, now, due = [], 1000.0, 1000.0
    while len(ts) < n:
        if now >= due:
            ts.append(now)
            due += 0.025
        now += 512 / 44100
    return ts


def test_a_jump_from_still_never_overshoots_and_steps_back():
    # 1.16.4 fed the jump frame forward as a target speed: tilt 128 -> 134 -> 136 -> 134.
    for steps in range(4, 14):   # 3 or fewer: the No crawling hold (GATE_STEPS)
        rig, g, out = default_rig(), HeadGlide(), []
        h = rig.bars[0].movers[0]
        for i, t in enumerate(_show_frames(40)):
            h.pan, h.tilt = 0.4, (128 + (steps if i >= 7 else 0)) / 255
            g.apply(rig, t)
            out.append(round(h.tilt * 255))
        assert all(y >= x for x, y in zip(out, out[1:])), (steps, out)
        assert out[-1] == 128 + steps
        assert next(i for i, v in enumerate(out) if v == out[-1]) - 7 <= 4   # alone, still quick


def test_no_head_backs_up_mid_move_in_demo(tmp_path):
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
            back = sum(1 for i in range(2, len(v)) if (v[i] - v[i - 1]) * (v[i - 1] - v[i - 2]) < 0)
            assert back == 0, (song_id, HB[k], back)
