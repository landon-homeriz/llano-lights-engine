"""Shows (his recording 2026-11-08, 1:10 to 7:08): a playlist in, every song analyzed, the whole show
designed and laid out front to back, played in the window, saved by name and opened again."""
import json
import sqlite3
import struct

import pytest

from tools.gigbar_lights import settings_contract as contract
from tools.gigbar_lights import show_settings, shows
from tools.gigbar_lights.demo_songs import SongClock
from tools.gigbar_lights.mixxx_db import MixxxLibrary
from tools.gigbar_lights.show import Show
from tools.gigbar_lights.show_script import ScriptCache, Section, ShowScript


def _varint(n):
    out = b""
    while True:
        b, n = n & 0x7F, n >> 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def _grid(bpm, first_frame):
    bpm_msg = bytes([0x09]) + struct.pack("<d", bpm)
    beat = _varint(1 << 3) + _varint(first_frame)
    return (_varint(1 << 3 | 2) + _varint(len(bpm_msg)) + bpm_msg +
            _varint(2 << 3 | 2) + _varint(len(beat)) + beat)


@pytest.fixture
def lib(tmp_path):
    db = tmp_path / "mixxxdb.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE library (id INTEGER PRIMARY KEY, artist TEXT, title TEXT, duration REAL,
            bpm REAL, samplerate INTEGER, beats BLOB, beats_version TEXT, mixxx_deleted INTEGER,
            location INTEGER, datetime_added TEXT);
        CREATE TABLE track_locations (id INTEGER PRIMARY KEY, location TEXT);
        CREATE TABLE Playlists (id INTEGER PRIMARY KEY, name TEXT, hidden INTEGER);
        CREATE TABLE PlaylistTracks (id INTEGER PRIMARY KEY, playlist_id INTEGER, track_id INTEGER,
            position INTEGER, pl_datetime_added TEXT);
        CREATE TABLE crates (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE crate_tracks (crate_id INTEGER, track_id INTEGER);
    """)
    files = []
    for i in range(1, 5):
        f = tmp_path / f"song{i}.mp3"
        f.write_bytes(b"x")
        files.append(f)
    rows = [(1, "Earth, Wind & Fire", "September", 215.0, 126.0),
            (2, "Etta James", "At Last", 182.0, 87.0),
            (3, "Dua Lipa", "Levitating", 203.0, 103.0),
            (4, "Journey", "Don't Stop Believin' - Remastered 2022", 250.0, 119.0)]
    for tid, a, t, d, bpm in rows:
        conn.execute("INSERT INTO library VALUES (?,?,?,?,?,44100,?,'BeatGrid-2.0',0,?,'2026-11-01')",
                     (tid, a, t, d, bpm, _grid(bpm, 22050), tid))
        conn.execute("INSERT INTO track_locations VALUES (?,?)", (tid, str(files[tid - 1])))
    conn.execute("INSERT INTO library VALUES (9,'Gone','Deleted',100,120,44100,NULL,NULL,1,NULL,'')")
    conn.executemany("INSERT INTO Playlists VALUES (?,?,?)", [(1, "Megan party", 0), (2, "2026-11-06", 2)])
    conn.executemany("INSERT INTO PlaylistTracks (playlist_id, track_id, position) VALUES (1,?,?)",
                     [(3, 1), (1, 2), (2, 3), (9, 4)])
    conn.execute("INSERT INTO crates VALUES (1, 'Wedding')")
    conn.execute("INSERT INTO crate_tracks VALUES (1, 2)")
    conn.commit()
    conn.close()
    return MixxxLibrary(db)


@pytest.fixture(autouse=True)
def fresh_settings():
    show_settings.set_current(contract.defaults())
    show_settings.set_show_looks(None)
    yield
    show_settings.set_current(contract.defaults())
    show_settings.set_show_looks(None)


def test_mixxx_playlists_and_crates_in_order_history_and_deleted_left_out(lib):
    got = shows.lists(lib)
    assert [(x["kind"], x["name"], x["count"]) for x in got] == [("playlist", "Megan party", 4), ("crate", "Wedding", 1)]
    tracks = shows.list_tracks(lib, "playlist", 1)
    assert [t.title for t in tracks] == ["Levitating", "September", "At Last"]   # play order, deleted gone
    assert tracks[0].grid.bpm == 103.0 and tracks[0].location.is_file()
    assert [t.title for t in shows.list_tracks(lib, "crate", 1)] == ["At Last"]
    assert [t.title for t in shows.search(lib, "etta last")] == ["At Last"]
    assert shows.lists(MixxxLibrary(lib.path.parent / "none.sqlite")) == []


def test_pasted_list_every_common_shape():
    text = """1. Earth, Wind & Fire - September 3:35
    2) At Last by Etta James
    Levitating – Dua Lipa
    https://open.spotify.com/track/abc
    • Mr. Brightside"""
    got = shows.parse_list(text)
    assert got == [{"artist": "Earth, Wind & Fire", "title": "September", "secs": 215},
                   {"artist": "Etta James", "title": "At Last", "secs": 0.0},
                   {"artist": "Levitating", "title": "Dua Lipa", "secs": 0.0},
                   {"artist": "", "title": "Mr. Brightside", "secs": 0.0}]
    csv_text = "Track Name,Artist Name(s),Duration (ms)\nSeptember,\"Earth, Wind & Fire\",215000\n"
    assert shows.parse_list(csv_text) == [{"artist": "Earth", "title": "September", "secs": 215.0}]


def test_names_found_in_the_library_either_way_round_and_forgiving(lib):
    idx = shows.LibraryIndex(lib)
    assert idx.find("Journey", "Don't Stop Believin'").track_id == 4    # "Remastered 2022" forgiven
    assert idx.find("Levitating", "Dua Lipa").track_id == 3             # typed Title - Artist
    assert idx.find("", "At Last").track_id == 2
    assert idx.find("Nobody", "Not Here") is None


def test_spotify_playlist_read_from_the_public_embed_page_titles_only():
    data = {"props": {"pageProps": {"state": {"data": {"entity": {"name": "Wedding", "trackList": [
        {"title": "September", "subtitle": "Earth, Wind & Fire", "duration": 215000,
         "audioPreview": {"url": "https://p.scdn.co/never-fetched"}},
        {"title": "At Last", "subtitle": "Etta James", "duration": 182000}]}}}}}}
    page = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
    seen = []
    name, songs = shows.spotify_playlist("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=x",
                                         fetch=lambda u: seen.append(u) or page)
    assert seen == ["https://open.spotify.com/embed/playlist/37i9dQZF1DXcBWIGoYBM5M"]
    assert name == "Wedding"
    assert songs == [{"artist": "Earth", "title": "September", "secs": 215.0},
                     {"artist": "Etta James", "title": "At Last", "secs": 182.0}]
    with pytest.raises(shows.SpotifyError, match="isn't a Spotify playlist"):
        shows.spotify_playlist("https://example.com/x")
    with pytest.raises(shows.SpotifyError, match="public"):
        shows.spotify_playlist("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M", fetch=lambda u: "<html>")

    def offline(u):
        raise OSError("no network")
    with pytest.raises(shows.SpotifyError, match="paste the song names"):
        shows.spotify_playlist("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M", fetch=offline)


def test_sections_from_the_cached_analysis_in_seconds_else_estimated(lib, tmp_path):
    cache = ScriptCache(tmp_path / "cache")
    cache.put(1, ShowScript([Section("intro", 0, 32, 0.2), Section("drop", 32, 96, 0.9), Section("outro", 96, 128, 0.3)], 3))
    s = shows.analyze(shows.ShowSong("Earth, Wind & Fire", "September", track_id=1), lib, cache, read_audio=False)
    assert s.source == "mixxx" and s.playable and s.bpm == 126.0 and s.first_beat_s == 0.5
    assert [x["kind"] for x in s.sections] == ["intro", "drop", "outro"]
    assert s.sections[1]["start"] == pytest.approx(0.5 + 32 * 60 / 126, abs=0.01)
    assert s.sections[-1]["end"] == 215.0   # the last section runs to the song's end
    est = shows.analyze(shows.ShowSong("Nobody", "Spotify only", secs=200, bpm=128), lib, cache)
    assert est.source == "estimated" and not est.playable
    kinds = [x["kind"] for x in est.sections]
    assert kinds[0] == "intro" and kinds[-1] == "outro" and "drop" in kinds and est.sections[-1]["end"] == 200
    assert all(a["end"] == b["start"] for a, b in zip(est.sections, est.sections[1:]))


def test_design_gives_the_night_an_arc_and_keeps_what_he_chose():
    songs = [shows.ShowSong("A", f"S{i}", bpm=bpm) for i, bpm in enumerate([120, 124, 85, 122, 128, 126, 110, 124, 118, 120])]
    shows.design(songs)
    assert [s.look for s in songs] == ["warm-up", "warm-up", "slow-dance", "groove", "groove",
                                       "peak", "groove", "peak", "peak", "sing-along"]
    assert songs[2].why == "slow (85 BPM)"
    songs[4].look = "peak"
    filed = {"a-s0": "first-dance"}
    shows.design(songs, filed=filed, styles={"first-dance": {}}, keep=False)
    assert songs[0].look == "first-dance" and songs[0].why == "you filed it under first-dance"
    songs[3].look = "slow-dance"
    shows.design(songs, keep=True)
    assert songs[3].look == "slow-dance"


def test_saved_by_name_reopened_with_its_order_and_looks(lib, tmp_path):
    songs = [shows.ShowSong("Dua Lipa", "Levitating", look="peak", secs=203, bpm=103),
             shows.ShowSong("Nobody", "Spotify only", look="slow-dance", secs=180, bpm=80)]
    name, ops = shows.save_ops("Megan's birthday party", [s.saved() for s in songs])
    assert name == "megans-birthday-party"
    doc, _ = contract.apply_ops(show_settings.current(), ops)
    show_settings.set_current(doc)
    assert shows.list_public() == [{"name": name, "title": "Megan's birthday party", "songs": 2, "secs": 383}]
    got = shows.load(name, lib, ScriptCache(tmp_path / "c"))
    assert [(s["title"], s["look"], s["track_id"]) for s in got["songs"]] == [("Levitating", "peak", 3),
                                                                              ("Spotify only", "slow-dance", 0)]
    assert got["timeline"] == {"starts": [0.0, 203.0], "total": 383.0}
    # A different show with the same name words gets its own name; re-saving under its name replaces it.
    other, _ = shows.save_ops("Megans Birthday Party!", [songs[0].saved()])
    assert other == "megans-birthday-party-2"
    same, _ = shows.save_ops("Megan's birthday party v2", [songs[0].saved()], name=name)
    assert same == name
    with pytest.raises(contract.ContractError):
        shows.save_ops("", [songs[0].saved()])
    with pytest.raises(contract.ContractError):
        shows.save_ops("Empty", [])


def test_m3u_for_mixxx_lists_files_in_order(lib):
    songs = [shows.ShowSong("Dua Lipa", "Levitating", secs=203, track_id=3), shows.ShowSong("X", "Not here")]
    text = shows.m3u(songs, lib)
    assert text.splitlines()[:3] == ["#EXTM3U", "#EXTINF:203,Dua Lipa - Levitating", str(lib.path.parent / "song3.mp3")]
    assert "# not on this laptop: X - Not here" in text


def test_playing_a_show_walks_its_songs_and_each_plays_its_look():
    songs = [shows.ShowSong("A", "First", look="slow-dance", secs=4, bpm=120),
             shows.ShowSong("B", "Second", look="peak", secs=4, bpm=128)]
    for s in songs:
        s.sections = shows.estimated_sections(s.secs, s.bpm)
    show_settings.set_show_looks(shows.looks_for(songs))
    show = Show(analyze=False)
    feed = shows.ShowFeed(show, songs, SongClock())
    seen = []
    t = 100.0
    while t < 107.5:
        feed(t)
        show.frame(t) if hasattr(show, "frame") else None
        seen.append(feed.index)
        cfg, what = show.looks.show_for(show_settings.current(), show.tracks[1].song, show.tracks[1].keys)
        if t in (101.0, 106.0):
            assert what == ("show:slow-dance" if feed.index == 0 else "show:peak")
            assert (cfg["strobe"]["intensity"] == 0.0) == (feed.index == 0)
        t = round(t + 0.5, 2)
    assert seen[0] == 0 and seen[-1] == 1 and sorted(set(seen)) == [0, 1]
    assert show.tracks[1].info.title == "Second"
    # The window's report wins over the own clock: it says song 0, at 1.5 s.
    clock = SongClock()
    feed = shows.ShowFeed(show, songs, clock)
    clock.report("0", 1.5, True, now=200.0)
    feed(200.0)
    assert feed.index == 0
    clock.report("1", 0.2, True, now=201.0)
    feed(201.0)
    assert feed.index == 1


# --- the window: the Shows page end to end through the app's local server ---------------------------

def _call(url, body=None, token=""):
    import urllib.error
    import urllib.request
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",
                                 headers={"X-Llano-Token": token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw, ctype = r.read(), r.headers.get("Content-Type", "")
            return r.status, json.loads(raw) if "json" in ctype else raw
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


@pytest.fixture
def window(tmp_path, monkeypatch, lib):
    import argparse
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
    import gigbar_app
    from tools.gigbar_lights import demo_songs
    from tools.gigbar_lights.venue import LayoutStore

    monkeypatch.setenv("LLANO_LIGHTS_SYNC", "0")
    monkeypatch.setattr(gigbar_app.updater, "check", lambda: (None, "no update in tests"))
    monkeypatch.setattr(gigbar_app.show_settings, "default_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(gigbar_app, "MixxxLibrary", lambda *a: lib)
    monkeypatch.setattr(gigbar_app, "default_cache_dir", lambda: tmp_path / "scripts")
    # song 3 is a real, playable mp3 (a demo song) so the window can fetch it
    real = demo_songs.load()[0].path
    (lib.path.parent / "song3.mp3").write_bytes(real.read_bytes())
    opts = argparse.Namespace(seconds=0.0, bpm=128.0, no_browser=True, no_window=True, updated=False, update_failed=False)
    app = gigbar_app.App(opts, gigbar_app.LogBuffer(tmp_path / "log.txt"))
    app.preview = gigbar_app.Preview("", LayoutStore(tmp_path / "layouts"), app=app)
    yield app, app.preview.url, app.preview.token, tmp_path
    app.stop()
    if app.runner:
        app.runner.join(timeout=8)
    app.preview.close()


def test_shows_page_playlist_in_designed_saved_reopened_and_played(window):
    import time
    app, url, token, tmp = window
    code, page = _call(url + "shows")
    assert code == 200 and token.encode() in page and b"Pick the lights for every song" in page
    # the four look-alike buttons are gone (his 2026-11-13 ask): one for the order, two for the lights
    for old in (b">Design the whole show<", b">Design the rest<", b">Design it with Llano<", b">Arrange the set<", b'id="designrest"'):
        assert old not in page, old
    for now in (b"Put the songs in a good order", b"Have Llano design the lights", b"Start over, my picks too"):
        assert now in page, now
    code, home = _call(url + "api/shows-home", {}, token)
    assert code == 200 and home["mixxx"] and home["shows"] == [] and home["lists"][0]["name"] == "Megan party"
    assert {"slow-dance", "peak", "sing-along"} <= {l["name"] for l in home["looks"]}
    assert _call(url + "api/shows-home", {}, "wrong")[0] == 403

    _, got = _call(url + "api/shows-from-mixxx", {"kind": "playlist", "id": 1}, token)
    songs = got["songs"]
    assert [s["title"] for s in songs] == ["Levitating", "September", "At Last"]
    _, pasted = _call(url + "api/shows-paste", {"text": "Journey - Don't Stop Believin'\nNobody - Spotify only 3:00"}, token)
    assert [(s["track_id"], s["playable"]) for s in pasted["songs"]] == [(4, True), (0, False)]
    songs += pasted["songs"]
    for i, s in enumerate(songs):   # the page reads sections one song at a time
        code, r = _call(url + "api/shows-analyze", {"song": s}, token)
        assert code == 200
        songs[i] = r["song"]
    assert all(s["sections"] for s in songs) and songs[-1]["source"] == "estimated"
    _, d = _call(url + "api/shows-design", {"songs": songs}, token)
    songs = d["songs"]
    assert [s["look"] for s in songs] == ["warm-up", "groove", "slow-dance", "peak", "sing-along"]
    assert d["timeline"]["total"] == pytest.approx(203 + 215 + 182 + 250 + 180)

    code, saved = _call(url + "api/shows-save", {"title": "Megan's birthday party", "songs": songs}, token)
    assert code == 200 and saved["name"] == "megans-birthday-party"
    assert json.loads((tmp / "settings.json").read_text())["shows"]["megans-birthday-party"]["songs"][2]["look"] == "slow-dance"
    _, opened = _call(url + "api/shows-open", {"name": "megans-birthday-party"}, token)
    assert opened["title"] == "Megan's birthday party" and [s["look"] for s in opened["songs"]][-1] == "sing-along"
    assert opened["songs"][0]["track_id"] == 3

    code, audio = _call(url + "show-audio/3")
    assert code == 200 and len(audio) > 100_000
    assert _call(url + "show-audio/99")[0] == 404 and _call(url + "show-audio/..%2Fx")[0] == 404

    code, m = _call(url + "api/shows-mixxx-playlist", {"songs": songs, "title": "Megan's birthday party"}, token)
    assert code == 200 and m["path"].endswith("megans-birthday-party.m3u8")

    assert _call(url + "api/shows-play", {"songs": [], "title": "x"}, token)[0] == 400
    code, _ = _call(url + "api/shows-play", {"songs": opened["songs"], "title": "Megan's birthday party"}, token)
    assert code == 200
    deadline = time.time() + 10
    while app.preview.frames == 0 and time.time() < deadline:
        time.sleep(0.05)
    assert app.running == "show" and app.preview.frames > 0
    assert show_settings.show_looks()["dua-lipa-levitating"] == "warm-up"
    _, st = _call(url + "api/app")
    assert st["show_title"] == "Megan's birthday party" and st["show"] is True
    _call(url + "api/demo-clock", {"song": "2", "t": 10.0, "playing": True}, token)
    _call(url + "api/stop", {}, token)
    app.runner.join(timeout=8)
    assert app.running is None and show_settings.show_looks() is None

    code, left = _call(url + "api/shows-delete", {"name": "megans-birthday-party"}, token)
    assert code == 200 and left["shows"] == []


def test_live_show_follows_the_chosen_saved_show(window, monkeypatch):
    import time
    app, url, token, tmp = window
    monkeypatch.setattr(app, "prefs_file", tmp / "window.json")
    songs = [{"artist": "Dua Lipa", "title": "Levitating", "look": "peak", "secs": 203, "bpm": 103}]
    assert _call(url + "api/shows-live", {"name": "nope"}, token)[0] == 400
    _, saved = _call(url + "api/shows-save", {"title": "Avery's wedding", "songs": songs}, token)
    code, r = _call(url + "api/shows-live", {"name": saved["name"]}, token)
    assert code == 200 and r["live_show"] == "averys-wedding"
    assert _call(url + "api/shows-home", {}, token)[1]["live_show"] == "averys-wedding"
    seen = {}
    import gigbar_app
    monkeypatch.setitem(gigbar_app.MODES, "preview", ("Music, no lights", lambda opts: seen.update(
        looks=show_settings.show_looks()) or 0))
    assert app.run("preview")[0] == 200
    app.runner.join(timeout=8)
    assert seen["looks"]["dua-lipa-levitating"] == "peak"
    assert show_settings.show_looks() is None   # only while that Live show runs
    _call(url + "api/shows-live", {"name": ""}, token)
    seen.clear()
    app.run("preview")
    app.runner.join(timeout=8)
    assert seen["looks"] is None


def test_bad_input_from_the_page_never_stops_a_show():
    junk = [None, 5, {"title": ""}, {"title": "Ok", "secs": "x"}, {"title": "Fine", "artist": "A", "secs": 100, "bpm": 120,
             "track_id": "7", "sections": [{"kind": "drop", "start": 0, "end": 50}, {"kind": "evil", "start": 0, "end": 1},
                                           {"kind": "main", "start": "nan", "end": 9}, "x", {"kind": "intro"},
                                           {"kind": "outro", "start": 60, "end": 50}]}]
    songs = shows.from_public(junk)
    assert [s.title for s in songs] == ["Fine"]
    assert songs[0].track_id == 7 and songs[0].sections == [{"kind": "drop", "start": 0.0, "end": 50.0, "energy": 0.5}]
    assert shows.from_public("not a list") == [] and shows.parse_list("") == [] and shows.parse_list(None) == []
    show = Show(analyze=False)
    feed = shows.ShowFeed(show, [shows.ShowSong("A", "No sections", secs=0, bpm=0)], SongClock())
    feed(1.0)
    feed(2.0)   # no sections, no length, no tempo: plays on defaults instead of crashing
    assert feed.index == 0
    assert shows.slug("con") == "show-con" and shows.slug("!!!") == "show" and len(shows.slug("x" * 200)) <= 48


# --- review fixes (fresh-context review, 2026-11-08) ---------------------------------------------

def test_an_old_llano_without_shows_never_erases_the_laptops_shows(tmp_path):
    llano_sync = pytest.importorskip("tools.gigbar_lights.llano_sync", reason="the Llano link is not in this edition")
    link = llano_sync.LlanoLink(show_settings.SettingsFile(tmp_path / "settings.json"), version="1.11.0")
    name, ops = shows.save_ops("Megan's birthday party", [{"artist": "A", "title": "B", "look": "peak", "secs": 1, "bpm": 1}])
    doc, _ = contract.apply_ops(show_settings.current(), ops)
    show_settings.set_current(doc)
    old_server_doc = {k: v for k, v in contract.normalize({"master": 0.5}).items() if k != "shows"}
    link._apply(7, old_server_doc, force=True)
    assert show_settings.current()["master"] == 0.5 and name in show_settings.current()["shows"]
    link._apply(8, contract.normalize({"master": 0.4}), force=True)   # a Llano that knows shows: it wins
    assert show_settings.current()["shows"] == {}


def test_a_show_too_big_to_store_is_refused_before_saving_never_cut_later():
    wide = [{"artist": "é" * 80, "title": "ü" * 120, "look": "peak", "secs": 200, "bpm": 120}] * 80
    with pytest.raises(contract.ContractError, match="first 38 songs fit"):
        shows.save_ops("Huge", wide)
    with pytest.raises(contract.ContractError, match="too long"):
        shows.save_ops("Too many", [{"artist": "A", "title": f"S{i}"} for i in range(contract.MAX_SHOW_SONGS + 1)])
    name, ops = shows.save_ops("Full", [{"artist": "Some Artist Name", "title": f"A fairly long song title {i}", "look": "groove",
                                         "secs": 200, "bpm": 120} for i in range(contract.MAX_SHOW_SONGS)])
    assert len(contract.apply_ops(contract.defaults(), ops)[0]["shows"][name]["songs"]) == contract.MAX_SHOW_SONGS
    # the whole document stays under Llano's limit with every cap full
    doc = contract.defaults()
    for i in range(contract.MAX_SHOWS):
        doc["shows"][f"show-{i}"] = {"title": "x" * 80, "note": "n" * 300, "songs": [
            {"artist": "é" * 80, "title": "ü" * 120, "look": "peak", "secs": 1, "bpm": 1}] * contract.MAX_SHOW_SONGS}
    full = contract.normalize(doc)
    assert all(len(contract._dumps_ascii(s)) <= contract.MAX_SHOW_BYTES for s in full["shows"].values())
    # Llano's document limit is store.MAX_DOC_BYTES there (1280 KB as of BL #12087), 64 KB kept for the rest
    assert len(json.dumps(full["shows"], separators=(",", ":"))) < 1280 * 1024 - 64 * 1024 - 24 * 16 * 1024


def test_long_titles_normalize_the_same_twice():
    doc = contract.normalize({"shows": {"m": {"title": ("ab " * 40), "songs": [{"artist": "x " * 50, "title": "y " * 70}]}}})
    assert contract.normalize(doc) == doc and contract.diff_ops(doc, contract.normalize(doc)) == []


def test_a_style_change_mid_show_reaches_the_shows_looks():
    from tools.gigbar_lights.looks import LooksEngine
    eng = LooksEngine()
    show_settings.set_show_looks({"a-b": "peak", "c-d": ""})
    base = contract.defaults()
    cfg, what = eng.show_for(base, "a-b", ("a-b",))
    assert what == "show:peak" and cfg["strobe"]["intensity"] == 1.0
    base2 = contract.normalize({**base, "crowd_safe": False, "palettes": {**base["palettes"], "hot": [[0.5, 0.5]]}})
    cfg2, _ = eng.show_for(base2, "a-b", ("a-b",))
    assert cfg2["palettes"]["hot"] == [[0.5, 0.5]]   # the new settings, not the ones from the show's start
    assert eng.show_for(base2, "c-d", ("c-d",)) == (base2, "show:house")


def test_editing_a_show_while_it_plays_updates_the_running_show(window):
    import time
    app, url, token, tmp = window
    songs = [{"artist": "Dua Lipa", "title": "Levitating", "look": "peak", "secs": 203, "bpm": 103, "track_id": 3,
              "sections": [{"kind": "drop", "start": 0, "end": 203}]},
             {"artist": "Etta James", "title": "At Last", "look": "slow-dance", "secs": 182, "bpm": 87, "track_id": 2,
              "sections": [{"kind": "verse", "start": 0, "end": 182}]}]
    assert _call(url + "api/shows-play", {"songs": songs, "title": "Wedding"}, token)[0] == 200
    deadline = time.time() + 10
    while app.preview.frames == 0 and time.time() < deadline:
        time.sleep(0.05)
    code, r = _call(url + "api/shows-play", {"songs": songs[::-1], "title": "Wedding"}, token)
    assert code == 200 and r["updated"] is True
    assert [s.title for s in app.show_opts.show_songs] == ["At Last", "Levitating"]
    assert app.show_opts.show_feed.songs is app.show_opts.show_songs
    assert show_settings.show_looks()["etta-james-at-last"] == "slow-dance"
    assert _call(url + "show-audio/%C2%B2")[0] == 404


def test_a_page_missing_from_the_build_says_so_instead_of_an_empty_reply(window, monkeypatch, tmp_path):
    """1.11.0 shipped without shows.html; Edge showed ERR_EMPTY_RESPONSE (his 11-08 2:40 PM recording)."""
    import sys
    gigbar_app = sys.modules["gigbar_app"]
    _app, url, _token, _tmp = window
    monkeypatch.setattr(gigbar_app, "SHOWS_HTML", tmp_path / "gone" / "shows.html")
    code, body = _call(url + "shows")
    assert code == 500 and b"missing shows.html" in body and b"Check for updates" in body


# --- Llano's design (lights_show_design): the show's own looks, synced from llano.app ------------

GOLD = {"palettes": {"gold": [[0.1, 0.95]]}, "section_palette": {"verse": "gold"}, "strobe": {"intensity": 0.2},
        "note": "warm gold"}


def test_a_shows_own_look_plays_over_the_house_show_and_only_in_its_show():
    from tools.gigbar_lights.looks import LooksEngine
    eng = LooksEngine()
    base = contract.normalize({**contract.defaults(), "strobe": {"speed": 0.4}})
    show_settings.set_show_looks({"a-b": "golden-hour"}, {"golden-hour": contract.show_look(GOLD)})
    cfg, what = eng.show_for(base, "a-b", ("a-b",))
    assert what == "show:golden-hour" and cfg["section_palette"]["verse"] == "gold"
    assert cfg["strobe"]["intensity"] == 0.2 and cfg["strobe"]["speed"] == 0.4   # his house show underneath
    show_settings.set_show_looks({"a-b": "golden-hour"})            # another show: no such look, house show
    assert eng.show_for(base, "a-b", ("a-b",)) == (base, "show:golden-hour")
    show_settings.set_show_looks(None)
    assert show_settings.show_own_looks() == {}


def test_saving_from_the_laptop_keeps_llanos_looks_and_why(monkeypatch):
    doc = contract.normalize({"shows": {"wedding": {"title": "Wedding", "looks": {"golden-hour": GOLD}, "songs": [
        {"artist": "A", "title": "T", "look": "golden-hour", "why": "warm opener"}]}}})
    show_settings.set_current(doc)
    name, ops = shows.save_ops("Wedding", [{"artist": "A", "title": "T", "look": "golden-hour", "why": "warm opener"},
                                           {"artist": "B", "title": "U", "look": "", "why": ""}],
                               name="wedding", looks=doc["shows"]["wedding"]["looks"])
    saved = contract.normalize(contract.apply_ops(doc, ops)[0])["shows"]["wedding"]
    assert name == "wedding" and saved["looks"] == doc["shows"]["wedding"]["looks"]
    assert saved["songs"][0]["look"] == "golden-hour" and saved["songs"][0]["why"] == "warm opener"


def test_opening_a_llano_designed_show_brings_its_looks_and_why(window):
    app, url, token, tmp = window
    from tools.gigbar_lights import show_settings as ss
    ss.set_current(contract.normalize({"shows": {"wedding": {"title": "Wedding", "looks": {"golden-hour": GOLD},
                                                             "songs": [{"artist": "Earth, Wind & Fire", "title": "September",
                                                                        "look": "golden-hour", "why": "warm opener"}]}}}))
    code, got = _call(url + "api/shows-open", {"name": "wedding"}, token)
    assert code == 200 and "golden-hour" in got["looks"] and got["songs"][0]["why"] == "warm opener"
    code, page = _call(url + "shows")
    assert code == 200 and b"Design it with Llano" in page


# --- Shows, A folder: Browse, a pasted path, and a Save button that says why (Llano BL #12132) -------

def test_the_folder_picker_asks_windows_and_hands_back_only_a_real_folder(tmp_path, monkeypatch):
    from tools.gigbar_lights import folder_picker as fp
    assert fp.pick()[0] == "" and "Windows" in fp.pick()[1]              # off Windows it says so and opens nothing
    monkeypatch.setattr(fp, "_on_windows", lambda: True)
    songs = tmp_path / "Avery and Jordan Wedding"
    songs.mkdir()
    ran = []

    def modern(script, title, start):
        ran.append((script is fp.MODERN, title, start))
        return 0, str(songs), ""
    monkeypatch.setattr(fp, "_run", modern)
    assert fp.pick("Choose the folder", f'"{songs}"') == (str(songs), "")
    assert ran == [(True, "Choose the folder", str(songs))], "the Explorer-style picker first, opened where he was"
    monkeypatch.setattr(fp, "_run", lambda *a: (0, "", ""))
    assert fp.pick() == ("", "")                                          # Cancel is not an error
    monkeypatch.setattr(fp, "_run", lambda *a: (0, str(tmp_path / "gone"), ""))
    assert fp.pick() == ("", "")                                          # never a path that is not a folder
    # the Explorer-style picker can't start on this laptop: the older one is tried, then a plain reason
    tried = []

    def failing(script, title, start):
        tried.append(script is fp.MODERN)
        return (1, "", "Add-Type : cannot compile") if script is fp.MODERN else (0, str(songs), "")
    monkeypatch.setattr(fp, "_run", failing)
    assert fp.pick() == (str(songs), "") and tried == [True, False]
    monkeypatch.setattr(fp, "_run", lambda *a: (1, "", "no"))
    path, why = fp.pick()
    assert path == "" and "Paste the folder's path" in why
    monkeypatch.setattr(fp, "_run", lambda *a: (_ for _ in ()).throw(OSError("no powershell")))
    assert fp.pick()[1].startswith("Windows' folder picker didn't open")
    # one picker at a time: a second press while it is open is answered, never a second window
    assert fp._one.acquire(blocking=False)
    try:
        assert "already open" in fp.pick()[1]
    finally:
        fp._one.release()
    # what is sent: the Explorer-style dialog asked for folders, on top of the window he clicked in,
    # and nothing of his (a title, a path) is ever written into the script itself
    assert "DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7" in fp.MODERN and "0x20 | 0x40" in fp.MODERN
    assert "GetForegroundWindow()" in fp.MODERN and "0x80058000" in fp.MODERN
    assert "$env:LLANO_PICK_TITLE" in fp.MODERN and "$env:LLANO_PICK_START" in fp.CLASSIC
    for raw, want in ((f'"{songs}"', str(songs)), (f"  {songs}\n", str(songs)), ("file:///C:/Users/L/My%20Music", "C:\\Users\\L\\My Music"),
                      ("", ""), (None, "")):
        assert fp.clean(raw) == want


def test_browse_adds_a_folders_songs_in_folder_then_file_order(window, monkeypatch):
    app, url, token, tmp = window
    import gigbar_app
    src = tmp / "Wedding"
    for folder, name in (("2 - Dinner", "Etta James - At Last"), ("1 - Cocktail Hour", "b band - Zebra"),
                         ("1 - Cocktail Hour", "A Band - Apple"), ("3 - Dancing", "Dua Lipa - Levitating")):
        (src / folder).mkdir(parents=True, exist_ok=True)
        (src / folder / f"{name}.mp3").write_bytes(b"x")
    monkeypatch.setattr(gigbar_app.folder_picker, "pick", lambda title, start: (str(src), ""))
    code, r = _call(url + "api/shows-pick-folder", {"title": "Choose", "start": ""}, token)
    assert (code, r) == (200, {"path": str(src)})
    # the order he asked about: folder name, then file name, A to Z, whatever the capitals
    code, r = _call(url + "api/shows-folder", {"path": f'"{src}"'}, token)   # quoted, as "Copy as path" gives it
    assert code == 200 and [(x["title"], x["part"]) for x in r["songs"]] == [
        ("Apple", "cocktail"), ("Zebra", "cocktail"), ("At Last", "dinner"), ("Levitating", "dancing")]
    monkeypatch.setattr(gigbar_app.folder_picker, "pick", lambda title, start: ("", ""))
    assert _call(url + "api/shows-pick-folder", {}, token) == (200, {"path": ""})           # Cancel
    monkeypatch.setattr(gigbar_app.folder_picker, "pick", lambda title, start: ("", "Windows' folder picker didn't open on this laptop. Paste the folder's path in the box instead."))
    code, r = _call(url + "api/shows-pick-folder", {}, token)
    assert code == 501 and "Paste the folder's path" in r["error"]
    monkeypatch.setattr(gigbar_app.folder_picker, "pick", lambda title, start: ("", "The folder picker is already open. Look for it on the taskbar."))
    assert _call(url + "api/shows-pick-folder", {}, token)[0] == 409


def test_the_shows_page_browse_paste_and_save_in_a_real_browser(window, monkeypatch):
    pw = pytest.importorskip("playwright.sync_api")
    app, url, token, tmp = window
    import gigbar_app
    src = tmp / "Wedding"
    (src / "3 - Dancing").mkdir(parents=True)
    for name in ("Dua Lipa - Levitating", "Journey - Faithfully"):
        (src / "3 - Dancing" / f"{name}.mp3").write_bytes(b"x")
    moments = tmp / "Moments"                      # a song nobody knows a moment for is listed, not played
    (moments / "4 - Moments").mkdir(parents=True)
    (moments / "4 - Moments" / "Zz Nobody - Our Own Song.mp3").write_bytes(b"x")
    asked = []
    monkeypatch.setattr(gigbar_app.folder_picker, "pick", lambda title, start: (asked.append((title, start)), (str(src), ""))[1])
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            ctx = browser.new_context()
            ctx.grant_permissions(["clipboard-read", "clipboard-write"])
            page = ctx.new_page()
            page.goto(url + "shows")
            page.wait_for_selector("#save")
            # 1.20: the page is the seven numbered steps, top to bottom, with a strip that marks the done ones
            strip = page.eval_on_selector_all("#steps a", "els => els.map(e => e.innerText.replace(/\\s+/g, ' ').trim())")
            assert strip == ["1 Load", "2 Moments", "3 Listen", "4 Mood", "5 Review", "6 Build", "7 Rehearse"]
            tops = page.eval_on_selector_all(".stepsec", "els => els.map(e => [e.id, e.getBoundingClientRect().top])")
            assert [t[0] for t in tops] == [f"step-{k}" for k in range(1, 8)] and [t[1] for t in tops] == sorted(t[1] for t in tops)
            assert page.eval_on_selector_all("#steps a.done", "els => els.length") == 0
            # step 1 opens on A folder; the Build the night panel is step 6, Play it somewhere else folds away
            assert page.get_attribute('[role=tab]:first-child', "data-tab") == "folder" and page.is_visible("#browse")
            assert page.eval_on_selector("#nightbuild", "e => e.closest('.stepsec').id") == "step-6"
            assert page.eval_on_selector("#nightmoments", "e => e.closest('.stepsec').id") == "step-2"
            assert page.eval_on_selector("#livefollow", "e => e.closest('.stepsec').id") == "step-7" and not page.is_visible("#m3u")
            assert "moving heads on people, spotlights, strobe or laser" in page.inner_text("#rules")
            page.wait_for_function("document.querySelectorAll('#moods .mood').length === 2", timeout=5000)
            # Save show is never a dead button: with no songs it is pressable and says why
            assert not page.is_disabled("#save") and page.is_visible("#savewhy")
            page.fill("#title", "Avery and Jordan")
            page.click("#save")
            page.wait_for_function("document.body.innerText.includes('There is nothing to save yet')", timeout=3000)
            # a path pasted the way Windows' Copy as path gives it lands clean, and Enter adds its songs
            page.click('[data-tab="folder"]')
            page.evaluate("t => navigator.clipboard.writeText(t)", f'"{src}"')
            page.click("#folder")
            page.keyboard.press("Control+V")
            page.wait_for_function("document.querySelector('#folder').value.length > 0", timeout=3000)
            assert page.input_value("#folder") == str(src)
            page.keyboard.press("Enter")
            page.wait_for_function("document.body.innerText.includes('Added 2 songs from the folder')", timeout=8000)
            assert not page.is_visible("#savewhy")
            # 'Added' is said before the add ends (its lights are still being designed); one add at a
            # time, so wait for it before Browse starts the next (Llano BL #12438)
            page.wait_for_function("!document.querySelector('#addfolder').disabled", timeout=20000)
            # Browse: the app's picker hands back the folder and its songs are added with no second press
            page.fill("#folder", "")
            page.click("#browse")
            page.wait_for_function("document.querySelector('#folder').value.length > 0", timeout=5000)
            assert asked and asked[0][0] == "Choose the folder your songs are in" and page.input_value("#folder") == str(src)
            page.wait_for_function("document.querySelector('#msg').innerText.includes('No new songs: all 2 were already in the show')", timeout=8000)
            # the order job and the lights jobs are told apart by name, each with a line under it
            jobs = page.eval_on_selector_all(".job", "els => els.map(e => [e.querySelector('h3').innerText, e.querySelector('button').innerText, e.querySelector('.hint').innerText.length > 40])")
            assert jobs == [["SONG ORDER", "Put the songs in a good order", True], ["LIGHTS", "Pick the lights for every song", True],
                            ["LIGHTS MADE FOR THIS NIGHT", "Have Llano design the lights", True]]
            page.wait_for_function("!document.querySelector('#design').disabled", timeout=20000)
            page.click("#design")
            page.wait_for_function("document.body.innerText.includes('Every song has its lights')", timeout=5000)
            page.click("#save")
            page.wait_for_function("document.body.innerText.includes('Saved \"Avery and Jordan\"')", timeout=5000)
            assert page.is_visible("#nightbrowse")
            # Load, Listen, Rules and Review are done; the moments are next
            done = page.eval_on_selector_all("#steps a.done", "els => els.map(e => e.dataset.step)")
            assert done == ["1", "3", "4", "5"] and page.get_attribute("#steps a.next", "data-step") == "2"
            assert page.inner_text("#listenline").startswith("Read 2 of 2 songs")
            # step 2: a Moments song no dance is known for is listed and offered in every moment's song list
            page.fill("#folder", str(moments))
            page.click("#addfolder")
            page.wait_for_function("document.querySelector('#momentsfrom').innerText.includes('Our Own Song')", timeout=8000)
            offered = page.eval_on_selector_all("#momentsongs option", "els => els.map(e => e.value)")
            assert offered[0] == "Zz Nobody - Our Own Song" and "Dua Lipa - Levitating" in offered
            assert page.get_attribute("#nm-song-first-dance", "list") == "momentsongs"
            # it is never left out (Llano BL #11473): it is in the show as a Dancing song, and Review asks for its moment
            page.wait_for_function("document.querySelectorAll('#songs select[data-part]').length === 3", timeout=8000)
            page.wait_for_function("document.querySelector('#nopart').innerText.includes('Our Own Song by Zz Nobody is in the Moments folder')", timeout=5000)
            assert "pick its moment in step 2" in page.inner_text("#nopart")
            # picked beside a moment in step 2, its line goes
            page.fill("#nm-song-first-dance", "Zz Nobody - Our Own Song")
            page.dispatch_event("#nm-song-first-dance", "change")
            page.wait_for_function("!document.querySelector('#nopart li[data-kind=unplaced]')", timeout=5000)
            page.evaluate("() => { show.songs.pop(); renderAll(); }")   # back to the two songs below
            # step 5: every row has its part; a cocktail-hour row says soft wash only, and the lights are redone
            assert page.eval_on_selector_all("#songs select[data-part]", "els => els.map(e => e.value)") == ["dancing", "dancing"]
            assert page.locator("#songs .chip.soft").count() == 0
            page.select_option('#songs select[data-part="0"]', "cocktail")
            page.wait_for_function("document.querySelectorAll('#songs .chip.soft').length === 1", timeout=5000)
            assert "cocktail hour" in page.inner_text('#songs tr[data-i="0"] td.why')
            # a new show starts clean: the last show's Moments songs never turn up in it
            page.on("dialog", lambda d: d.accept())
            page.click("#new")
            page.wait_for_function("!document.querySelector('#momentsfrom').innerText.includes('Our Own Song')", timeout=3000)
            assert page.eval_on_selector_all("#momentsongs option", "els => els.length") == 0
        finally:
            browser.close()
