"""Load Mixxx (BL #12343): a built night into Mixxx 2.5's own library, with a backup first.

The library here is built the way Mixxx 2.5.4 builds it: every revision of its res/schema.xml
(mixxx_2_5_4_schema.xml, copied from the 2.5.4 tag) run in order, split on ";" like Mixxx's
SchemaManager, then the settings rows it writes and the Auto DJ and history playlists it makes on
first start. The real Mixxx 2.5.4 proof (its own startup reading the loaded library, Auto DJ
playing from it) is in the PR.
"""
import json
import sqlite3
import wave
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tools.gigbar_lights import mixxx_load
from tools.gigbar_lights.wedding_night import read_cfg

SCHEMA = Path(__file__).with_name("mixxx_2_5_4_schema.xml")


def mixxx_library(path: Path, *, version: int = 39, autodj: bool = True) -> Path:
    conn = sqlite3.connect(path)
    for rev in ET.parse(SCHEMA).getroot().findall("revision"):
        if int(rev.get("version")) > version:
            break
        sql = "".join(rev.find("sql").itertext())
        for stmt in sql.split(";"):
            if stmt.strip():
                conn.execute(stmt)
    conn.executemany("INSERT INTO settings (name, value) VALUES (?, ?)",
                     [("mixxx.schema.version", str(version)), ("mixxx.schema.min_compatible_version", "3"),
                      ("mixxx.schema.last_used_version", str(version))])
    if autodj:   # what Mixxx makes on its first start: the Auto DJ queue, a history playlist
        conn.execute("INSERT INTO Playlists (name, position, hidden, date_created, date_modified) "
                     "VALUES ('Auto DJ', 1, 1, datetime('now'), datetime('now'))")
        conn.execute("INSERT INTO Playlists (name, position, hidden, date_created, date_modified) "
                     "VALUES ('2026-11-14', 2, 2, datetime('now'), datetime('now'))")
    conn.commit()
    conn.close()
    return path


def tone(path: Path, secs: float = 0.5) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 2 * int(8000 * secs))
    return path


PLAYLISTS = {"1 - Cocktail hour": ["Songs/1 - Cocktail hour/A - Sip.wav", "Songs/1 - Cocktail hour/B - Mingle.wav"],
             "2 - Grand entrance, First dance": ["Holds/HOLD - Grand entrance.wav", "Songs/Moments/Randy Travis - Forever.wav",
                                                 "Songs/1 - Cocktail hour/A - Sip.wav"],
             "3 - Dancing": ["Songs/3 - Dancing/D - Jump.wav", "Songs/3 - Dancing/E - Spin.wav"]}


def built_night(root: Path, playlists=PLAYLISTS) -> Path:
    """A night folder as wedding_night.build leaves it: the files, the numbered .m3u8 playlists (relative
    paths, #EXTINF lines, a MISSING comment) and night.json naming them in order."""
    night = root / "Music" / "Llano Lights shows" / "proof-night"
    rows = []
    for name, files in playlists.items():
        lines = ["#EXTM3U", f"#PLAYLIST:{name}"]
        for rel in files:
            tone(night / rel)
            lines += [f"#EXTINF:1,{Path(rel).stem}", rel]
        lines.append("# MISSING: Nobody - Not Here")
        (night / f"{name}.m3u8").write_text("\n".join(lines) + "\n", encoding="utf-8")
        rows.append({"file": f"{name}.m3u8", "name": name.split(" - ", 1)[1], "rows": len(files)})
    (night / "night.json").write_text(json.dumps({"playlists": rows}), encoding="utf-8")
    return night


@pytest.fixture
def mixxx(tmp_path):
    settings = tmp_path / "Mixxx"
    settings.mkdir()
    db = mixxx_library(settings / "mixxxdb.sqlite")
    cfg = settings / "mixxx.cfg"
    cfg.write_text("[Config]\nLocale en\n\n[Auto DJ]\nTransition 10\nTransitionMode 0\nRequeue 0\n\n[Master]\nnum_decks 2\n",
                   encoding="utf-8")
    return db, cfg


