"""BL #11615: the Light doctor works a head out from where he taps its beams.

The app drives one head to five fixed raw poses; he taps where each beam lands on the room
picture (or skips it). The fit tries every swap and turn direction and the center that lands
the beams nearest his taps. These plant a known head (the "real" one), land its beams on the
floor, and check the doctor recovers it from those taps alone, starting from no calibration.
"""
from __future__ import annotations

import copy
import itertools
import math

import pytest

from tools.gigbar_lights import venue
from tools.gigbar_lights.venue import HeadCal, Layout, presets


def his_layout() -> Layout:
    return copy.deepcopy(presets()["small-room-front"])


def floor_hit(lay: Layout, bar: int, m: int, pan: float, tilt: float):
    """Where head m's beam lands on the floor (z 0) for a raw pose, or None above level."""
    o = lay.heads(bar)[m]
    d = lay.beam_of(bar, m, pan, tilt)
    if d[2] >= -1e-6:
        return None
    k = -o[2] / d[2]
    return (o[0] + d[0] * k, o[1] + d[1] * k)


def real_head(lay: Layout, bar: int, m: int, cal: HeadCal) -> Layout:
    real = copy.deepcopy(lay)
    real.spots[f"bar{bar}"].cal[m] = cal
    return real


def taps_from(real: Layout, bar: int, m: int, poses):
    out = []
    for pan, tilt in poses:
        hit = floor_hit(real, bar, m, pan, tilt)
        if hit is not None and 0 <= hit[0] <= real.room[0] and 0 <= hit[1] <= real.room[1]:   # he taps the picture
            out.append((pan, tilt, hit))
    return out


def test_the_poses_are_on_the_dmx_step_and_land_in_the_room_by_todays_guess():
    lay = his_layout()
    for bar, m in itertools.product((1, 2), (0, 1)):
        poses = lay.doctor_poses(bar, m)
        assert len(poses) == len(venue.DOCTOR_PLUS)
        assert all(abs(v * 255 - round(v * 255)) < 1e-9 for p in poses for v in p)
        assert len(set(poses)) == len(poses)   # five different beams, or the fit learns nothing
        assert all(floor_hit(lay, bar, m, *p) is not None for p in poses)


# His heads could be any of these: the turn directions and a swapped pan/tilt are the unknowns.
TRUTHS = [(pi, ti, sw) for pi in (False, True) for ti in (False, True) for sw in (False, True)]


@pytest.mark.parametrize("pan_invert,tilt_invert,swap", TRUTHS)
def test_the_doctor_recovers_a_head_from_his_taps(pan_invert, tilt_invert, swap):
    lay = his_layout()
    bar, m = 1, 0
    guess = lay.aim(bar, lay.heads(bar)[m], lay.ref_target("center"), m)
    # The real head's center sits a few steps off today's guess, as a hung bar's would.
    center = (min(1, guess[0] + 0.03), max(0, guess[1] - 0.02))
    if tilt_invert:   # a head whose tilt turns the other way is turned round: pan half a turn, tilt the other
        it, ip = (0, 1) if swap else (1, 0)   # side of straight down (tilt 0.5, manual p. 8; 1.16.7 venue.side_cal)
        c = list(center)
        c[it] = 1.0 - c[it]
        c[ip] = min((c[ip] + k / 3 for k in (-1, 1) if 0 <= c[ip] + k / 3 <= 1), key=lambda v: abs(v - 0.5))
        center = tuple(c)
    truth = HeadCal(center, {}, pan_invert, tilt_invert, swap)   # raw bytes on the middle, swapped or not
    real = real_head(lay, bar, m, truth)
    taps = taps_from(real, bar, m, lay.doctor_poses(bar, m))   # the beams that land in the room
    assert len(taps) >= venue.DOCTOR_MIN_TAPS
    cal, miss = lay.fit_taps(bar, m, taps)
    assert miss < 1.0, (cal, miss)
    # the head's turn directions; a head turned round (pan 180, tilt the other side of straight down)
    # points every raw pose exactly where its twin does, so either is the head (1.16.7: with straight
    # down at tilt 0.5 the taps can't tell them apart, and the fit keeps the one nearest today's aim)
    assert (cal.pan_invert, cal.swap) == (pan_invert, swap)
    if cal.tilt_invert == tilt_invert:
        assert cal.center == pytest.approx(center, abs=2 / 255)
    lay.spots[f"bar{bar}"].cal[m] = cal
    # What matters on the night: every beam now lands where the real head puts it.
    for pan, tilt, (x, y) in taps:
        hx, hy = floor_hit(lay, bar, m, pan, tilt)
        assert math.hypot(hx - x, hy - y) < 0.15, (pan, tilt)
    # and aiming at the floor's middle sends the real head there
    aim = lay.aim(bar, lay.heads(bar)[m], lay.ref_target("center"), m)
    hit = floor_hit(real, bar, m, *aim)
    fl = lay.floor
    assert math.hypot(hit[0] - fl.cx, hit[1] - fl.cy) < 0.3


