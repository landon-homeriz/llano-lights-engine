"""Small Shows page fixes (Llano BL #11473, PR 2).

a. No dead boxes in step 2. The build and the Live screen play run_of_show.DEFAULT_ORDER, and a tick only
   ever adds to `skip`, so a box for a moment outside the order (garter, the quiet moment, welcome,
   bouquet, last dance, closing song, send-off) did nothing either way. The page now offers only the
   moments in the night's order, with the app's OPTIONAL list unticked by default (served, never a list
   typed into the page), and every box it shows changes the built night when unticked.
b. The Mixxx block under Build the night says what Load Mixxx does and where the two wordless Auto DJ buttons
   are, with the four by-hand steps in a closed fold, shown whenever a night is built, after a restart too.
d. Build the night starts with the show's own folder, and says which folder it builds from.
e. A build that fails names the song or hold it stopped on; the generic line only for a true surprise.
f. The greyed night buttons say why: "These wake up once the night is built."
g. A time in step 2 that can't be read turns amber, says "Type it like 6:30." and is not used.
h. Mixxx's settings not found is said in plain words, with what to do.
c. Earlier and Later on the Live screen were the wrong way round: Earlier sent "]", which made the lights
   later. Earlier now makes them earlier (offset_ms up, "ms early" on the main screen).
"""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))   # gigbar_app
from tests.gigbar_lights import test_shows  # noqa: E402
from tests.gigbar_lights.test_shows import _call, lib  # noqa: E402,F401
from tests.gigbar_lights.test_studio_app import lit, live, live_app, post  # noqa: E402,F401
from tools.gigbar_lights import run_of_show  # noqa: E402

@pytest.fixture(scope="module")
def window(tmp_path_factory):
    """One window server for the whole file, like test_studio_app's: each server a test opens holds one of
    the window's 20 ports for a minute after it closes, and a suite that opens one per test runs out (CI
    did, on this PR)."""
    import argparse
    import gigbar_app
    from tools.gigbar_lights import demo_songs
    from tools.gigbar_lights.venue import LayoutStore

    tmp = tmp_path_factory.mktemp("window")
    mixxx = test_shows.lib.__wrapped__(tmp)
    mp = pytest.MonkeyPatch()
    mp.setenv("LLANO_LIGHTS_SYNC", "0")
    mp.setattr(gigbar_app.updater, "check", lambda: (None, "no update in tests"))
    mp.setattr(gigbar_app.show_settings, "default_path", lambda: tmp / "settings.json")
    mp.setattr(gigbar_app, "MixxxLibrary", lambda *a: mixxx)
    mp.setattr(gigbar_app, "default_cache_dir", lambda: tmp / "scripts")
    (mixxx.path.parent / "song3.mp3").write_bytes(demo_songs.load()[0].path.read_bytes())
    opts = argparse.Namespace(seconds=0.0, bpm=128.0, no_browser=True, no_window=True, updated=False, update_failed=False)
    app = gigbar_app.App(opts, gigbar_app.LogBuffer(tmp / "log.txt"))
    app.preview = gigbar_app.Preview("", LayoutStore(tmp / "layouts"), app=app)
    try:
        yield app, app.preview.url, app.preview.token, tmp
    finally:
        app.stop()
        if app.runner:
            app.runner.join(timeout=8)
        app.preview.close()
        mp.undo()


PAGE = (Path(__file__).resolve().parents[2] / "tools/gigbar_lights/windows/src/shows.html").read_text(encoding="utf-8")
SONGS = [{"artist": "George Strait", "title": "Check Yes or No", "part": "cocktail"},
         {"artist": "Norah Jones", "title": "Come Away With Me", "part": "dinner"},
         {"artist": "Journey", "title": "Faithfully", "part": "dancing"}]


def _shown(home: dict) -> list:
    """The moments step 2 offers, as the page picks them from night-home."""
    return [m["key"] for m in home["moments"] if m["key"] in home["order"]]


def _plan_keys(app, lib, moments: dict) -> list:
    """The built night's steps for what the panel sent: _night_plan (the build's own reading of the
    ticks) into run_of_show.plan, the same order the build and the Live screen use."""
    p = app._night_plan({"moments": moments}, lib, [dict(s) for s in SONGS], Path("/nonexistent-night"))
    parts = {k: [s for s in SONGS if s["part"] == k] for k in ("cocktail", "dinner", "dancing")}
    return [s.key for s in run_of_show.plan(parts, p["moment_songs"], skip=p["skip"]) if s.kind != "music"]


