"""1.12.3, the 11-08 report: calibration had no way to turn the lights on,
the GigBAR's other parts (the lasers) had no channels, calibration did not survive a restart,
and the heads' left and right were swapped.

Lights on: the line-up page lights every GigBAR head as a white open spot at full, by itself, and a
switch turns them off and on. Calibration keeps: every Set saves to his layout file, which a restart,
an update or a reboot reads back. Left and right are as he faces the bar from the dance floor.
Every GigBAR Move 35CH channel is driven as the Chauvet manual (Rev. 3/4) and QLC+ map it.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
import gigbar_app  # noqa: E402
from tools.gigbar_lights import __main__ as gl  # noqa: E402
from tools.gigbar_lights import settings_contract as contract, show_settings  # noqa: E402
from tools.gigbar_lights.looks import Frame, LooksEngine  # noqa: E402
from tools.gigbar_lights.rig import FreedomStick, GigBarMove, Tetra6, default_rig  # noqa: E402
from tools.gigbar_lights.venue import LayoutStore, presets  # noqa: E402

PAGE = (Path(gigbar_app.__file__).parent / "preview.html").read_text()
APP_PAGE = (Path(gigbar_app.__file__).parent / "app.html").read_text()


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
    a.preview = gigbar_app.Preview("", LayoutStore(tmp_path / "profile"), app=a)
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
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


HEAD_DIMS = (25, 31, 65, 71)   # universe index of each head's dimmer: ch26/32 of bars at 1 and 41


# --- Lights on --------------------------------------------------------------------------------

def test_lights_on_starts_the_lineup_lit_and_the_switch_turns_the_heads_off_and_on(app):
    url, h = app.preview.url, {"X-Llano-Token": app.preview.token}
    assert call(url + "lights?on=1", b"", h)[0] == 200
    assert wait(lambda: app.running == "lineup")
    assert wait(lambda: all(app.preview.universe[i] == 255 for i in HEAD_DIMS))
    for i in HEAD_DIMS:   # white (wheel slot open) and an open round spot (no gobo), steady
        assert app.preview.universe[i + 1] == 0 and app.preview.universe[i + 2] == 4 and app.preview.universe[i + 3] == 4
    assert call(url + "lights?on=0", b"", h)[0] == 200
    assert wait(lambda: all(app.preview.universe[i] == 0 for i in HEAD_DIMS))
    assert app.running == "lineup"   # dark, still lined up: on again shows the beams
    assert call(url + "lights?on=1", b"", h)[0] == 200
    assert wait(lambda: all(app.preview.universe[i] == 255 for i in HEAD_DIMS))
    assert call(url + "lights?on=3", b"", h)[0] == 400   # 2 is the whole bar since 1.14.1
    assert call(url + "lineup?b=&s=", b"", h)[0] == 200   # leaving the page: the heads go dark
    assert wait(lambda: app.running is None, 3.0)


def test_lights_off_with_nothing_running_starts_nothing(app):
    url, h = app.preview.url, {"X-Llano-Token": app.preview.token}
    assert call(url + "lights?on=0", b"", h)[0] == 200
    time.sleep(0.3)
    assert app.running is None


def test_leaving_the_lineup_ends_calibrating_and_the_next_one_starts_lit():
    class S:
        looks = LooksEngine()
    for k in ("lineup:0:center", "cal:1:0:0.3:0.7", "lights:0"):
        gl.handle_key(k, S)
    ov = S.looks.overrides
    assert ov.raw_head and not ov.lights_on
    rig = default_rig()
    S.looks.render(Frame(1.0, 128.0, True, level=0.9), rig)
    assert all(m.dim == 0 for bar in rig.bars for m in bar.movers) and S.looks.mode.endswith("lights off")
    gl.handle_key("lineup:", S)
    assert ov.lineup is None and ov.raw_head is None and ov.lights_on


def test_the_page_has_the_switch_and_lights_on_by_itself():
    for s in ('id="lightson"', ">Turn the lights off<", '"/lights?on="', "setLights(!lightsOn)",
              "if (!lightsOn) setLights(true)", "if (LINEVIEW) { sendLineup(); showLights(); }"):
        assert s in PAGE, s


# --- calibration keeps ------------------------------------------------------------------------

def test_every_set_saves_the_calibration_and_a_restart_reads_it_back(app, tmp_path):
    """What the page's keepCal() sends on Set center: a preset is kept as his own copy, a second
    Set rewrites that copy, and a fresh store on the same profile folder (a restart, an update or
    a reboot: the folder is outside the install) has every head's dots."""
    url, h = app.preview.url, {"X-Llano-Token": app.preview.token, "Content-Type": "application/json"}
    lay = json.loads(call(url + "layout")[1])["layout"]
    assert lay["preset"]
    lay["fixtures"]["bar1"]["cal"] = [{"center": [0.40, 0.80]}, {}]
    label = lay["label"] + " (mine)"
    code, out = call(url + "layout", json.dumps({"action": "save", "layout": {**lay, "name": label, "label": label,
                                                                             "preset": False}}).encode(), h)
    assert code == 200
    mine = json.loads(out)["layout"]
    for b, cal in (("bar1", [{"center": [0.40, 0.80]}, {"center": [0.55, 0.81]}]),
                   ("bar2", [{"center": [0.45, 0.79]}, {"center": [0.60, 0.82]}])):
        mine["fixtures"][b]["cal"] = cal
        code, out = call(url + "layout", json.dumps({"action": "save", "layout": mine}).encode(), h)
        assert code == 200
        mine = json.loads(out)["layout"]
    saved = list((tmp_path / "profile" / "layouts").glob("*.json"))
    assert len(saved) == 1   # one file, rewritten: not a new "(mine) (mine)" copy per Set

    again = LayoutStore(tmp_path / "profile").current()   # the restart
    assert again.label == label
    assert [c.center for c in again.spots["bar1"].cal] == [(0.40, 0.80), (0.55, 0.81)]
    assert [c.center for c in again.spots["bar2"].cal] == [(0.45, 0.79), (0.60, 0.82)]


