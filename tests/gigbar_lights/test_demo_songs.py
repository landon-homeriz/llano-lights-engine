"""The demo's real songs: free to ship, analyzed, followed beat for beat, served to the window."""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tools.gigbar_lights import demo_songs
from tools.gigbar_lights.show import Show
from tools.gigbar_lights.show_script import SECTION_KINDS

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
import gigbar_app  # noqa: E402
from tools.gigbar_lights.venue import LayoutStore  # noqa: E402

SONGS = demo_songs.load()
FREE = {"CC0 1.0 (public domain)"}  # CC-BY would also do, with its credit shown; nothing else ships


def test_three_songs_with_different_energy_all_free_to_ship():
    assert [s.id for s in SONGS] == ["groove", "drop", "slow"]
    for s in SONGS:
        assert s.path.is_file() and s.path.stat().st_size > 1_000_000
        assert s.license in FREE and s.license_url.startswith("https://creativecommons.org/")
        assert s.source.startswith("https://opengameart.org/content/") and s.title in s.credit and s.artist in s.credit
    by = {s.id: s for s in SONGS}
    assert by["slow"].bpm < 100 < by["groove"].bpm < by["drop"].bpm


def test_each_song_went_through_find_song_sections():
    for s in SONGS:
        kinds = [x["kind"] for x in s.sections]
        assert kinds and set(kinds) <= set(SECTION_KINDS)
        beats = [(x["start_beat"], x["end_beat"]) for x in s.sections]
        assert all(a < b for a, b in beats) and all(b1 == a2 for (_, b1), (a2, _) in zip(beats, beats[1:]))
        assert s.duration_s * s.bpm / 60 >= beats[-1][1] - 8  # sections cover the song
        assert len(s.bars) >= 16 and all(0 <= v <= 1 for v in s.bars)
    drop = next(s for s in SONGS if s.id == "drop")
    kinds = [x["kind"] for x in drop.sections]
    assert kinds.index("build") < kinds.index("drop")  # the build-and-drop song really has one


def test_song_clock_follows_the_window_and_goes_stale():
    c = demo_songs.SongClock()
    assert c.position("drop", 10.0) is None
    c.report("drop", 12.0, True, now=100.0)
    assert c.position("drop", 100.5) == (12.5, True)
    assert c.position("groove", 100.5) is None          # another song's report doesn't count
    c.report("drop", 12.0, False, now=100.0)
    assert c.position("drop", 101.0) == (12.0, False)   # paused: holds
    assert c.position("drop", 100.0 + demo_songs.STALE_S + 0.1) is None


def run_feed(song, clock, seconds, start=1000.0):
    show = Show(analyze=False)
    feed = demo_songs.SongFeed(show, song, clock)
    now = start
    while now < start + seconds:
        feed(now)
        now += 512 / 44100
    return show, now


def test_lights_follow_the_reported_song_position():
    song = next(s for s in SONGS if s.id == "drop")
    clock = demo_songs.SongClock()
    at = 42.0  # into the song, where the window says it is
    clock.report("drop", at, True, now=1000.0)
    show, now = run_feed(song, clock, 1.0)
    expected = (at + 1.0 - song.first_beat_s) * song.bpm / 60
    assert abs(show.clock.beat_at(now) - expected) < 0.3
    t = show.tracks[1]
    assert t.info.title == "Neon Hyperdrive" and t.script.sections[0].kind == song.sections[0]["kind"]
    sec, _ = t.script.at(expected)
    assert sec is not None


def test_without_the_window_the_song_runs_on_its_own_clock():
    song = next(s for s in SONGS if s.id == "groove")
    show, now = run_feed(song, None, 2.0)
    expected = (2.0 - song.first_beat_s) * song.bpm / 60
    assert abs(show.clock.beat_at(now) - expected) < 0.3


# --- the window's side --------------------------------------------------------------------------

def call(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(gigbar_app.updater, "check", lambda: (None, "no update in tests"))
    opts = argparse.Namespace(seconds=0.0, bpm=128.0, no_browser=True, no_window=True,
                              updated=False, update_failed=False)
    app = gigbar_app.App(opts, gigbar_app.LogBuffer(tmp_path / "log.txt"))
    app.preview = gigbar_app.Preview("", LayoutStore(tmp_path / "layouts"), app=app)
    yield app, app.preview.url, {"X-Llano-Token": app.preview.token}
    app.stop()
    if app.runner:
        app.runner.join(timeout=8)
    app.preview.close()


def test_state_lists_the_songs_with_their_credits(server):
    app, url, _ = server
    st = json.loads(call(url + "api/app")[2])
    assert [s["id"] for s in st["songs"]] == ["groove", "drop", "slow"]
    assert all(s["credit"] and s["license"] and s["url"].startswith("/demo-songs/") for s in st["songs"])


def test_audio_is_served_with_byte_ranges_and_nothing_else(server):
    app, url, _ = server
    song = SONGS[0]
    code, h, body = call(url + "demo-songs/" + song.file)
    assert code == 200 and h["Content-Type"] == "audio/mpeg" and body == song.path.read_bytes()
    req = urllib.request.Request(url + "demo-songs/" + song.file, headers={"Range": "bytes=100-199"})
    with urllib.request.urlopen(req, timeout=5) as r:
        assert r.status == 206 and r.headers["Content-Range"].endswith(f"/{song.path.stat().st_size}")
        assert r.read() == song.path.read_bytes()[100:200]
    for bad in ("songs.json", "../demo_songs.py", "..%2Fversion.py", "nope.mp3"):
        assert call(url + "demo-songs/" + bad)[0] == 404


def test_demo_runs_the_picked_song_and_follows_the_window(server):
    app, url, tok = server
    assert call(url + "api/run", b'{"mode": "demo", "song": "nope"}', tok)[0] == 400
    assert call(url + "api/run", b'{"mode": "check", "song": "drop"}', tok)[0] == 400
    assert call(url + "api/run", b'{"mode": "demo", "song": "drop"}', tok)[0] == 200
    assert call(url + "api/demo-clock", json.dumps({"song": "drop", "t": 42.5, "playing": True}).encode(), tok)[0] == 200
    for _ in range(40):
        st = json.loads(call(url + "api/app")[2])
        if st["show"] and "Neon Hyperdrive" in st["status"]:
            break
        time.sleep(0.1)
    assert st["running"] == "demo" and st["song"] == "drop" and "Playing" in st["status"], st["status"]
    assert call(url + "api/demo-clock", b'{"song": "drop", "t": "x"}', tok)[0] == 400
    call(url + "api/stop", b"", tok)
    app.runner.join(timeout=8)
    assert json.loads(call(url + "api/app")[2])["song"] == ""


def test_the_window_has_the_picker_and_reports_the_position():
    page = (Path(gigbar_app.__file__).parent / "app.html").read_text()
    for needed in ('id="song"', "/api/demo-clock", "audio.currentTime", "Pretend song (no music)", "s.credit", "s.license"):
        assert needed in page
