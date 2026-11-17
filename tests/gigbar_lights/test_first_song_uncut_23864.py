"""A set's opening song plays from its first note (Llano PM #23864).

From a wedding's prep notes: Footloose is the first song, so it needs to start at the
beginning. Build the night (1.34.0) cut every dance song's intro, the dancing's first song included
(Footloose started at 0:17). Now the first song of cocktail hour, of dinner and of each dancing set keeps
its intro; Llano's reading of where the dancing starts stays on offer in Review, and his own Starts at
still wins."""
import pytest

np = pytest.importorskip("numpy")

from tests.gigbar_lights.test_starts_ends_23751 import RATE, dance_song, write  # noqa: E402
from tools.gigbar_lights import set_cuts as sc  # noqa: E402
from tools.gigbar_lights import wedding_night as wn  # noqa: E402


@pytest.fixture(scope="module")
def song():
    return dance_song()


def S(title, part="dancing", **kw):
    return {"artist": "Band", "title": title, "part": part, "secs": 180, **kw}


# --- the cut -----------------------------------------------------------------------------------------

def test_an_opening_song_keeps_its_intro_and_still_offers_the_cut(song):
    c = sc.plan(song, RATE, "dancing", keep_intro=True)
    assert c.start_s < 0.5 and c.fade_in_s == 0.0                  # from its first note
    assert abs(c.suggest_start_s - 30.0) <= 0.6 and c.intro_s > sc.LONG_INTRO_S   # Llano's cut, still offered
    assert c.kind == "left the outro"                              # its ending is cut as any other's
    assert "where the dancing starts" not in c.why


def test_an_opening_songs_quiet_intro_stays_too():
    quiet = np.concatenate([0.01 * np.sin(2 * np.pi * 440 * np.arange(8 * RATE) / RATE),
                            0.3 * np.sin(2 * np.pi * 110 * np.arange(60 * RATE) / RATE)])
    x = np.stack([quiet, quiet], axis=1).astype(np.float32)
    assert sc.plan(x, RATE, "dancing").start_s > 5.0               # any other song: the quiet intro is trimmed
    assert sc.plan(x, RATE, "dancing", keep_intro=True).start_s < 0.5


def test_his_own_starts_at_still_wins_on_an_opening_song(song):
    c = sc.plan(song, RATE, "dancing", keep_intro=True, start_at_s=17.0)
    assert abs(c.start_s + c.fade_in_s - 17.0) < 0.01 and c.mine == "start"


# --- which songs open a set --------------------------------------------------------------------------

def test_the_first_song_of_each_part_opens_and_a_moment_song_does_not():
    songs = [S("Toast song", moment="toasts"), S("Cocktail 1", "cocktail"), S("Cocktail 2", "cocktail"),
             S("Dinner 1", "dinner"), S("Dinner 2", "dinner"), S("Footloose"), S("Baby"), S("Wagon Wheel")]
    arranged = wn.arrange(songs, {})
    got = wn.opening_keys(arranged["parts"], arranged["moment_songs"], skip=arranged["off"])
    assert {wn.key_of(S(t)) for t in ("Cocktail 1", "Dinner 1", "Footloose")} <= got
    assert not got & {wn.key_of(S(t)) for t in ("Baby", "Wagon Wheel", "Cocktail 2", "Dinner 2", "Toast song")}


def test_a_song_with_no_file_does_not_open_the_next_one_does():
    songs = [S("Footloose"), S("Baby")]
    parts = wn.arrange(songs, {})["parts"]
    got = wn.opening_keys(parts, files={wn.key_of(S("Baby")): "x.wav"})
    assert got == {wn.key_of(S("Baby"))}


def test_every_dancing_set_has_its_opener():
    songs = [S(f"Dance {i}") for i in range(8)]
    arranged = wn.arrange(songs, {})
    order = ("dancing", "cake", "dancing")
    got = wn.opening_keys(arranged["parts"], arranged["moment_songs"], order=order, skip=set())
    assert wn.key_of(S("Dance 0")) in got and len(got) == 2


def test_cut_args_marks_an_opener_only_in_a_set():
    assert wn.cut_args(S("A"), "dancing", opens=True)["keep_intro"] is True
    assert wn.cut_args(S("A"), "dancing")["keep_intro"] is False
    assert wn.cut_args(S("A"), "moment", opens=True)["keep_intro"] is False
    assert wn.cut_args(S("A"), "toasts-background", opens=True)["keep_intro"] is False


# --- the build: Footloose from 0:00 ------------------------------------------------------------------