def test_a_tried_layout_survives_the_next_run(app):
    """Picking a head starts the line-up run; that start used to swap his unsaved try for the
    saved layout, dropping the dots before it (his 11-08 layout: only GigBAR 1's head 2)."""
    url, h = app.preview.url, {"X-Llano-Token": app.preview.token, "Content-Type": "application/json"}
    lay = json.loads(call(url + "layout")[1])["layout"]
    lay["fixtures"]["bar2"]["cal"] = [{"center": [0.5, 0.8]}, {}]
    assert call(url + "layout", json.dumps({"action": "try", "layout": lay}).encode(), h)[0] == 200
    assert call(url + "calibrate?b=1&m=0&p=0.5&t=0.8", b"", {"X-Llano-Token": app.preview.token})[0] == 200
    assert wait(lambda: app.running == "lineup")
    assert app.preview.layout.spots["bar2"].cal[0].center == (0.5, 0.8)
    assert call(url + "lineup?b=&s=", b"", {"X-Llano-Token": app.preview.token})[0] == 200
    assert wait(lambda: app.running is None, 3.0)


def test_the_page_saves_on_every_set():
    assert "async function keepCal(" in PAGE
    assert 'keepCal(() => { $("#cmsg").textContent = calStatus() + " Saved."; })' in PAGE


# --- left and right ---------------------------------------------------------------------------

def test_left_and_right_are_as_seen_from_the_dance_floor():
    """Head 1 (ch24-29) sits on the bar's own left as it faces out (venue.heads), which is the
    RIGHT as he faces the bar from the dance floor; picking "left" moved the right-hand head."""
    assert '<button data-head="1:1">GigBAR 1 left</button><button data-head="1:0">GigBAR 1 right</button>' in PAGE
    assert '<button data-head="2:1">GigBAR 2 left</button><button data-head="2:0">GigBAR 2 right</button>' in PAGE
    assert 'const HEADNAME = ["right", "left"];' in PAGE
    # the bar card draws head 1 (Spot R) at the right end, as the manual's Front Panel View spaces it (1.17.1)
    assert 'class="head down m${m}" style="--x:${m==1?93:7}%"' in PAGE
    lay = presets()["small-room-front"]
    # From the floor, looking toward the booth (-y), the viewer's right is +x, as the view from the
    # dance floor draws it (1.16.0: this said -x, so both pictures moved the left head when he
    # picked GigBAR 2 right; test_head_mapping_116 pins it from the page's own camera).
    for b in (1, 2):
        h1, h2 = lay.heads(b)
        assert h1[0] > h2[0], b


# --- every 35CH channel (manual Rev. 3/4 and QLC+ Chauvet-GigBAR-Move.qxf) ---------------------

