"""A song's part of the night is re-read from its folder every time (Llano BL #12338).

His AJ Wedding show (2026-11-14) held 54 songs and none had a part: every dinner song was designed as
a dance song, the night would have built as one Dancing playlist, and adding the folder again answered
"No new songs: all 54 were already in the show" and changed nothing. Now a folder places the songs
already in the show too, a name a Drive zip mangled is still the same song, and the Review step says
how many songs have no part."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.gigbar_lights.test_shows import _call, lib, window  # noqa: E402,F401
from tools.gigbar_lights import song_folder  # noqa: E402


def _folder(tmp: Path) -> Path:
    root = tmp / "Avery and Jordan Wedding"
    for sub, names in (("1 - Cocktail Hour", ["Clint Black - Killin' Time", "George Strait - Check Yes or No"]),
                       ("2 - Dinner", ["Lonestar - Amazed"]),
                       ("3 - Dancing", ["Journey - Faithfully"]),
                       ("4 - Moments", ["Steven Curtis Chapman - Cinderella"]),
                       ("Extra", ["Owl City - Fireflies"])):
        (root / sub).mkdir(parents=True)
        for n in names:
            (root / sub / f"{n}.mp3").write_bytes(b"x")
    return root


def test_songs_already_in_a_show_take_their_folders_part(tmp_path):
    _name, found = song_folder.read_folder(str(_folder(tmp_path)))
    have = [{"artist": "Clint Black", "title": "Killin_ Time"},            # the Drive zip's spelling
            {"artist": "Lonestar", "title": "Amazed", "part": "dancing"},   # filed wrong before
            {"artist": "Journey", "title": "Faithfully", "part": "dancing"},   # already right: untouched
            {"artist": "Steven Curtis Chapman", "title": "Cinderella"},
            {"artist": "Owl City", "title": "Fireflies"},                    # its folder names no part
            {"artist": "Nobody", "title": "Not In The Folder"}]
    placed = song_folder.place_from_folder(have, found)
    assert placed == [{"i": 0, "part": "cocktail", "moment": ""},
                      {"i": 1, "part": "dinner", "moment": ""},
                      {"i": 3, "part": "dancing", "moment": "father-daughter"}]


def test_a_dance_he_tied_to_a_song_is_left_alone(tmp_path):
    _name, found = song_folder.read_folder(str(_folder(tmp_path)))
    # a first dance filed in the Dinner folder stays the first dance
    have = [{"artist": "Lonestar", "title": "Amazed", "part": "dancing", "moment": "first-dance"}]
    assert song_folder.place_from_folder(have, found) == []
    assert song_folder.place_from_folder([], found) == [] and song_folder.place_from_folder(have, []) == []
    assert song_folder.place_from_folder(["junk", None], found) == []


def test_the_folder_action_places_the_shows_songs(window):  # noqa: F811
    _app, url, token, tmp = window
    root = _folder(tmp)
    have = [{"artist": "Clint Black", "title": "Killin_ Time", "part": "", "moment": ""},
            {"artist": "Lonestar", "title": "Amazed", "part": "", "moment": ""}]
    code, r = _call(url + "api/shows-folder", {"path": str(root), "have": have}, token)
    assert code == 200 and r["placed"] == [{"i": 0, "part": "cocktail", "moment": ""}, {"i": 1, "part": "dinner", "moment": ""}]
    # an older page that sends no songs still gets its folder, with nothing placed
    code, r = _call(url + "api/shows-folder", {"path": str(root)}, token)
    assert code == 200 and r["placed"] == [] and len(r["songs"]) == 6


def test_adding_the_folder_again_sorts_a_show_with_no_parts_in_a_real_browser(window):  # noqa: F811
    pw = pytest.importorskip("playwright.sync_api")
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
            page.fill("#title", "AJ Wedding")
            page.fill("#folder", str(root))
            page.click("#addfolder")
            page.wait_for_function("document.body.innerText.includes('Added 6 songs from the folder')", timeout=8000)
            page.wait_for_function("document.querySelectorAll('#songs select[data-part]').length === 6", timeout=8000)
            # only Fireflies (the Extra folder) has no part, and the page says so
            page.wait_for_function("document.querySelector('#nopart').innerText.includes('Fireflies by Owl City has no part of the night')", timeout=5000)
            # the show as his was saved: no song has a part, and names the way a Drive zip writes them
            page.wait_for_function("!document.querySelector('#design').disabled", timeout=20000)
            # the design the folder add started must be back first: its answer replaces show.songs
            page.wait_for_function("document.querySelector('#msg').innerText.includes('Every song has its lights')", timeout=20000)
            page.evaluate("""() => { for (const s of show.songs) { s.part = ""; s.moment = ""; s.title = s.title.replace("'", "_"); } renderAll(); }""")
            assert page.eval_on_selector_all("#songs select[data-part]", "els => els.map(e => e.value)") == [""] * 6
            page.wait_for_function("document.querySelectorAll('#nopart li[data-kind=part]').length === 6", timeout=5000)
            page.click("#addfolder")
            # adding it again repairs, and says how many (Llano BL #11473)
            page.wait_for_function("document.querySelector('#msg').innerText.includes('No new songs. Fixed 5 songs that were missing a part of the night or a look.')", timeout=8000)
            # no song was added twice, and each one sits in its folder's part
            parts = page.evaluate("() => show.songs.map(s => [s.title, s.part, s.moment || ''])")
            assert len(parts) == 6
            assert dict((t, p) for t, p, _m in parts) == {"Killin_ Time": "cocktail", "Check Yes or No": "cocktail", "Amazed": "dinner",
                                                          "Faithfully": "dancing", "Cinderella": "dancing", "Fireflies": ""}
            assert [m for t, _p, m in parts if t == "Cinderella"] == ["father-daughter"]
            page.wait_for_function("document.querySelectorAll('#nopart li[data-kind=part]').length === 1", timeout=5000)
            assert "Fireflies by Owl City has no part of the night: pick its part in its row." in page.inner_text("#nopart")
            # the lights follow the parts: a cocktail-hour song is a soft wash again
            page.wait_for_function("[...document.querySelectorAll('#songs td.why')].some(e => e.innerText.includes('cocktail hour'))", timeout=8000)
            # adding it a third time changes nothing, and says so
            page.click("#addfolder")
            page.wait_for_function("document.querySelector('#msg').innerText.includes('No new songs: all 6 were already in the show')", timeout=8000)
        finally:
            browser.close()
