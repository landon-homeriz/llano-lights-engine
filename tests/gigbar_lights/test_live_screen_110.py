"""The live screen and setup fixes from his 2026-11-08 recording (1.10.0).

0:07 an update closes the old window and the new one opens; 0:36 and 3:27 Stop is pinned to the
top and its second click only changes its color; 4:12 a show that needs the lights box says so
instead of failing; 4:47 Test each light lights each light (it lit nothing before); 6:09 control
any light by hand; 7:12 Check my setup answers at once; 7:46 the lights box, loopMIDI and Mixxx
are always in sight, and pressing play warns about what isn't connected; 8:38 a crash leaves its
trace for Llano; 9:30 and 11:12 scenes and wedding moments work here with no music.
"""
import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
import gigbar_app  # noqa: E402
from tools.gigbar_lights import moments, show_settings  # noqa: E402
from tools.gigbar_lights.rig import default_rig  # noqa: E402
from tools.gigbar_lights.venue import LayoutStore  # noqa: E402
from tools.gigbar_lights import __main__ as gl  # noqa: E402

PAGE = (Path(gigbar_app.__file__).parent / "app.html").read_text()


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


@pytest.fixture
def classic_app(monkeypatch, request):
    """The classic window (the LLANO_LIGHTS_STUDIO=0 kill switch, still shipped from 1.20.0): a
    moment there is a play with its label, which a draft from Llano replaces."""
    monkeypatch.setenv("LLANO_LIGHTS_STUDIO", "0")
    return request.getfixturevalue("app")


@pytest.fixture
def studio_app(monkeypatch, request):
    """The Live screen as the front page (1.20.0): a moment is the studio's held look."""
    monkeypatch.setenv("LLANO_LIGHTS_STUDIO", "1")
    return request.getfixturevalue("app")


def wait(cond, s=6.0):
    end = time.monotonic() + s
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


# --- 4:47 Test each light -------------------------------------------------------------------------

def test_a_reset_keeps_the_fixtures_so_test_each_light_lights_the_one_it_names():
    rig = default_rig()
    held = rig.fixtures
    for i, fx in enumerate(held):
        rig.reset()
        gl.light_white(fx)
        u = rig.render()
        lit = [j for j, f in enumerate(rig.fixtures)
               if any(u[f.address - 1:f.address - 1 + f.footprint][k] == 255 for k in range(f.footprint))]
        assert lit == [i], (fx.name, lit)
        assert rig.fixtures[i] is fx and fx.address == held[i].address


def test_test_each_light_shows_white_in_the_room_picture(app):
    assert app.run("test")[0] == 200
    assert wait(lambda: "Light 1 of 12" in app.preview.status)
    bar = default_rig().bars[0]
    assert wait(lambda: app.preview.universe[bar.address - 1] == 255)   # GigBAR 1's first par, red full
    assert app.warning and "room picture only" in app.warning["text"]   # said, not silent
    app.stop()
    assert wait(lambda: app.running is None, 3.0)


# --- 4:12 the lights box, 7:46 and 8:03 the heads-up --------------------------------------------

def test_the_show_starts_with_no_lights_box_and_says_so_calmly(app):
    """The ask, 2026-11-13 (getting back to the show with no USB box plugged in):
    no adapter never locks him out. The live show starts in the room picture with a calm note
    he can clear, and it clears itself when the box arrives."""
    code, body = app.run("live")
    assert code == 200, body
    assert wait(lambda: app.running == "live")
    w = app.state()["warning"]
    assert w["level"] == "warn" and w["text"].startswith("Lights not connected") and "Not started" not in w["text"]
    app.lights_changed("COM3")                        # the box is plugged in mid-show
    assert app.state()["warning"] is None and app.state()["conn"]["enttec"]["ok"] is True
    app.lights_changed("")                            # and pulled out again
    assert app.state()["warning"]["text"].startswith("Lights not connected")
    assert app.post("warning-ok", {})[0] == 200
    assert app.state()["warning"] is None
    app.stop()
    assert wait(lambda: app.running is None, 3.0)


def test_pressing_play_warns_what_isnt_connected_and_still_plays(app):
    assert app.run("preview")[0] in (200,)
    w = app.state()["warning"]
    assert w["level"] == "warn" and "loopMIDI" in w["text"] and "Mixxx isn't open" in w["text"]
    assert app.state()["conn"]["enttec"]["ok"] is False
    app.stop()
    assert wait(lambda: app.running is None, 4.0)


