"""The live screen's fixes from his recording (1.7.0).

1:28 strobe and blackout show whether they are on; 1:45 tap tempo has a visible beat; 3:34 and
4:04 Stop sits beside what is running and takes two clicks; 4:13 Test each light runs with no
live show and no lights box (the room picture); 5:44 Start with Mixxx; 7:00 the live show says
the music comes from Mixxx, Spotify or YouTube Music, and the demo can play on the lights;
7:24 Check my setup says what it checks and what it found.
"""
import argparse
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
import gigbar_app  # noqa: E402
from tools.gigbar_lights.venue import LayoutStore  # noqa: E402

PAGE = (Path(gigbar_app.__file__).parent / "app.html").read_text()


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(gigbar_app.updater, "check", lambda: (None, "no update in tests"))
    monkeypatch.setattr(gigbar_app, "app_data_dir", lambda: tmp_path)
    opts = argparse.Namespace(seconds=0.0, bpm=128.0, no_browser=True, no_window=True,
                              updated=False, update_failed=False)
    a = gigbar_app.App(opts, gigbar_app.LogBuffer(tmp_path / "log.txt"))
    a.preview = gigbar_app.Preview("", LayoutStore(tmp_path / "layouts"), app=a)
    yield a
    a.quit.set()
    a.stop()
    if a.runner:
        a.runner.join(timeout=8)
    a.preview.close()


def wait(cond, s=6.0):
    end = time.monotonic() + s
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_a_running_show_reports_its_buttons_and_beat_and_a_key_shows_at_once(app):
    assert app.run("demo")[0] == 200
    assert wait(lambda: app.state()["live"] is not None)
    live = app.state()["live"]
    assert live["bpm"] > 0 and not live["blackout"] and not live["strobe"] and live["master"] == 1.0
    app.preview.keys.put("b")
    app.preview.keys.put("-")
    assert wait(lambda: app.state()["live"]["blackout"] and app.state()["live"]["master"] == 0.9, 2.0)
    b1 = app.state()["live"]
    time.sleep(0.6)
    b2 = app.state()["live"]
    assert b2["beat"] > b1["beat"] and b2["at"] > b1["at"]   # the window's beat light runs from these
    app.stop()
    assert wait(lambda: app.running is None)
    assert app.state()["live"] is None


def test_test_each_light_runs_with_no_box_in_the_picture_and_stop_ends_it(app, monkeypatch):
    monkeypatch.setattr(gigbar_app, "find_port", lambda: None)
    assert app.run("test")[0] == 200
    assert wait(lambda: "Light 1 of 12" in app.preview.status)
    assert "in the picture" in app.preview.status
    assert wait(lambda: any(app.preview.universe))         # the room picture sees a light lit
    assert app.state()["show"] is False                     # the show keys stay off during the test
    app.stop()
    assert wait(lambda: app.running is None, 3.0)
    assert app.last_run.endswith("stopped")
    assert not any(app.preview.universe)


def test_the_demo_on_the_lights_plays_even_when_the_box_will_not_open(app, monkeypatch):
    """No adapter never stops a run (his ask, 2026-11-13): a box that is found but won't open (SoundSwitch
    holds it) leaves the demo playing in the room picture, still looking for the box."""
    assert app.run("live", lights=True)[0] == 400
    monkeypatch.setattr(gigbar_app, "_enttec_port", lambda: "COM3")   # found, but it won't open
    assert app.run("demo", lights=True)[0] == 200
    time.sleep(0.5)
    assert app.running == "demo" and "not connected" in app.preview.mode
    app.stop()
    assert wait(lambda: app.running is None, 3.0)


def test_check_that_finds_something_missing_says_so_rather_than_didnt_start(app, monkeypatch):
    monkeypatch.setattr(gigbar_app, "setup_status", lambda: [{"key": "x", "label": "App files", "ok": False, "detail": "missing"}])
    assert app.run("check")[0] == 200
    assert wait(lambda: app.running is None)
    assert "found something to fix" in app.last_run


def test_start_with_mixxx_starts_the_live_show_once_when_mixxx_opens(app):
    started = []
    app.run = lambda mode, *a, **k: started.append(mode) or (200, {"ok": True})
    app.set_auto_live(True)
    assert gigbar_app.App(app.opts, app.log).auto_live is True      # remembered across launches
    t = threading.Thread(target=app.watch_mixxx, args=(0.02,), daemon=True)
    t.start()
    app.mixxx.running = False
    time.sleep(0.1)
    app.mixxx.running = True
    assert wait(lambda: started == ["live"], 2.0)
    time.sleep(0.15)
    assert started == ["live"]                    # still open: not again
    app.mixxx.running = False
    time.sleep(0.1)
    app.set_auto_live(False)
    app.mixxx.running = True
    time.sleep(0.15)
    assert started == ["live"]                    # switched off: Mixxx opening starts nothing
    app.quit.set()
    t.join(timeout=2)


def test_the_window_shows_toggle_state_a_beat_light_and_a_two_click_stop():
    for needed in ('data-on="blackout"', 'data-on="strobe"', 'aria-pressed', 'class="beat"', 'id="bpm"',
                   'Click again to stop', 'id="now"', 'id="autolive"', 'id="onlights"',
                   'This app makes no sound itself', 'Nothing changes in Mixxx', 'Checks the app\'s files'):
        assert needed in PAGE, needed
    header = PAGE[PAGE.index("<header>"):PAGE.index("</header>")]
    # 1.10.0 (his recording 0:36): Stop is pinned in the header so it never scrolls away, beside
    # what is running on the left, never back in the right-hand corner by the window's X (1.7.0)
    assert header.index('id="now"') < header.index('id="stop"') < header.index('class="grow"')
