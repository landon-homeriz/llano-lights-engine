"""Starts at and Ends at (Llano PM #23751): a dance song's copy for the night starts where the dancing
starts and ends where it stops, he can hear it and move both in Review, Cocktail hour, dinner and the
moments stay whole unless he changes them, his files are never changed, and the lights follow the copy.

The report: "I Gotta Feeling" has about 30 seconds before the song really starts; Mixxx's Auto DJ plays
every file from its first second, so the floor would wait. Its intro is NOT quiet (as loud as the verse),
so the old rule ("start where the music arrives") kept all of it."""
import json
import math
import sqlite3

import pytest

np = pytest.importorskip("numpy")

from tools.gigbar_lights import set_cuts as sc  # noqa: E402
from tools.gigbar_lights import settings_contract as contract  # noqa: E402
from tools.gigbar_lights import shows  # noqa: E402
from tools.gigbar_lights import wedding_night as wn  # noqa: E402

RATE = 22050


def tone(secs, parts, hits=0.0, hit_every=0.5, rate=RATE):
    """`parts` [(hz, level)] summed, with a click every `hit_every` seconds at `hits` level."""
    n = int(secs * rate)
    t = np.arange(n) / rate
    x = sum(lv * np.sin(2 * np.pi * hz * t) for hz, lv in parts)
    if hits:
        x[:: int(rate * hit_every)] += hits
    return x


def dance_song(intro=30.0, groove=120.0, tail=20.0):
    """A loud opening loop with no bass (I Gotta Feeling's shape), the song with kick and bass, then an
    ambient tail with no beat, about 8 dB down."""
    a = tone(intro, [(880, 0.20), (1320, 0.10)], hits=0.15)                 # as loud as the song, other timbre
    b = tone(groove, [(55, 0.25), (110, 0.15), (440, 0.10)], hits=0.30)    # kick and bass
    c = tone(tail, [(880, 0.08), (1320, 0.04)])                             # a pad: no beat, no bass
    x = np.concatenate([a, b, c])
    return np.stack([x, x], axis=1).astype(np.float32)


@pytest.fixture(scope="module")
def song():
    return dance_song()


# --- where the dancing starts and stops -------------------------------------------------------------

def test_a_loud_intro_is_found_where_the_song_changes_and_the_tail_where_the_beat_stops(song):
    p = sc.dance_points(song, RATE)
    assert abs(p.starts_s - 30.0) <= 0.6, p             # on the hit where the groove comes in
    assert 28.5 <= p.intro_s <= 30.6 and p.intro_s > sc.LONG_INTRO_S
    assert 148.0 <= p.ends_s <= 151.0, p
    assert 18.0 <= p.outro_s <= 22.0 and p.outro_s > sc.LONG_OUTRO_S
    assert 0.0 < p.bar_s < 6.0


def test_a_song_with_no_change_has_no_intro_and_no_tail():
    x = tone(120, [(55, 0.25), (440, 0.1)], hits=0.3)
    p = sc.dance_points(np.stack([x, x], axis=1).astype(np.float32), RATE)
    assert p.starts_s < 0.5 and p.intro_s == 0.0 and p.outro_s < sc.OUTRO_MIN_S


def test_a_change_late_in_the_song_is_a_verse_not_an_intro():
    # 60 s of opening before the change: past INTRO_MAX_S, so nothing is cut
    x = dance_song(intro=60.0)
    assert sc.dance_points(x, RATE).starts_s < 0.5


def test_a_dance_cut_starts_on_the_downbeat_and_leaves_where_the_dancing_stops(song):
    c = sc.plan(song, RATE, "dancing")
    assert abs(c.start_s + c.fade_in_s - c.suggest_start_s) < 0.01 and c.fade_in_s == sc.START_FADE_S
    assert abs(c.suggest_start_s - 30.0) <= 0.6 and "where the dancing starts" in c.why
    assert c.kind == "left the outro" and abs(c.end_s - (c.suggest_end_s)) < 0.01
    assert c.end_s < 152.6 and c.fade_s == sc.END_FADE_S
    y = sc.render(song, RATE, c)
    lead = int(sc.LEAD_S * RATE)
    assert np.abs(y[lead:lead + 20]).max() < 0.05       # faded in: no click at the cut
    down = lead + int(c.fade_in_s * RATE)
    assert np.abs(y[down: down + int(0.3 * RATE)]).max() > 0.3   # the downbeat lands at full
    assert np.abs(y[-20:]).max() < 0.02                 # faded out at the end: no dead air, no click