# --- a: no dead boxes ----------------------------------------------------------------------------

def test_step_2_offers_only_moments_that_change_the_night(window, lib):  # noqa: F811
    app, url, token, _tmp = window
    code, home = _call(url + "api/shows-night-home", {}, token)
    assert code == 200 and home["optional"] == list(run_of_show.OPTIONAL)
    shown = _shown(home)
    assert shown and set(shown) <= set(run_of_show.DEFAULT_ORDER)
    everything_on = {k: {"on": True} for k in shown}
    base = _plan_keys(app, lib, everything_on)
    for key in shown:   # every box shown changes the night when unticked
        off = _plan_keys(app, lib, {**everything_on, key: {"on": False}})
        assert key in base and key not in off, key
    # a moment the page does not offer would be a dead box: ticked or not, the night is the same
    for key in (k for k in run_of_show.MOMENTS if k not in shown):
        assert _plan_keys(app, lib, {**everything_on, key: {"on": True}}) == _plan_keys(app, lib, {**everything_on, key: {"on": False}}), key


def test_the_page_follows_the_apps_lists_not_its_own():
    # the old typed list of moments that start unticked is gone: the page reads OPTIONAL from the app
    assert '["garter", "close"]' not in PAGE and "N.optional" in PAGE and "order.includes(m.key)" in PAGE


def test_the_page_draws_a_box_only_for_each_moment_in_the_order(window):  # noqa: F811
    pw = pytest.importorskip("playwright.sync_api")
    _app, url, token, _tmp = window
    shown = _shown(_call(url + "api/shows-night-home", {}, token)[1])
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            page = browser.new_page()
            page.goto(url + "shows")
            page.wait_for_selector("#nightmoments input[type=checkbox]")
            boxes = page.eval_on_selector_all("#nightmoments input[type=checkbox]", "els => els.map(e => [e.id.slice(6), e.checked])")
            assert [k for k, _ in boxes] == shown
            assert all(on for k, on in boxes if k not in run_of_show.OPTIONAL)
        finally:
            browser.close()


# --- b: the Mixxx block ----------------------------------------------------------------------------

NEXT = ("After the build: close Mixxx (if it asks whether to exit while a deck is playing, click Yes) and press "
        "Load Mixxx. It saves a copy of Mixxx's library first, adds this night's songs and numbered playlists, lines "
        "up playlist 1 in Auto DJ, sets Auto DJ to Full Track with 2 seconds, and opens Mixxx. On the night, click "
        "Auto DJ in Mixxx's list on the left. The first button at the top of that page starts the music (Enable Auto "
        "DJ). The second button moves on each time a moment is over (Fade Now). Neither has words on it; the run "
        "sheet has a picture.")


def test_the_mixxx_block_shows_after_a_restart_with_the_steps_folded(window, monkeypatch):  # noqa: F811
    pw = pytest.importorskip("playwright.sync_api")
    app, url, _token, tmp = window
    built = tmp / "Music" / "Llano Lights shows" / "aj-wedding-night"
    built.mkdir(parents=True, exist_ok=True)   # the window is shared by the file
    # the app was opened again: nothing built this launch, the last night on this laptop is found
    monkeypatch.setattr(type(app), "_last_night", lambda self: {"folder": str(built), "sheet": str(built / "Run of show.html")})
    app.night = None
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            page = browser.new_page()
            page.goto(url + "shows")
            page.wait_for_function("document.querySelector('#nightnext').style.display === 'block'", timeout=8000)
            text = " ".join(page.inner_text("#nightnext p").split())
            assert text == NEXT
            assert page.inner_text("#nighthand summary") == "If Load Mixxx can't do it: the same thing by hand"
            assert page.evaluate("() => document.querySelector('#nighthand').open") is False
            assert page.locator("#nighthand li").count() == 4
            assert page.text_content("#nightpath") == str(built)   # inside the fold, filled while it is closed
            page.click("#nighthand summary")
            assert page.is_visible("#nighthand li >> nth=0")
        finally:
            browser.close()


def test_the_mixxx_block_waits_until_a_night_is_built():
    # hidden until there is a night: renderNight shows it for a finished build or the last one on this laptop
    assert 'id="nightnext" style="display:none"' in PAGE
    assert '$("#nightnext").style.display = where ? "block" : "none";' in PAGE


# --- c: Earlier and Later --------------------------------------------------------------------------

