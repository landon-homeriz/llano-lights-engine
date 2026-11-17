"""The room picture draws a head bent onto his confirmed spots the way it is aimed (Llano BL #12381).

His video 2026-11-14 9:06 PM CT on 1.26.1 (the line-up check, "Every head is aiming at the spot you tapped"):
"it's fine here and here and here but when I come to the left side see how this sticks out weird". The heads
are aimed with each head's confirmed spots bending the model (venue.anchored); the picture drew every
calibrated head with the plain model, so where a bend is large (GigBAR 1's right head toward the front left of
his floor, about 3.6 degrees of tilt from his spot at 1.9, 5.0) its beam landed up to 1.3 m past the spot.
The fixture is his saved room as the laptop held it at 9:03 PM (Llano settings rev 79).
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools.gigbar_lights import venue

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1] / "tools" / "gigbar_lights" / "windows" / "src"))
import gigbar_app  # noqa: E402

HEADS = [(1, 0), (1, 1), (2, 0), (2, 1)]


def _his():
    return venue.Layout.from_dict(json.loads((HERE / "his_layout_rev79_12381.json").read_text()))


def _grid(lay, n=9):
    fl = lay.floor
    return [(fl.x + fl.w * i / (n - 1), fl.y + fl.d * j / (n - 1)) for j in range(n) for i in range(n)]


def _lands(o, d):
    k = -o[2] / d[2]
    return o[0] + k * d[0], o[1] + k * d[1]


def test_his_left_side_spot_is_where_the_plain_model_overshoots():
    """The failing input: without the bends a head's beam misses a left-side spot by over a meter."""
    lay = _his()
    worst = 0.0
    for x, y in _grid(lay):
        for b, m in HEADS:
            o = lay.heads(b)[m]
            p, t = lay.aim(b, o, (x, y, 0.0), m)
            worst = max(worst, math.dist(_lands(o, lay._cal_beam(b, m, lay.cal(b, m), p, t)), (x, y)))
            assert math.dist(_lands(o, lay.beam_of(b, m, p, t)), (x, y)) < 0.02   # the aim itself is right
    assert worst > 1.0


def test_the_page_gets_each_heads_pulls():
    d = gigbar_app.layout_payload(_his())["derived"]
    assert d["pull_reach"] == venue.ANCHOR_REACH
    assert [len(d["pull"][f"bar{b}"][m]) for b, m in HEADS] == [3, 3, 3, 3]
    assert all(len(a) == 5 for b, m in HEADS for a in d["pull"][f"bar{b}"][m])
    plain = venue.Layout.from_dict(json.loads((HERE / "his_layout_12381.json").read_text()))
    assert gigbar_app.layout_payload(plain)["derived"]["pull"] is not None


PAGE = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const body = src.slice(src.indexOf('function facingOf'), src.indexOf('function hitRoom'));
const rad = (d) => d * Math.PI / 180;
let L = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const {beamDir} = new Function('L', 'rad', body + '; return {beamDir}')(L.layout, rad);
const out = L.poses.map(([b, m, p, t]) => beamDir(b, p, t, m));
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_the_picture_lands_every_beam_on_the_spot_across_his_floor():
    lay = _his()
    poses, want = [], []
    for x, y in _grid(lay):
        for b, m in HEADS:
            o = lay.heads(b)[m]
            poses.append([b, m, *lay.aim(b, o, (x, y, 0.0), m)])
            want.append((o, (x, y)))
    page = Path(gigbar_app.__file__).with_name("preview.html")
    res = subprocess.run(["node", "-e", PAGE, str(page)], input=json.dumps({"layout": gigbar_app.layout_payload(lay), "poses": poses}),
                         capture_output=True, text=True, timeout=30, check=True)
    dirs = json.loads(res.stdout)
    worst = max(math.dist(_lands(o, d), xy) for (o, xy), d in zip(want, dirs))
    assert worst < 0.02, worst


# His three-spot line-up at 9:03 PM (settings rev 79), each (bar, head, pan, tilt, x, y), on his room as saved at 9:01 PM (rev 78).
REV79_SAMPLES = [[1, 0, 0.35294117647058826, 0.69923, 4.032495007277528, 2.5478116643536537], [1, 0, 0.28627450980392155, 0.8235294117647058, 1.9, 5.0], [1, 0, 0.34458, 0.71864, 4.0, 2.9], [1, 1, 0.41568627450980394, 0.74402, 4.032495007277528, 2.5478116643536537], [1, 1, 0.3333333333333333, 0.80632, 1.9, 5.0], [1, 1, 0.40524, 0.75535, 4.0, 2.9], [2, 0, 0.26666666666666666, 0.72638, 4.032495007277528, 2.5478116643536537], [2, 0, 0.2627450980392157, 0.8470588235294118, 1.9, 5.0], [2, 0, 0.27634, 0.7408, 4.0, 2.9], [2, 1, 0.3215686274509804, 0.69184, 4.032495007277528, 2.5478116643536537], [2, 1, 0.2784313725490196, 0.81898, 1.9, 5.0], [2, 1, 0.3176470588235294, 0.71262, 4.0, 2.9]]


def test_three_spots_never_hang_a_bar_at_the_ceiling():
    """1.26.1 "solved" GigBAR 2 at 3.0 m (his ceiling, the search's top) and moved it 0.9 m toward the booth;
    every spot still played back. A solve pinned on the height bound keeps the bar where it stands."""
    lay = venue.Layout.from_dict(json.loads((HERE / "his_layout_rev78_12381.json").read_text()))
    rep = lay.converge([(b, m, p, t, (x, y)) for b, m, p, t, x, y in REV79_SAMPLES])
    s2 = lay.spots["bar2"]
    assert (s2.x, s2.y, s2.z) == (5.7, 0.8, 2.4) and s2.facing is None
    assert rep["bars"][2]["solved"] is False and rep["bars"][2]["stayed"] is True
    assert "ceiling" in rep["bars"][2]["why"]
    assert all(r["held"] for r in rep["held"]), rep["held"]
    assert [lay.cal_problem(b, m) for b, m in HEADS] == [None] * 4


def test_a_height_inside_the_room_is_still_an_answer():
    lay = _his()
    assert lay._height_inside(2.4) and lay._height_inside(2.9)
    assert not lay._height_inside(3.0) and not lay._height_inside(2.99) and not lay._height_inside(0.32)