def test_two_trimmed_dance_songs_hand_off_with_no_dead_air(song):
    c = sc.plan(song, RATE, "dancing")
    a = sc.render(song, RATE, c)
    mix, _ = sc.handoff(a, a, RATE, before_s=3, after_s=4)
    env = sc.envelope(mix, RATE, 0.1)
    assert (env < -35).sum() * 0.1 <= 0.5


def test_line_dances_and_soft_parts_stay_whole_and_a_line_dance_still_shows_the_suggestion(song):
    line = sc.plan(song, RATE, "dancing", whole=True)          # a line dance: its calls start in the intro
    assert line.start_s < 0.5 and line.end_s > 165
    assert abs(line.suggest_start_s - 30.0) <= 0.6 and line.intro_s > sc.LONG_INTRO_S
    dinner = sc.plan(song, RATE, "dinner")
    # dinner keeps the intro; it leaves a long fade the way it always has, later than a dance song would
    assert dinner.start_s < 0.5 and dinner.end_s > line.suggest_end_s and dinner.intro_s == 0.0
    assert dinner.suggest_start_s < 0.5


def test_his_starts_at_and_ends_at_win_for_any_part(song):
    c = sc.plan(song, RATE, "dancing", start_at_s=10.0, end_at_s=100.0)
    assert abs(c.start_s + c.fade_in_s - 10.0) < 0.01 and c.end_s == 100.0
    assert c.kind == "yours" and c.mine == "both" and "where you set it" in c.why
    top = sc.plan(song, RATE, "dancing", start_at_s=0.0)       # from the top: every note
    assert top.start_s < 0.05 and top.fade_in_s == 0.0 and top.mine == "start"
    to_end = sc.plan(song, RATE, "dancing", end_at_s=999.0)    # to the end: the tail plays out
    assert to_end.end_s > 165 and to_end.mine == "end"
    dinner = sc.plan(song, RATE, "dinner", start_at_s=30.0)    # a dinner song he chose to start later
    assert abs(dinner.start_s + dinner.fade_in_s - 30.0) < 0.01
    bad = sc.plan(song, RATE, "dancing", start_at_s=168.0)     # past the end: ignored
    assert bad.mine == ""


# --- the build -------------------------------------------------------------------------------------

def write(path, x):
    sf = pytest.importorskip("soundfile")
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), x, RATE)
    return path


def test_the_build_cuts_at_his_points_reports_the_seconds_and_never_touches_his_file(tmp_path, song):
    pytest.importorskip("soundfile")
    src = write(tmp_path / "songs" / "3 - Dancing" / "Black Eyed Peas - I Gotta Feeling.wav", song)
    before = src.read_bytes()
    s = {"artist": "Black Eyed Peas", "title": "I Gotta Feeling", "part": "dancing"}
    # a song opens the dancing ahead of it: the set's first song keeps its intro (PM #23864)
    first = {"artist": "Opener", "title": "First", "part": "dancing"}
    write(tmp_path / "songs" / "3 - Dancing" / "Opener - First.wav", dance_song(intro=0.0, groove=60.0, tail=0.0))
    files = wn.index_folder(tmp_path / "songs")
    out = tmp_path / "night"

    def mine(r):
        return next(c for c in r["cuts"] if c["title"] == "I Gotta Feeling")
    r = wn.build(out, [first, s], files, extras=False)
    c = mine(r)
    assert not c["opens"] and next(c for c in r["cuts"] if c["title"] == "First")["opens"]
    assert 29.0 <= c["cut_start_s"] <= 30.0 and 15.0 <= c["cut_end_s"] <= 22.0
    assert c["long_intro"] and c["long_outro"] and c["kind"] == "left the outro"
    assert src.read_bytes() == before                         # his original is never changed
    import soundfile
    built = soundfile.info(str(out / c["file"]))
    assert abs(built.duration - c["plays_s"]) < 0.1           # the file is the shorter song
    # he moves Starts at in Review: the next build measures that song again and cuts there
    r2 = wn.build(out, [first, {**s, "start_at": 12.0, "end_at": 0}], files, extras=False)
    c2 = mine(r2)
    assert abs(c2["start_s"] + c2["fade_in_s"] - 12.0) < 0.01 and c2["mine"] == "start" and r2["redone"] == 1
    # the same again is kept, not measured again
    r3 = wn.build(out, [first, {**s, "start_at": 12.0, "end_at": 0}], files, extras=False)
    assert r3["kept"] == 2 and r3["redone"] == 0


