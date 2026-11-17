"""BL #11615: the room picture's beams glide like the real heads instead of jumping once per poll.

The page polled /state every 30 ms and drew whatever one 40 Hz frame it caught, so a slow
sweep stepped and stuttered on screen. Now every frame sent leaves its head bytes, stamped,
in a short trail that /state returns; the page plays the trail back a little late and eases
pan/tilt between real frames. The playback runs the page's own keepTrail/smoothHeads in node
(the GitHub runner has it) and skips where node is missing.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
import gigbar_app  # noqa: E402
from tools.gigbar_lights.enttec import NullOutput  # noqa: E402
from tools.gigbar_lights.venue import LayoutStore  # noqa: E402

PREVIEW = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src" / "preview.html"


def _frame(pan: int) -> bytes:
    u = bytearray(512)
    for ch in gigbar_app.HEAD_BYTES:
        u[ch] = pan
    return bytes(u)


@pytest.fixture
def preview(tmp_path):
    p = gigbar_app.Preview("demo", LayoutStore(tmp_path / "profile"))
    yield p
    p.close()


def test_every_frame_sent_leaves_its_head_bytes_stamped_in_the_trail(preview):
    tee = gigbar_app.TeeOutput(NullOutput(), preview)
    for pan in range(40):
        tee.send(_frame(pan))
    rows = list(preview.trail)
    assert len(rows) == gigbar_app.TRAIL_FRAMES                     # the newest ~0.4 s only
    assert [r[1] for r in rows] == list(range(40 - gigbar_app.TRAIL_FRAMES, 40))
    assert all(len(r) == 1 + len(gigbar_app.HEAD_BYTES) for r in rows)
    assert all(a[0] <= b[0] for a, b in zip(rows, rows[1:]))         # stamped in order


def test_state_hands_the_page_the_trail_and_the_clock_it_was_stamped_with(preview):
    tee = gigbar_app.TeeOutput(NullOutput(), preview)
    for pan in (10, 20, 30):
        tee.send(_frame(pan))
    with urllib.request.urlopen(preview.url + "state", timeout=5) as r:
        s = json.loads(r.read())
    assert [row[1] for row in s["trail"]] == [10, 20, 30]
    assert s["now"] >= s["trail"][-1][0]
    assert len(s["u"]) == 192                                        # the old fields still there
    preview.end()
    assert not preview.trail                                        # a stopped show leaves no ghost beams


PLAYBACK = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const body = src.slice(src.indexOf('const HEAD_AT'), src.indexOf('function frame()'));
const {keepTrail, smoothHeads} = new Function(body + '; return {keepTrail, smoothHeads}')();
// Frames every 25 ms from the app (its clock 1000 ms ahead of the page's), pan climbing 4 a frame.
const rows = [];
for (let i = 0; i < 16; i++) rows.push([1000 + 25 * i, 4 * i, 0, 4 * i, 0, 0, 0, 0, 0]);
keepTrail(rows.slice(0, 8), 1000 + 25 * 7, 25 * 7);     // a poll: sent the moment frame 7 left
keepTrail(rows.slice(4, 16), 1000 + 25 * 15, 25 * 15);  // the next poll overlaps the first
const u = new Array(192).fill(0);
const out = [];
for (let here = 25 * 6; here <= 25 * 15; here += 5) out.push(smoothHeads(u, here)[23]);
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_the_picture_glides_between_frames_instead_of_jumping_per_poll():
    res = subprocess.run(["node", "-e", PLAYBACK, str(PREVIEW)], capture_output=True, text=True,
                         timeout=30, check=True)
    pans = json.loads(res.stdout)
    steps = [b - a for a, b in zip(pans, pans[1:])]
    assert all(s >= 0 for s in steps), pans                          # never steps back (overlap deduped)
    assert max(steps) <= 1.0, pans                                   # 5 ms of a 4-per-25-ms climb, not a jump
    assert any(p != round(p) for p in pans), pans                    # in between real frames, not on them
    # Drawn BEHIND ms late: at page time t the beam is where the app's frame at t - 90 ms put it.
    here = 25 * 10
    assert pans[(here - 25 * 6) // 5] == pytest.approx(4 * (here - 90) / 25)
