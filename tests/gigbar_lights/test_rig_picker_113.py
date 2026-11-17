"""1.13.0, the rig picker (Llano BL #11606, his 11-08 "I've only got 3 tetras running right now").

How many of each light are set up tonight (settings rig.counts: GigBARs 0-2, Tetras 0-6, Freedom
Sticks 0-4, the first N of each) and saved rigs by name (rig.saved). The show, the room picture,
the line-up, calibration and Test each light use only tonight's lights; a light left out sends
nothing (its DMX slots stay 0) and every address stays where it was.
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
import gigbar_app  # noqa: E402
from tools.gigbar_lights import settings_contract as contract, show_settings  # noqa: E402
from tools.gigbar_lights.looks import Frame, LooksEngine, Overrides  # noqa: E402
from tools.gigbar_lights.rig import active_counts, default_rig  # noqa: E402
from tools.gigbar_lights.show_script import Section  # noqa: E402
from tools.gigbar_lights.venue import LayoutStore, presets  # noqa: E402

PAGE = (Path(gigbar_app.__file__).parent / "preview.html").read_text()
APP_PAGE = (Path(gigbar_app.__file__).parent / "app.html").read_text()
DROP = Section("drop", 0, 64, 0.9)


@pytest.fixture(autouse=True)
def _fresh_settings():
    show_settings.set_current(contract.defaults())
    yield
    show_settings.set_current(contract.defaults())


def settings(**counts):
    d = contract.defaults()
    d["rig"]["counts"].update(counts)
    return contract.normalize(d)


def lit(beat=8.0):
    return Frame(beat, 128.0, True, level=0.9, section=DROP, track_key=3)


def test_counts_clamp_to_the_rig_and_default_to_every_light():
    assert active_counts(None) == {"bars": 2, "tetras": 6, "sticks": 4}
    assert active_counts({"bars": 1, "tetras": 9, "sticks": -1}) == {"bars": 1, "tetras": 6, "sticks": 0}
    assert active_counts({"tetras": True}) == {"bars": 2, "tetras": 6, "sticks": 4}


def test_a_light_left_out_sends_nothing_and_addresses_never_move():
    cfg = settings(bars=1, tetras=3, sticks=0)
    rig = default_rig()
    LooksEngine(settings=cfg).render(lit(), rig)
    full = rig.render(contract.defaults()["rig"])
    u = rig.render(cfg["rig"])
    assert u[0:35] == full[0:35] and any(u[0:35])            # GigBAR 1 at address 1, as before
    assert u[40:75] == bytes(35)                             # GigBAR 2 dark
    assert u[80:110] == full[80:110] and any(u[80:110])      # Tetras 1-3 at 81, 91, 101
    assert u[110:140] == bytes(30)                           # Tetras 4-6 dark
    assert u[150:190] == bytes(40)                           # every stick dark


def test_three_tetras_chase_as_a_row_of_three():
    eng = LooksEngine(settings=settings(tetras=3))
    eng.apply_venue(next(iter(presets().values())))
    rig = default_rig()
    eng.render(lit(), rig)
    assert len(eng.tetra_order) == 3 and eng.tetra_order[0] == 0.0
    eng.settings = settings(tetras=6)
    eng.render(lit(), rig)
    assert len(eng.tetra_order) == 6


@pytest.mark.parametrize("counts", [{"bars": 0, "tetras": 0, "sticks": 0}, {"bars": 1, "tetras": 1, "sticks": 1},
                                    {"bars": 2, "tetras": 0, "sticks": 4}, {"bars": 0, "tetras": 6, "sticks": 0}])
def test_every_look_plays_on_any_rig(counts):
    eng = LooksEngine(settings=settings(**counts))
    eng.apply_venue(next(iter(presets().values())))
    rig = default_rig()
    for beat in (0.0, 4.5, 31.0, 63.9):
        eng.render(lit(beat), rig)
        eng.render(Frame(beat, 128.0, False, track_key=3), rig)
        rig.render(settings(**counts)["rig"])
    eng.overrides = Overrides(autoloop_override=True)
    eng.render(lit(), rig)


def test_line_up_and_calibration_skip_a_gigbar_left_out():
    eng = LooksEngine(settings=settings(bars=1))
    rig = default_rig()
    eng.overrides = Overrides(lineup=(2, "center"))
    eng.render(lit(), rig)
    assert "isn't in tonight's rig" in eng.mode
    eng.overrides = Overrides(raw_head=(2, 0, 0.5, 0.5))
    eng.render(lit(), rig)
    assert "isn't in tonight's rig" in eng.mode
    eng.overrides = Overrides(lineup=(0, "center"))
    eng.render(lit(), rig)
    assert rig.bars[0].movers[0].dim == 1.0 and "both" in eng.mode


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))   # settings.json and layouts in ~/.gigbar_lights: never the real one
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


def test_the_window_sets_tonights_lights_and_saves_rigs_by_name(app):
    assert app.state()["rig"]["counts"] == {"bars": 2, "tetras": 6, "sticks": 4}
    assert app.post("rig", {"counts": {"tetras": 3}})[0] == 200
    assert show_settings.current()["rig"]["counts"] == {"bars": 2, "tetras": 3, "sticks": 4}
    assert app.post("rig", {"counts": {"bars": 1, "sticks": 0}})[0] == 200
    code, body = app.post("rig", {"save": "Small gig"})
    assert code == 200 and body["rig"]["saved"] == {"small-gig": {"bars": 1, "tetras": 3, "sticks": 0}}
    app.post("rig", {"counts": {"bars": 2, "tetras": 6, "sticks": 4}})
    assert app.post("rig", {"use": "small-gig"})[0] == 200
    assert show_settings.current()["rig"]["counts"] == {"bars": 1, "tetras": 3, "sticks": 0}
    st = app.state()
    assert [l["present"] for l in st["lights_list"]] == [True, False] + [True] * 3 + [False] * 3 + [False] * 4
    assert app.post("rig", {"delete": "small-gig"})[0] == 200
    assert show_settings.current()["rig"]["saved"] == {}
    # the change waits for Llano like any other laptop change, so llano.app/lights shows it too
    assert any(p["path"] == "rig.counts.tetras" for p in app.link.pending) or not app.link.linked


@pytest.mark.parametrize("msg", [{"counts": {"tetras": 7}}, {"counts": {"bars": -1}}, {"counts": {"sticks": "2"}},
                                 {"save": "!!"}, {"use": "nope"}, {"delete": "nope"}, {}])
def test_a_bad_rig_change_is_refused(app, msg):
    assert app.post("rig", msg)[0] in (400, 404)
    assert show_settings.current()["rig"]["counts"] == {"bars": 2, "tetras": 6, "sticks": 4}


def test_line_up_and_calibrate_refuse_a_gigbar_left_out(app):
    app.post("rig", {"counts": {"bars": 1}})
    code, body = app.lineup("2", "center")
    assert code == 409 and "tonight's rig" in body["error"]
    code, body = app.calibrate("cal:2:0:0.50000:0.50000")
    assert code == 409 and "tonight's rig" in body["error"]


def test_the_pages_show_only_tonights_lights():
    assert 'id="rig"' in APP_PAGE and "Tonight's lights" in APP_PAGE and '"/api/rig"' in APP_PAGE
    assert "x.present === false" in APP_PAGE
    assert "function setCounts" in PAGE and "out.tetras.length = CNT.tetras" in PAGE
    assert "if (!present(id)) continue" in PAGE   # the layout editor can't grab a light left out
