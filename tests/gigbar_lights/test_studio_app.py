"""The Light studio in the laptop app (1.20.0, Llano PM #23195): one studio for the launch, the one
command door every screen uses (/api/studio), and the classic buttons routed through it."""
import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
import gigbar_app  # noqa: E402
from tools.gigbar_lights import show_settings, studio  # noqa: E402
from tools.gigbar_lights.venue import LayoutStore  # noqa: E402


def call(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def make(tmp_path, monkeypatch, on="1"):
    monkeypatch.setattr(gigbar_app.updater, "check", lambda: (None, "no update in tests"))
    monkeypatch.setattr(studio, "default_path", lambda: tmp_path / "studio.json")
    monkeypatch.setattr(gigbar_app.tonight_mod.Tonight, "load", classmethod(lambda cls, root=None, **kw: cls.plain()))
    if on is None:
        monkeypatch.delenv("LLANO_LIGHTS_STUDIO", raising=False)
    else:
        monkeypatch.setenv("LLANO_LIGHTS_STUDIO", on)
    opts = argparse.Namespace(seconds=0.0, bpm=128.0, no_browser=True, no_window=True,
                              updated=False, update_failed=False)
    app = gigbar_app.App(opts, gigbar_app.LogBuffer(tmp_path / "log.txt"))
    app.preview = gigbar_app.Preview("", LayoutStore(tmp_path / "layouts"), app=app)
    return app


def close(app):
    app.stop()
    if app.runner:
        app.runner.join(timeout=8)
    app.preview.close()
    show_settings.clear_play()


@pytest.fixture(scope="module")
def live_app(tmp_path_factory):
    """One window server for the file: each one a test opens holds a port of the window's 20 for a
    minute after it closes, and a shared machine has few to spare."""
    mp = pytest.MonkeyPatch()
    app = make(tmp_path_factory.mktemp("studio"), mp)
    yield app
    close(app)
    mp.undo()


@pytest.fixture
def live(live_app):
    app = live_app
    yield app, app.preview.url, {"X-Llano-Token": app.preview.token, "Content-Type": "application/json"}
    app.stop()
    if app.runner:
        app.runner.join(timeout=8)
    assert app.running is None
    show_settings.clear_play()
    st = app.studio
    with st.lock:   # as a fresh launch: nothing held, saved or dimmed
        st.reset()
        st.pads, st.marks, st.pins = [], {}, {}
        st.masters = {z: 1.0 for z in st.masters}
        st.speed, st.fade_s = 1.0, 3.0
        st.night = gigbar_app.tonight_mod.Tonight.plain()
    app.manual.clear()
    app.warning, app.preview.peek, app.moment = None, None, ""


def post(url, h, cmd):
    code, body = call(url + "api/studio", json.dumps(cmd).encode(), h)
    return code, json.loads(body)


def lit(app, seconds=6.0):
    """Wait until the run sends a frame with a light on; the universe it sent."""
    end = time.time() + seconds
    while time.time() < end:
        if any(app.preview.universe):
            return app.preview.universe
        time.sleep(0.05)
    return app.preview.universe


def house_lit(app, seconds=6.0):
    """Wait until House lights reach the sent universe. lit() can return a frame from before the look
    lands (a light already on from the run underneath), so a check on House's own channel waits for it."""
    end = time.time() + seconds
    while time.time() < end and app.preview.universe[84] <= 200:
        time.sleep(0.05)
    return app.preview.universe[84]


def wait_stopped(app):
    if app.runner:
        app.runner.join(timeout=8)


def test_a_pad_with_nothing_running_starts_the_lights_and_holds(live):
    app, url, h = live
    assert app.studio.live and app.running is None
    code, out = post(url, h, {"op": "look", "key": "simple:house"})
    assert code == 200 and out["studio"]["look"]["key"] == "simple:house"
    assert app.running == "scenes"
    u = lit(app)
    # House lights: the first Tetra (address 81: red, green, blue, amber, dimmer) bright white
    assert u[80] > 200 and u[81] > 200 and u[82] > 200 and u[84] > 200
    st = json.loads(call(url + "api/studio")[1])
    assert st["on"] and st["running"] == "scenes" and st["show"]
    assert st["studio"]["look"]["name"] == "House lights"
    assert [p["key"] for p in st["catalog"]["pages"]] == ["simple", "wedding", "party", "mine"]
    assert st["studio"]["night"]["steps"], "the plain wedding order is tonight's list"


def test_the_command_door_needs_the_window_token(live):
    app, url, h = live
    assert call(url + "api/studio", b'{"op": "look", "key": "simple:house"}', {"X-Llano-Token": "wrong"})[0] == 403
    assert app.running is None and app.studio.look is None


def test_a_refused_command_leaves_nothing_running(live):
    app, url, h = live
    code, out = post(url, h, {"op": "look", "key": "simple:nope"})
    assert code == 400 and out["error"] == "no such look"
    wait_stopped(app)
    assert app.running is None
    code, out = post(url, h, {"op": "format_disk"})
    assert code == 400 and "update Llano Lights" in out["error"] and app.running is None
    assert post(url, h, {"op": "look", "key": "x" * 700})[0] == 400


def test_stop_ends_what_he_held_and_keeps_brightness(live):
    app, url, h = live
    assert post(url, h, {"op": "master", "zone": "main", "value": 0.5})[0] == 200
    assert app.running is None, "brightness alone starts nothing"
    assert post(url, h, {"op": "look", "key": "simple:steady"})[0] == 200
    lit(app)
    assert call(url + "api/stop", b"{}", h)[0] == 200
    wait_stopped(app)
    assert app.running is None and app.studio.look is None and app.studio.layout is None
    assert app.studio.masters["main"] == 0.5
    assert json.loads(call(url + "state")[1])["u"] == [0] * 192


def test_brightness_dims_the_held_look(live):
    app, url, h = live
    post(url, h, {"op": "fade", "seconds": 0})
    post(url, h, {"op": "look", "key": "simple:house"})
    assert house_lit(app) > 200
    post(url, h, {"op": "master", "zone": "main", "value": 0.25})
    end = time.time() + 4
    while time.time() < end and app.preview.universe[84] > 80:
        time.sleep(0.05)
    assert 40 < app.preview.universe[84] < 80


def test_the_classic_moment_button_holds_the_look_in_the_studio(live):
    app, url, h = live
    assert call(url + "api/moment", b'{"key": "toast"}', h)[0] == 200
    assert app.studio.look["key"] == "moment:toast" and app.running == "scenes"
    lit(app)
    assert json.loads(call(url + "api/app")[1])["studio"]["look"]["name"] == "Toast"
    assert call(url + "api/moment", b'{"key": ""}', h)[0] == 200
    assert app.studio.look is None


def test_a_classic_scene_pad_and_blackout_are_the_studios(live):
    app, url, h = live
    assert call(url + "api/scene", b'{"name": "party"}', h)[0] == 200
    end = time.time() + 6
    while time.time() < end and not app.studio.look:
        time.sleep(0.05)
    assert app.studio.look["key"] == "scene:party"
    assert call(url + "key?k=b", b"", h)[0] == 200
    end = time.time() + 4
    while time.time() < end and not app.studio.blackout:
        time.sleep(0.05)
    assert app.studio.blackout


def test_spots_start_on_the_floor_and_show_on_the_stage(live):
    app, url, h = live
    code, out = post(url, h, {"op": "spots", "on": True})
    assert code == 200 and app.running == "scenes"
    lit(app)
    lay = app.preview.layout
    spots = json.loads(call(url + "state")[1])["spots"]
    assert spots["on"] and spots["size"] == list(lay.room[:2]) and spots["room"] == 0.2   # the room dips to 20% round the spot (PM #23789)
    assert spots["plan"]["room"] == [round(v, 2) for v in lay.room[:2]] and len(spots["plan"]["bars"]) == 2
    assert spots["at"] == [[round(lay.floor.cx, 3), round(lay.floor.cy, 3)]]
    assert post(url, h, {"op": "spot_goal", "x": lay.floor.cx + 0.5, "y": lay.floor.cy})[0] == 200
    end = time.time() + 4
    while time.time() < end and json.loads(call(url + "state")[1])["spots"]["at"][0][0] < lay.floor.cx + 0.45:
        time.sleep(0.05)
    assert json.loads(call(url + "state")[1])["spots"]["at"][0][0] == pytest.approx(lay.floor.cx + 0.5, abs=0.06)


def test_tap_and_timing_need_a_running_show(live):
    app, url, h = live
    assert post(url, h, {"op": "tap"})[0] == 409
    assert post(url, h, {"op": "timing", "d": 5})[0] == 400
    post(url, h, {"op": "look", "key": "simple:steady"})
    lit(app)
    assert post(url, h, {"op": "tap"})[0] == 200
    assert post(url, h, {"op": "timing", "d": 1})[0] == 200      # Later: the lights 5 ms behind
    end = time.time() + 4
    while time.time() < end and not (app.preview.live or {}).get("offset_ms"):
        time.sleep(0.05)
    assert app.preview.live["offset_ms"] == -5


def test_a_press_while_something_else_runs_says_stop_it_first(live):
    app, url, h = live
    assert call(url + "api/manual", b'{"light": "2", "on": true}', h)[0] == 200
    assert app.running == "manual"
    code, out = post(url, h, {"op": "look", "key": "simple:steady"})
    assert code == 409 and "Control a light" in out["error"] and app.studio.look is None


@pytest.fixture(scope="module")
def stable_app(tmp_path_factory):
    """A stable copy with the kill switch thrown (LLANO_LIGHTS_STUDIO=0): the classic window."""
    mp = pytest.MonkeyPatch()
    app = make(tmp_path_factory.mktemp("stable"), mp, on="0")
    yield app
    close(app)
    mp.undo()


def test_on_by_default_in_a_stable_copy_from_1_20(monkeypatch):
    from tools.gigbar_lights import version
    monkeypatch.delenv("LLANO_LIGHTS_STUDIO", raising=False)
    monkeypatch.setattr(version, "CHANNEL", "stable")
    assert version.STUDIO is True and studio.enabled(), "1.20.0 makes the Live screen the front page"
    monkeypatch.setenv("LLANO_LIGHTS_STUDIO", "0")
    assert not studio.enabled(), "the kill switch still brings the classic window back"


def test_the_kill_switch_brings_the_classic_window_back_and_the_door_still_answers(stable_app):
    app, url = stable_app, stable_app.preview.url
    assert not app.studio.live and app.studio.idle()
    st = json.loads(call(url + "api/studio")[1])
    assert st["on"] is False and st["studio"]["live"] is False
    assert json.loads(call(url + "api/app")[1])["studio_on"] is False
    page = call(url)[1]   # the classic window is the front page
    assert b"studio_console.js" not in page and b'id="livelink"' in page
    # the classic moment button still plays the moment the classic way
    h = {"X-Llano-Token": app.preview.token, "Content-Type": "application/json"}
    assert call(url + "api/moment", b'{"key": "toast"}', h)[0] == 200
    assert app.studio.look is None and show_settings.play_label() == "Toast"


# --- the Live screen's pages, the pad preview and the swap to the live show ---------------------------

SRC = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"


def test_the_live_screen_is_the_front_page_and_the_classic_window_is_set_up(live):
    app, url, h = live
    code, page = call(url)
    assert code == 200 and b"studio_console.js" in page and app.preview.token.encode() in page
    code, setup = call(url + "setup")
    assert code == 200 and b'id="livelink"' in setup and app.preview.token.encode() in setup
    code, js = call(url + "studio_console.js")
    assert code == 200 and js == (SRC / "studio_console.js").read_bytes()
    assert b"llano-token" not in js, "the console file is the same bytes on every screen: no window token in it"


# llano.app/lights draws this same file (Llano repo: llano-ui/src/pages/lights/studio_console.js) and
# that repo's test pins the same sha256, so the phone app and the laptop can never draw two consoles.
# Changing the file means copying it there and changing both pins together.
CONSOLE_SHA256 = "6fbb71a7777240c331dfd4707365dae1a1ca6567956567014215ffb6f8dedb83"


def test_the_console_bytes_match_the_pin_shared_with_the_llano_repo():
    assert hashlib.sha256((SRC / "studio_console.js").read_bytes()).hexdigest() == CONSOLE_SHA256


def test_a_slow_path_never_holds_back_stop_and_never_sends_a_toggle_twice():
    js = (SRC / "studio_console.js").read_text(encoding="utf-8")
    assert "/^(next|run)$/" in js and "never STOP" in js, "STOP always takes a press, even while another press waits"
    assert 't.closest(".wait")' in js and 'cmd.op !== "tap" && cmd.op !== "timing"' in js


def test_every_studio_command_has_a_button_on_the_one_console():
    """The same buttons on every screen: a command the engine takes that the console never sends
    would be a feature one screen has and no screen can reach."""
    js = (SRC / "studio_console.js").read_text(encoding="utf-8")
    ops = sorted(n[4:] for n in dir(studio.Studio) if n.startswith("_op_"))
    assert len(ops) >= 28
    missing = [op for op in ops if f'"{op}"' not in js]
    assert not missing, f"no button sends: {missing}"
    for op in ("tap", "timing"):   # the app's own two (the beat)
        assert f'"{op}"' in js


def test_resting_on_a_pad_previews_it_in_the_picture_only(live):
    app, url, h = live
    code, out = call(url + "api/studio-peek", b'{"key": "simple:house"}', h)
    assert code == 200 and json.loads(out)["name"] == "House lights"
    s = json.loads(call(url + "state")[1])
    assert s["previewing"] == "House lights" and s["u"][80:85] == [255, 255, 255, 0, 255] and s["trail"] == []
    assert app.running is None and not any(app.preview.universe), "nothing started, nothing was sent"
    assert app.studio.look is None
    # a wedding moment previews without becoming the draft the real show plays
    assert call(url + "api/studio-peek", b'{"key": "moment:toast"}', h)[0] == 200
    s = json.loads(call(url + "state")[1])
    assert s["previewing"] == "Toast" and any(s["u"]) and show_settings.play_label() == ""
    assert call(url + "api/studio-peek", b'{"key": ""}', h)[0] == 200
    s = json.loads(call(url + "state")[1])
    assert s["previewing"] == "" and s["u"] == [0] * 192
    assert call(url + "api/studio-peek", b'{"key": "simple:nope"}', h)[0] == 400


def test_a_preview_nobody_renews_ends_by_itself(live, monkeypatch):
    app, url, h = live
    call(url + "api/studio-peek", b'{"key": "simple:steady"}', h)
    assert json.loads(call(url + "state")[1])["previewing"] == "Steady"
    app.preview.peek.until = 0.0   # the pointer left without saying so
    assert json.loads(call(url + "state")[1])["previewing"] == "" and app.preview.peek is None


def test_a_preview_over_a_running_show_leaves_the_lights_alone(live):
    app, url, h = live
    post(url, h, {"op": "fade", "seconds": 0})
    post(url, h, {"op": "look", "key": "simple:house"})
    assert house_lit(app) > 200
    call(url + "api/studio-peek", b'{"key": "scene:party"}', h)
    s = json.loads(call(url + "state")[1])
    assert s["previewing"] == "Party" and s["u"][80:83] != [255, 255, 255]
    time.sleep(0.2)
    assert list(app.preview.universe[80:85]) == [255, 255, 255, 0, 255], "the lights still play House lights"
    assert app.studio.look["key"] == "simple:house"


def test_starting_the_live_show_over_scenes_keeps_what_he_holds(live, monkeypatch):
    app, url, h = live
    monkeypatch.setattr(gigbar_app, "connections", lambda *a, **k: {
        "enttec": {"ok": False, "detail": ""}, "loopmidi": {"ok": True, "detail": ""}, "mixxx": {"ok": True, "detail": ""}})
    post(url, h, {"op": "look", "key": "simple:steady"})
    post(url, h, {"op": "spots", "on": True})
    lit(app)
    # no lights box never locks him out (his ask, 2026-11-13): the live show starts in the room picture
    # with a calm note, and what he holds carries over
    code, out = call(url + "api/studio-go", b'{"mode": "live"}', h)
    assert code == 200, out
    assert app.running == "live" and app.studio.look["key"] == "simple:steady" and app.studio.spots["on"]
    assert app.warning["level"] == "warn" and app.warning["text"].startswith("Lights not connected")
    # music with no lights swaps the run under the held look and the spots
    code, out = call(url + "api/studio-go", b'{"mode": "preview"}', h)
    assert code == 200, out
    assert app.running == "preview" and app.studio.look["key"] == "simple:steady" and app.studio.spots["on"]
    assert app.keep_studio is False
    assert call(url + "api/studio-go", b'{"mode": "designer"}', h)[0] == 400


# --- the studio over the internet: llano.app's commands and scene pads --------------------------------

def test_a_command_from_llano_runs_like_a_press_here_and_a_refusal_is_kept_for_the_phone(live):
    app, url, h = live
    assert app._llano_studio({"op": "look", "key": "simple:house"})[0] == 200
    assert app.studio.look["key"] == "simple:house" and app.running == "scenes" and app.studio_refused is None
    lit(app)
    status = app._sync_status(True)
    assert status["studio"]["studio"]["look"]["name"] == "House lights" and status["studio"]["catalog"]["pages"]
    assert status["studio"]["glow"]["lamps"], "the room's light rides up for the phone's picture"
    assert len(json.dumps(status)) < 40_000, "well inside what Llano keeps for a status"
    app.link.studio_seen = 12
    assert app._llano_studio({"op": "look", "key": "simple:nope"})[0] == 400
    assert app.studio_refused["n"] == 12 and app.studio_refused["error"] == "no such look"
    assert json.loads(call(url + "api/studio")[1])["refused"]["error"] == "no such look"
    app.studio_refused = None


def test_live_show_pressed_on_llano_swaps_the_run_and_keeps_what_he_holds(live):
    app, url, h = live
    assert app._llano_studio({"op": "look", "key": "simple:house"})[0] == 200 and app.running == "scenes"
    seen = []
    app.switch_show = lambda mode: (seen.append(mode), (200, {"ok": True}))[1]
    assert app._llano_studio({"op": "go", "mode": "live"}) == (200, {"ok": True}) and seen == ["live"]
    assert app.studio.look["key"] == "simple:house", "go is the app's, the studio's layers are untouched"
    del app.switch_show
    app.link.studio_seen = 31
    assert app._llano_studio({"op": "go", "mode": "everything"})[0] == 400   # the app's own check, kept for the phone
    assert app.studio_refused["n"] == 31 and "live show" in app.studio_refused["error"]
    app.studio_refused = None


def test_llanos_scene_pads_are_the_studios_and_back_to_the_show_leaves_his_own_look(live):
    app, url, h = live
    assert app._llano_scene("party") is True
    assert app.studio.look["key"] == "scene:party" and app.running == "scenes"
    assert app._llano_scene("whiteout") is True and "whiteout" in app.studio.hits
    assert app._llano_scene(None) is True
    assert app.studio.look is None and not app.studio.hits and not app.studio.blackout
    # a look he holds himself is not Llano's to end
    post(url, h, {"op": "look", "key": "moment:toast"})
    assert app._llano_scene(None) is True and app.studio.look["key"] == "moment:toast"


def test_a_classic_window_leaves_llanos_scene_pad_to_the_classic_path(stable_app):
    assert stable_app._llano_scene("party") is False and stable_app.studio.look is None
    assert "studio" not in stable_app._sync_status(True)


# --- from the independent review, 2026-11-13 ------------------------------------------------------------

def test_a_malformed_command_never_leaves_the_lights_it_started_running(live, monkeypatch):
    app, url, h = live

    def boom(cmd, now=None):
        raise TypeError("unhashable type: 'list'")
    monkeypatch.setattr(app.studio, "command", boom)
    code, out = post(url, h, {"op": "spots", "on": True, "pace": []})
    assert code == 400 and "couldn't read" in out["error"]
    wait_stopped(app)
    assert app.running is None, "Scenes was started for the press and stopped again"
    for bad in ({"op": "timing", "d": []}, {"op": "timing", "d": True}, {"op": "timing", "d": 1.5}):
        assert post(url, h, bad)[0] == 400


def test_a_live_show_that_fails_to_start_after_the_swap_leaves_nothing_reading_as_held(live, monkeypatch):
    app, url, h = live
    monkeypatch.setattr(gigbar_app, "connections", lambda *a, **k: {
        "enttec": {"ok": True, "detail": ""}, "loopmidi": {"ok": True, "detail": ""}, "mixxx": {"ok": True, "detail": ""}})
    post(url, h, {"op": "look", "key": "simple:steady"})
    lit(app)
    real = app.run
    monkeypatch.setattr(app, "run", lambda mode, *a, **k: (409, {"error": "an update is being installed"}) if mode == "live" else real(mode, *a, **k))
    code, out = call(url + "api/studio-go", b'{"mode": "live"}', h)
    assert code == 409 and app.running is None
    assert app.studio.look is None and app.switching is False and app.keep_studio is False
    # and while a swap is under way a pad press is asked to wait, never starts Scenes under it
    app.switching = True
    code, out = post(url, h, {"op": "look", "key": "simple:steady"})
    assert code == 409 and "starting" in out["error"] and app.running is None
    app.switching = False


def test_the_phone_code_pairs_the_app_for_the_internet_and_this_wifi_in_one_scan():
    """1.20: the main code on Set up, Phone control is llano.app/lights carrying this laptop's Wi-Fi
    addresses and key in the link's fragment (never sent to a server); llano.app's pairFromHash and the
    installed app's offline page read exactly this shape. With no local mode it stays the plain link."""
    import re
    from pathlib import Path
    pw = pytest.importorskip("playwright.sync_api")
    src = (Path(__file__).resolve().parents[2] / "tools/gigbar_lights/windows/src/app.html").read_text(encoding="utf-8")
    fn = re.search(r"function pairedApp\(lc\) \{.*?\n\}\n", src, re.S).group(0)
    phone = re.search(r'const PHONE_APP = "([^"]+)";', src).group(1)
    assert phone == "https://llano.app/lights"
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            page = browser.new_page()
            page.add_script_tag(content=f'const PHONE_APP = "{phone}";\n{fn}')
            got = page.evaluate("""() => [
              pairedApp({urls: ["http://192.168.137.1:8790/", "http://10.0.0.4:8790/"], key: "a b/c"}),
              pairedApp({urls: [], key: "k"}), pairedApp({urls: ["http://192.168.1.2:8790/"], key: ""})]""")
        finally:
            browser.close()
    assert got == ["https://llano.app/lights#k=a%20b%2Fc&lan=192.168.137.1:8790,10.0.0.4:8790",
                   "https://llano.app/lights", "https://llano.app/lights"]
    assert "qr(pairedApp(lc)," in src and "No app yet? This laptop's own page" not in src   # two codes, not three (1.19.4 ask)
