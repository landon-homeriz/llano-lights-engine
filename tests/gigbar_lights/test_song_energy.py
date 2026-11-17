"""Every Dancing song carries Hype, Dance or Slow, read from the song itself, never from where it sits
in the list; the tag picks the look, shows in Review and on the Live screen, and a tap changes it
(Llano BL #12341, room llano-lights-music-flow)."""
import json
import random
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.gigbar_lights import settings_contract as contract
from tools.gigbar_lights import show_settings, shows

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "tools" / "gigbar_lights" / "windows" / "src"
sys.path.insert(0, str(SRC))
import gigbar_app  # noqa: E402


def dancing(artist, title, bpm=0.0, **kw):
    return shows.ShowSong(artist, title, bpm=bpm, part="dancing", **kw)


def measured(artist, title, bpm, level):
    """A song read from its file: every section at `level`."""
    return dancing(artist, title, bpm, secs=200.0, source="mixxx",
                   sections=[{"kind": "main", "start": 0.0, "end": 200.0, "energy": level}])


@pytest.fixture(autouse=True)
def clean():
    show_settings.set_current(contract.defaults())
    show_settings.set_show_looks(None)
    yield
    show_settings.set_current(contract.defaults())
    show_settings.set_show_looks(None)


# --- the tag comes from the song ------------------------------------------------------------------

def test_known_songs_take_the_tag_he_expects():
    # his room: Footloose is Hype and Cupid Shuffle is Dance, though both sit early in the night
    assert shows.energy_tag(dancing("Kenny Loggins", "Footloose", 174))[0] == "hype"
    assert shows.energy_tag(dancing("Cupid", "Cupid Shuffle", 142))[0] == "dance"
    assert shows.energy_tag(dancing("Lonestar", "Amazed", 70))[0] == "slow"


def test_an_unknown_song_reads_its_tempo_and_how_full_its_audio_is():
    assert shows.energy_tag(measured("Nobody", "Loud Fast One", 128, 0.95))[0] == "hype"
    assert shows.energy_tag(measured("Nobody", "Thin Fast One", 124, 0.15))[0] == "dance"
    assert shows.energy_tag(measured("Nobody", "Quiet Slow One", 78, 0.2))[0] == "slow"
    tag, why = shows.energy_tag(dancing("Nobody", "Estimated", 118))
    assert tag == "dance" and "118 BPM" in why


def test_moving_songs_around_never_changes_a_tag_or_its_look():
    def night(order):
        songs = [dancing("Kenny Loggins", "Footloose", 174), dancing("Cupid", "Cupid Shuffle", 142),
                 dancing("Lonestar", "Amazed", 70), measured("Nobody", "Loud Fast One", 128, 0.95),
                 measured("Nobody", "Thin Fast One", 124, 0.15), dancing("Bon Jovi", "Livin' on a Prayer", 123)]
        songs = [songs[i] for i in order]
        return {s.title: (s.tag, s.look) for s in shows.design(songs)}

    first = night(range(6))
    for seed in range(5):
        order = list(range(6))
        random.Random(seed).shuffle(order)
        assert night(order) == first
    assert first["Footloose"] == ("hype", "peak")
    assert first["Cupid Shuffle"] == ("dance", "groove")
    assert first["Amazed"] == ("slow", "slow-dance")


def test_the_why_says_the_tag_and_where_it_came_from():
    (s,) = shows.design([dancing("Kenny Loggins", "Footloose", 174)])
    assert s.why == "Hype: a known floor-filler"


def test_his_own_tag_survives_designing_again():
    s = dancing("Kenny Loggins", "Footloose", 174, tag="slow", tag_mine=True)
    (s,) = shows.design([s])
    assert (s.tag, s.look, s.why) == ("slow", "slow-dance", "Slow: you tagged it")


def test_cocktail_dinner_and_moments_carry_no_tag():
    songs = shows.design([shows.ShowSong("Lonestar", "Amazed", bpm=70, part="dinner"),
                          dancing("Lonestar", "Amazed", 70, moment="first-dance")])
    assert [s.tag for s in songs] == ["", ""]