def dump(db: Path) -> list:
    conn = sqlite3.connect(db)
    try:
        return list(conn.iterdump())
    finally:
        conn.close()


def run(night, db, cfg, **kw):
    kw.setdefault("running", lambda: False)
    kw.setdefault("opener", lambda: True)
    return mixxx_load.load(night, db_path=db, cfg_path=cfg, **kw)


def playlist(conn, name):
    return [r[0] for r in conn.execute(
        "SELECT tl.location FROM PlaylistTracks pt JOIN Playlists p ON p.id = pt.playlist_id "
        "JOIN library l ON l.id = pt.track_id JOIN track_locations tl ON tl.id = l.location "
        "WHERE p.name = ? ORDER BY pt.position", (name,))]


def test_the_fixture_is_mixxx_2_5s_library(mixxx):
    db, _ = mixxx
    conn = sqlite3.connect(db)
    assert mixxx_load.schema_version(conn) == "39"
    cols = {r[1] for r in conn.execute("PRAGMA table_info(library)")}
    assert {"source_synchronized_ms", "beats", "header_parsed", "mixxx_deleted"} <= cols   # late revisions applied
    assert {r[1] for r in conn.execute("PRAGMA table_info(PlaylistTracks)")} >= {"pl_datetime_added", "position"}


def test_load_puts_the_night_into_mixxx_and_opens_it(tmp_path, mixxx):
    db, cfg = mixxx
    night = built_night(tmp_path)
    before = dump(db)
    opened = []
    r = run(night, db, cfg, opener=lambda: opened.append(1) or True)

    assert r["ok"] and r["opened"] and opened == [1] and r["mixxx"] == "Mixxx 2.5"
    assert dump(Path(r["backup"])) == before and dump(db) != before         # the copy is the library as it was
    assert (db.parent / "Llano Lights backups").is_dir()
    assert len(list((db.parent / "Llano Lights backups").glob("mixxx *.cfg"))) == 1
    assert r["added"] == 6 and r["known"] == 0                               # A - Sip is in two playlists: one row
    assert [p["name"] for p in r["playlists"]] == list(PLAYLISTS)
    assert r["autodj"] == 2 and r["queue_had"] == 0

    conn = sqlite3.connect(db)
    for name, files in PLAYLISTS.items():
        assert playlist(conn, name) == [(night / f).resolve().as_posix() for f in files]
    assert conn.execute("SELECT hidden FROM Playlists WHERE name = '1 - Cocktail hour'").fetchone() == (0,)
    # the Auto DJ queue is playlist 1, positions from 1, as Mixxx's PlaylistDAO numbers them
    q = conn.execute("SELECT pt.position, tl.filename FROM PlaylistTracks pt JOIN Playlists p ON p.id = pt.playlist_id "
                     "JOIN library l ON l.id = pt.track_id JOIN track_locations tl ON tl.id = l.location "
                     "WHERE p.hidden = 1 ORDER BY pt.position").fetchall()
    assert q == [(1, "A - Sip.wav"), (2, "B - Mingle.wav")]
    row = conn.execute("SELECT l.artist, l.title, l.duration, l.samplerate, l.channels, l.filetype, l.mixxx_deleted, "
                       "tl.directory, tl.filesize, tl.fs_deleted FROM library l JOIN track_locations tl ON tl.id = l.location "
                       "WHERE tl.filename = 'A - Sip.wav'").fetchone()
    a = night / "Songs/1 - Cocktail hour/A - Sip.wav"
    assert row[:2] == ("A", "Sip") and row[5:7] == ("wav", 0)
    assert row[7] == a.resolve().parent.as_posix() and row[8] == a.stat().st_size and row[9] == 0
    assert conn.execute("SELECT COUNT(*) FROM Playlists WHERE hidden = 1").fetchone() == (1,)   # Mixxx's own queue, reused
    assert schema_untouched(conn)

    adj = read_cfg(cfg)
    assert adj["[Auto DJ]"] == {"Transition": "2", "TransitionMode": "2", "Requeue": "0"}
    assert adj["[Config]"] == {"Locale": "en"} and adj["[Master]"] == {"num_decks": "2"}