def _offset(app, want, timeout=4.0):
    end = time.time() + timeout
    while time.time() < end and (app.preview.live or {}).get("offset_ms") != want:
        time.sleep(0.05)
    return (app.preview.live or {}).get("offset_ms")


def test_earlier_makes_the_lights_earlier_and_later_makes_them_later(live):  # noqa: F811
    app, url, h = live
    post(url, h, {"op": "look", "key": "simple:steady"})
    lit(app)
    assert post(url, h, {"op": "timing", "d": 0})[0] == 200
    assert _offset(app, 0) == 0
    # the Live screen's own buttons, exactly as it sends them
    js = (Path(__file__).resolve().parents[2] / "tools/gigbar_lights/windows/src/studio_console.js").read_text(encoding="utf-8")
    assert 'cmdAttr({op: "timing", d: -1}) + \'>Earlier</button>' in js and 'cmdAttr({op: "timing", d: 1}) + \'>Later</button>' in js
    assert post(url, h, {"op": "timing", "d": -1})[0] == 200          # Earlier
    assert _offset(app, 5) == 5                                        # + is earlier (show.beat_at reads ahead)
    app_html = (Path(__file__).resolve().parents[2] / "tools/gigbar_lights/windows/src/app.html").read_text(encoding="utf-8")
    assert 'off > 0 ? off + " ms early"' in app_html                  # the main screen reads + as early
    assert post(url, h, {"op": "timing", "d": 1})[0] == 200           # Later
    assert post(url, h, {"op": "timing", "d": 1})[0] == 200
    assert _offset(app, -5) == -5
    assert post(url, h, {"op": "timing", "d": 0})[0] == 200
    assert _offset(app, 0) == 0
    assert json.dumps(app.preview.live["offset_ms"]) == "0"



# --- d: the folder it builds from ---------------------------------------------------------------------

def _browser(p):
    try:
        return p.chromium.launch()
    except Exception as e:  # noqa: BLE001 -- no browser on this machine
        pytest.skip(f"no headless chromium: {e}")


def test_build_the_night_starts_with_the_shows_own_folder_and_says_it(window):  # noqa: F811
    pw = pytest.importorskip("playwright.sync_api")
    _app, url, _token, tmp = window
    with pw.sync_playwright() as p:
        browser = _browser(p)
        try:
            page = browser.new_page()
            page.goto(url + "shows")
            page.wait_for_selector("#nightmoments input")
            # a show with a remembered folder: the box is filled, and one line says where it builds from
            page.evaluate("""f => { localStorage.setItem('llano-night:cm', JSON.stringify({folder: f, moments: {}, times: {}}));
                                    show.name = 'cm'; $('#folder').value = 'C:\\\\Other show'; nightForShow(); }""", str(tmp / "Wedding"))
            assert page.input_value("#nightfolder") == str(tmp / "Wedding")
            assert page.inner_text("#nightfrom") == f"It builds from the songs in {tmp / 'Wedding'}."
            # a show with none: never another show's folder from the step 1 box
            page.evaluate("() => { show.name = 'fresh'; nightForShow(); }")
            assert page.input_value("#nightfolder") == ""
            assert "Choose the folder your song files are in" in page.inner_text("#nightfrom")
        finally:
            browser.close()


# --- e: a failed build says why ---------------------------------------------------------------------------

def test_a_failed_build_names_the_song_it_stopped_on():
    import gigbar_app  # noqa: PLC0415 -- on the path from the window fixture's module
    words = gigbar_app.night_failure_words
    assert words(RuntimeError("x"), "Reading Clint Black - Killin' Time") == (
        "The file for Killin' Time by Clint Black could not be read. Replace that file, or take the song out of the show, then build again.")
    assert words(PermissionError("x"), "Writing Journey - Faithfully").startswith(
        "Faithfully by Journey could not be written into the night's folder. Windows would not let a file be written.")
    assert words(RuntimeError("x"), "Writing the hold for First dance").startswith("The silent hold for First dance could not be written.")
    # known causes are said as they are, and the generic line is only for a true surprise
    import errno
    full = OSError(errno.ENOSPC, "full")
    assert words(full, "Writing Journey - Faithfully") == "The disk is full. Free some space and build again."
    assert words(RuntimeError("x"), "").startswith("Something went wrong that the build did not expect")
    assert words(RuntimeError("x"), "Writing the backup for Dinner").startswith("Something went wrong")
    for t in (words(RuntimeError("x"), "Reading A - B"), words(RuntimeError("x"), "Writing A - B")):
        assert " - " not in t


# --- f, g, h, and nothing cut off ---------------------------------------------------------------------------