# --- saved, and opened again ------------------------------------------------------------------------

def test_the_tag_saves_and_a_bad_one_is_dropped():
    doc = contract.normalize({"shows": {"w": {"title": "W", "songs": [
        {"artist": "A", "title": "One", "part": "dancing", "tag": "hype", "tag_mine": True},
        {"artist": "A", "title": "Two", "part": "dancing", "tag": "loud", "tag_mine": True},
        {"artist": "A", "title": "Three", "part": "dancing"}]}}})
    one, two, three = doc["shows"]["w"]["songs"]
    assert one["tag"] == "hype" and one["tag_mine"] is True
    assert "tag" not in two and "tag_mine" not in two
    assert "tag" not in three   # a show saved before tags keeps its exact bytes


def test_a_show_song_round_trips_its_tag():
    s = dancing("A", "One", tag="dance", tag_mine=True)
    saved = s.saved()
    assert saved["tag"] == "dance" and saved["tag_mine"] is True
    (back,) = shows.from_public([s.public()])
    assert (back.tag, back.tag_mine) == ("dance", True)
    (bad,) = shows.from_public([{"title": "X", "tag": "loud", "tag_mine": True}])
    assert (bad.tag, bad.tag_mine) == ("", False)


def test_an_older_show_opens_with_every_dancing_song_tagged():
    songs = [dancing("Kenny Loggins", "Footloose", 174, look="groove", why="steady dancing"),
             dancing("Cupid", "Cupid Shuffle", 142, look="sing-along", why="your pick"),
             dancing("Mark Ronson", "Uptown Funk", 115, look="llano-peak", why="Llano designed it"),
             shows.ShowSong("George Strait", "Amarillo by Morning", part="cocktail", look="warm-up")]
    shows.prefill_tags(songs, {"llano-peak": {}})
    assert [s.tag for s in songs] == ["hype", "dance", "hype", ""]
    assert (songs[0].look, songs[0].why) == ("peak", "Hype: a known floor-filler")   # the old position look is replaced
    assert (songs[1].look, songs[1].why) == ("sing-along", "your pick")              # his pick stays
    assert songs[2].look == "llano-peak"                                              # Llano's design stays
    assert songs[3].look == "warm-up"


# --- the Live screen ----------------------------------------------------------------------------------

def _save_show(name="wedding"):
    songs = [dancing("Kenny Loggins", "Footloose", 174), dancing("Cupid", "Cupid Shuffle", 142)]
    shows.design(songs)
    _, ops = shows.save_ops("Wedding", [s.saved() for s in songs], name=name)
    doc, _ = contract.apply_ops(show_settings.current(), ops)
    show_settings.set_current(doc)
    return shows.from_public(shows.saved_shows()[name]["songs"])


def _fake_app(name="wedding"):
    songs = shows.from_public(shows.saved_shows()[name]["songs"])
    app = SimpleNamespace(running="live", live_tags=(name, shows.tag_index(songs)), relooked=0)

    def local_change(ops):
        doc, _ = contract.apply_ops(show_settings.current(), ops)
        show_settings.set_current(doc)

    def live_show_looks():
        app.relooked += 1
        fresh = shows.from_public(shows.saved_shows()[name]["songs"])
        app.live_tags = (name, shows.tag_index(fresh))
        return True

    app.link = SimpleNamespace(local_change=local_change)
    app.live_show_looks = live_show_looks
    return app


def test_the_live_screen_names_the_playing_songs_part_and_tag():
    _save_show()
    app = _fake_app()
    tag = gigbar_app.App.song_tag(app, {"artist": "Kenny Loggins", "title": "Footloose"})
    assert tag == {"i": 0, "part": "dancing", "part_title": "Dancing", "tag": "hype", "tag_title": "Hype",
                   "can_tag": True}
    assert gigbar_app.App.song_tag(app, {"artist": "Someone", "title": "Not In The Show"}) is None
    app.running = ""
    assert gigbar_app.App.song_tag(app, {"artist": "Kenny Loggins", "title": "Footloose"}) is None