def test_cut_args_moments_line_dances_and_his_points():
    assert wn.cut_args({"artist": "A", "title": "B"}, "dancing")["whole"] is False
    assert wn.cut_args({"artist": "Cupid", "title": "Cupid Shuffle"}, "dancing")["whole"] is True
    assert wn.cut_args({"artist": "A", "title": "B"}, "moment") == {"part": "dinner", "whole": True,
                                                                    "start_at_s": None, "end_at_s": None,
                                                                    "keep_intro": False}
    got = wn.cut_args({"artist": "A", "title": "B", "start_at": 29.5, "end_at": "x"}, "cocktail")
    assert got["part"] == "dinner" and got["start_at_s"] == 29.5 and got["end_at_s"] is None
    for junk in (True, -1, float("nan"), "29", None, ""):
        assert wn._point(junk) is None or junk == "29"     # a typed string number is read as seconds


def test_song_points_and_the_cache_read_each_file_once(tmp_path, song, monkeypatch):
    pytest.importorskip("soundfile")
    src = write(tmp_path / "Black Eyed Peas - I Gotta Feeling.wav", song)
    s = {"artist": "Black Eyed Peas", "title": "I Gotta Feeling", "part": "dancing"}
    cache = wn.PointsCache(tmp_path / "song_points.json")
    p = cache.get(s, "dancing", src)
    assert p["follows"] and p["dancing"] and p["long_intro"] and p["long_outro"]
    assert abs(p["start_s"] - p["suggest_start_s"]) < 0.01 and abs(p["suggest_start_s"] - 30.0) <= 0.6
    monkeypatch.setattr(sc, "read", lambda *a: (_ for _ in ()).throw(AssertionError("read again")))
    assert wn.PointsCache(tmp_path / "song_points.json").get(s, "dancing", src) == p   # kept on disk
    monkeypatch.undo()
    dinner = wn.PointsCache(tmp_path / "song_points.json").get(s, "dinner", src)
    assert not dinner["follows"] and dinner["start_s"] < 0.5 and not dinner["long_intro"]


# --- the show keeps his points -------------------------------------------------------------------------

def test_the_show_and_the_shared_contract_keep_his_points():
    raw = {"title": "W", "songs": [{"artist": "A", "title": "B", "look": "", "start_at": 29.237, "end_at": 250},
                                   {"artist": "C", "title": "D", "look": "", "start_at": True, "end_at": -4},
                                   {"artist": "E", "title": "F", "look": "", "start_at": float("nan"), "end_at": "12"}]}
    got = contract._show(raw, {})
    assert got["songs"][0]["start_at"] == 29.24 and got["songs"][0]["end_at"] == 250.0
    assert "start_at" not in got["songs"][1] and "end_at" not in got["songs"][1]
    assert "start_at" not in got["songs"][2] and "end_at" not in got["songs"][2]
    plain = contract._show({"title": "W", "songs": [{"artist": "A", "title": "B", "look": ""}]}, {})
    assert "start_at" not in plain["songs"][0]                # an older show keeps its exact bytes
    songs = shows.from_public([{"artist": "A", "title": "B", "start_at": 29.24, "end_at": None},
                               {"artist": "C", "title": "D", "start_at": "soon"}])
    assert songs[0].start_at == 29.24 and songs[0].end_at is None and songs[1].start_at is None
    assert songs[0].saved()["start_at"] == 29.24 and "end_at" not in songs[0].saved()
    assert "start_at" not in songs[1].saved()


