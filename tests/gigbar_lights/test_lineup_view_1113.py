"""Line up my lights gets its own view (1.11.3, his 2:40 PM recording on 2026-11-08).

0:44 the line-up sat under the room picture, so lining up lost the view; 0:57 pressing the middle
of the dance floor did nothing with no show running ("it doesn't even start"); 1:51 at the venue
it has to drive the lights by itself, with no demo; 2:02 all four heads meet on one dot at the
middle of the floor, so he knows everything is aimed; 2:23 one page where he picks a light and
nudges it while he watches the room.
"""
import argparse
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
from tools.gigbar_lights.looks import Frame, LooksEngine  # noqa: E402
from tools.gigbar_lights.rig import default_rig  # noqa: E402
from tools.gigbar_lights.show_script import Section  # noqa: E402
from tools.gigbar_lights.venue import LayoutStore, presets  # noqa: E402

PAGE = (Path(gigbar_app.__file__).parent / "preview.html").read_text()
HEAD_DIMS = (25, 31, 65, 71)   # each GigBAR head's dimmer: bar 1 at address 1, bar 2 at 41 (35CH)


def _lands(lay, bar, m, head):
    o = lay.heads(bar)[m]
    d = lay.beam(bar, o, head.pan, head.tilt)
    t = -o[2] / d[2]
    return o[0] + d[0] * t, o[1] + d[1] * t


def test_both_gigbars_put_all_four_heads_on_one_dot_at_the_middle_of_the_floor():
    for name in ("small-room-front", "open-space"):
        lay = presets()[name]
        eng = LooksEngine()
        eng.apply_venue(lay)
        eng.overrides.lineup = (0, "center")
        rig = default_rig()
        eng.render(Frame(8.5, 128.0, True, level=0.9, section=Section("drop", 0, 64, 0.9)), rig)
        assert eng.mode == "line-up: both GigBARs at the middle of the dance floor"
        for b in (1, 2):
            for m, head in enumerate(rig.bars[b - 1].movers):
                x, y = _lands(lay, b, m, head)
                assert math.hypot(x - lay.floor.cx, y - lay.floor.cy) < 0.15, (name, b, m)
                assert head.dim == 1.0 and head.strobe == 0
        assert all(m.color == 0 and m.gobo == 0 for bar in rig.bars for m in bar.movers)   # white spots (1.12.3)
        assert all(fx.dim == 0 for fx in (*rig.tetras, *rig.sticks))


def test_the_window_key_takes_both_bars():
    class S:
        looks = LooksEngine()
    gl.handle_key("lineup:0:center", S)
    assert S.looks.overrides.lineup == (0, "center")


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


def test_lining_up_with_nothing_running_lights_the_heads_by_itself_and_done_ends_it(app):
    assert app.lineup("1", "center")[0] == 200
    assert wait(lambda: app.running == "lineup")
    assert wait(lambda: app.preview.universe[HEAD_DIMS[0]] == 255)
    assert app.preview.universe[HEAD_DIMS[2]] == 0   # GigBAR 2 stays dark
    assert app.lineup("0", "center")[0] == 200
    assert wait(lambda: all(app.preview.universe[i] == 255 for i in HEAD_DIMS))
    assert app.lineup("", "")[0] == 200
    assert wait(lambda: app.running is None, 3.0)
    assert app.preview.universe[HEAD_DIMS[0]] == 0   # lights left dark


def test_lining_up_over_a_running_show_leaves_the_show_running_when_done(app):
    assert app.run("demo")[0] == 200
    assert wait(lambda: app.running == "demo")
    assert app.lineup("0", "center")[0] == 200
    assert wait(lambda: all(app.preview.universe[i] == 255 for i in HEAD_DIMS))
    assert app.running == "demo"
    assert app.lineup("", "")[0] == 200
    time.sleep(0.3)
    assert app.running == "demo"


def test_lining_up_waits_while_a_light_is_controlled_by_hand(app):
    assert app.post("manual", {"light": 0, "on": True})[0] == 200
    assert wait(lambda: app.running == "manual")
    code, body = app.lineup("1", "center")
    assert code == 409 and "Stop" in body["error"]


def test_the_lineup_page_and_its_post(app):
    url, token = app.preview.url, app.preview.token
    code, page = call(url + "lineup.html?embed=1")
    assert code == 200 and token.encode() in page
    h = {"X-Llano-Token": token}
    assert call(url + "lineup?b=3&s=center", b"", h)[0] == 400
    assert call(url + "lineup?b=0&s=nowhere", b"", h)[0] == 400
    assert call(url + "lineup?b=0&s=center", b"", {"X-Llano-Token": "wrong"})[0] == 403
    assert call(url + "lineup?b=0&s=center", b"", h)[0] == 200
    assert wait(lambda: app.running == "lineup")
    assert call(url + "lineup?b=&s=", b"", h)[0] == 200
    assert wait(lambda: app.running is None, 3.0)


def test_the_page_has_its_own_view_both_bars_and_no_demo_first():
    assert 'location.pathname === "/lineup.html"' in PAGE
    assert 'data-bar="0"' in PAGE and "Both GigBARs" in PAGE
    assert 'id="lineuplink"' in PAGE and 'href="/lineup.html"' in PAGE
    assert "start the Live show with the lights plugged in" not in PAGE   # 1:51: no show needed
    assert 'addEventListener("pagehide"' in PAGE   # leaving the view ends the line-up