def schema_untouched(conn) -> bool:
    return mixxx_load.schema_version(conn) == "39"


def test_loading_again_replaces_only_its_own_playlists(tmp_path, mixxx):
    db, cfg = mixxx
    conn = sqlite3.connect(db)
    # his own song, cue points and playlist, and his own queue
    conn.execute("INSERT INTO track_locations (location, filename, directory, filesize, fs_deleted, needs_verification) "
                 "VALUES ('C:/Music/His - Song.mp3', 'His - Song.mp3', 'C:/Music', 1, 0, 0)")
    conn.execute("INSERT INTO library (artist, title, location, mixxx_deleted, bpm) VALUES ('His', 'Song', 1, 0, 98.5)")
    conn.execute("INSERT INTO cues (track_id, type, position, hotcue) VALUES (1, 1, 4410, 0)")
    conn.execute("INSERT INTO Playlists (name, position, hidden) VALUES ('His set', 3, 0)")
    conn.execute("INSERT INTO PlaylistTracks (playlist_id, track_id, position) VALUES (3, 1, 1)")
    conn.execute("INSERT INTO PlaylistTracks (playlist_id, track_id, position) VALUES (1, 1, 1)")   # queued in Auto DJ
    conn.commit()
    night = built_night(tmp_path)
    first = run(night, db, cfg)
    assert first["queue_had"] == 1
    ids = dict(conn.execute("SELECT name, id FROM Playlists WHERE hidden = 0").fetchall())

    # the night is built again with a different playlist 3
    (night / "3 - Dancing.m3u8").write_text("#EXTM3U\nSongs/3 - Dancing/E - Spin.wav\n", encoding="utf-8")
    again = run(night, db, cfg)
    assert again["added"] == 0 and again["known"] == 5                      # no second row for any file (Jump left 3)
    assert [p["replaced"] for p in again["playlists"]] == [True, True, True]
    assert dict(conn.execute("SELECT name, id FROM Playlists WHERE hidden = 0").fetchall()) == ids   # same playlists
    assert playlist(conn, "3 - Dancing") == [(night / "Songs/3 - Dancing/E - Spin.wav").resolve().as_posix()]
    assert conn.execute("SELECT COUNT(*) FROM library").fetchone() == (7,)
    # his song, its cue point and his playlist are as they were
    assert conn.execute("SELECT artist, title, bpm, mixxx_deleted FROM library WHERE id = 1").fetchone() == ("His", "Song", 98.5, 0)
    assert conn.execute("SELECT position, hotcue FROM cues WHERE track_id = 1").fetchall() == [(4410, 0)]
    assert playlist(conn, "His set") == ["C:/Music/His - Song.mp3"]
    assert len(list((db.parent / "Llano Lights backups").glob("mixxxdb *.sqlite"))) >= 1


def test_a_song_mixxx_already_knows_keeps_its_row(tmp_path, mixxx):
    db, cfg = mixxx
    night = built_night(tmp_path)
    sip = (night / "Songs/1 - Cocktail hour/A - Sip.wav").resolve()
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO track_locations (location, filename, directory, filesize, fs_deleted, needs_verification) "
                 "VALUES (?, 'A - Sip.wav', ?, 1, 1, 0)", (sip.as_posix(), sip.parent.as_posix()))
    conn.execute("INSERT INTO library (artist, title, location, mixxx_deleted, bpm, beats_version) "
                 "VALUES ('A', 'Sip (his tags)', 1, 1, 121.0, 'BeatGrid-2.0')")
    conn.commit()
    r = run(night, db, cfg)
    assert r["added"] == 5 and r["known"] == 1
    assert conn.execute("SELECT title, bpm, beats_version, mixxx_deleted FROM library WHERE id = 1").fetchone() == \
        ("Sip (his tags)", 121.0, "BeatGrid-2.0", 0)
    assert conn.execute("SELECT fs_deleted FROM track_locations WHERE id = 1").fetchone() == (0,)


