"""One spot never re-solves a lined-up GigBAR (Llano BL #12381 follow-up to 1.26.1).

1.26.1 keeps a one-spot solve only when every head plays its spot back and passes the tilt check. That
still let a solve through that was a different bar: his rig as lined up on Nov 10 (the fixture: his saved
room, bars as on Nov 10), re-lined on one spot with poses two DMX steps off the Nov 10 aims, "solved"
GigBAR 1 at 2.99 m under his 3 m ceiling, facing -0.8 degrees; it held the spot, and every other aim moved
up to 30 DMX steps ("once I lined up the lights everything suddenly got screwed up even though they were
aligned before"). A bar whose two heads were both lined up keeps where it stands on one spot; each head's
aim moves to the spot and keeps its turn directions.
"""
import json
import random
from pathlib import Path

from tools.gigbar_lights import venue

HERE = Path(__file__).parent
HEADS = [(1, 0), (1, 1), (2, 0), (2, 1)]
# The input that moved GigBAR 1 on 1.26.1: (bar, head, pan, tilt, spot)
SPOT = (3.072299, 3.538073)
POSES = [(1, 0, 0.321125, 0.727934), (1, 1, 0.380479, 0.745583), (2, 0, 0.244301, 0.797995), (2, 1, 0.288181, 0.768261)]


def _his():
    return venue.Layout.from_dict(json.loads((HERE / "his_layout_12381.json").read_text()))


def _drift(lay, base):
    fl = base.floor
    targets = [(fl.cx, fl.cy, 0.0), (fl.x, fl.y, 0.0), (fl.x + fl.w, fl.y + fl.d, 0.0), (fl.x, fl.y + fl.d, 0.0),
               (fl.x + fl.w, fl.y, 0.0)]
    worst = 0.0
    for b, m in HEADS:
        for t in targets:
            a, a0 = lay.aim(b, lay.heads(b)[m], t, m), base.aim(b, base.heads(b)[m], t, m)
            worst = max(worst, abs(a[0] - a0[0]) * 255, abs(a[1] - a0[1]) * 255)
    return worst


def test_the_input_that_moved_gigbar_1_keeps_both_bars_in_place():
    base, lay = _his(), _his()
    rep = lay.converge([(b, m, p, t, SPOT) for b, m, p, t in POSES])
    for b in (1, 2):
        s, s0 = lay.spots[f"bar{b}"], base.spots[f"bar{b}"]
        assert (s.x, s.y, s.z, s.facing) == (s0.x, s0.y, s0.z, s0.facing)
        assert rep["bars"][b]["solved"] is False and rep["bars"][b]["stayed"] is True
    assert all(r["held"] for r in rep["held"]), rep["held"]
    assert [lay.cal_problem(b, m) for b, m in HEADS] == [None] * 4
    assert _drift(lay, base) <= 4


def test_any_one_spot_re_line_up_keeps_the_rig_aligned():
    base = _his()
    fl = base.floor
    rnd = random.Random(12381)
    for _ in range(25):
        spot = (fl.x + rnd.random() * fl.w, fl.y + rnd.random() * fl.d)
        samples = []
        for b, m in HEADS:
            p, t = base.aim(b, base.heads(b)[m], (*spot, 0.0), m)
            samples.append((b, m, min(1.0, max(0.0, p + rnd.choice((-2, -1, 0, 1, 2)) / 255)),
                            min(1.0, max(0.0, t + rnd.choice((-2, -1, 0, 1, 2)) / 255)), spot))
        lay = _his()
        lay.converge(samples)
        assert [lay.spots[f"bar{b}"].z for b in (1, 2)] == [base.spots[f"bar{b}"].z for b in (1, 2)], spot
        assert _drift(lay, base) <= 4, spot


def test_a_bar_not_yet_lined_up_still_solves_from_one_spot():
    lay = _his()
    for c in lay.spots["bar2"].cal:
        c.center, c.points, c.anchors = None, {}, []
    rep = lay.converge([(b, m, p, t, SPOT) for b, m, p, t in POSES])
    r2 = rep["bars"][2]
    # the solve ran (kept or not); on his poses it lands on the ceiling, so the height guard keeps the bar (1.26.3)
    assert "rms_m" in r2 or "ceiling" in r2.get("why", "")
    assert "already lined up" not in r2.get("why", "")
    assert rep["bars"][1]["stayed"] is True