def test_the_build_plays_the_dancings_first_song_from_its_first_note(tmp_path, song):
    pytest.importorskip("soundfile")
    write(tmp_path / "songs" / "3 - Dancing" / "Kenny Loggins - Footloose.wav", song)
    write(tmp_path / "songs" / "3 - Dancing" / "Black Eyed Peas - I Gotta Feeling.wav", song)
    first = {"artist": "Kenny Loggins", "title": "Footloose", "part": "dancing"}
    second = {"artist": "Black Eyed Peas", "title": "I Gotta Feeling", "part": "dancing"}
    files = wn.index_folder(tmp_path / "songs")
    out = tmp_path / "night"
    r = wn.build(out, [first, second], files, extras=False)
    cuts = {c["title"]: c for c in r["cuts"]}
    assert cuts["Footloose"]["opens"] and cuts["Footloose"]["cut_start_s"] < 0.5
    assert abs(cuts["Footloose"]["suggest_start_s"] - 30.0) <= 0.6         # the cut is still offered
    assert not cuts["I Gotta Feeling"]["opens"] and 29.0 <= cuts["I Gotta Feeling"]["cut_start_s"] <= 30.0
    # he reorders: the new opener plays whole, the old one is cut, both measured again
    r2 = wn.build(out, [second, first], files, extras=False)
    cuts = {c["title"]: c for c in r2["cuts"]}
    assert cuts["I Gotta Feeling"]["cut_start_s"] < 0.5 and 29.0 <= cuts["Footloose"]["cut_start_s"] <= 30.0
    assert r2["redone"] == 2


def test_a_night_built_under_the_old_rules_is_measured_again(tmp_path, song, monkeypatch):
    """His laptop's night.json carries 1.34.0's cut of Footloose (0:17): the next build must not keep it."""
    pytest.importorskip("soundfile")
    write(tmp_path / "songs" / "3 - Dancing" / "Kenny Loggins - Footloose.wav", song)
    s = {"artist": "Kenny Loggins", "title": "Footloose", "part": "dancing"}
    files = wn.index_folder(tmp_path / "songs")
    out = tmp_path / "night"
    monkeypatch.setattr(wn, "opening_keys", lambda *a, **k: set())     # the old build: no opener
    monkeypatch.setattr(wn, "CUT_RULES", 2)
    old = wn.build(out, [s], files, extras=False)
    assert old["cuts"][0]["cut_start_s"] > 29.0
    monkeypatch.undo()
    r = wn.build(out, [s], files, extras=False)
    assert r["redone"] == 1 and r["cuts"][0]["cut_start_s"] < 0.5


# --- Review ------------------------------------------------------------------------------------------

def test_review_points_for_an_opener_read_0_00_and_offer_llanos_cut(tmp_path, song):
    pytest.importorskip("soundfile")
    src = write(tmp_path / "Kenny Loggins - Footloose.wav", song)
    s = {"artist": "Kenny Loggins", "title": "Footloose", "part": "dancing"}
    cache = wn.PointsCache(tmp_path / "song_points.json")
    p = cache.get(s, "dancing", src, opens=True)
    assert p["opens"] and p["start_s"] < 0.5 and abs(p["suggest_start_s"] - 30.0) <= 0.6 and p["long_intro"]
    other = cache.get(s, "dancing", src)                 # not first: a separate cache row, the cut
    assert not other["opens"] and abs(other["start_s"] - 30.0) <= 0.6


from tests.gigbar_lights.test_shows import lib, window  # noqa: E402,F401


def test_review_shows_the_first_song_from_the_top_with_llanos_cut_on_a_button(window, tmp_path, song):  # noqa: F811
    pw = pytest.importorskip("playwright.sync_api")
    pytest.importorskip("soundfile")
    app, url, token, tmp = window
    folder = tmp_path / "Wedding"
    write(folder / "3 - Dancing" / "Kenny Loggins - Footloose.wav", song)
    write(folder / "3 - Dancing" / "Black Eyed Peas - I Gotta Feeling.wav", song)
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url + "shows")
            page.wait_for_selector("#save")
            page.evaluate("""f => { show.songs = [
                {artist: "Kenny Loggins", title: "Footloose", part: "dancing", look: "", secs: 170, sections: [{kind: "main", start: 0, end: 170, energy: 0.8}]},
                {artist: "Black Eyed Peas", title: "I Gotta Feeling", part: "dancing", look: "", secs: 170, sections: [{kind: "main", start: 0, end: 170, energy: 0.8}]}];
                $("#nightfolder").value = f; renderAll(); }""", str(folder))
            page.wait_for_function("document.querySelectorAll('#songs .cutbtn').length === 2", timeout=60000)
            cells = page.eval_on_selector_all("#songs .cut", "els => els.map(e => e.innerText.replace(/\\s+/g, ' ').trim())")
            assert cells[0].startswith("0:00") and "intro 30 s" in cells[0], cells     # Footloose: from the top
            assert cells[1].startswith("0:30"), cells
            page.click("#songs .cutbtn >> nth=0")
            page.wait_for_selector("tr.cutedit")
            text = page.inner_text("tr.cutedit")
            assert "first song of its set, so it plays from the top" in text and "Llano's (0:30" in text, text
            page.click("tr.cutedit [data-cutdo='startllano']")
            assert 29.0 <= page.evaluate("show.songs[0].start_at") <= 31.0        # he can still take the cut
            page.click("tr.cutedit [data-cutdo='starttop']")
            assert page.evaluate("show.songs[0].start_at") == 0
            assert errors == []
        finally:
            browser.close()