def test_every_gigbar_channel_is_driven_in_its_manual_band():
    bar = GigBarMove("x", 1)
    assert bar.channels() == [0] * 10 + [5, 0, 0, 5, 0, 0, 5, 0, 0, 0, 0, 0, 0] + [128, 128, 0, 0, 4, 4] * 2
    bar.laser, bar.laser_strobe, bar.laser_rotate = "alternate", 1.0, -1.0
    bar.strobe_program, bar.strobe_uv, bar.strobe_speed = 3, 1.0, 0.5
    bar.derbies[0].color, bar.derbies[0].rotate = "auto2", -0.5
    c = bar.channels()
    assert 225 <= c[10] <= 255 and 134 <= c[12] <= 255          # derby: two-color auto, counter-clockwise
    assert 240 <= c[16] <= 255 and c[17] == 239 and c[18] == 255  # laser: alternate flash, strobe, CCW
    assert 50 <= c[19] <= 69 and c[21] == 255 and c[22] == 128   # strobe program 3, UV strobe, speed
    bar.strobe_white = 0.5
    c = bar.channels()
    assert c[20] == 128 and c[21] == 0   # the manual: ch21 and ch22 never together, white wins
    for name, lo, hi in (("red", 40, 79), ("green", 80, 119), ("both", 120, 159), ("red_flash", 160, 199),
                         ("green_flash", 200, 239)):
        bar.laser = name
        assert lo <= bar.channels()[16] <= hi, name
    bar.strobe_program = 10
    assert 190 <= bar.channels()[19] <= 209   # all strobing


def test_tetra_and_freedom_stick_maps_match_qlc():
    t = Tetra6("t", 81)   # QLC+ Venue-Tetra-6 "6 Channel": R G B Amber Dimmer Strobe
    t.red, t.amber, t.dim, t.strobe = 1.0, 0.5, 1.0, 0.0
    assert t.channels() == [255, 0, 0, 128, 255, 0]
    s = FreedomStick("s", 151)   # "8 Channel": Dimmer R G B Macros Strobe Auto Speed; macros/auto 0-10 off
    s.dim, s.blue, s.strobe = 1.0, 1.0, 0.0
    assert s.channels() == [255, 0, 0, 255, 0, 0, 0, 0]
    s.strobe = 0.01
    assert s.channels()[5] >= 11   # the stick's strobe starts at 11


def test_crowd_safe_caps_the_new_strobes():
    eng = LooksEngine()
    rig = default_rig()
    for bar in rig.bars:
        bar.laser_strobe, bar.strobe_program, bar.laser = 1.0, 5, "alternate"
    eng._crowd_safe(rig)
    for bar in rig.bars:
        assert bar.laser_strobe <= contract.SAFE_STROBE_MAX and bar.strobe_program == 0 and bar.laser == "both"


def test_the_show_turns_the_derbies_and_laser_both_ways_and_flashes_the_laser():
    from tools.gigbar_lights.show_script import Section
    eng = LooksEngine()
    seen = set()
    for beat in (2.0, 14.5, 34.0):
        rig = default_rig()
        eng.render(Frame(beat, 128.0, True, level=0.9, section=Section("drop", 0, 64, 0.9)), rig)
        bar = rig.bars[0]
        seen.add((bar.laser_rotate > 0, bar.derbies[0].rotate > 0))
        if beat == 14.5:
            assert bar.laser_strobe > 0
    assert (True, True) in seen and (False, False) in seen


# --- the per-light panel ----------------------------------------------------------------------

def test_the_panel_drives_every_gigbar_light():
    ids, change = gigbar_app.clean_manual({"light": "0", "on": True, "derby": "auto", "derby_spin": -0.5,
                                           "laser": "green_flash", "laser_strobe": 0.4, "laser_spin": 0.3,
                                           "white": 0, "uv": 0.8, "head_color": 3, "gobo": 2}, 12)
    lights = {0: {**gigbar_app.MANUAL_DEFAULT, **change}}
    rig = default_rig()
    gigbar_app.apply_manual(rig, lights)
    bar = rig.bars[0]
    assert bar.derbies[0].color == "auto" and bar.derbies[1].rotate == -0.5
    assert (bar.laser, bar.laser_strobe, bar.laser_rotate) == ("green_flash", 0.4, 0.3)
    assert bar.strobe_uv == 0.8 and [(m.color, m.gobo) for m in bar.movers] == [(3, 2), (3, 2)]
    for bad in ({"laser": "blue"}, {"derby": "pink"}, {"gobo": 9}, {"head_color": True}):
        with pytest.raises(ValueError):
            gigbar_app.clean_manual({"light": "0", **bad}, 12)
    for s in ('id="mgig"', 'data-k="laser"', 'data-k="derby"', 'data-k="uv"', 'data-k="gobo"', 'data-k="laser_spin"'):
        assert s in APP_PAGE, s
