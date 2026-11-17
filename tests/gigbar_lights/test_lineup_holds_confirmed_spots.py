"""Line up my lights: a spot he confirmed stays put when he lines up the next one (Llano BL #11766).

The report 2026-11-10 on 1.16.8: only the last spot lined up stayed aligned; each new spot
moved the earlier ones. converge() fitted each head's one model over every spot, and no
model lands his real poses on three spots at once, so each new spot pulled the earlier ones up to 0.59 m.
Now each confirmed spot is an anchor on the head: aiming at it plays back the exact bytes he confirmed,
after any number of later spots, through saving, and with the bar's facing re-solved; and a spot his heads
can't agree on is named.
"""
import json
import math

import pytest

from tools.gigbar_lights.venue import ANCHOR_WARN_M, HeadCal, Layout, presets

# His run, 15:06Z 2026-11-10 (light_doctor "one spot", 1.16.8.16), on his layout: small-room-front's
# geometry (bars at 2.3,0.8 and 5.7,0.8, 2.4 m up). (bar, head 1/2, pan byte, tilt byte, x, y).
HIS_POSES = [(1, 2, 101, 210, 4.0, 5.0), (1, 1, 88, 204, 4.0, 5.0), (2, 2, 84, 203, 4.0, 5.0), (2, 1, 73, 204, 4.0, 5.0),
             (1, 2, 109, 193, 4.0, 2.9), (1, 1, 90, 178, 4.0, 2.9), (2, 2, 80, 179, 4.0, 2.9), (2, 1, 63, 189, 4.0, 2.9),
             (1, 2, 87, 205, 1.9, 5.0), (1, 1, 74, 208, 1.9, 5.0), (2, 2, 71, 211, 1.9, 5.0), (2, 1, 64, 216, 1.9, 5.0)]
HIS_SPOTS = [(4.0, 5.0), (4.0, 2.9), (1.9, 5.0)]


def his_layout() -> Layout:
    return Layout.from_dict({**presets()["small-room-front"].to_dict(), "name": "his-room", "preset": False})


def samples(spots):
    return [(b, h - 1, p / 255, t / 255, (x, y)) for b, h, p, t, x, y in HIS_POSES if (x, y) in spots]


def aimed_bytes(lay, b, m, x, y):
    p, t = lay.aim(b, lay.heads(b)[m], (x, y, 0.0), m)
    return round(p * 255), round(t * 255)


def confirmed(b, m, x, y):
    return next((p, t) for bb, h, p, t, xx, yy in HIS_POSES if (bb, h - 1, xx, yy) == (b, m, x, y))


@pytest.mark.parametrize("k", [1, 2, 3])
def test_every_spot_he_confirmed_plays_back_his_exact_pose_after_the_next_spot(k):
    lay = his_layout()
    lay.converge(samples(HIS_SPOTS[:k]))
    for x, y in HIS_SPOTS[:k]:
        for b in (1, 2):
            for m in (0, 1):
                assert aimed_bytes(lay, b, m, x, y) == confirmed(b, m, x, y), (x, y, b, m)


def test_the_first_spot_does_not_move_when_the_second_and_third_are_lined_up():
    """The run as he did it: one layout, a spot at a time, each converge carrying the earlier spots."""
    lay = his_layout()
    for k in range(1, 4):
        lay = Layout.from_dict(lay.to_dict())   # the page posts the saved layout back each time
        lay.converge(samples(HIS_SPOTS[:k]))
        first = [aimed_bytes(lay, b, m, *HIS_SPOTS[0]) for b in (1, 2) for m in (0, 1)]
        assert first == [confirmed(b, m, *HIS_SPOTS[0]) for b in (1, 2) for m in (0, 1)]


def test_the_picture_draws_a_confirmed_pose_landing_on_its_spot():
    lay = his_layout()
    lay.converge(samples(HIS_SPOTS))
    for b, h, p, t, x, y in HIS_POSES:
        o = lay.heads(b)[h - 1]
        d = lay.beam(b, o, p / 255, t / 255, h - 1)
        s = -o[2] / d[2]
        assert math.dist((o[0] + d[0] * s, o[1] + d[1] * s), (x, y)) < 0.05


