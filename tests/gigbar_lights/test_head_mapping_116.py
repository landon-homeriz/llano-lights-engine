"""Which GigBAR head is which, everywhere, and where the heads rest after Done (1.16.0).

His 11-09 reports: with GigBAR 2 right picked in Line up my lights, the real right head moved but both
room pictures moved the left one; and after Done, GigBAR 2's right head sat a quarter turn off the
others. Cause of the first: the model put head 1 (channels 24-29, the right head from the floor) at
the bar's other end, so the pictures drew its beam from the left head (venue.heads). The second is not
a mapping on Done: Done leaves every head at the same pan 0, tilt 0; the line-up slammed the heads
there (and between calibration poses) in one frame at full motor speed, the way a stepper skips. Now
every big move in the line-up glides calmly and Stop parks the heads gently (glide.py).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
from tools.gigbar_lights import __main__ as gl  # noqa: E402
from tools.gigbar_lights.enttec import NullOutput  # noqa: E402
from tools.gigbar_lights.looks import CAL_OTHERS  # noqa: E402
from tools.gigbar_lights.rig import head_picture  # noqa: E402
from tools.gigbar_lights.show import Show  # noqa: E402
from tools.gigbar_lights.venue import presets, rest_pan  # noqa: E402

PREVIEW = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src" / "preview.html"
NODE = os.environ.get("NODE") or shutil.which("node")
# Each head's pan and tilt byte (0-based): bar 1 at address 1, bar 2 at 41, head 1 at ch24, head 2 at ch30.
PAN_TILT = {(1, 0): (23, 24), (1, 1): (29, 30), (2, 0): (63, 64), (2, 1): (69, 70)}
DIM = {(b, m): pt[0] + 2 for (b, m), pt in PAN_TILT.items()}


def _viewer_right(lay, bar):
    """+1 when head 1 is on the right as you stand on the dance floor facing the bar."""
    h1, h2 = lay.heads(bar)
    return 1 if h1[0] > h2[0] else -1


@pytest.mark.parametrize("name", sorted(presets()))
def test_head_1_is_the_right_head_seen_from_the_dance_floor_on_both_bars(name):
    lay = presets()[name]
    # Standing on the floor facing the booth (-y), house left (small x) is on the left: the view from
    # the dance floor draws it so (test_preview_views), and so does the plan from above.
    assert [_viewer_right(lay, b) for b in (1, 2)] == [1, 1]


PROBE = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const pick = (a, b) => src.slice(src.indexOf(a), src.indexOf(b));
const code = pick('function facingOf', '// A calibrated head') ;
const rad = d => d * Math.PI / 180;
const out = {};
for (const [name, L] of Object.entries(JSON.parse(process.argv[2]))) {
  const headsOf = new Function('L', 'rad', code + '; return headsOf')(L, rad);
  out[name] = [headsOf(1), headsOf(2)];
}
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="node is not installed here")
def test_the_room_pictures_put_each_head_where_the_lights_model_does():
    lays = {n: l for n, l in presets().items()}
    res = subprocess.run([NODE, "-e", PROBE, str(PREVIEW), json.dumps({n: l.to_dict() for n, l in lays.items()})],
                         capture_output=True, text=True, timeout=30, check=True)
    for name, heads in json.loads(res.stdout).items():
        for b in (1, 2):
            for m in (0, 1):
                assert heads[b - 1][m] == pytest.approx(list(lays[name].heads(b)[m]), abs=1e-9), (name, b, m)


def test_gigbar_2_right_drives_gigbar_2_heads_channels_and_stands_out():
    """GigBAR 2 right (head 0) moves channels 64-65 and is the bright one; its neighbor dims."""
    show = Show(analyze=False)
    show.looks.overrides.lineup = (0, "center")
    gl.handle_key("cal:2:0:0.3:0.7", show)
    for i in range(120):   # the line-up glides there from home (glide.py, calm)
        u = show.render(i * 0.025)
    assert (u[63], u[64]) == (round(0.3 * 255), round(0.7 * 255))
    assert u[DIM[(2, 0)]] == 255
    assert [u[DIM[k]] for k in ((1, 0), (1, 1), (2, 1))] == [round(CAL_OTHERS * 255)] * 3


class Frames(NullOutput):
    def __init__(self):
        super().__init__()
        self.sent = []

    def send(self, universe: bytes) -> None:
        super().send(universe)
        self.sent.append(bytes(universe))


def test_done_leaves_every_head_at_the_same_rest_pose_and_glides_there():
    show = Show(analyze=False)
    show.looks.overrides.lineup = (0, "center")
    gl.handle_key("cal:2:0:0.9:0.85", show)   # GigBAR 2 right turned far round, as after the Light doctor
    t = 0.0
    for _ in range(120):                    # the line-up glides it there
        show.render(t)
        t += 0.025
    gl.handle_key("lineup:", show)          # Done
    out = Frames()
    clock = [t]

    def tick(dt):
        clock[0] += dt
    gl.park(show, out, clock=lambda: clock[0], sleep=tick)
    out.send(show.park(clock[0]))           # what _run_loop sends last (1.16.4: never an all-zero frame)
    last = out.sent[-1]
    rest = {i: round(v) for i, v in head_picture({(b, m): (rest_pan(540.0), 0.0) for b in (0, 1) for m in (0, 1)}).items()}
    assert all(last[i] == rest[i] for pt in PAN_TILT.values() for i in pt)   # one rest pose for all four heads
    assert all(last[DIM[k]] == 0 for k in DIM)
    # On the way there: no frame jumps a head across the room at full motor speed.
    pans = [f[63] for f in out.sent]
    assert pans[0] > 150 and max(abs(a - b) for a, b in zip(pans, pans[1:])) <= 12
    assert len(out.sent) > 10


def test_a_new_line_up_run_glides_from_home_instead_of_jumping_on_its_first_frame():
    """Review 1.16.0: the heads rest straight ahead and level (Stop parks them there; 1.16.4: on the pan
    twin nearest DMX middle, venue.rest_pan), and a fresh line-up run's first frame used to land its
    pose at once, a full-speed slam."""
    show = Show(analyze=False)
    show.looks.overrides.lineup = (0, "center")
    first = show.render(100.0)
    rest = head_picture({(b, m): (rest_pan(540.0), 0.0) for b in (0, 1) for m in (0, 1)})
    assert all(abs(first[PAN_TILT[k][0]] - rest[PAN_TILT[k][0]]) <= 12 for k in PAN_TILT)
    for i in range(1, 120):
        u = show.render(100.0 + i * 0.025)
    assert all(u[PAN_TILT[k][0]] > 40 for k in PAN_TILT)   # and gets there


def test_a_nudge_in_the_line_up_lands_at_once_and_a_jump_glides():
    show = Show(analyze=False)
    show.looks.overrides.lineup = (0, "center")
    gl.handle_key("cal:2:0:0.5:0.5", show)
    t = 0.0
    for _ in range(120):
        show.render(t)
        t += 0.025
    gl.handle_key("cal:2:0:" + f"{129 / 255:.5f}" + ":0.5", show)   # one arrow press
    assert show.render(t)[63] == 129
    gl.handle_key("cal:2:0:0.0:0.5", show)   # Center all from the far end: glides, never in one frame
    t += 0.025
    assert show.render(t)[63] > 100
