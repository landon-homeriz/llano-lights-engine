"""The setup guide (1.21, Llano PM #23415): his "I don't have a clue as to what to do". One numbered
path from a fresh install to a built night; each step checks itself where the app can sense it,
asks him where it can't, and sends him to the page that already does the work."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from tools.gigbar_lights import setup_guide
from tools.gigbar_lights.venue import presets

from test_update_relaunch_11612 import make_app

SRC = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"

FRESH = {"app_ok": True, "mapping": True}
ALL = {"app_ok": True, "mapping": True, "box": True, "box_port": "COM3", "lights_confirmed": True, "lined_up": True,
       "midi": True, "heard_ever": True, "shows_with_songs": 1, "night": {"folder": "C:/Music/x-night"},
       "autodj": {"found": True, "ok": True, "items": []}}


def close(a):
    a.quit.set()
    a.preview.close()


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


# --- the steps, from facts -----------------------------------------------------------------------

def test_a_fresh_laptop_starts_at_the_lights_box_in_the_right_order():
    items = setup_guide.steps(FRESH)
    assert [s["key"] for s in items] == list(setup_guide.KEYS)
    s = setup_guide.summary(items)
    assert s == {"done": 1, "total": 9, "next": "box", "complete": False}
    for st in items:   # every step says what to do, what worked looks like, and what to do if not
        assert st["title"] and st["do"] and st["worked"] and st["fix"]


def test_everything_done_is_complete_and_names_the_port_and_folder():
    items = setup_guide.steps(ALL)
    assert setup_guide.summary(items) == {"done": 9, "total": 9, "next": "", "complete": True}
    by = {s["key"]: s for s in items}
    assert "COM3" in by["box"]["worked"] and "x-night" in by["built"]["worked"]


def test_beats_heard_now_or_ever_both_count_and_listening_says_so():
    assert setup_guide.steps({**FRESH, "heard_now": True})[5]["ok"] is True
    assert setup_guide.steps({**FRESH, "heard_ever": True})[5]["ok"] is True
    beat = setup_guide.steps({**FRESH, "listening": True})[5]
    assert beat["key"] == "beat" and beat["ok"] is False and "play a track" in beat["detail"]


def test_what_the_laptop_cannot_tell_is_unknown_never_done():
    by = {s["key"]: s for s in setup_guide.steps({**FRESH, "midi": None, "autodj": None})}
    assert by["loopmidi"]["ok"] is None and "couldn't list" in by["loopmidi"]["detail"]
    assert by["autodj"]["ok"] is None
    assert setup_guide.summary(list(by.values()))["complete"] is False


def test_auto_dj_fix_names_what_is_wrong():
    bad = {"found": True, "ok": False, "items": [
        {"ok": False, "fix": "pick Full Track"}, {"ok": True, "fix": "never shown"}]}
    st = setup_guide.steps({**ALL, "autodj": bad})[-1]
    assert st["ok"] is False and st["fix"] == "pick Full Track"


def test_only_the_lights_step_asks_him_to_confirm():
    assert [s["key"] for s in setup_guide.steps(FRESH) if s["confirm"]] == ["lights"]
    assert setup_guide.CONFIRMABLE == {"lights"}


def test_each_step_sends_him_to_the_page_that_already_does_it():
    by = {s["key"]: s["action"] for s in setup_guide.steps(FRESH)}
    assert by["lights"] == "run:test" and by["beat"] == "run:preview"
    assert by["lineup"] == "page:/lineup.html" and by["music"] == by["built"] == "page:/shows"


def test_lined_up_reads_a_saved_center_or_confirmed_spot():
    lay = next(iter(presets().values()))
    assert setup_guide.lined_up(lay) is False
    lay.spots["bar1"].cal[0].anchors.append((0.0, 3.0, 0.5, 0.4))
    assert setup_guide.lined_up(lay) is True
    assert setup_guide.lined_up(object()) is False


# --- in the window -------------------------------------------------------------------------------

def test_the_window_serves_the_steps_and_remembers_the_lights_confirm(tmp_path, monkeypatch):
    a = make_app(tmp_path, monkeypatch)
    try:
        g = a.guide_public()
        assert g["total"] == 9 and [s["key"] for s in g["steps"]] == list(setup_guide.KEYS)
        assert g["steps"][2]["ok"] is False
        assert a.post("guide-confirm", {"key": "lights"}) == (200, {"ok": True})
        assert a.post("guide-confirm", {"key": "box"})[0] == 400, "a step that checks itself can't be ticked"
    finally:
        close(a)
    b = make_app(tmp_path, monkeypatch)   # launched again
    try:
        assert b.guide_public()["steps"][2]["ok"] is True
        assert b.post("guide-confirm", {"key": "lights", "ok": False}) == (200, {"ok": True})
        assert b.guide_public()["steps"][2]["ok"] is False
    finally:
        close(b)


def test_beats_from_mixxx_are_remembered_once_heard(tmp_path, monkeypatch):
    a = make_app(tmp_path, monkeypatch)
    try:
        a.running, a.preview.live = "preview", {"mixxx_heard": True}
        assert {s["key"]: s["ok"] for s in a.guide_public()["steps"]}["beat"] is True
        a.running, a.preview.live = None, None
        assert {s["key"]: s["ok"] for s in a.guide_public()["steps"]}["beat"] is True
        assert json.loads(a.prefs_file.read_text(encoding="utf-8"))["guide_heard"] is True
    finally:
        a.running = None
        close(a)


def test_live_state_says_when_mixxx_beats_are_coming_in():
    import gigbar_app
    from tools.gigbar_lights.show import Show
    show = Show(analyze=False)
    assert gigbar_app.live_state(show)["mixxx_heard"] is False
    show.state.last_message = time.perf_counter()
    assert gigbar_app.live_state(show)["mixxx_heard"] is True
    show.state.last_message = time.perf_counter() - 10
    assert gigbar_app.live_state(show)["mixxx_heard"] is False


def test_first_launch_opens_on_the_guide_once_and_not_now_stops_it(tmp_path, monkeypatch):
    monkeypatch.setenv("LLANO_LIGHTS_GUIDE", "1")   # conftest switches it off for every other test
    a = make_app(tmp_path, monkeypatch)
    try:
        base = a.preview.url
        code, body = get(base)
        assert code == 200 and b"Set up Llano Lights, step by step" in body
        code, body = get(base)
        assert code == 200 and b"step by step" not in body, "Go to the Live screen must reach it in the same launch"
        code, body = get(base + "guide")
        assert code == 200 and b"/api/guide" in body
        code, body = get(base + "api/guide")
        assert code == 200 and json.loads(body)["next"] == "box"
        assert a.post("guide-later", {}) == (200, {"ok": True})
    finally:
        close(a)
    b = make_app(tmp_path, monkeypatch)
    try:
        assert b.guide_first() is False, "Not now holds on the next launch"
    finally:
        close(b)


def test_the_guide_can_be_switched_off_and_a_finished_guide_stays_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("LLANO_LIGHTS_GUIDE", "0")
    a = make_app(tmp_path, monkeypatch)
    try:
        assert a.guide_first() is False
        monkeypatch.setenv("LLANO_LIGHTS_GUIDE", "1")
        monkeypatch.setattr(setup_guide, "summary", lambda items: {"complete": True})
        assert a.guide_first() is False
        assert json.loads(a.prefs_file.read_text(encoding="utf-8"))["guide_done"] is True
    finally:
        close(a)


def test_the_pages_link_up():
    app_html = (SRC / "app.html").read_text(encoding="utf-8")
    assert "box.append(guideButton());" in app_html and 'location.href = "/guide"' in app_html
    guide = (SRC / "guide.html").read_text(encoding="utf-8")
    for call in ('fetch("/api/guide"', 'post("/api/guide-confirm"', 'post("/api/guide-later")', 'post("/api/run"',
                 'post("/api/check")', 'post("/api/stop")'):
        assert call in guide, call