def unchanged(db, cfg, before_db, before_cfg):
    return db.read_bytes() == before_db and cfg.read_bytes() == before_cfg and not (db.parent / "Llano Lights backups").exists()


def test_refused_while_mixxx_runs(tmp_path, mixxx):
    db, cfg = mixxx
    night = built_night(tmp_path)
    b, c = db.read_bytes(), cfg.read_bytes()
    with pytest.raises(mixxx_load.LoadRefused, match="Close Mixxx"):
        run(night, db, cfg, running=lambda: True)
    assert unchanged(db, cfg, b, c)


def test_refused_when_it_cannot_tell_whether_mixxx_runs(tmp_path, mixxx):
    db, cfg = mixxx
    night = built_night(tmp_path)
    b, c = db.read_bytes(), cfg.read_bytes()
    with pytest.raises(mixxx_load.LoadRefused, match="could not tell whether Mixxx is open"):
        run(night, db, cfg, running=lambda: None)
    assert unchanged(db, cfg, b, c)


@pytest.mark.parametrize("version", [38, 40])
def test_refused_on_a_library_version_it_does_not_know(tmp_path, version):
    settings = tmp_path / "Mixxx"
    settings.mkdir()
    db = mixxx_library(settings / "mixxxdb.sqlite", version=min(version, 39))
    if version > 39:   # a future Mixxx: same tables, a newer revision number
        conn = sqlite3.connect(db)
        conn.execute("UPDATE settings SET value = ? WHERE name = 'mixxx.schema.version'", (str(version),))
        conn.commit()
        conn.close()
    cfg = settings / "mixxx.cfg"
    cfg.write_text("[Auto DJ]\nTransitionMode 0\n", encoding="utf-8")
    night = built_night(tmp_path)
    b, c = db.read_bytes(), cfg.read_bytes()
    with pytest.raises(mixxx_load.LoadRefused, match=f"schema {version}.*Nothing was changed"):
        run(night, db, cfg)
    assert unchanged(db, cfg, b, c)


def test_refused_when_he_has_a_playlist_of_that_name(tmp_path, mixxx):
    db, cfg = mixxx
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO Playlists (name, position, hidden) VALUES ('3 - Dancing', 3, 0)")
    conn.commit()
    conn.close()
    night = built_night(tmp_path)
    b, c = db.read_bytes(), cfg.read_bytes()
    with pytest.raises(mixxx_load.LoadRefused, match='"3 - Dancing".*didn\'t make'):
        run(night, db, cfg)
    assert unchanged(db, cfg, b, c)


def test_refused_with_no_mixxx_or_no_built_night(tmp_path, mixxx):
    db, cfg = mixxx
    with pytest.raises(mixxx_load.LoadRefused, match="Build the night first"):
        run(tmp_path / "nothing", db, cfg)
    night = built_night(tmp_path)
    with pytest.raises(mixxx_load.LoadRefused, match="Open Mixxx once"):
        run(night, tmp_path / "none.sqlite", cfg)
    (night / "Songs/3 - Dancing/E - Spin.wav").unlink()
    b, c = db.read_bytes(), cfg.read_bytes()
    with pytest.raises(mixxx_load.LoadRefused, match="missing, like E - Spin.wav"):
        run(night, db, cfg)
    assert unchanged(db, cfg, b, c)


