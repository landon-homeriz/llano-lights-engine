"""1.14.1, the 11-08 correction: each GigBAR Move is 2 moving heads, 2 RGB derbies, 2 RGB+UV pars,
4 white/UV strobes and a red/green laser (11 parts per bar).

Checked against the Chauvet manual's 35CH table (Rev. 3/4): every part's channels were already mapped,
but ch20 (strobe control) 0-9 is the strobes' blackout and the show sent 0 there under every white
or UV level, so the 4 strobes never flashed; and the room picture read only Par R (ch1-5). Control a
light picks each part by name ("Bar 1: Spot L" ... "Bar 1: Laser"), and Lights on can light the whole
bar. R is the first of each pair on the map (head 1 is the right one from the floor, 1.12.3).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
import gigbar_app  # noqa: E402
from tools.gigbar_lights import __main__ as gl, settings_contract as contract, show_settings  # noqa: E402
from tools.gigbar_lights.looks import Frame, LooksEngine, Overrides  # noqa: E402
from tools.gigbar_lights.rig import ALL_STROBING, GigBarMove, default_rig  # noqa: E402

PAGE = (Path(gigbar_app.__file__).parent / "preview.html").read_text()
APP_PAGE = (Path(gigbar_app.__file__).parent / "app.html").read_text()
ON = {**gigbar_app.MANUAL_DEFAULT, "on": True}


@pytest.fixture(autouse=True)
def _fresh_settings():
    show_settings.set_current(contract.defaults())
    yield
    show_settings.set_current(contract.defaults())


def bar1(rig):
    return rig.render()[0:35]


def test_a_white_or_uv_strobe_level_runs_all_strobing_not_the_blackout():
    b = GigBarMove("b", 1)
    assert b.channels()[19] == 0                       # nothing asked: blackout, as before
    b.strobe_white = 1.0
    assert b.channels()[19:22] == [ALL_STROBING, 255, 0]
    assert 190 <= ALL_STROBING <= 209                  # the manual's "All strobing" band
    b.strobe_white, b.strobe_uv = 0.0, 0.5
    assert b.channels()[19:22] == [ALL_STROBING, 0, 128]
    b.strobe_program = 3
    assert b.channels()[19] == 55                      # a chosen program still wins (50-69)


def test_the_show_now_flashes_the_strobes_it_asks_for():
    eng, rig = LooksEngine(), default_rig()
    eng.overrides = Overrides(strobe=True)
    eng.render(Frame(8.0, 128.0, True, level=0.9, track_key=3), rig)
    assert bar1(rig)[19] == ALL_STROBING and bar1(rig)[20] > 0


def test_every_gigbar_part_is_its_own_pick_by_name():
    names = [p["name"] for l in gigbar_app.light_list() for p in l.get("parts", [])]
    assert names[:8] == ["Bar 1: Spot L", "Bar 1: Spot R", "Bar 1: Derby L", "Bar 1: Derby R",
                         "Bar 1: Par L", "Bar 1: Par R", "Bar 1: Strobes", "Bar 1: Laser"]
    assert names[8] == "Bar 2: Spot L" and len(names) == 16
    assert gigbar_app.clean_manual({"light": "0:par_l", "on": True}, 12)[0] == ["0:par_l"]
    for bad in ("0:wheel", "2:par_l:x", "x:par_l"):
        with pytest.raises(ValueError):
            gigbar_app.clean_manual({"light": bad, "on": True}, 12)


@pytest.mark.parametrize("part, check", [
    ("par_l", lambda u: u[5:10] == bytes([255, 0, 0, 0, 127]) and u[0:5] == bytes(5)),
    ("par_r", lambda u: u[0:5] == bytes([255, 0, 0, 0, 127]) and u[5:10] == bytes(5)),
    ("derby_l", lambda u: u[13] == 180 and u[10] == 5),        # white band 175-199; Derby R stays blackout
    ("derby_r", lambda u: u[10] == 180 and u[13] == 5),
    ("spot_r", lambda u: u[25] == 255 and u[31] == 0),         # head 1's dimmer only
    ("spot_l", lambda u: u[31] == 255 and u[25] == 0),
    ("strobes", lambda u: u[19:21] == bytes([ALL_STROBING, 255])),
    ("laser", lambda u: u[16] == 125),                         # red + green, 120-159
])
def test_each_part_lights_alone(part, check):
    rig = default_rig()
    gigbar_app.apply_manual(rig, {f"0:{part}": {**ON, "color": "#ff0000"}})
    u = bar1(rig)
    assert check(u), list(u)
    others = [k for k, _ in gigbar_app.GIGBAR_PARTS if k != part]
    rig2 = default_rig()
    gigbar_app.apply_manual(rig2, {f"0:{k}": dict(gigbar_app.MANUAL_DEFAULT) for k in others})
    assert bar1(rig2) == bar1(default_rig())   # every other part off: the bar at rest


def test_a_part_turned_off_goes_dark_over_the_whole_bar():
    rig = default_rig()
    gigbar_app.apply_manual(rig, {0: {**ON, "laser": "red", "par_uv": 0.5}, "0:laser": dict(gigbar_app.MANUAL_DEFAULT)})
    u = bar1(rig)
    assert u[16] == 5 and u[0] == 255 and u[3] == 128      # laser dark; the pars still on, with their UV


def test_lights_on_whole_bar_lights_all_eleven_parts():
    eng, rig = LooksEngine(), default_rig()
    eng.overrides = Overrides(lineup=(1, "center"), lights_whole=True)
    eng.render(Frame(0.0, 128.0, False, track_key=3), rig)
    u = bar1(rig)
    assert u[0:3] == bytes([255] * 3) and u[5:8] == bytes([255] * 3)    # Par R, Par L white
    assert u[10] == 180 and u[13] == 180                                 # Derby R, Derby L white
    assert u[16] == 125 and u[19] == ALL_STROBING and u[20] == 255      # laser, the 4 strobes
    assert u[25] == 255 and u[31] == 255 and "whole bar" in eng.mode    # both spots
    eng.overrides = Overrides(lineup=(1, "center"))
    eng.render(Frame(0.0, 128.0, False, track_key=3), rig)
    assert bar1(rig)[0:23] == bar1(default_rig())[0:23] and bar1(rig)[25] == 255   # spots only, as 1.12.3


def test_the_line_up_key_takes_the_whole_bar():
    class _Show:   # handle_key reads show.looks.overrides
        def __init__(self):
            self.looks = LooksEngine()
            self.looks.overrides = Overrides(lineup=(0, "center"))
    for key, want in (("lights:2", (True, True)), ("lights:1", (True, False)), ("lights:0", (False, False))):
        sh = _Show()
        assert gl.handle_key(key, sh)
        ov = sh.looks.overrides
        assert (ov.lights_on, ov.lights_whole) == want


def test_labels_read_the_rig_blocks_address():
    d = contract.defaults()
    d["rig"]["addresses"]["tetra1"] = 301
    show_settings.set_current(contract.normalize(d))
    row = next(l for l in gigbar_app.light_list() if l["name"].startswith("Tetra 6 #1"))
    assert row["address"] == 301


def test_the_pages_name_every_part():
    for name in ("Spot ${m==1?\"R\":\"L\"}", "Par R", "Par L", "Derby R", "Derby L", "Strobes", "Laser"):
        assert name in PAGE
    assert 'id="lightswhole"' in PAGE and "lights?on=\" + (on ? (lightsWhole ? 2 : 1) : 0)" in PAGE
    assert "if (c < 10) return" in PAGE and "bar.pars = [0, 5].map" in PAGE
    assert 'data-for="par"' in APP_PAGE and "p.name" in APP_PAGE and 'data-k="par_uv"' in APP_PAGE
