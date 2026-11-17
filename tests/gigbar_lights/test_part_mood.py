"""Cocktail hour and dinner each get a mood he picks (Llano BL #12340).

He could not see how to choose one standard color or a very slow fade for cocktail hour and dinner:
the soft wash borrowed each song's colors. Now each part has a mood, one color or a slow fade through
two to four colors (a one minute melt, a change every 2, 5 or 10 minutes), at its own brightness,
saved with the show, kept in the night he builds, changeable on the Live screen, and pre-filled with
Llano's suggestion so he only changes what he dislikes (the 2026-11-14 comment: suggestions come
filled in).

End state: a show saves a mood per soft part and the soft wash plays it: one color holds steady, a
fade visits each picked color.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.gigbar_lights import settings_contract as contract
from tools.gigbar_lights import show_settings, shows, tonight
from tools.gigbar_lights.looks import SOFT_WASH, Frame, LooksEngine
from tools.gigbar_lights.rig import default_rig
from tools.gigbar_lights.show_script import Section
from tools.gigbar_lights.song_match import candidates

AMBER = "#ffb347"
FADE = {"kind": "fade", "colors": ["#ff0000", "#00ff00", "#0000ff"], "every": 2, "bright": 1.0}


@pytest.fixture(autouse=True)
def fresh():
    def clear():
        show_settings.set_current(contract.defaults())
        show_settings.set_show_looks(None)
        for src in ("night", "show"):
            show_settings.set_soft_songs(src, None)
            show_settings.set_still_songs(src, None)
            show_settings.set_soft_parts(src, None)
            show_settings.set_moods(src, None)
        show_settings.set_soft_now(False)
        show_settings.set_still_now(False)
    clear()
    yield
    clear()


def frame(title: str, now: float, artist: str = "The Band") -> Frame:
    keys = candidates(artist, title)
    return Frame(8.0, 128.0, True, level=0.95, section=Section("drop", 0, 32, 1.0), track_key=7,
                 song=keys[0], song_keys=keys, now=now)


def wash(rig) -> tuple:
    p = rig.bars[0].pars[0]
    return (round(p.red, 3), round(p.green, 3), round(p.blue, 3)), round(p.dim, 3)


SIP = shows.ShowSong("The Band", "Sip", look="peak", part="cocktail", bpm=128)
EAT = shows.ShowSong("The Band", "Eat", look="peak", part="dinner", bpm=128)
JUMP = shows.ShowSong("The Band", "Jump", look="peak", part="dancing", bpm=128)


def test_every_part_comes_pre_filled_with_llanos_suggestion():
    m = contract.moods(None)
    assert set(m) == {"cocktail", "dinner"}
    assert m["cocktail"]["kind"] == "fade" and 2 <= len(m["cocktail"]["colors"]) <= 4
    assert m["dinner"] == {"kind": "color", "colors": [AMBER], "every": 5, "bright": 0.45}
    assert show_settings.moods() == m, "no show and no night: the suggestion plays"


def test_a_mood_is_clamped_to_what_he_can_pick():
    got = contract.part_mood({"kind": "fade", "colors": ["#FF0000", "red", "#00ff00", "#0000ff", "#ffffff", "#000000"],
                              "every": 7, "bright": 4}, "cocktail")
    assert got == {"kind": "fade", "colors": ["#ff0000", "#00ff00", "#0000ff", "#ffffff"], "every": 5, "bright": 1.0}
    assert contract.part_mood({"kind": "fade", "colors": ["#123456"]}, "dinner")["kind"] == "color", "one color is not a fade"
    assert contract.part_mood({"kind": "color", "colors": ["#123456", "#654321"]}, "dinner")["colors"] == ["#123456"]
    assert contract.part_mood("junk", "dinner") == contract.SUGGESTED_MOODS["dinner"]


def test_a_show_saves_its_moods_and_an_old_show_keeps_its_bytes():
    old = {"title": "Old", "note": "", "looks": {}, "songs": [{"artist": "A", "title": "B"}]}
    doc = contract.normalize({"shows": {"old": old, "new": {**old, "title": "New",
                                                            "moods": {"dinner": {"kind": "color", "colors": ["#c3b1e1"]}}}}})
    assert "moods" not in doc["shows"]["old"]
    assert doc["shows"]["new"]["moods"]["dinner"]["colors"] == ["#c3b1e1"]
    assert doc["shows"]["new"]["moods"]["cocktail"] == contract.SUGGESTED_MOODS["cocktail"]
    show_settings.set_current(contract.defaults())
    name, ops = shows.save_ops("New", [{"artist": "A", "title": "B"}], moods={"dinner": {"kind": "color", "colors": ["#c3b1e1"]}})
    assert ops[0]["value"]["moods"]["dinner"]["colors"] == ["#c3b1e1"]


def test_one_color_holds_steady_at_its_brightness():
    shows.follow([SIP, EAT, JUMP], None, {"dinner": {"kind": "color", "colors": [AMBER], "bright": 0.5}})
    eng = LooksEngine(settings=contract.normalize({**contract.defaults(), "crowd_safe": False}))
    seen = {wash(eng.render(frame("Eat", t), default_rig())) for t in (0.0, 30.0, 300.0, 1800.0)}
    assert seen == {((1.0, 0.702, 0.278), round(SOFT_WASH * 0.5, 3))}
    assert eng.limit == "soft" and eng.soft_part == "dinner" and eng.mode == "mood:dinner"
    rig = eng.render(frame("Eat", 10.0), default_rig())
    assert max(m.dim for bar in rig.bars for m in bar.movers) == 0, "the soft limit still holds"


def test_a_slow_fade_visits_each_color_and_melts_over_a_minute():
    shows.follow([SIP, EAT, JUMP], None, {"cocktail": FADE})
    eng = LooksEngine(settings=contract.defaults())
    step = 120.0
    colors = [wash(eng.render(frame("Sip", step * i + 90), default_rig()))[0] for i in range(3)]
    assert colors == [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)], "rests on each color after the melt"
    mid = wash(eng.render(frame("Sip", step + 30), default_rig()))[0]
    assert 0 < mid[0] < 1 and 0 < mid[1] < 1, "half way through the minute long melt"
    assert wash(eng.render(frame("Sip", step * 3 + 90), default_rig()))[0] == (1.0, 0.0, 0.0), "and round again"


def test_dancing_never_plays_a_mood():
    shows.follow([SIP, EAT, JUMP], None, {"dinner": {"kind": "color", "colors": [AMBER]}})
    eng = LooksEngine(settings=contract.normalize({**contract.defaults(), "crowd_safe": False}))
    eng.render(frame("Jump", 5.0), default_rig())
    assert eng.limit == "" and not eng.mode.startswith("mood")


def test_the_night_keeps_its_moods_and_the_live_screen_changes_them(tmp_path):
    report = {"title": "C & M", "moods": {"cocktail": {"kind": "color", "colors": ["#9ec9f0"]}}, "steps": [
        {"kind": "music", "key": "cocktail", "name": "Cocktail hour", "songs": [{"artist": "The Band", "title": "Sip"}]},
        {"kind": "music", "key": "dinner", "name": "Dinner", "songs": [{"artist": "The Band", "title": "Eat"}]},
        {"kind": "music", "key": "dancing", "name": "Dancing", "songs": [{"artist": "The Band", "title": "Jump"}]}]}
    folder = tmp_path / "Llano Lights shows" / "cm-night"
    folder.mkdir(parents=True)
    (folder / "night.json").write_text(json.dumps(report), encoding="utf-8")
    night = tonight.Tonight.load(tmp_path / "Llano Lights shows")
    assert night.moods["cocktail"]["colors"] == ["#9ec9f0"] and night.moods["dinner"] == contract.SUGGESTED_MOODS["dinner"]
    night.tell_lights()
    eng = LooksEngine(settings=contract.defaults())
    assert wash(eng.render(frame("Sip", 1.0), default_rig()))[0] == (0.62, 0.788, 0.941)

    class Studio:
        look = None
        blackout = frozen = False
        _frozen = None

        def _remember(self):
            pass
    # a request nobody listed, while the night stands on dinner, plays dinner's mood
    night.see(Studio(), candidates("The Band", "Eat"), 0.0)
    show_settings.set_soft_now(night.soft_now(), night.spared_keys(), part=night.soft_part_now())
    assert night.public()["mood_part"] == "dinner"
    eng.render(frame("A Request", 1.0, artist="Somebody"), default_rig())
    assert eng.limit == "soft" and eng.soft_part == "dinner"
    # he changes dinner on the Live screen: it plays now and the night's file keeps it
    got = night.set_mood("dinner", {"kind": "color", "colors": ["#f4b6c2"], "bright": 0.3})
    assert got["colors"] == ["#f4b6c2"]
    assert wash(eng.render(frame("Eat", 1.0), default_rig()))[0] == (0.957, 0.714, 0.761)
    assert json.loads((folder / "night.json").read_text())["moods"]["dinner"]["colors"] == ["#f4b6c2"]
    from tools.gigbar_lights.studio import CommandError
    with pytest.raises(CommandError):
        night.set_mood("dancing", {})


def test_the_night_build_writes_the_moods(tmp_path):
    from tools.gigbar_lights import wedding_night
    with pytest.raises(wedding_night.NeedsPart):   # (the build reads moods before songs; a quick refusal)
        wedding_night.build(tmp_path / "n", [{"artist": "A", "title": "B"}], {}, moods={"dinner": {}}, extras=False)
    import inspect
    assert "moods" in inspect.signature(wedding_night.build).parameters


from tests.gigbar_lights.test_shows import lib, window  # noqa: E402,F401


def test_set_the_mood_in_a_real_browser(window):  # noqa: F811
    """Step 4 draws both moods already filled in, a tap changes one, and See it on the room picture
    plays the show from that part's first song."""
    pw = pytest.importorskip("playwright.sync_api")
    from tests.gigbar_lights.test_parts_from_folder import _folder  # noqa: PLC0415
    _app, url, _token, tmp = window
    root = _folder(tmp)
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            page = browser.new_page()
            page.goto(url + "shows")
            page.wait_for_selector("#moods .mood")
            assert page.eval_on_selector_all("#moods .mood b", "els => els.map(e => e.innerText)") == ["Cocktail hour", "Dinner"]
            for part in ("cocktail", "dinner"):   # Llano's suggestion: a color is already picked on each
                assert page.locator(f'#moods .mood[data-part="{part}"] .sw.on').count() >= 1
            page.click('#moods .mood[data-part="dinner"] button[data-mkind="fade"]')
            assert "linear-gradient" in page.get_attribute('#moods .mood[data-part="dinner"] .strip', "style")
            assert page.locator('#moods .mood[data-part="dinner"] .sw.on').count() >= 2
            page.fill("#title", "AJ Wedding")
            page.fill("#folder", str(root))
            page.click("#addfolder")
            page.wait_for_function("document.querySelector('#msg').innerText.includes('Every song has its lights')", timeout=20000)
            with page.expect_request(lambda r: r.url.endswith("api/shows-play"), timeout=10000) as req:
                page.click('#moods .mood[data-part="cocktail"] button[data-mpreview]')
            body = json.loads(req.value.post_data)
            assert body["moods"]["dinner"]["kind"] == "fade"   # the mood he just changed goes with it
            page.wait_for_function("playing.index >= 0", timeout=10000)   # and it plays from cocktail hour's first song
            assert page.evaluate("playing.songs[playing.index].part") == "cocktail"
        finally:
            browser.close()