def test_nothing_missing_means_no_warning(app, monkeypatch):
    monkeypatch.setattr(gigbar_app, "midi_port", lambda: "Llano Mixxx 0")
    app.mixxx.running = True
    assert app.preflight("preview", False) is None and app.warning is None


def test_connection_reads_wait_their_turn():
    """Clicks used to start parallel MIDI and serial scans; now each waits for the one before."""
    order, gate = [], threading.Event()

    def slow():
        order.append("in")
        gate.wait(0.3)
        order.append("out")
        return None
    orig = gigbar_app._enttec_port
    gigbar_app._enttec_port = slow
    try:
        ts = [threading.Thread(target=gigbar_app.connections, args=(False,)) for _ in range(3)]
        [t.start() for t in ts]
        [t.join(3) for t in ts]
    finally:
        gigbar_app._enttec_port = orig
    assert order == ["in", "out"] * 3


# --- 7:12 Check my setup ------------------------------------------------------------------------

def test_check_says_when_it_ran_and_stop_never_interrupts_it(app, monkeypatch):
    monkeypatch.setattr(gigbar_app, "setup_status", lambda: [{"key": "x", "label": "loopMIDI port", "ok": None, "detail": "no"}])
    assert app.post("check", {})[0] == 200
    assert wait(lambda: app.state()["setup_at"] > 0 and not app.state()["setup_busy"])
    assert "Checked at" in PAGE and "not ready" in PAGE
    assert 'k === "check" ? checkSetup()' in PAGE      # the Check button scans in place, it is not a mode


# --- 6:09 Control a light -----------------------------------------------------------------------

def test_control_a_light_starts_by_itself_and_lights_only_that_light(app):
    tetra = default_rig().tetras[0]
    idx = next(l["id"] for l in app.state()["lights_list"] if l["name"] == tetra.name)
    assert app.post("manual", {"light": idx, "on": True, "color": "#ff0000", "dim": 1.0})[0] == 200
    assert wait(lambda: app.running == "manual")
    a = tetra.address - 1
    assert wait(lambda: bytes(app.preview.universe[a:a + 5]) == bytes([255, 0, 0, 0, 255]))
    assert "1 light on" in app.preview.status and "room picture only" in app.preview.status
    app.post("manual", {"light": idx, "strobe": 0.5})
    assert wait(lambda: app.preview.universe[a + 5] > 0)
    app.post("manual-off", {})
    assert wait(lambda: not any(app.preview.universe[a:a + 6]))
    assert app.post("manual", {"light": 99})[0] == 400
    assert app.post("manual", {"light": idx, "color": "red"})[0] == 400
    app.stop()
    assert wait(lambda: app.running is None, 3.0)


def test_a_gigbars_heads_aim_by_pan_and_tilt():
    rig = default_rig()
    gigbar_app.apply_manual(rig, {0: {**gigbar_app.MANUAL_DEFAULT, "on": True, "pan": 0.0, "tilt": 1.0}})
    m = rig.bars[0].movers[0]
    assert (m.pan, m.tilt, m.dim) == (0.0, 1.0, 1.0)


def test_the_panel_waits_while_another_show_runs(app):
    assert app.run("demo")[0] == 200
    code, body = app.post("manual", {"light": 0, "on": True})
    assert code == 409 and "Stop" in body["error"]
    app.stop()
    assert wait(lambda: app.running is None, 3.0)


# --- 9:30 and 11:12 scenes and moments with no music ---------------------------------------------

def test_on_the_live_screen_a_held_moment_lights_its_button_and_back_to_the_show(studio_app):
    """1.20.0 release CI: the studio holds a moment as a look, and the window still has to see it
    (its button lit, Back to the show enabled), whichever screen held it."""
    app = studio_app
    assert app.studio.live
    assert app.post("moment", {"key": "first-dance"})[0] == 200
    assert app.state()["moment"] == "first-dance"
    assert app._sync_status(False)["moment"] == "first-dance"
    assert app.studio_post({"op": "look", "key": "moment:toast"})[0] == 200   # held from the Live screen
    assert app.state()["moment"] == "toast"
    assert app.studio_post({"op": "look", "key": "scene:party"})[0] == 200    # a scene is not a moment
    assert app.state()["moment"] == "" and "moment" not in app._sync_status(False)
    assert app.post("moment", {"key": "cake"})[0] == 200
    assert app.post("moment", {"key": ""})[0] == 200                            # back to the show
    assert app.state()["moment"] == ""
    app.stop()
    assert wait(lambda: app.running is None, 3.0)


