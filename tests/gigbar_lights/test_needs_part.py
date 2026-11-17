"""A song with no part of the night waits under Needs a part; the night never builds it as Dancing
(Llano BL #12338).

His AJ Wedding show (2026-11-14) held 54 songs with no part. wedding_night.build filed every blank part
under Dancing, so his dinner songs would have been cut as dance songs and played in the dance playlist.
Now the build refuses, naming the songs, the app refuses before it starts, and the Shows page puts those
songs in their own group with a way to sort them."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.gigbar_lights.test_shows import _call, lib, window  # noqa: E402,F401
from tools.gigbar_lights import wedding_night  # noqa: E402

PAGE = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src" / "shows.html"


def test_only_a_song_with_no_part_and_no_moment_needs_one():
    songs = [{"artist": "Lonestar", "title": "Amazed"},                                   # no part
             {"artist": "Journey", "title": "Faithfully", "part": "dancing"},
             {"artist": "Randy Travis", "title": "Forever and Ever, Amen", "moment": "first-dance"},
             {"artist": "George Strait", "title": "Check Yes or No", "part": "nonsense"},  # not a part
             "junk"]
    assert wedding_night.needs_part(songs) == ["Lonestar - Amazed", "George Strait - Check Yes or No"]
    words = wedding_night.needs_part_words(["Lonestar - Amazed"])
    assert "Lonestar - Amazed" in words and "Needs a part" in words and "Dancing" not in words


def test_the_build_refuses_before_writing_anything(tmp_path):
    out = tmp_path / "night"
    songs = [{"artist": "Journey", "title": "Faithfully", "part": "dancing"},
             {"artist": "Lonestar", "title": "Amazed", "part": ""}]
    with pytest.raises(wedding_night.NeedsPart) as e:
        wedding_night.build(out, songs, {}, extras=False)
    assert e.value.songs == ["Lonestar - Amazed"]
    assert wedding_night.plain_error(e.value) == str(e.value) and "Lonestar - Amazed" in str(e.value)
    assert not out.exists() or not any(out.rglob("*"))


def test_a_moment_that_is_off_tonight_still_needs_its_part(tmp_path):
    # the garter dance is off: its song plays in its part, and it has none
    songs = [{"artist": "Journey", "title": "Faithfully", "part": "dancing"},
             {"artist": "Joe Cocker", "title": "You Can Leave Your Hat On", "moment": "garter"}]
    with pytest.raises(wedding_night.NeedsPart) as e:
        wedding_night.build(tmp_path / "night", songs, {}, skip={"garter"}, extras=False)
    assert e.value.songs == ["Joe Cocker - You Can Leave Your Hat On"]


def test_the_app_refuses_to_build_and_names_the_songs(window, tmp_path, monkeypatch):  # noqa: F811
    _app, url, token, _tmp = window
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    songs = [{"artist": "Journey", "title": "Faithfully", "part": "dancing"},
             {"artist": "Lonestar", "title": "Amazed"}]
    code, r = _call(url + "api/shows-night-build", {"songs": songs, "folder": str(tmp_path)}, token)
    assert code == 400 and r["needs_part"] == ["Lonestar - Amazed"] and "Lonestar - Amazed" in r["error"]
    code, n = _call(url + "api/shows-night-status", {}, token)
    assert code == 200 and n.get("state") != "building"
    assert not (tmp_path / "home" / "Music").exists()


def test_the_page_groups_them_and_build_waits():
    page = PAGE.read_text(encoding="utf-8")
    assert "const needsPart = (s) => !s.part && !s.moment;" in page
    assert "Needs a part &middot;" in page and 'id="sortparts"' in page
    build = page[page.index('$("#nightbuild").addEventListener("click"'):]
    build = build[:build.index('api("night-build"')]
    assert "show.songs.filter(needsPart)" in build and "return;" in build
    # the old words that told him they would play as Dancing are gone
    assert "would play as Dancing" not in page


def test_needs_a_part_in_a_real_browser(window):  # noqa: F811
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
            page.fill("#title", "AJ Wedding")
            page.fill("#folder", str(root))
            page.click("#addfolder")
            page.wait_for_function("document.querySelector('#msg').innerText.includes('Every song has its lights')", timeout=20000)
            # Fireflies (the Extra folder) has no part: it waits in its own group, first
            assert page.text_content("#needspart").replace("\xa0", " ") == "Needs a part · 1"
            assert page.eval_on_selector_all("table.needspart td.song b", "els => els.map(e => e.innerText)") == ["Fireflies"]
            assert page.is_visible("#sortparts")
            # Build the night waits and names it; nothing starts building
            page.fill("#nightfolder", str(root))
            page.click("#nightbuild")
            page.wait_for_function("document.querySelector('#msg').innerText.includes('Build waits')", timeout=5000)
            assert "Owl City - Fireflies" in page.inner_text("#msg")
            assert page.inner_text("#nightline") == ""
            # placing it empties the group
            page.select_option("table.needspart select[data-part]", "dancing")
            page.wait_for_function("!document.querySelector('#needspart')", timeout=20000)
            # the Review panel has no part line left (its files are stand-ins, so their lengths are still listed)
            page.wait_for_function("document.querySelectorAll('#nopart li[data-kind=part]').length === 0", timeout=5000)
            assert page.is_visible("#nopart") and not page.is_visible("#sortparts")
        finally:
            browser.close()
