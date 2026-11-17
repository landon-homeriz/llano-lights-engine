"""1.16.3: the 11-09 demo video (1.16.1, Demo, no lights): the heads stepped one at a time, left light
then right light, instead of both moving together in one fluid motion.

Each head axis waited for its own hold-and-move gate (glide.py, 1.15.1), and the two heads of a bar
aim from different spots, so they reached the gate on different frames and took turns. Now a slow
axis starting its short move takes every other due axis with it, and the room picture draws an
ungated, unrounded twin of the glide, so it sweeps instead of stepping.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

from tools.gigbar_lights import demo_songs, rig as rig_mod, show_settings
from tools.gigbar_lights.show import Show
from tools.gigbar_lights.venue import LayoutStore

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
import gigbar_app  # noqa: E402
from tools.gigbar_lights.enttec import NullOutput  # noqa: E402


@pytest.fixture(autouse=True)
def _slow_legs(monkeypatch):
    """These pin how the glide moves a head that crawls (No crawling, Together, Arrive together, Pan in slides),
    which still governs every move under its crawl line. Fluid travel (Llano BL #12400) now runs a slow glide or
    sweep above that line, so the slow legs these build are made with it off; test_heads_face_and_flow_12400.py
    pins the fluid legs."""
    monkeypatch.setenv("LLANO_LIGHTS_FLUID_TRAVEL", "0")

HB = gigbar_app.HEAD_BYTES


def _demo(tmp_path, song_id="groove", secs=45.0):
    """The app's Demo with no lights: the default room, the song fed like the window does, 40 Hz."""
    song = next(s for s in demo_songs.load() if s.id == song_id)
    show = Show(analyze=False)
    show.set_venue(LayoutStore(tmp_path / "profile").current())
    feed = demo_songs.SongFeed(show, song, None)
    now, due, rows, pics = 1000.0, 1000.0, [], []
    while now < 1000.0 + secs:
        feed(now)
        if now >= due:
            u = show.render(now)
            ps = show.picture_slots()
            rows.append([u[i] for i in HB])
            pics.append([ps.get(i, u[i]) for i in HB])
            due += 0.025
        now += 512 / 44100
    return rows, pics


def _starts(rows, k):
    """Frames where a head axis starts a move (after at least 3 still frames)."""
    ch = [i for i in range(1, len(rows)) if rows[i][k] != rows[i - 1][k]]
    return [c for j, c in enumerate(ch) if j == 0 or c - ch[j - 1] > 2]


@pytest.mark.parametrize("song_id", ["groove", "drop"])
def test_a_bars_two_heads_never_take_turns(tmp_path, song_id):
    rows, _ = _demo(tmp_path, song_id)
    for right, left in ((0, 2), (1, 3), (4, 6), (5, 7)):   # pan, tilt of each bar: head 1 vs head 2
        a, b = _starts(rows, right), _starts(rows, left)
        solo = sorted([(x, "R") for x in a if not any(abs(x - y) <= 1 for y in b)] +
                      [(y, "L") for y in b if not any(abs(x - y) <= 1 for x in a)])
        turns = [(p, q) for p, q in zip(solo, solo[1:]) if p[1] != q[1] and q[0] - p[0] <= 40]
        assert not turns, f"head axes {right}/{left} alternated at frames {turns[:5]}"


def test_tilt_moves_start_in_the_same_frame(tmp_path):
    rows, _ = _demo(tmp_path)
    for right, left in ((1, 3), (5, 7)):
        a, b = _starts(rows, right), _starts(rows, left)
        assert a and len(a) == len(b) and all(abs(x - y) <= 1 for x, y in zip(a, b))


def test_moving_together_never_flickers_a_byte_back_and_forth(tmp_path):
    rows, _ = _demo(tmp_path)
    for k in range(len(HB)):
        d = [rows[i][k] - rows[i - 1][k] for i in range(1, len(rows))]
        assert not [i for i in range(1, len(d)) if d[i] * d[i - 1] < 0 and abs(d[i]) <= 1 and abs(d[i - 1]) <= 1]


def test_the_picture_sweeps_and_stays_with_the_heads(tmp_path):
    rows, pics = _demo(tmp_path)
    for k in range(len(HB)):
        bytes_moved = sum(rows[i][k] != rows[i - 1][k] for i in range(1, len(rows)))
        pic_moved = sum(abs(pics[i][k] - pics[i - 1][k]) > 1e-6 for i in range(1, len(pics)))
        assert pic_moved > 5 * bytes_moved                  # a sweep, where the bytes hold and hop
    assert max(abs(p - b) for pr, br in zip(pics, rows) for p, b in zip(pr, br)) <= gigbar_app.PIC_SLACK


def test_head_picture_lands_where_render_puts_the_byte_through_the_head_settings():
    cfg = copy.deepcopy(show_settings.current()["rig"])
    cfg["heads"]["bar1"]["swap_heads"] = True
    cfg["heads"]["bar1"]["head1"]["pan_invert"] = True
    cfg["heads"]["bar2"]["head2"]["pan_tilt_swap"] = True
    cfg["heads"]["bar2"]["head1"]["tilt_invert"] = True
    rig = rig_mod.default_rig()
    vals = {(0, 0): (0.10, 0.20), (0, 1): (0.30, 0.40), (1, 0): (0.55, 0.65), (1, 1): (0.75, 0.85)}
    for (b, m), (p, t) in vals.items():
        rig.bars[b].movers[m].pan, rig.bars[b].movers[m].tilt = p, t
    u = rig.render(cfg)
    pic = rig_mod.head_picture(vals, cfg)
    assert sorted(pic) == sorted(HB)
    assert all(abs(pic[i] - u[i]) <= 0.5 for i in HB)


def test_the_trail_carries_the_picture_and_the_motion_report_only_the_bytes(tmp_path):
    p = gigbar_app.Preview("demo", LayoutStore(tmp_path / "profile"))
    try:
        tee = gigbar_app.TeeOutput(NullOutput(), p, picture=lambda: {i: 100.4 for i in HB})
        u = bytearray(512)
        for i in HB:
            u[i] = 101
        tee.send(bytes(u))
        tee.send(bytes(u))
        row = list(p.trail)[-1]
        assert row[1:9] == [101] * 8 and row[9:] == [100.4] * 8
        far = gigbar_app.TeeOutput(NullOutput(), p, picture=lambda: {i: 50.0 for i in HB})
        far.send(bytes(u))                                   # a probe moved the head: draw the byte
        assert list(p.trail)[-1][9:] == [101] * 8
        app = gigbar_app.App.__new__(gigbar_app.App)
        app.preview, app.running = p, "demo"
        m = app._motion()
        assert m and all(len(r) == 1 + len(HB) for r in m["trail"])
    finally:
        p.close()


PAGE = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const body = src.slice(src.indexOf('const HEAD_AT'), src.indexOf('function frame()'));
const {keepTrail, smoothHeads} = new Function(body + '; return {keepTrail, smoothHeads}')();
// The bytes hold at 10 then hop to 13; the picture's columns climb 0.1 a frame. The page draws the picture's.
const rows = [];
for (let i = 0; i < 16; i++) rows.push([1000 + 25 * i, ...Array(8).fill(i < 12 ? 10 : 13), ...Array(8).fill(10 + 0.1 * i)]);
keepTrail(rows, 1000 + 25 * 15, 25 * 15);
const out = [];
for (let here = 25 * 6; here <= 25 * 15; here += 25) out.push(smoothHeads(new Array(192).fill(0), here)[23]);
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(__import__("shutil").which("node") is None, reason="node is not installed here")
def test_the_page_draws_the_pictures_columns_when_a_row_has_them():
    import json
    import subprocess
    page = Path(gigbar_app.__file__).with_name("preview.html")
    res = subprocess.run(["node", "-e", PAGE, str(page)], capture_output=True, text=True, timeout=30, check=True)
    pans = json.loads(res.stdout)
    steps = [b - a for a, b in zip(pans, pans[1:])]
    assert all(0 < s <= 0.11 for s in steps), pans           # an even sweep, not hold-then-hop