# --- the lights follow the copy: Mixxx measures a re-cut song again ----------------------------------------

def test_load_mixxx_clears_the_old_beat_grid_of_a_song_whose_cut_changed(tmp_path):
    pytest.importorskip("soundfile")
    from tests.gigbar_lights.test_mixxx_load import mixxx_library  # noqa: PLC0415
    from tools.gigbar_lights import mixxx_load  # noqa: PLC0415

    db = mixxx_library(tmp_path / "mixxxdb.sqlite")
    conn = sqlite3.connect(db)
    f = write(tmp_path / "night" / "Songs" / "3 - Dancing" / "A - B.flac", dance_song()[: RATE * 60])
    same = write(tmp_path / "night" / "Songs" / "3 - Dancing" / "C - D.flac", dance_song()[: RATE * 50])
    rows = []
    for p, stored in ((f, 90.0), (same, 50.0)):     # the first was 90 s when Mixxx measured it; now 60 s
        loc = conn.execute("INSERT INTO track_locations (location, filename, directory, filesize, fs_deleted, "
                           "needs_verification) VALUES (?, ?, ?, 1, 0, 0)",
                           (p.as_posix(), p.name, p.parent.as_posix())).lastrowid
        lib = conn.execute("INSERT INTO library (artist, title, location, duration, bpm, beats, beats_version, "
                           "mixxx_deleted) VALUES ('A', 'B', ?, ?, 128.0, x'00', 'BeatGrid-2.0', 0)",
                           (loc, stored)).lastrowid
        conn.execute("INSERT INTO cues (track_id, type, position, hotcue) VALUES (?, 1, 4410, 0)", (lib,))
        rows.append(lib)
    for p in (f, same):
        mixxx_load._track_id(conn, p)
    got = {r[0]: r[1:] for r in conn.execute("SELECT id, duration, bpm, beats, beats_version FROM library")}
    assert abs(got[rows[0]][0] - 60.0) < 0.1 and got[rows[0]][1:] == (0, None, None)
    assert got[rows[1]] == (50.0, 128.0, b"\x00", "BeatGrid-2.0")          # an unchanged cut keeps all of it
    cues = {r[0] for r in conn.execute("SELECT track_id FROM cues")}
    assert cues == {rows[1]}


# --- the app: Review reads each song's points, and plays only its own file -----------------------------------

def test_the_app_reads_points_one_song_at_a_time_and_plays_only_that_songs_file(window, tmp_path, song):  # noqa: F811
    pytest.importorskip("soundfile")
    from tests.gigbar_lights.test_shows import _call  # noqa: PLC0415

    app, url, token, tmp = window
    folder = tmp_path / "Wedding"
    write(folder / "3 - Dancing" / "Black Eyed Peas - I Gotta Feeling.wav", song)
    s = {"artist": "Black Eyed Peas", "title": "I Gotta Feeling", "part": "dancing"}
    code, r = _call(url + "api/shows-points", {"song": s, "folder": str(folder)}, token)
    assert code == 200 and r["points"]["long_intro"] and r["points"]["follows"]
    audio = r["points"]["audio"]
    assert audio.startswith("/song-audio/")
    code, body = _call(url + audio.lstrip("/"))
    assert code == 200 and body[:4] == b"RIFF"
    assert _call(url + "song-audio/..%2F..%2Fsettings.json")[0] == 404
    assert _call(url + "song-audio/nobody-nothing")[0] == 404
    code, r = _call(url + "api/shows-points", {"song": {**s, "title": "Not Here"}, "folder": str(folder)}, token)
    assert code == 200 and r["points"] is None and "not in the song folder" in r["why"]
    code, r = _call(url + "api/shows-points", {"song": {"artist": "A", "title": "B"}, "folder": str(folder)}, token)
    assert r["points"] is None and "part" in r["why"]


from tests.gigbar_lights.test_shows import lib, window  # noqa: E402,F401