def test_spots_survive_saving_and_reach_llano_as_plain_numbers():
    lay = his_layout()
    lay.converge(samples(HIS_SPOTS))
    stored = json.loads(json.dumps(lay.to_dict()))
    assert len(stored["fixtures"]["bar1"]["cal"][0]["anchors"]) == 3
    back = Layout.from_dict(stored)
    for x, y in HIS_SPOTS:
        for b in (1, 2):
            for m in (0, 1):
                assert aimed_bytes(back, b, m, x, y) == confirmed(b, m, x, y)


def test_three_spots_say_where_each_bar_really_hangs_and_the_plan_is_kept():
    """His three spots put both bars about 0.9 m from the plan, closer to the floor and to each other (an
    independent Nelder-Mead on the same poses: bar1 ~(2.83, 1.62), bar2 ~(5.17, 1.47)). The bars move there,
    the plan stays for Back to plan, every spot still holds, and with the bars where they are no single
    spot stands out, so none is named; the advice is no longer "line up a second spot"."""
    lay = his_layout()
    found = lay.converge(samples(HIS_SPOTS))
    for b, (x, y) in ((1, (2.8, 1.6)), (2, (5.2, 1.5))):
        r = found["bars"][b]
        assert r["moved"]["x"] == pytest.approx(x, abs=0.1) and r["moved"]["y"] == pytest.approx(y, abs=0.1)
        plan = lay.planned(f"bar{b}")
        assert (r["moved"]["from_x"], r["moved"]["from_y"]) == (plan["x"], plan["y"]) == ((2.3, 5.7)[b - 1], 0.8)
        assert (lay.spots[f"bar{b}"].x, lay.spots[f"bar{b}"].y) == (r["moved"]["x"], r["moved"]["y"])
        assert r["rms_m"] < r["moved"]["fit_was_m"]
        assert "second spot" not in r["why"] and "held exactly" in r["why"]
        assert "keeps the position" not in r["why"] and "moved there" in r["why"]   # never contradicts `moved`
    assert found["disagree"] == []
    assert all(r["held"] for r in found["held"]) and len(found["held"]) == 12
    lay.reset_to_plan()
    assert (lay.spots["bar1"].x, lay.spots["bar1"].y) == (2.3, 0.8)


def test_one_spot_never_moves_a_bar():
    found = his_layout().converge(samples(HIS_SPOTS[:1]))
    assert all("moved" not in r for r in found["bars"].values())


def test_spots_that_agree_name_nothing():
    """A rig that really is where the layout says: poses made by the model itself agree, nothing named."""
    lay = his_layout()
    lay.converge(samples(HIS_SPOTS[:1]))
    rows = []
    for x, y in [(3.0, 4.0), (5.0, 4.5), (4.0, 6.0)]:
        for b in (1, 2):
            for m in (0, 1):
                p, t = lay.aim(b, lay.heads(b)[m], (x, y, 0.0), m)
                rows.append((b, m, round(p * 255) / 255, round(t * 255) / 255, (x, y)))
    fresh = his_layout()
    found = fresh.converge(rows)
    assert found["disagree"] == []


def test_aims_between_spots_move_smoothly():
    """The anchors bend aims near them and fade away from them: no jump anywhere across the floor."""
    lay = his_layout()
    lay.converge(samples(HIS_SPOTS))
    fl = lay.floor
    for b in (1, 2):
        for m in (0, 1):
            for y in (3.0, 5.0, 6.5):
                prev = None
                for i in range(81):
                    p = lay.aim(b, lay.heads(b)[m], (fl.x + fl.w * i / 80, y, 0.0), m)
                    if prev:
                        assert max(abs(p[0] - prev[0]), abs(p[1] - prev[1])) * 255 < 1.5
                    prev = p


def test_a_layout_without_spots_aims_exactly_as_before():
    lay = his_layout()
    lay.converge(samples(HIS_SPOTS))
    plain = Layout.from_dict(lay.to_dict())
    for b in (1, 2):
        for c in plain.spots[f"bar{b}"].cal:
            c.anchors = []
    model = Layout.from_dict(plain.to_dict())
    for b in (1, 2):
        for m in (0, 1):
            for target in ((6.4, 7.4, 0.0), (3.0, 4.0, 0.0), (4.0, 5.0, 0.0)):   # no spots: exactly the model's aim
                c = model.cal(b, m)
                assert model.aim(b, model.heads(b)[m], target, m) == model._cal_aim(b, m, c, target)
    assert "anchors" not in json.dumps(model.to_dict())


