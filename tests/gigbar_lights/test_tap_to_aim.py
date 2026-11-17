"""Tap to aim (his 11-09 ask): tap where a head's beam lands, then where it should; Llano works the
head out from the taps so far, aims it at the second tap and saves it. One or two taps solve the
head's center with its turn directions kept; three or more solve everything (the doctor's fit)."""
from __future__ import annotations

import math

import pytest

from tools.gigbar_lights import venue
from tools.gigbar_lights.venue import HeadCal
from test_light_doctor_11615 import _post, floor_hit, his_layout, preview, real_head  # noqa: F401


def _miss_m(real, bar, m, pose, want):
    hit = floor_hit(real, bar, m, *pose)
    return math.dist(hit, want)


def _offset_truth(lay, bar, m, dp=0.04, dt=-0.03, **kw):
    """A real head a few steps off the guess, turning the way the guess turns in the room (1.16.0:
    the guessed model's pan turns the other way round in the room, venue._guess_turn)."""
    guess = lay.aim(bar, lay.heads(bar)[m], lay.ref_target("center"), m)
    kw.setdefault("pan_invert", venue._guess_turn(lay.spots[f"bar{bar}"]) < 0)
    return HeadCal((guess[0] + dp, guess[1] + dt), {}, **kw)


@pytest.mark.parametrize("bar,m", [(1, 0), (1, 1), (2, 0), (2, 1)])
def test_one_tap_of_a_head_whose_turns_match_the_guess_lands_the_next_aim(bar, m):
    lay = his_layout()
    real = real_head(lay, bar, m, _offset_truth(lay, bar, m))   # the guess is off by a few steps
    pose = lay.aim(bar, lay.heads(bar)[m], lay.ref_target("center"), m)
    seen = floor_hit(real, bar, m, *pose)
    cal, miss = lay.fit_taps(bar, m, [(pose[0], pose[1], seen)])
    lay.spots[f"bar{bar}"].cal[m] = cal
    want = (lay.floor.x + 0.3 * lay.floor.w, lay.floor.y + 0.6 * lay.floor.d)
    new = lay.aim(bar, lay.heads(bar)[m], (*want, 0.0), m)
    assert miss < 0.5
    assert _miss_m(real, bar, m, new, want) < 0.15   # within a beam's width on the floor


def test_one_tap_keeps_a_saved_heads_turn_directions():
    lay = his_layout()
    lay.spots["bar1"].cal[0] = _offset_truth(lay, 1, 0, 0, 0, pan_invert=False)   # the other way from the guess
    real = real_head(lay, 1, 0, _offset_truth(lay, 1, 0, pan_invert=False))
    pose = lay.aim(1, lay.heads(1)[0], lay.ref_target("center"), 0)
    cal, _ = lay.fit_taps(1, 0, [(pose[0], pose[1], floor_hit(real, 1, 0, *pose))])
    assert not cal.pan_invert and not cal.swap


def test_the_page_round_aims_the_head_and_tells_llano(preview):
    lay = preview.layout
    real = real_head(lay, 2, 1, _offset_truth(lay, 2, 1))
    pose = lay.aim(2, lay.heads(2)[1], lay.ref_target("center"), 1)
    seen = floor_hit(real, 2, 1, *pose)
    want = (lay.floor.x + 0.5 * lay.floor.w, lay.floor.y + 0.3 * lay.floor.d)
    code, body = _post(preview, {"action": "tapaim", "bar": 2, "m": 1, "layout": lay.to_dict(),
                                 "samples": [{"p": pose[0], "t": pose[1], "x": seen[0], "y": seen[1]}],
                                 "want": {"x": want[0], "y": want[1]}})
    assert code == 200, body
    assert _miss_m(real, 2, 1, body["pose"], want) < 0.15
    rep = body["doctor"]
    assert rep["kind"] == "tap to aim" and (rep["bar"], rep["head"]) == (2, 2)
    assert rep["aimed"] == {"pan": round(body["pose"][0] * 255), "tilt": round(body["pose"][1] * 255)}
    assert preview.app.doctor == rep and preview.tried
    assert body["layout"]["fixtures"]["bar2"]["cal"][1]["center"]


def test_the_doctor_still_wants_three_taps(preview):
    lay = preview.layout
    samples = [{"p": 0.5, "t": 0.8, "x": 1.0, "y": 1.0}]
    code, body = _post(preview, {"action": "doctor", "bar": 1, "m": 0, "samples": samples, "layout": lay.to_dict()})
    assert code == 400 and "at least 3" in body["error"]