def test_review_shows_starts_and_ends_and_he_can_hear_and_move_them(window, tmp_path, song):  # noqa: F811
    """In a real browser: the dance song's row says where its copy starts and ends and flags the long
    intro and ending; its times open the editor, a bar's nudge moves the start and plays from there,
    From the top and Llano's put it back, and the times go out with the show (start_at)."""
    pw = pytest.importorskip("playwright.sync_api")
    pytest.importorskip("soundfile")
    app, url, token, tmp = window
    folder = tmp_path / "Wedding"
    write(folder / "3 - Dancing" / "Black Eyed Peas - I Gotta Feeling.wav", song)
    write(folder / "2 - Dinner" / "Lonestar - Amazed.wav", song)
    write(folder / "3 - Dancing" / "Opener - First.wav", dance_song(intro=0.0, groove=60.0, tail=0.0))
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url + "shows")
            page.wait_for_selector("#save")
            page.evaluate("""f => { show.songs = [
                {artist: "Opener", title: "First", part: "dancing", look: "", secs: 60, sections: [{kind: "main", start: 0, end: 60, energy: 0.8}]},
                {artist: "Black Eyed Peas", title: "I Gotta Feeling", part: "dancing", look: "", secs: 170, sections: [{kind: "main", start: 0, end: 170, energy: 0.8}]},
                {artist: "Lonestar", title: "Amazed", part: "dinner", look: "", secs: 170, sections: [{kind: "main", start: 0, end: 170, energy: 0.4}]}];
                $("#nightfolder").value = f; renderAll(); }""", str(folder))
            page.wait_for_function("document.querySelectorAll('#songs .cutbtn').length === 3", timeout=60000)
            cells = page.eval_on_selector_all("#songs .cut", "els => els.map(e => e.innerText.replace(/\\s+/g, ' ').trim())")
            assert cells[1].startswith("0:30") and "intro 30 s" in cells[1] and "ending" in cells[1], cells
            assert cells[2].startswith("0:00") and "intro" not in cells[2], cells        # dinner plays whole
            assert "Long intros (1 song): I Gotta Feeling 30 s" in page.inner_text("#cutsum")
            assert "Found where 3 songs start and end." in page.inner_text("#listenline")
            page.click("#songs .cutbtn >> nth=1")
            page.wait_for_selector("tr.cutedit")
            assert "Llano hears the dancing start at 0:30" in page.inner_text("tr.cutedit")
            from tests.gigbar_lights.test_shows_page_fixes_11473 import _overflow  # noqa: PLC0415
            for w in (1024, 1366):                    # the open editor fits a laptop screen
                page.set_viewport_size({"width": w, "height": 700})
                assert _overflow(page) == [], w
            before = page.input_value("tr.cutedit input[data-cutat=start]")
            page.click("tr.cutedit [data-cutdo='start+']")
            after = page.input_value("tr.cutedit input[data-cutat=start]")
            assert after != before and page.evaluate("show.songs[1].start_at") > 30
            page.wait_for_function("!cutAudio.paused && cutAudio.currentTime > 30", timeout=10000)   # it plays from there
            assert page.evaluate("cutAudio.src").endswith("/song-audio/black-eyed-peas-i-gotta-feeling")
            page.click("tr.cutedit [data-cutdo='starttop']")
            assert page.evaluate("show.songs[1].start_at") == 0 and "0:00" in page.inner_text("#songs .cutbtn >> nth=1")
            page.click("tr.cutedit [data-cutdo='startllano']")
            assert page.evaluate("show.songs[1].start_at === undefined")
            page.fill("tr.cutedit input[data-cutat=end]", "2:10")
            page.press("tr.cutedit input[data-cutat=end]", "Enter")
            page.wait_for_function("show.songs[1].end_at === 130")
            page.fill("tr.cutedit input[data-cutat=end]", "soon")
            page.press("tr.cutedit input[data-cutat=end]", "Enter")
            page.wait_for_function("document.querySelector('#msg').innerText.includes('Type a time like')")
            assert page.evaluate("show.songs[1].end_at") == 130
            assert errors == []
        finally:
            browser.close()