def test_greyed_buttons_say_why_times_are_checked_and_mixxx_not_found_is_plain(window, monkeypatch):  # noqa: F811
    pw = pytest.importorskip("playwright.sync_api")
    app, url, _token, _tmp = window
    import gigbar_app  # noqa: PLC0415
    monkeypatch.setattr(gigbar_app.wedding_night, "check_mixxx", lambda: {"found": False, "ok": False, "items": [
        {"ok": False, "name": "Mixxx's settings", "is": "not found", "want": "Mixxx opened once on this laptop", "fix": "x"}]})
    monkeypatch.setattr(type(app), "_last_night", lambda self: None)
    app.night = None
    with pw.sync_playwright() as p:
        browser = _browser(p)
        try:
            page = browser.new_page()
            page.goto(url + "shows")
            page.wait_for_selector("#nightmoments input")
            # f
            assert page.is_disabled("#nightload") and page.is_visible("#nightwake")
            assert page.inner_text("#nightwake") == "These wake up once the night is built."
            # g: the same rule as run_of_show.parse_clock
            samples = ["6", "6:30", "6.30", "6:30 pm", "6:30pm", "18:30", "0:30", "12", "11 am", "abc", "25:99",
                       "6:60", "24", "6:30:10", "", "  7  ", "6.", ":30", "-1"]
            js = page.evaluate("s => s.map(readableTime)", samples)
            assert js == [x == "" or run_of_show.parse_clock(x) is not None for x in samples], list(zip(samples, js))
            page.fill("#nt-dinner", "25:99")
            page.dispatch_event("#nt-dinner", "input")
            assert "bad" in page.get_attribute("#nt-dinner", "class") and page.is_visible("#timebad")
            assert page.get_attribute("#nt-dinner", "title") == "Type it like 6:30."
            first = page.locator("#nightmoments input.t").first
            first.fill("abc")
            first.dispatch_event("input")
            form = page.evaluate("() => nightForm()")
            assert form["times"]["dinner"] == "" and all(m["at"] == "" for m in form["moments"].values())
            page.fill("#nt-dinner", "6:30")
            first.fill("5:30")
            page.dispatch_event("#nt-dinner", "input")
            assert page.is_hidden("#timebad") and page.evaluate("() => nightForm().times.dinner") == "6:30"
            # h
            page.click("#nightcheck")
            page.wait_for_function("document.querySelector('#nightmixxx').innerText.length > 0", timeout=5000)
            assert page.inner_text("#nightmixxx") == ("Llano Lights could not find Mixxx's settings. Open Mixxx once, close it, "
                                                      "then press Check Mixxx's Auto DJ again.")
        finally:
            browser.close()


@pytest.mark.parametrize("size", [(1366, 768), (1024, 700)])
def test_nothing_in_step_6_is_cut_off(window, monkeypatch, size):  # noqa: F811
    pw = pytest.importorskip("playwright.sync_api")
    app, url, _token, tmp = window
    built = tmp / "Music" / "Llano Lights shows" / "a-long-wedding-show-name-night"
    built.mkdir(parents=True, exist_ok=True)   # the window is shared by the file
    monkeypatch.setattr(type(app), "_last_night", lambda self: {"folder": str(built), "sheet": str(built / "Run of show.html")})
    app.night = None
    with pw.sync_playwright() as p:
        browser = _browser(p)
        try:
            page = browser.new_page(viewport={"width": size[0], "height": size[1]})
            page.goto(url + "shows")
            page.wait_for_function("document.querySelector('#nightnext').style.display === 'block'", timeout=8000)
            page.click("#nighthand summary")
            assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
            cut = page.evaluate("""() => {
              const box = document.querySelector('#step-6').getBoundingClientRect(), out = [];
              for (const el of document.querySelectorAll('#step-6 button, #step-6 input, #step-6 p, #step-6 li, #step-6 summary, #step-6 span.hint')) {
                const r = el.getBoundingClientRect();
                if (!r.width || getComputedStyle(el).display === 'none') continue;
                if (r.left < box.left - 1 || r.right > box.right + 1 || el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflow !== 'visible')
                  out.push((el.id || el.tagName) + ' ' + Math.round(r.left) + '-' + Math.round(r.right));
              }
              return out; }""")
            assert cut == [], cut
        finally:
            browser.close()