def test_a_tap_on_the_live_screen_saves_the_tag_and_its_look():
    _save_show()
    app = _fake_app()
    code, body = gigbar_app.App.retag_live(app, {"op": "song_tag", "i": 1, "tag": "hype"})
    assert code == 200, body
    song = shows.saved_shows()["wedding"]["songs"][1]
    assert (song["tag"], song.get("tag_mine"), song["look"]) == ("hype", True, "peak")
    assert app.relooked == 1
    assert gigbar_app.App.song_tag(app, {"artist": "Cupid", "title": "Cupid Shuffle"})["tag"] == "hype"
    assert gigbar_app.App.retag_live(app, {"op": "song_tag", "i": 1, "tag": "loud"})[0] == 400
    assert gigbar_app.App.retag_live(app, {"op": "song_tag", "i": 9, "tag": "slow"})[0] == 400
    app.live_tags = ("", {})
    assert gigbar_app.App.retag_live(app, {"op": "song_tag", "i": 1, "tag": "slow"})[0] == 409


def test_both_screens_draw_the_tag_and_send_the_tap():
    page = (SRC / "shows.html").read_text(encoding="utf-8")
    assert 'data-tag="${i}"' in page and "NEXT_TAG" in page and "s.tag_mine = true" in page
    console = (SRC / "studio_console.js").read_text(encoding="utf-8")
    assert 'data-t="songtag"' in console and 'op: "song_tag"' in console
    app = (SRC / "gigbar_app.py").read_text(encoding="utf-8")
    assert '"song_tag": self.song_tag(playing)' in app and 'if op == "song_tag":' in app


from tests.gigbar_lights.test_part_mood import mount_console  # noqa: E402
from tests.gigbar_lights.test_shows import lib, window  # noqa: E402,F401


def test_the_live_tag_line_in_a_real_browser(window):  # noqa: F811
    """While a Dancing song plays, the Live screen says Dancing · Hype beside it with three taps, the
    tag on is marked, and a tap sends song_tag for that song."""
    pw = pytest.importorskip("playwright.sync_api")
    app, _url, _token, _tmp = window
    state = json.loads(json.dumps(app.studio_state()))
    state.update(running="live", running_label="Live show",
                 now_playing={"artist": "Kenny Loggins", "title": "Footloose"},
                 song_tag={"i": 3, "part": "dancing", "part_title": "Dancing", "tag": "hype", "tag_title": "Hype",
                           "can_tag": True})
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            page = browser.new_page()
            mount_console(page, state)
            page.wait_for_selector(".lls-tags em")
            assert page.inner_text(".lls-tags em") == "Dancing · Hype"
            assert page.eval_on_selector_all(".lls-tags button", "els => els.map(e => e.innerText)") == ["Hype", "Dance", "Slow"]
            assert page.inner_text(".lls-tags button.on") == "Hype"
            page.click(".lls-tags button:has-text('Slow')")
            page.wait_for_function("SENT.length === 1")
            assert page.evaluate("SENT[0]") == {"op": "song_tag", "i": 3, "tag": "slow"}
        finally:
            browser.close()


def test_the_review_chip_in_a_real_browser(window):  # noqa: F811
    """Every Dancing row carries its tag as a chip; a tap moves it to the next tag, keeps it as his and
    plays that tag's look."""
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
            page.wait_for_selector("#save")
            page.fill("#folder", str(root))
            page.click("#addfolder")
            page.wait_for_function("document.querySelector('#msg').innerText.includes('Every song has its lights')", timeout=20000)
            chips = page.locator("#songs button.chip.tag")
            assert chips.count() == 1   # Faithfully, the one Dancing song; cocktail, dinner and moments carry none
            before = chips.inner_text()
            assert before in ("Hype", "Dance", "Slow")
            chips.click()
            after = {"Hype": "Dance", "Dance": "Slow", "Slow": "Hype"}[before]
            page.wait_for_function(f"document.querySelector('#songs button.chip.tag').innerText === '{after}'")
            song = page.evaluate("show.songs.find(s => s.title === 'Faithfully')")
            assert song["tag_mine"] is True and song["look"] == {"Hype": "peak", "Dance": "groove", "Slow": "slow-dance"}[after]
        finally:
            browser.close()