def test_a_scene_with_nothing_running_starts_scenes_with_no_music(app):
    assert app.post("scene", {"name": "party"})[0] == 200
    assert wait(lambda: app.running == "scenes")
    assert wait(lambda: (app.state()["live"] or {}).get("scene") == "party")
    assert app.state()["show"] is True
    app.post("scene", {"name": ""})
    assert wait(lambda: app.state()["live"]["scene"] is None)
    assert app.post("scene", {"name": "nope"})[0] == 400
    app.stop()
    assert wait(lambda: app.running is None, 3.0)


def test_the_phones_moments_play_here_and_stop_ends_them(classic_app):
    app = classic_app
    assert not app.studio.live
    assert [m["key"] for m in app.state()["moments"]] == list(moments.KEYS)
    assert app.post("moment", {"key": "first-dance"})[0] == 200
    assert wait(lambda: app.running == "scenes")
    assert app.state()["moment"] == "first-dance"
    assert show_settings.playing()["note"].startswith("First dance")
    assert app._sync_status(False)["draft_until"] == 0      # Llano isn't told a draft plays
    assert wait(lambda: "moment First dance" in app.preview.status)
    assert "Llano's draft" not in app.link.public()["line"]
    show_settings.set_play(show_settings.playing(), time.time() + 60)   # a draft from Llano replaces it
    assert app.state()["moment"] == ""
    app.post("moment", {"key": "first-dance"})
    app.post("moment", {"key": ""})
    assert app.state()["moment"] == "" and show_settings.playing() is None
    app.post("moment", {"key": "dinner"})
    app.stop()
    assert wait(lambda: app.running is None, 3.0)
    assert show_settings.playing() is None and app.moment == ""


def test_laptop_moments_match_llanos(tmp_path):
    """The laptop's copy is aios scripts/lights/moments.py with one import changed."""
    repo = os.environ.get("LLANO_REPO", "")   # a Llano checkout, where the other copy lives
    aios = Path(repo) / "scripts" / "lights" / "moments.py"
    if not repo or not aios.is_file():
        pytest.skip("no Llano checkout here (set LLANO_REPO)")
    mine = (Path(moments.__file__)).read_text().replace("from . import settings_contract as contract",
                                                         "from scripts.lights import settings_contract as contract")
    theirs = aios.read_text()
    assert mine.split('"""', 2)[2] == theirs.split('"""', 2)[2]


# --- 8:38 the crash trace -----------------------------------------------------------------------

def test_a_run_that_never_closed_leaves_its_last_lines_for_llano(tmp_path):
    gigbar_app.mark_running(tmp_path)
    started = json.loads((tmp_path / gigbar_app.RUN_MARKER).read_text())["started"]
    (tmp_path / "llano-lights.log").write_text(
        "2000-01-01 00:00:00 an older run\n" + f"{started} Llano Lights 1.8.0 starting\n{started} clicked around\n")
    (tmp_path / "crash.log").write_text("Fatal Python error: Segmentation fault\n")
    rep = gigbar_app.last_crash(tmp_path)
    assert rep["lines"] == [f"{started} Llano Lights 1.8.0 starting", f"{started} clicked around"]
    assert "Segmentation fault" in rep["fault"] and (tmp_path / "crash-report.txt").is_file()
    gigbar_app.clear_running(tmp_path)
    assert gigbar_app.last_crash(tmp_path) is None             # a clean close leaves nothing to report


def test_the_crash_goes_to_llano_with_the_status(app):
    app.crash = {"version": "1.8.0", "started": "x", "lines": ["a"], "fault": ""}
    assert app._sync_status(False)["last_crash"]["lines"] == ["a"]


# --- 0:07 the update's old window, 0:36 Stop ----------------------------------------------------

def test_an_old_window_closes_itself_when_a_new_run_answers():
    assert "S.launch !== launch) { closeSelf(" in PAGE and "location.reload()" not in PAGE
    assert 'if (updating) closeSelf("' in PAGE and "contentWindow.location.replace(want)" in PAGE
    assert "You can close this window" not in PAGE
    assert "--hide-crash-restore-bubble" in gigbar_app.EDGE_FLAGS