def test_a_failure_mid_write_leaves_the_library_as_it_was(tmp_path, mixxx, monkeypatch):
    db, cfg = mixxx
    night = built_night(tmp_path)
    conn = sqlite3.connect(db)
    snapshot = lambda: [conn.execute(f"SELECT * FROM {t}").fetchall() for t in ("library", "track_locations", "Playlists", "PlaylistTracks")]  # noqa: E731
    was = snapshot()
    real = mixxx_load._fill
    calls = []

    def boom(*a):
        calls.append(1)
        if len(calls) == 3:
            raise sqlite3.OperationalError("disk I/O error")
        return real(*a)

    monkeypatch.setattr(mixxx_load, "_fill", boom)
    with pytest.raises(sqlite3.OperationalError):
        run(night, db, cfg)
    assert snapshot() == was
    assert read_cfg(cfg)["[Auto DJ]"]["TransitionMode"] == "0"            # settings untouched too


def test_auto_dj_settings_are_added_when_mixxx_never_wrote_them(tmp_path):
    cfg = tmp_path / "mixxx.cfg"
    cfg.write_text("[Config]\nLocale en\n", encoding="utf-8")
    mixxx_load.set_autodj(cfg, {"TransitionMode": "2", "Transition": "2"})
    assert read_cfg(cfg) == {"[Config]": {"Locale": "en"}, "[Auto DJ]": {"TransitionMode": "2", "Transition": "2"}}
    cfg.write_text("[Auto DJ]\nRequeue 0\n\n[Master]\nnum_decks 4\n", encoding="utf-8")
    mixxx_load.set_autodj(cfg, {"TransitionMode": "2", "Transition": "2"})
    assert cfg.read_text().startswith("[Auto DJ]\nRequeue 0\nTransitionMode 2\nTransition 2\n\n[Master]")


def test_a_library_mixxx_never_gave_an_auto_dj_queue_gets_one(tmp_path):
    settings = tmp_path / "Mixxx"
    settings.mkdir()
    db = mixxx_library(settings / "mixxxdb.sqlite", autodj=False)
    cfg = settings / "mixxx.cfg"
    cfg.write_text("[Auto DJ]\n", encoding="utf-8")
    run(built_night(tmp_path), db, cfg)
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT name FROM Playlists WHERE hidden = 1").fetchall() == [("Auto DJ",)]
    assert len(playlist(conn, "Auto DJ")) == 2


# --- the Shows page --------------------------------------------------------------------------------------

from tests.gigbar_lights.test_shows import _call, lib, window  # noqa: E402,F401


def test_the_shows_page_has_load_mixxx_and_keeps_the_hand_steps(window, tmp_path, monkeypatch):  # noqa: F811
    app, url, token, tmp = window
    home = tmp_path / "home"
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    code, page = _call(url + "shows")
    assert code == 200 and b'id="nightload"' in page and b">Load Mixxx</button>" in page
    assert b"Import Playlist: import each numbered playlist" in page          # the hand import stays
    code, r = _call(url + "api/shows-night-load-mixxx", {}, token)
    assert code == 404 and "Build the night first" in r["error"]

    night = built_night(home)
    (night / "Run of show.html").write_text("<html></html>", encoding="utf-8")   # a night built earlier
    monkeypatch.setattr(mixxx_load, "mixxx_running", lambda: False)
    monkeypatch.setattr(mixxx_load, "open_mixxx", lambda: False)
    code, r = _call(url + "api/shows-night-load-mixxx", {}, token)
    assert code == 409 and "Open Mixxx once" in r["error"]                  # no Mixxx on this laptop yet

    settings = Path(mixxx_load.mixxx_db.default_db_path()).parent
    settings.mkdir(parents=True)
    mixxx_library(settings / "mixxxdb.sqlite")
    (settings / "mixxx.cfg").write_text("[Auto DJ]\nTransitionMode 0\n", encoding="utf-8")
    code, r = _call(url + "api/shows-night-load-mixxx", {}, token)
    assert code == 200 and r["ok"] and r["added"] == 6 and r["autodj"] == 2 and r["opened"] is False
    monkeypatch.setattr(mixxx_load, "mixxx_running", lambda: True)
    code, r = _call(url + "api/shows-night-load-mixxx", {}, token)
    assert code == 409 and "Close Mixxx" in r["error"]
