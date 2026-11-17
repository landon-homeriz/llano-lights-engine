"""Per-head calibration (1.12.1, his real-rig report 2026-11-08).

"The GigBAR spots do not follow the light paths drawn in the preview at all. The Mirror button
moves them, but now both heads aim outside the dance floor." The aim model was a guess (raw pan
0.5 = the bar's facing, tilt 0.5 = straight down, both heads alike) and the preview drew through
the same guess, so it always looked right; Mirror reversed pan around raw 0.5, doubling any
offset. Now each head keeps the raw pan/tilt that put its beam on the floor's dots, aims outward
from its center dot, fits its turn directions from the dots, and mirrors around that center.
"""
import argparse
import json
import copy
import math
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
import gigbar_app  # noqa: E402
from tools.gigbar_lights import __main__ as gl  # noqa: E402
from tools.gigbar_lights import show_settings  # noqa: E402
from tools.gigbar_lights.looks import CAL_OTHERS, Frame, LooksEngine  # noqa: E402
from tools.gigbar_lights.rig import default_rig  # noqa: E402
from tools.gigbar_lights.show_script import Section  # noqa: E402
from tools.gigbar_lights.venue import REF_POINTS, HeadCal, Layout, LayoutStore, presets  # noqa: E402

PAGE = (Path(gigbar_app.__file__).parent / "preview.html").read_text()


def _lands(lay, bar, m, pan, tilt):
    o = lay.heads(bar)[m]
    d = lay.beam(bar, o, pan, tilt, m)
    t = -o[2] / d[2]
    return o[0] + d[0] * t, o[1] + d[1] * t


def _real_rig(truths):
    """A layout whose heads behave like `truths` (bar, m) -> HeadCal flags, with the raw pan/tilt
    he would find on each dot recorded, the way the line-up page records them. Each true head is
    off the guess: its center sits at raw values the guessed model would never send."""
    lay = presets()["small-room-front"]
    # Each center on the side of straight down (tilt 0.5, manual p. 8) its tilt direction reaches the dot
    # from (1.16.7, venue.side_cal): (2, 0) tilts the other way, so it sits below 0.5.
    centers = {(1, 0): (0.31, 0.62), (1, 1): (0.74, 0.58), (2, 0): (0.22, 0.35), (2, 1): (0.66, 0.41)}
    real = {}
    for (b, m), flags in truths.items():
        lay.spots[f"bar{b}"].cal[m] = HeadCal(center=centers[(b, m)], **flags)
    for (b, m) in truths:
        real[(b, m)] = {n: lay.aim(b, lay.heads(b)[m], lay.ref_target(n), m) for n in REF_POINTS}
    return lay, real


TRUTHS = {(1, 0): {"pan_invert": True}, (1, 1): {}, (2, 0): {"tilt_invert": True},
          (2, 1): {"pan_invert": True, "swap": True}}


def test_the_fit_finds_each_heads_turn_directions_and_swap_from_three_dots():
    truth, real = _real_rig(TRUTHS)
    d = truth.to_dict()
    for (b, m), raws in real.items():   # what the page saves: the raw values only, no signs
        d["fixtures"][f"bar{b}"]["cal"][m] = {"center": list(raws["center"]),
                                              "points": {"near": list(raws["near"]), "side": list(raws["side"])}}
    lay = Layout.from_dict(d)
    for (b, m), flags in TRUTHS.items():
        c = lay.spots[f"bar{b}"].cal[m]
        assert (c.pan_invert, c.tilt_invert, c.swap) == (flags.get("pan_invert", False), flags.get("tilt_invert", False),
                                                         flags.get("swap", False)), (b, m)
        assert lay.fit_head(b, m) < 0.5
        # Anywhere on the floor, the fitted head sends what the real head needs to land there.
        fl = lay.floor
        for fx, fy in ((0.2, 0.3), (0.8, 0.9), (0.5, 0.1)):
            target = (fl.x + fl.w * fx, fl.y + fl.d * fy, 0.0)
            pan, tilt = lay.aim(b, lay.heads(b)[m], target, m)
            x, y = _lands(truth, b, m, pan, tilt)
            assert math.hypot(x - target[0], y - target[1]) < 0.05, (b, m, fx, fy)


def test_the_guessed_model_was_why_the_real_beams_missed():
    """The same real heads, driven by the guess: their beams land well off the dots."""
    truth, _ = _real_rig(TRUTHS)
    guess = presets()["small-room-front"]
    worst = 0.0
    for (b, m) in TRUTHS:
        pan, tilt = guess.aim(b, guess.heads(b)[m], guess.ref_target("center"), m)
        x, y = _lands(truth, b, m, pan, tilt)
        worst = max(worst, math.hypot(x - guess.floor.cx, y - guess.floor.cy))
    assert worst > 1.0   # meters off the middle of the floor


