"""The cue workspace (Llano PM #23869). His words 2026-11-17: the Cue timeline tab was "pointless, too small,
not editable, I can't see it on the screen. This really needs its own dedicated workspace to adjust cues."

What is checked here:
  - the new markers as stored (settings_contract.cue): blackout, strobe burst, repeat in a new color, a note;
  - the live show plays them (Show.frame/render through cues.place/dress): dark is dark, a strobe burst flashes on
    the beat, a repeat plays the earlier stretch's beats in its color;
  - the workspace's picture of the show (cue_workspace.lanes) says the same thing at the same moments, on his
    worked example (Justin Bieber's Sorry: flashes at 0:48, dark at 0:58.5, the build again in a new color, the
    drop at 1:08) laid on a demo song;
  - the window and the phone serve the page, the song and its file, and an edit reaches the lanes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tools.gigbar_lights import cues as cues_mod
from tools.gigbar_lights import demo_songs, show_settings
from tools.gigbar_lights import settings_contract as contract
from tools.gigbar_lights.beat_clock import TrackGrid
from tools.gigbar_lights.song_match import candidates

SONG = next(s for s in demo_songs.load() if s.id == "drop")
KEY = candidates(SONG.artist, SONG.title)[0]


@pytest.fixture(autouse=True)
def _settings():
    before = show_settings.current()
    yield
    show_settings.set_current(before)


def _set_cues(cs):
    show_settings.set_current({**contract.normalize({}), "cues": {KEY: cs}})


# --- what is stored -------------------------------------------------------------------------------------------

def test_the_new_markers_are_cleaned_and_kept():
    got = contract.song_cues([
        {"at": 58.5, "do": "blackout", "len": 0.6},
        {"at": 48.0, "do": "strobe", "len": 999},                       # clamped to CUE_MAX_LEN
        {"at": 59.1, "do": "repeat", "len": 8.9, "from": 49.5, "color": "#2040FF"},
        {"at": 52.0, "do": "note", "text": "  make the   build pulse  ", "len": 2},
        {"at": 10.0, "do": "repeat", "len": 4, "from": 12.0},             # plays from later than itself: dropped
        {"at": 11.0, "do": "note", "text": "   "},                        # a note with no words: dropped
        {"at": 12.0, "do": "strobe", "len": True},                        # a bad length: one second
        {"at": 1.0, "do": "explode"},
    ])
    assert got == [
        {"at": 12.0, "do": "strobe", "len": 1.0},
        {"at": 48.0, "do": "strobe", "len": contract.CUE_MAX_LEN},
        {"at": 52.0, "do": "note", "len": 2.0, "text": "make the build pulse"},
        {"at": 58.5, "do": "blackout", "len": 0.6},
        {"at": 59.1, "do": "repeat", "len": 8.9, "from": 49.5, "color": "#2040ff"},
    ]
    assert contract.song_cues(got) == got   # normalizing twice changes nothing


def test_a_long_note_is_cut_and_the_old_cues_still_read():
    note = contract.cue({"at": 3, "do": "note", "text": "x" * 500})
    assert len(note["text"]) == contract.CUE_NOTE_CHARS
    # every cue a 1.36/1.37 laptop saved reads the same (the five white hits on Livin' on a Prayer)
    old = [{"at": 40.0 + i, "do": "hit", "size": 1} for i in range(5)] + [{"at": 30.0, "do": "section", "kind": "drop"}]
    assert contract.song_cues(old) == sorted(old, key=lambda c: c["at"])


# --- the live show plays them ----------------------------------------------------------------------------------

def _play_at(at, seconds=0.25):
    from tools.gigbar_lights.show import Show
    clock = demo_songs.SongClock()
    clock.report(SONG.id, at, True, now=1000.0)
    show = Show(analyze=False, latency_ms=0.0)
    feed = demo_songs.SongFeed(show, SONG, clock)
    now = 1000.0
    while now < 1000.0 + seconds:
        feed(now)
        now += 512 / 44100
    show.render(now)
    return show, show.rig, show.last_frame


def _lit(rig) -> float:
    return sum(fx.dim for fx in (*rig.tetras, *rig.sticks, *(p for b in rig.bars for p in b.pars), *(m for b in rig.bars for m in b.movers)))


def test_a_blackout_is_dark_for_its_length_and_only_then():
    _set_cues([{"at": 60.0, "do": "blackout", "len": 1.0}])
    _s, rig, f = _play_at(60.1)
    assert 60.0 <= f.secs < 61.0 and _lit(rig) == 0.0 and all(b.laser == "off" for b in rig.bars)
    _s, rig, f = _play_at(61.3)
    assert f.secs > 61.0 and _lit(rig) > 0.5


def test_a_strobe_burst_flashes_on_the_beat():
    _set_cues([{"at": 30.0, "do": "strobe", "len": 8.0}])
    on = off = 0
    for k in range(12):
        _s, rig, f = _play_at(30.0 + k * 0.137)
        flash = (f.beat % 1.0) < cues_mod.STROBE_FLASH
        white = max(b.strobe_white for b in rig.bars)
        assert white == (1.0 if flash else 0.0), (f.beat, white)
        on, off = on + flash, off + (not flash)
    assert on and off   # it really flashes, not a steady white


def test_a_repeat_plays_the_earlier_stretch_in_its_color():
    grid = SONG.grid()
    rep = {"at": 60.0, "do": "repeat", "len": 8.0, "from": 50.0, "color": "#2040ff"}
    _set_cues([rep])
    _s, _rig, f = _play_at(62.0)
    shift = cues_mod.repeat_shift(rep, grid, None)
    assert shift % 4 == 0 and shift > 0
    real = grid.beat_at_seconds(f.secs)
    assert f.beat == pytest.approx(real - shift, abs=0.01)   # the look plays the beats of 0:50 on
    assert f.feel[1] == "#2040ff"
    _s, _rig, f = _play_at(70.0)
    assert f.feel[1] == "" and f.beat == pytest.approx(grid.beat_at_seconds(f.secs), abs=0.01)


def test_a_note_changes_no_light():
    _s, plain, _f = _play_at(40.0)
    _set_cues([{"at": 39.0, "do": "note", "text": "flash red on the snare", "len": 4}])
    _s, noted, _f = _play_at(40.0)
    assert bytes(plain.render()) == bytes(noted.render())


# --- the workspace's picture of the show ------------------------------------------------------------------------

def _lane(lanes, name, t):
    for a, b, color, level in lanes[name]:
        if a <= t < b:
            return color, level
    return "#000000", 0.0


SORRY_MARKS = [   # his worked example, as he placed it in the workspace on Sorry (100 BPM), laid on this song
    {"at": 47.99, "do": "strobe", "len": 1.2},
    {"at": 48.58, "do": "section", "kind": "build"},
    {"at": 52.0, "do": "note", "len": 2.4, "text": "make the build pulse brighter every bar"},
    {"at": 58.5, "do": "blackout", "len": 0.6},
    {"at": 59.1, "do": "repeat", "len": 8.9, "from": 50.2, "color": "#2040ff"},
    {"at": 68.0, "do": "section", "kind": "drop"},
]


def test_the_lanes_show_his_worked_example():
    pytest.importorskip("numpy")
    pytest.importorskip("soundfile")
    from tools.gigbar_lights import cue_workspace as cw
    song = cw.analyze(SONG.path, SONG.grid())
    cues = tuple(contract.song_cues(SORRY_MARKS))
    lanes = cw.lanes(song, cues, (KEY,))
    assert set(lanes) == set(cw.LANES)
    # 0:48 to 0:49: the strobes flash with the beat, white
    flashes = [_lane(lanes, "strobe", 47.99 + i * 0.05) for i in range(24)]
    assert ("#ffffff", 1.0) in flashes and any(lv == 0.0 for _c, lv in flashes)
    # 0:58.5: everything dark
    for lane in cw.LANES:
        assert _lane(lanes, lane, 58.7)[1] == 0.0, lane
    # the build again, in his blue
    assert _lane(lanes, "wash", 63.0)[0] == "#2040ff"
    # 1:08: his drop is the drop the lights play (on the beat nearest it)
    secs = cw.sections(song, cues)
    drop = next(s for s in secs if s["kind"] == "drop")
    assert abs(drop["start"] - 68.0) <= 60.0 / song.bpm / 2 + 0.01
    assert not any(s["kind"] == "drop" and s["start"] < 60.0 for s in secs)   # no early drop left over


def test_the_estimated_grid_lands_on_the_beat_all_song_long():
    """A song not in Mixxx gets a grid from its sound. The demo songs' own tempos were estimated too (more
    coarsely), so the check is the sound itself: its beats land on as much onset as the demo's grid's do, and
    far more than the same grid half a beat over (a tempo a hair off would drift onto the off-beats)."""
    np = pytest.importorskip("numpy")
    pytest.importorskip("soundfile")
    from tools.gigbar_lights import cue_workspace as cw
    from tools.gigbar_lights.show_script import load_mono
    for s in demo_songs.load():
        x, rate = load_mono(s.path)
        g = cw.estimate_grid(x, rate)
        assert g.bpm == pytest.approx(s.bpm, rel=0.01), s.id
        env = cw.onset_envelope(x, rate)
        theirs = TrackGrid(samplerate=rate, first_beat=s.first_beat_s * rate, bpm=s.bpm)
        ours = cw.grid_fit(env, rate, g)
        assert ours >= 0.97 * cw.grid_fit(env, rate, theirs), s.id
        half = TrackGrid(samplerate=rate, first_beat=g.first_beat + rate * 30.0 / g.bpm, bpm=g.bpm)
        assert ours > 1.15 * cw.grid_fit(env, rate, half), s.id   # on the beat, not between them
    assert np is not None


def test_his_markers_override_the_detected_drop_when_he_sets_one():
    pytest.importorskip("numpy")
    pytest.importorskip("soundfile")
    from tools.gigbar_lights import cue_workspace as cw
    song = cw.analyze(SONG.path, SONG.grid())
    auto_drops = [s["start"] for s in cw.sections(song, ()) if s["kind"] == "drop"]
    assert auto_drops
    mine = tuple(contract.song_cues([{"at": 5.0, "do": "section", "kind": "intro"}, {"at": 100.0, "do": "section", "kind": "drop"}]))
    assert [s["start"] for s in cw.sections(song, mine) if s["kind"] == "drop"] == [pytest.approx(100.0, abs=0.3)]


# --- the window and the phone ---------------------------------------------------------------------------------

from tests.gigbar_lights.test_shows import _call, lib, window  # noqa: E402,F401


def test_the_window_opens_a_song_and_an_edit_reaches_the_lanes(window):  # noqa: F811
    pytest.importorskip("numpy")
    pytest.importorskip("soundfile")
    app, url, token, _tmp = window
    code, page = _call(url + "cues", token=token)
    assert code == 200 and b"Cue workspace" in page and token.encode() in page
    code, got = _call(url + "api/cues-song", {"artist": "Dua Lipa", "title": "Levitating"}, token)
    assert code == 200, got
    assert got["key"] == "dua-lipa-levitating" and got["grid"] == "mixxx" and got["length"] > 60
    assert got["peaks"] and got["beats"] and set(got["lanes"]) == {"wash", "strobe", "heads", "sticks", "laser", "derby"}
    marks = [{"at": 20.0, "do": "blackout", "len": 2.0}, {"at": 30.0, "do": "note", "text": "brighter here", "len": 2.0}]
    code, out = _call(url + "api/settings", {"ops": [{"path": "cues.dua-lipa-levitating", "value": marks}]}, token)
    assert code == 200, out
    code, lanes = _call(url + "api/cues-lanes", {"key": "dua-lipa-levitating"}, token)
    assert code == 200 and [c["do"] for c in lanes["cues"]] == ["blackout", "note"]
    assert all(_lane(lanes["lanes"], ln, 21.0)[1] == 0.0 for ln in lanes["lanes"])
    # the song's own file, with byte ranges for seeking; nothing by path
    import urllib.request
    req = urllib.request.Request(url + "cue-audio/dua-lipa-levitating", headers={"Range": "bytes=0-99"})
    with urllib.request.urlopen(req, timeout=10) as r:
        assert r.status == 206 and len(r.read()) == 100
    assert _call(url + "cue-audio/..%2F..%2Fsettings.json", token=token)[0] == 404
    code, songs = _call(url + "api/cues-songs", {}, token)
    assert code == 200 and isinstance(songs["songs"], list)


def test_a_song_with_no_file_says_why(window):  # noqa: F811
    _app, url, token, _tmp = window
    code, got = _call(url + "api/cues-song", {"artist": "Nobody", "title": "Not Here"}, token)
    assert code == 404 and "isn't in Mixxx's library" in got["error"]
    assert _call(url + "api/cues-song", {"artist": "Dua Lipa", "title": "Levitating"}, "wrong")[0] == 403


def test_the_phone_gets_the_page_and_needs_the_key(tmp_path):
    import urllib.error
    import urllib.request

    from tools.gigbar_lights import local_mode
    song = tmp_path / "song.mp3"
    song.write_bytes(b"0123456789" * 50)
    calls = []
    srv = local_mode.LocalServer(local_mode.LocalKey(tmp_path), lambda: {}, lambda k: False,
                                 cues=lambda action, msg: (calls.append((action, msg)) or (200, {"ok": True, "action": action})),
                                 cue_audio=lambda key: song if key == "a-song" else None)
    if not srv.start():
        pytest.skip("no free local-mode port")
    try:
        base, key = f"http://127.0.0.1:{srv.port}", srv.key.get()
        with urllib.request.urlopen(base + "/cues", timeout=5) as r:
            html = r.read().decode()
        assert "Cue workspace" in html and "__LLANO_TITLE__" not in html

        def post(path, body, k):
            req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                         headers={"X-Llano-Key": k, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, {}
        assert post("/api/cues-song", {"title": "x"}, key) == (200, {"ok": True, "action": "song"})
        assert post("/api/cues-lanes", {}, "nope")[0] == 403 and calls == [("song", {"title": "x"})]
        req = urllib.request.Request(base + "/cue-audio/a-song?k=" + key, headers={"Range": "bytes=10-19"})
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 206 and r.read() == b"0123456789"
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/cue-audio/a-song?k=wrong", timeout=5)
    finally:
        srv.stop()


@pytest.mark.skipif(not os.environ.get("LLANO_LIGHTS_SORRY"), reason="his Sorry file (LLANO_LIGHTS_SORRY=path) is not here")
def test_sorry_auto_detection_lands_the_drop_at_1_08():
    from tools.gigbar_lights import cue_workspace as cw
    song = cw.analyze(Path(os.environ["LLANO_LIGHTS_SORRY"]))
    drops = [s["start"] for s in cw.sections(song, ()) if s["kind"] == "drop"]
    assert drops and abs(drops[0] - 68.0) < 0.6