CONSOLE = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src" / "studio_console.js"


def mount_console(page, state):
    """The Live console in a blank page, drawing `state` (App.studio_state); every tap is kept in SENT."""
    page.set_content('<div id="host" style="width:1200px"></div>')
    page.add_script_tag(content=CONSOLE.read_text(encoding="utf-8"))
    page.evaluate("""(st) => { window.SENT = [];
      LlanoStudio.mount(document.getElementById("host"), {layout: "wide", screen: "laptop", pollMs: 60000,
        transport: {state: () => Promise.resolve(st), stop: () => Promise.resolve({ok: true}),
                    send: (cmd) => { SENT.push(cmd); return Promise.resolve({ok: true}); }}}); }""", state)


def test_the_live_mood_row_in_a_real_browser(window, tmp_path):  # noqa: F811
    """The Live screen draws both moods with the night's choice marked, and a tap sends the whole new
    mood as one command."""
    pw = pytest.importorskip("playwright.sync_api")
    app, _url, _token, _tmp = window
    report = {"title": "C & M", "moods": {"cocktail": {"kind": "color", "colors": ["#9ec9f0"]}}, "steps": [
        {"kind": "music", "key": "cocktail", "name": "Cocktail hour", "songs": [{"artist": "The Band", "title": "Sip"}]},
        {"kind": "music", "key": "dinner", "name": "Dinner", "songs": [{"artist": "The Band", "title": "Eat"}]}]}
    folder = Path(tmp_path) / "shows" / "cm-night"
    folder.mkdir(parents=True)
    (folder / "night.json").write_text(json.dumps(report), encoding="utf-8")
    app.studio.night = tonight.Tonight.load(Path(tmp_path) / "shows")
    state = json.loads(json.dumps(app.studio_state()))
    assert state["studio"]["night"]["moods"]["cocktail"]["colors"] == ["#9ec9f0"]
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            page = browser.new_page()
            mount_console(page, state)
            page.wait_for_selector(".lls-mood")
            assert page.eval_on_selector_all(".lls-mood b", "els => els.map(e => e.innerText)") == ["Cocktail hour mood", "Dinner mood"]
            cocktail = page.locator(".lls-mood").nth(0)
            assert cocktail.locator('.sw button.on').get_attribute("title") == "soft blue"
            cocktail.locator('.k button', has_text="Slow fade").click()
            page.wait_for_function("SENT.length === 1")
            cmd = page.evaluate("SENT[0]")
            assert cmd["op"] == "mood" and cmd["part"] == "cocktail" and cmd["mood"]["kind"] == "fade"
            assert len(cmd["mood"]["colors"]) == 2 and cmd["mood"]["colors"][0] == "#9ec9f0"
        finally:
            browser.close()