def test_sloppy_taps_still_fit_and_say_how_far_off_they_are():
    lay = his_layout()
    bar, m = 2, 1
    real = real_head(lay, bar, m, HeadCal(lay.aim(bar, lay.heads(bar)[m], lay.ref_target("center"), m), {}, True))
    taps = taps_from(real, bar, m, lay.doctor_poses(bar, m))
    wobble = [(p, t, (x + 0.2 * (-1) ** i, y - 0.15 * (-1) ** i)) for i, (p, t, (x, y)) in enumerate(taps)]
    cal, miss = lay.fit_taps(bar, m, wobble)
    assert cal.pan_invert and 0 < miss < 15


def test_no_taps_is_said_plainly():
    with pytest.raises(ValueError, match="at least one"):
        his_layout().fit_taps(1, 0, [])


def test_ranges_he_set_are_kept():
    lay = his_layout()
    lay.spots["bar1"].cal[0] = HeadCal(None, {}, pan_range=500.0, tilt_range=200.0)
    taps = taps_from(lay, 1, 0, lay.doctor_poses(1, 0))
    cal, _ = lay.fit_taps(1, 0, taps)
    assert (cal.pan_range, cal.tilt_range) == (500.0, 200.0)
    assert Layout.from_dict(lay.to_dict()) is not None   # still a valid layout to save


# --- the app's side: the page posts its taps, the app fits, saves nothing yet, and reports to Llano ---

def _post(preview, msg):
    import json
    import urllib.error
    import urllib.request
    req = urllib.request.Request(preview.url + "layout", json.dumps(msg).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Llano-Token": preview.token})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@pytest.fixture
def preview(tmp_path):
    import sys
    import types
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
    import gigbar_app
    from tools.gigbar_lights.venue import LayoutStore
    p = gigbar_app.Preview("lineup", LayoutStore(tmp_path / "profile"),
                           app=types.SimpleNamespace(touch=lambda: None, doctor=None))
    yield p
    p.close()


def test_the_page_posts_its_taps_and_the_app_fits_the_head_and_tells_llano(preview):
    lay = preview.layout
    real = real_head(lay, 2, 1, HeadCal(lay.aim(2, lay.heads(2)[1], lay.ref_target("center"), 1), {}, True))
    poses = lay.doctor_poses(2, 1)
    taps = {(p, t): xy for p, t, xy in taps_from(real, 2, 1, poses)}
    samples = [{"p": p, "t": t, **({"x": taps[(p, t)][0], "y": taps[(p, t)][1]} if (p, t) in taps else {})} for p, t in poses]
    samples[1].pop("x", None), samples[1].pop("y", None)   # he couldn't see one: skipped
    code, body = _post(preview, {"action": "doctor", "bar": 2, "m": 1, "samples": samples, "layout": lay.to_dict()})
    assert code == 200, body
    rep = body["doctor"]
    assert (rep["bar"], rep["head"]) == (2, 2) and rep["miss_deg"] < 1
    assert len(rep["poses"]) == len(poses) and rep["poses"][1]["skipped"] is True
    assert all(isinstance(q["pan"], int) and 0 <= q["pan"] <= 255 for q in rep["poses"])   # the DMX bytes sent
    assert rep["fit"]["pan_invert"] is True
    assert body["layout"]["fixtures"]["bar2"]["cal"][1]["pan_invert"] is True
    assert preview.app.doctor == rep and preview.tried                # Llano's status carries it; not saved yet
    assert "doctor" in body["layout"]["derived"]


def test_too_few_taps_comes_back_as_a_plain_refusal(preview):
    lay = preview.layout
    samples = [{"p": p, "t": t} for p, t in lay.doctor_poses(1, 0)]
    code, body = _post(preview, {"action": "doctor", "bar": 1, "m": 0, "samples": samples, "layout": lay.to_dict()})
    assert code == 400 and "at least 3" in body["error"]
    code, body = _post(preview, {"action": "doctor", "bar": 3, "m": 0, "samples": samples, "layout": lay.to_dict()})
    assert code == 400