def test_every_mention_of_the_two_wordless_buttons_says_where_they_are():
    """Mixxx 2.5.4 shows no words on Enable Auto DJ or Fade Now (the buttons builder, PR 147): wherever the
    page names them, it says which button they are, and the box for the seconds is the one marked sec."""
    import re
    text = re.sub(r"<!--.*?-->", "", PAGE, flags=re.S)
    for name, where in (("Enable Auto DJ", "the first button at the top of"), ("Fade Now", "second button")):
        for m in re.finditer(re.escape(name), text):
            near = text[max(0, m.start() - 160):m.start()]
            assert where in near.lower() and text[m.start() - 1] == "(", text[m.start() - 80:m.end() + 10]
    assert "seconds box" not in text and "the box marked sec. beside it" in text
    wn = (Path(__file__).resolve().parents[2] / "tools/gigbar_lights/wedding_night.py").read_text(encoding="utf-8")
    assert "set the box marked sec. beside Full Track to" in wn and "seconds box beside the mode menu" not in wn


# --- PR 3, the leftovers (Llano BL #11473): the tests that need the window, on this file's one server ----
# (the rest are in test_shows_page_leftovers_11473.py; a second file's server ran CI out of ports)

from tests.gigbar_lights.test_compilation_fill_11473 import _compilation  # noqa: E402
from tests.gigbar_lights.test_shows_page_leftovers_11473 import GOOD  # noqa: E402
from tools.gigbar_lights import shows  # noqa: E402


def test_the_paste_door_returns_what_it_left_out_and_says_so_when_nothing_is_a_song(window):  # noqa: F811
    _app, url, token, _tmp = window
    code, r = _call(url + "api/shows-paste", {"text": "\n".join(GOOD[:3] + ["not a song", "----", "September"])}, token)
    assert code == 200 and r["left_out"] == ["not a song", "----"]
    # "September" alone is a song: his library has it
    assert [s["title"] for s in r["songs"]] == ["September", "At Last", "Levitating", "September"]
    code, r = _call(url + "api/shows-paste", {"text": "not a song\n----\n"}, token)
    assert code == 400 and "not a song, ----" in r["error"] and "Title by Artist" in r["error"]


def test_with_no_mixxx_library_bare_titles_are_left_out_named_and_he_is_told_title_by_artist(window, monkeypatch):  # noqa: F811
    """His laptop before Load Mixxx: no library to know a bare title by. Three bare titles are not
    songs; they are named, and he is told to type Title by Artist. Pinned so nobody lets junk in."""
    import gigbar_app
    from tools.gigbar_lights.mixxx_db import MixxxLibrary
    _app, url, token, tmp = window
    none = MixxxLibrary(tmp / "no-mixxx-here" / "mixxxdb.sqlite")
    assert not none.available()
    monkeypatch.setattr(gigbar_app, "MixxxLibrary", lambda *a: none)
    code, r = _call(url + "api/shows-paste", {"text": "September\nAt Last\nLevitating"}, token)
    assert code == 400 and "September, At Last, Levitating" in r["error"] and "Title by Artist" in r["error"]
    assert r["left_out"] == ["September", "At Last", "Levitating"]
    code, r = _call(url + "api/shows-paste", {"text": "September\nAt Last by Etta James"}, token)
    assert code == 200 and r["left_out"] == ["September"] and [s["title"] for s in r["songs"]] == ["At Last"]


# --- the page, PR 3 ------------------------------------------------------------------------------------------

def _overflow(page) -> list:
    """Every shown element whose right edge is past the page's, and the page's own sideways scroll."""
    return page.evaluate("""() => {
      const w = document.documentElement.clientWidth, out = [];
      if (document.documentElement.scrollWidth > w + 1) out.push('page scrolls sideways: ' + document.documentElement.scrollWidth + ' > ' + w);
      for (const el of document.querySelectorAll('body *')) {
        const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
        const cs = getComputedStyle(el); if (cs.visibility === 'hidden' || cs.position === 'fixed') continue;
        if (r.right > w + 1 && !el.closest('[hidden]')) out.push((el.id || el.className || el.tagName) + ' right ' + Math.round(r.right));
      }
      return out.slice(0, 12);
    }""")