def test_center_all_sends_every_calibrated_head_to_its_center_dot():
    truth, real = _real_rig(TRUTHS)
    eng = LooksEngine()
    eng.apply_venue(truth)
    eng.overrides.lineup = (0, "center")
    rig = default_rig()
    eng.render(Frame(8.5, 128.0, True, level=0.9, section=Section("drop", 0, 64, 0.9)), rig)
    for (b, m), raws in real.items():
        head = rig.bars[b - 1].movers[m]
        assert (head.pan, head.tilt) == pytest.approx(raws["center"], abs=1e-6)


def test_mirror_turns_a_head_around_its_calibrated_center_not_raw_half():
    lay = presets()["small-room-front"]
    lay.spots["bar1"].cal[0] = HeadCal(center=(0.31, 0.62))
    lay.spots["bar1"].cal[1] = HeadCal(center=(0.74, 0.58))
    before = {m: lay.aim(1, lay.heads(1)[m], lay.ref_target("near"), m) for m in (0, 1)}
    lay.flip_pan(1)
    for m, center in ((0, (0.31, 0.62)), (1, (0.74, 0.58))):
        assert lay.aim(1, lay.heads(1)[m], lay.ref_target("center"), m) == pytest.approx(center)   # the pivot
        after = lay.aim(1, lay.heads(1)[m], lay.ref_target("near"), m)
        assert after[0] - center[0] == pytest.approx(-(before[m][0] - center[0]), abs=1e-6)   # mirrored about it
        assert lay.spots["bar1"].cal[m].pan_invert


def test_mirror_on_an_uncalibrated_bar_still_finds_the_middle_of_the_floor():
    """Since the heads point along the bar at pan 0.5 (venue.HEAD_HOME, his 11-08 photos), Mirror on
    a bar with no calibrated head says pan turns the other way: the center's pan changes (the old
    value now points behind the bar), and every aim still lands where it should."""
    lay = copy.deepcopy(presets()["small-room-front"])
    lay.flip_pan(2)
    assert lay.spots["bar2"].pan_invert and not any(c.center for c in lay.spots["bar2"].cal)
    for m, p in enumerate(lay.heads(2)):
        x, y = _lands(lay, 2, m, *lay.aim(2, p, lay.ref_target("center"), m))
        assert math.hypot(x - lay.floor.cx, y - lay.floor.cy) < 0.05
        x, y = _lands(lay, 2, m, *lay.aim(2, p, lay.ref_target("near"), m))
        assert math.hypot(x - lay.floor.cx, y - lay.floor.y) < 0.05   # still on the floor, never outside it


def test_mirror_leaves_a_head_with_measured_dots_to_its_fit():
    truth, real = _real_rig({(1, 0): {"pan_invert": True}})
    truth.spots["bar1"].cal[0].points = {"near": real[(1, 0)]["near"]}
    truth.flip_pan(1)
    assert truth.spots["bar1"].cal[0].pan_invert   # unchanged: the dots decide


def test_calibration_saves_with_the_layout_and_older_layouts_read_back_unchanged():
    old = presets()["small-room-front"].to_dict()
    assert all("cal" not in f for f in old["fixtures"].values())
    d = json.loads(json.dumps(old))
    d["fixtures"]["bar2"]["cal"] = [{"center": [0.4, 0.6], "points": {"side": [0.3, 0.7]}, "pan_range": 530}, {}]
    back = Layout.from_dict(d).to_dict()
    assert back["fixtures"]["bar2"]["cal"][0]["center"] == [0.4, 0.6]
    assert back["fixtures"]["bar2"]["cal"][0]["pan_range"] == 530 and back["fixtures"]["bar2"]["cal"][1] == {}
    for bad in ([{"center": [2, 0]}, {}], [{"points": {"elsewhere": [0.1, 0.1]}}, {}], [{}]):
        d["fixtures"]["bar2"]["cal"] = bad
        with pytest.raises(ValueError):
            Layout.from_dict(d)
    d["fixtures"]["bar2"].pop("cal")
    d["fixtures"]["tetra1"]["cal"] = [{}, {}]
    with pytest.raises(ValueError):
        Layout.from_dict(d)


def test_a_calibrated_show_still_keeps_every_beam_in_front_of_its_bar():
    truth, _ = _real_rig(TRUTHS)
    eng = LooksEngine()
    eng.apply_venue(truth)
    for beat in range(0, 64, 3):
        rig = default_rig()
        eng.render(Frame(beat + 0.5, 128.0, True, level=0.9, section=Section("drop", 0, 64, 0.9)), rig)
        for b in (1, 2):
            for m, head in enumerate(rig.bars[b - 1].movers):
                if TRUTHS[(b, m)].get("swap"):
                    continue
                o = truth.heads(b)[m]
                d = truth.beam(b, o, head.pan, head.tilt, m)
                f = math.radians(truth.facing(f"bar{b}"))
                assert d[0] * math.sin(f) + d[1] * math.cos(f) >= -1e-6, (beat, b, m)