def test_stop_arms_at_one_size_and_says_nothing_extra():
    # Llano BL #11473: the armed Stop reads "Click again to stop" (the Shows page's words), at one fixed
    # width that fits both, so the first click never makes it grow
    js = PAGE[PAGE.index("let stopTimer"):PAGE.index('$("#checkupd").addEventListener')]
    assert 'b.textContent = "Click again to stop"' in js and 'b.textContent = "Stop"' in js
    assert "#stop { flex:none; width:148px" in PAGE and "#stop.armed" in PAGE
    assert "#stop.armed {" in PAGE and "width" not in PAGE[PAGE.index("#stop.armed {"):PAGE.index("}", PAGE.index("#stop.armed {"))]
    # "You don't need to say this right here": no words about Stop on the screen itself
    assert '"Stop takes two clicks."' not in PAGE and "Stop takes two clicks, so" not in PAGE
    assert '<p class="hint">One at a time.</p>' in PAGE


def test_the_first_110_run_reports_a_crash_from_before_markers_existed(tmp_path):
    (tmp_path / "llano-lights.log").write_text("\n".join([
        "2026-11-08 09:40:00 Llano Lights 1.8.0, built Nov 8 starting from C:\\x",
        "2026-11-08 09:40:01 Window server at http://127.0.0.1:8765/",
        "2026-11-08 09:41:00 Llano Lights closed",
        "2026-11-08 09:50:00 Llano Lights 1.8.0, built Nov 8 starting from C:\\x",
        "2026-11-08 09:50:01 Window server at http://127.0.0.1:8765/",
        "2026-11-08 10:02:10 --- Check my setup ---",
        "2026-11-08 10:02:50 Llano Lights 1.8.0, built Nov 8 starting from C:\\x",
        "2026-11-08 10:02:51 Window server at http://127.0.0.1:8765/",
    ]) + "\n")
    rep = gigbar_app.last_crash(tmp_path)
    assert rep["version"] == "1.8.0" and rep["started"] == "2026-11-08 09:50:00"
    assert rep["lines"][-1].endswith("--- Check my setup ---")
    assert not any("10:02:5" in ln for ln in rep["lines"])   # the relaunch isn't part of the crashed run
    assert gigbar_app.last_crash(tmp_path) is None             # once only


def test_a_clean_history_backfills_nothing(tmp_path):
    (tmp_path / "llano-lights.log").write_text(
        "2026-11-08 09:40:01 Window server at x\n2026-11-08 09:41:00 Llano Lights closed\n"
        "2026-11-08 09:50:01 Window server at x\n")
    assert gigbar_app.last_crash(tmp_path) is None


def test_only_our_own_app_window_ever_closes():
    """A browser tab with the app page or llano.app/lights must never be closed (fresh review)."""
    ok = gigbar_app.is_app_window_title
    assert ok("Llano Lights 1.10.0 (built Nov 8, 2026, 11:02 AM CT)") and ok("Llano Lights 1.10.0")
    assert ok("Llano Lights 1.10.0 (built x)", "1.10.0") and not ok("Llano Lights 1.9.0 (built x)", "1.10.0")
    for title in ("Llano Lights 1.10.0 (built x) - Google Chrome", "Llano Lights - Microsoft Edge",
                  "Llano Lights 1.10.0 — Mozilla Firefox", "Llano Lights 1.10.0 and 2 more pages", "Llano Lights x"):
        assert not ok(title), title


def test_a_start_never_waits_long_on_a_busy_scan(app):
    held = threading.Event()
    release = threading.Event()

    def hold():
        with gigbar_app.SETUP_LOCK:
            held.set()
            release.wait(5)
    t = threading.Thread(target=hold); t.start(); held.wait(2)
    try:
        t0 = time.monotonic()
        assert app.preflight("preview", False) is None
        assert time.monotonic() - t0 < gigbar_app.PREFLIGHT_WAIT_S + 1
    finally:
        release.set(); t.join(3)


@pytest.mark.skipif(not hasattr(gigbar_app.llano_sync, "PLAY_MAX"), reason="the Llano link is not in this edition")
def test_llano_ending_its_draft_leaves_a_laptop_moment(classic_app):
    app = classic_app
    assert app.post("moment", {"key": "toast"})[0] == 200
    app.link.play_token = "old"
    orig = type(app.link).linked
    try:
        type(app.link).linked = property(lambda self: True)
        app.link._play({"token": "new", "style": None, "until": None})
    finally:
        type(app.link).linked = orig
    assert show_settings.play_label() == "Toast"
    app.stop()
    assert wait(lambda: app.running is None, 3.0)


def test_the_tilt_slider_runs_from_straight_down_to_level_at_the_floor():
    """The heads hang under the bar: raw tilt 0.5 is straight down, 1 level (peer finding, bl11586)."""
    assert "tilt: 0.5 + +e.target.value / 200" in PAGE and "Down / out" in PAGE and "Up / down" not in PAGE