@pytest.mark.parametrize("size", [(1366, 768), (1024, 700)])
def test_the_shows_page_leftovers_in_a_browser(window, size):  # noqa: F811
    pw = pytest.importorskip("playwright.sync_api")
    app, url, token, tmp = window
    root = _compilation(tmp / f"w{size[0]}")
    for name in list(shows.saved_shows()):   # one file, one server: each size starts with no saved show
        app.link.local_change([{"path": f"shows.{name}", "value": None}])
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            page = browser.new_page(viewport={"width": size[0], "height": size[1]})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url + "shows")
            page.wait_for_selector("#save")
            assert "None yet" in page.inner_text("#saved")
            # 1: the folder names the show; the arranger's save shows it on the left at once, and says the name
            page.fill("#folder", str(root))
            page.click("#addfolder")
            page.wait_for_function("!document.querySelector('#design').disabled", timeout=30000)
            assert page.input_value("#title") == "C and M Wedding"
            # the add's long line wraps the header: the press still lands (a line cleared on pointerdown moved
            # the page under the pointer, and this press opened nothing)
            page.click("#arrange")
            page.wait_for_function("!document.querySelector('#arruse').disabled", timeout=20000)
            # 4: the arranger's note, at its longest, wraps inside the page
            page.evaluate("""() => { arr.suggestions = [{text: '3 songs the arranger doesn\\'t know by reputation (Come Away With Me, ' +
                'Just The Way You Are, One More Time, A Very Long Song Title Indeed, Another Long One): their energy comes from ' +
                'tempo alone, so check where they landed.'}]; renderArranger(); }""")
            assert _overflow(page) == []
            page.click("#arruse")
            page.wait_for_function("document.querySelector('#saved').innerText.includes('C and M Wedding')", timeout=10000)
            assert page.inner_text("#msg") == 'Saved as "C and M Wedding". Change the name at the top any time.'
            assert "Saved as the show's order" in page.inner_text("#log")
            # the next save of the same show is a plain one; two quick presses make one show, not two
            page.evaluate("() => { document.querySelector('#save').click(); document.querySelector('#save').click(); }")
            page.wait_for_function("document.querySelector('#msg').innerText === 'Saved \"C and M Wedding\".'", timeout=10000)
            time.sleep(0.5)
            assert [s["title"] for s in page.evaluate("H.shows")] == ["C and M Wedding"]
            assert list(shows.saved_shows()) == ["c-and-m-wedding"]
            # 5: a line about an action clears on a step change; a warning stays until he acts
            page.evaluate("() => say('Every song has its lights. The looks you chose yourself were kept.', false)")
            page.click('#steps [data-step="1"]')
            assert page.inner_text("#msg") == ""
            page.evaluate("() => say('Every song has its lights. The looks you chose yourself were kept.', false)")
            page.click('#steps [data-step="7"]')
            assert page.inner_text("#msg") == ""
            page.evaluate("() => { msgStep = 0; curStep = 0; say('Give the show a name first.'); }")
            page.mouse.move(5, 5)
            time.sleep(0.2)
            assert page.inner_text("#msg") == "Give the show a name first."
            page.click("#title")
            assert page.inner_text("#msg") == ""
            page.evaluate("() => say('Give the show a name first.')")
            page.fill("#title", "C and M Wedding")   # a box filled with no key pressed (a paste) is acting too
            assert page.inner_text("#msg") == ""
            page.evaluate("() => { curStep = 1; say('Added 3 songs.', false); }")
            page.click('#steps [data-step="1"]')       # the same step: a line about its action stays
            assert page.inner_text("#msg") == "Added 3 songs."
            page.evaluate("() => say('Saved.', false)")
            page.wait_for_function("document.querySelector('#msg').innerText === ''", timeout=11500)
            # 3: paste ten songs and three lines that are not
            page.click('[data-tab="paste"]')
            page.fill("#paste", "\n".join(GOOD + ["not a song", "----", ""]))
            page.click("#addpaste")
            page.wait_for_function("document.querySelector('#msg').innerText.includes('did not look like songs')", timeout=20000)
            msg = page.inner_text("#msg")
            assert "2 lines did not look like songs and were left out: not a song, ----. If one is a song, type it as Title by Artist." in msg, msg
            assert not page.evaluate("show.songs.filter(s => s.title === 'not a song' || s.title === '----').length")
            assert _overflow(page) == []
            # 2: rehearse, then leave the page: the app stops, and the header said Previewing only while it ran
            page.evaluate("() => { for (const s of show.songs) s.playable = false; }")
            page.click("#play")
            page.wait_for_function("document.querySelector('#runline').innerText.startsWith('Previewing:')", timeout=20000)
            assert app.running == "show"
            page.goto(url + "preview")
            for _ in range(80):
                if not app.running:
                    break
                time.sleep(0.1)
            assert not app.running, f"the rehearsal kept running after he left: {app.running}"
            assert errors == []
        finally:
            browser.close()