def test_spots_lined_up_before_saving_still_hold_after_reopening_and_a_new_spot():
    """Line up a spot, save, reopen the app (the page's memory is gone), line up a second spot alone:
    the first still plays back his exact pose. A new pose on an old spot replaces it."""
    lay = his_layout()
    lay.converge(samples(HIS_SPOTS[:1]))
    lay = Layout.from_dict(json.loads(json.dumps(lay.to_dict())))
    lay.converge(samples(HIS_SPOTS[1:2]))
    for x, y in HIS_SPOTS[:2]:
        for b in (1, 2):
            for m in (0, 1):
                assert aimed_bytes(lay, b, m, x, y) == confirmed(b, m, x, y), (x, y, b, m)
    assert [len(c.anchors) for b in (1, 2) for c in lay.spots[f"bar{b}"].cal] == [2, 2, 2, 2]
    redo = [(b, m, min(1.0, p + 2 / 255), t, xy) for b, m, p, t, xy in samples(HIS_SPOTS[:1])]
    lay.converge(redo)
    assert [len(c.anchors) for b in (1, 2) for c in lay.spots[f"bar{b}"].cal] == [2, 2, 2, 2]
    assert aimed_bytes(lay, 1, 0, *HIS_SPOTS[0]) == (confirmed(1, 0, *HIS_SPOTS[0])[0] + 2, confirmed(1, 0, *HIS_SPOTS[0])[1])
    lay.clear_lineup(1)                                  # starting over is explicit
    assert [len(c.anchors) for c in lay.spots["bar1"].cal] == [0, 0]


def test_a_head_turned_round_keeps_its_spots():
    """facing_cal can turn a head's calibration round (half a pan turn, tilt mirrored): its spots, saved
    the other way round, still hold (his head 4 case)."""
    lay = his_layout()
    lay.converge(samples(HIS_SPOTS))
    for b in (1, 2):
        for m in (0, 1):
            c = lay.cal(b, m)
            _, oc = lay._center_angles(b, m)
            flipped = [(x, y, *lay._other_way(c, oc, p, t)) for x, y, p, t in lay.spots[f"bar{b}"].cal[m].anchors]
            if all(0 <= v <= 1 for a in flipped for v in a[2:]):
                assert len(lay._anchor_misses(b, m, HeadCal(c.center, {}, c.pan_invert, c.tilt_invert, c.swap,
                                                                   c.pan_range, c.tilt_range, flipped))) == 3


def test_tap_to_aim_and_the_light_doctor_keep_the_spots(tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
    src = (Path(__file__).resolve().parents[2] / "tools/gigbar_lights/windows/src/gigbar_app.py").read_text()
    assert src.count("cal.anchors = list(lay.spots[f\"bar{bar}\"].cal[m].anchors)") == 2


def test_bad_anchors_are_refused_in_plain_words():
    with pytest.raises(ValueError, match="anchors"):
        HeadCal.from_dict({"center": [0.5, 0.5], "anchors": [[1, 2, 3]]}, "bar1 head 1")
    with pytest.raises(ValueError, match="anchor pan"):
        HeadCal.from_dict({"center": [0.5, 0.5], "anchors": [[1, 2, 3, 0.5]]}, "bar1 head 1")


def test_one_pose_far_off_its_spot_is_named_and_the_good_spots_still_hold():
    """A slip (a pose saved far from its spot) used to drag the head's whole fit: now that head refits
    without it, the other spots hold, and the slipped spot is the one named, as not held."""
    rows = [(b, m, 0.95, 0.2, xy) if (b, m, xy) == (1, 0, (1.9, 5.0)) else (b, m, p, t, xy)
            for b, m, p, t, xy in samples(HIS_SPOTS)]
    lay = his_layout()
    found = lay.converge(rows)
    worst = found["disagree"][0]
    assert (worst["bar"], worst["head"], worst["x"], worst["y"], worst["held"]) == (1, 1, 1.9, 5.0, False)
    for x, y in HIS_SPOTS[:2]:
        assert aimed_bytes(lay, 1, 0, x, y) == confirmed(1, 0, x, y)