def test_the_calibrate_key_moves_its_head_with_every_head_lit_white():
    """1.12.3 (his 11-08 report "how do i turn the lights on"): calibrating lights every head on
    both bars as a white open spot, and only the picked head follows the raw values. 1.16.0: the
    picked head at full, the others dim (looks.CAL_OTHERS), so he can tell which beam is his."""
    class S:
        looks = LooksEngine()
    gl.handle_key("cal:2:1:0.25:0.8", S)
    assert S.looks.overrides.raw_head == (2, 1, 0.25, 0.8)
    rig = default_rig()
    S.looks.render(Frame(1.0, 128.0, True, level=0.9), rig)
    heads = [h for bar in rig.bars for h in bar.movers]
    assert all(h.color == 0 and h.gobo == 0 and h.strobe == 0 for h in heads)
    assert [h.dim for h in heads] == [CAL_OTHERS, CAL_OTHERS, CAL_OTHERS, 1.0]
    assert (rig.bars[1].movers[1].pan, rig.bars[1].movers[1].tilt) == (0.25, 0.8)
    assert S.looks.mode.startswith("calibrating GigBAR 2 left head")   # head 2 = left from the floor
    assert all(fx.dim == 0 for fx in (*rig.tetras, *rig.sticks))
    for bad in ("cal:3:0:0.5:0.5", "cal:1:2:0.5:0.5", "cal:1:0:1.5:0.5", "cal:1:0:x:0.5", "cal:"):
        gl.handle_key("cal:1:0:0.5:0.5", S)
        gl.handle_key(bad, S)
        assert S.looks.overrides.raw_head is None, bad


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(gigbar_app.updater, "check", lambda: (None, "no update in tests"))
    monkeypatch.setattr(gigbar_app, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(gigbar_app, "_enttec_port", lambda: None)
    monkeypatch.setattr(gigbar_app, "midi_port", lambda: "")
    opts = argparse.Namespace(seconds=0.0, bpm=128.0, no_browser=True, no_window=True,
                              updated=False, update_failed=False)
    a = gigbar_app.App(opts, gigbar_app.LogBuffer(tmp_path / "log.txt"))
    a.mixxx.running = False
    a.preview = gigbar_app.Preview("", LayoutStore(tmp_path / "layouts"), app=a)
    yield a
    a.quit.set()
    a.stop()
    if a.runner:
        a.runner.join(timeout=8)
    a.preview.close()
    show_settings.clear_play()


def wait(cond, s=6.0):
    end = time.monotonic() + s
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def call(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_calibrating_runs_the_lights_by_itself_and_moves_only_that_head(app):
    url, h = app.preview.url, {"X-Llano-Token": app.preview.token}
    assert call(url + "calibrate?b=1&m=1&p=0.2&t=0.9", b"", h)[0] == 200
    assert wait(lambda: app.running == "lineup")
    assert wait(lambda: app.preview.universe[29:32] == bytes([51, 230, 255]))   # head 2 of bar 1: pan, tilt, dim
    assert app.preview.universe[25] == round(CAL_OTHERS * 255) == app.preview.universe[65]   # the others lit, dim (1.16.0)
    for bad in ("b=3&m=0&p=0.5&t=0.5", "b=1&m=0&p=2&t=0.5", "b=1&m=x&p=0.5&t=0.5"):
        assert call(url + "calibrate?" + bad, b"", h)[0] == 400
    assert call(url + "calibrate?b=", b"", h)[0] == 200
    assert wait(lambda: app.preview.universe[29:32] != bytes([51, 230, 255]))     # back to the line-up
    assert call(url + "lineup?b=&s=", b"", h)[0] == 200
    assert wait(lambda: app.running is None, 3.0)


def test_the_layout_payload_and_the_mirror_action(app):
    url, h = app.preview.url, {"X-Llano-Token": app.preview.token, "Content-Type": "application/json"}
    lay = json.loads(call(url + "layout")[1])["layout"]
    assert set(lay["derived"]["dots"]) == set(REF_POINTS)
    assert len(lay["derived"]["aims"]["bar1"]) == 2 and lay["derived"]["miss"]["bar1"] == [None, None]
    body = json.dumps({"action": "flip", "bar": 2, "layout": lay}).encode()
    code, out = call(url + "layout", body, h)
    flipped = json.loads(out)["layout"]
    # a bar with no calibrated head turns the other way as a whole (venue.flip_pan, HEAD_HOME)
    assert code == 200 and flipped["fixtures"]["bar2"].get("pan_invert") and "cal" not in flipped["fixtures"]["bar2"]
    assert call(url + "layout", json.dumps({"action": "flip", "bar": 3, "layout": lay}).encode(), h)[0] == 400


def test_the_page_calibrates_and_draws_through_the_calibration():
    for s in ('id="centerall"', ">Center all<", 'data-head="2:1"', 'data-dot="near"', 'data-dot="side"',
              'id="setdot"', 'data-cal="swap"', 'data-cal="pan_range"', '"/calibrate?"', 'action: "flip"'):
        assert s in PAGE, s
    assert "beamDir(n+1, hd.pan, hd.tilt, m)" in PAGE and "c.center" in PAGE
