"""Spotify and YouTube Music (1.5.0): the lights follow what the laptop plays, read the song name
Windows shows, match it to a saved style however it is spelled, and step aside for Mixxx."""
import importlib.util
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]  # the repo root
sys.path.insert(0, str(ROOT))

from tools.gigbar_lights import settings_contract as C  # noqa: E402
from tools.gigbar_lights import show_settings  # noqa: E402
from tools.gigbar_lights.beat_tracker import BeatTracker  # noqa: E402
from tools.gigbar_lights.media_session import MediaSessions, NowPlaying, app_name, choose  # noqa: E402
from tools.gigbar_lights.mixxx_db import MixxxLibrary  # noqa: E402
from tools.gigbar_lights.mixxx_link import SYSTEM_DECK, encode_tick, encode_track  # noqa: E402
from tools.gigbar_lights.show import Show  # noqa: E402
from tools.gigbar_lights.song_match import candidates, norm, pick  # noqa: E402
from tools.gigbar_lights.system_audio import LoopbackCapture, MixxxWatch, SystemFeed  # noqa: E402

SR = 44100


def drums(bpm, seconds, seed=0):
    """A band at an exact tempo: kick on every beat, snare on 2 and 4, hats on eighths, a bass
    line off the beat (the pattern that reads as half tempo without the half-lag score)."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    x = np.zeros(n, np.float32)
    bp = 60 / bpm

    def hit(t, sig):
        i = int(t * SR)
        if i < n:
            x[i:i + len(sig)] += sig[:n - i]

    tk = np.arange(int(0.25 * SR)) / SR
    kick = (np.sin(2 * np.pi * (50 + 80 * np.exp(-tk * 30)) * tk) * np.exp(-tk * 12)).astype(np.float32)
    snare = (rng.standard_normal(int(.15 * SR)) * np.exp(-np.arange(int(.15 * SR)) / SR * 25) * .5).astype(np.float32)
    hat = (rng.standard_normal(int(.04 * SR)) * np.exp(-np.arange(int(.04 * SR)) / SR * 120) * .2).astype(np.float32)
    tb = np.arange(int(.2 * SR)) / SR
    bass = (np.sin(2 * np.pi * 55 * tb) * np.exp(-tb * 8) * .6).astype(np.float32)
    k = 0
    while k * bp < seconds:
        t = k * bp
        hit(t, kick)
        if k % 2:
            hit(t, snare)
        hit(t, hat)
        hit(t + bp / 2, hat)
        if k % 2 == 0:
            hit(t + bp * .75, bass)
            hit(t + bp * 1.5, bass)
        k += 1
    return x * 0.5 + 0.05 * np.sin(2 * np.pi * 220 * np.arange(n) / SR).astype(np.float32)


# --- forgiving song matching ------------------------------------------------------------------

SAVED = {C.track_key("Bob Carlisle - Butterfly Kisses"): "father-daughter",
         C.track_key("Beyonce - Halo"): "first-dance",
         C.track_key("Simon & Garfunkel - The Boxer"): "calm",
         C.track_key("My Girl"): "mother-son"}


@pytest.mark.parametrize("artist,title,want", [
    ("Bob Carlisle", "Butterfly Kisses", "father-daughter"),                      # as saved
    ("BOB CARLISLE", "butterfly kisses!", "father-daughter"),                     # case, punctuation
    ("Bob Carlisle", "Butterfly Kisses - Remastered 2011", "father-daughter"),    # Spotify remaster suffix
    ("Bob Carlisle", "Butterfly Kisses (2011 Remaster)", "father-daughter"),
    ("Bob Carlisle", "Butterfly Kisses - Radio Edit", "father-daughter"),
    ("Bob Carlisle, Someone Else", "Butterfly Kisses", "father-daughter"),        # Spotify artist list
    ("Bob Carlisle", "Butterfly Kisses (feat. A Friend)", "father-daughter"),     # YouTube Music feat.
    ("Bob Carlisle feat. A Friend", "Butterfly Kisses", "father-daughter"),
    ("BobCarlisleVEVO", "Bob Carlisle - Butterfly Kisses (Official Video)", "father-daughter"),  # plain YouTube
    ("Bob Carlisle - Topic", "Butterfly Kisses", "father-daughter"),
    ("Beyoncé", "Halo", "first-dance"),                                           # accents
    ("Simon and Garfunkel", "The Boxer", "calm"),                                 # & vs and
    ("Simon & Garfunkel", "Boxer", "calm"),                                       # a leading "the"
    ("The Temptations", "My Girl", "mother-son"),                                 # saved under the title alone
    ("Bob Carlisle", "Butterfly", None),                                          # a different song stays off
    ("Someone", "Kisses", None),
    ("", "", None),
])
def test_forgiving_match(artist, title, want):
    hit = pick(SAVED, candidates(artist, title))
    assert (SAVED[hit] if hit else None) == want


def test_exact_key_wins_over_forgiving_match():
    songs = {"artist-song-live": "live-look", "artist-song": "studio-look"}
    assert pick(songs, candidates("Artist", "Song (Live)")) == "artist-song-live"
    assert pick(songs, candidates("Artist", "Song - Remastered")) == "artist-song"


def test_first_candidate_is_the_plain_track_key():
    assert candidates("Bob Carlisle", "Butterfly Kisses (Remastered)")[0] == \
        C.track_key("Bob Carlisle", "Butterfly Kisses (Remastered)")


# --- the beat from the speakers ---------------------------------------------------------------

def run_tracker(x, start_at=12.0):
    bt = BeatTracker(SR)
    out = []
    for i in range(0, len(x) - 1024, 1024):
        t = (i + 1024) / SR
        bt.feed(x[i:i + 1024], t)
        r = bt.reading(t)
        if r.locked and t > start_at:
            out.append(r)
    return bt, out


@pytest.mark.parametrize("bpm", [90, 120, 128])
def test_tracker_finds_tempo_and_lands_on_the_beat(bpm):
    _, readings = run_tracker(drums(bpm, 25))
    assert readings, "never locked"
    assert abs(np.median([r.bpm for r in readings]) / bpm - 1) < 0.015
    # time from each tracked beat to the nearest real beat
    errs = [abs(((r.at - (r.beat % 1) * 60 / r.bpm) * bpm / 60 + .5) % 1 - .5) * 60 / bpm for r in readings]
    assert np.median(errs) < 0.05 and np.percentile(errs, 90) < 0.08


def test_tracker_counts_forward():
    _, readings = run_tracker(drums(120, 20))
    beats = [r.beat for r in readings]
    assert all(b2 > b1 - 0.1 for b1, b2 in zip(beats, beats[1:]))


def test_tracker_hears_silence_as_nothing_playing():
    x = np.concatenate([drums(120, 10), np.zeros(int(3 * SR), np.float32)])
    bt, _ = run_tracker(x)
    r = bt.reading(len(x) / SR)
    assert not r.playing and not r.locked and r.level == 0.0


def test_library_bpm_picks_the_octave():
    bt = BeatTracker(SR)
    bt.hint_bpm = 64.0
    x = drums(128, 15)
    for i in range(0, len(x) - 1024, 1024):
        bt.feed(x[i:i + 1024], (i + 1024) / SR)
    assert abs(bt.reading(len(x) / SR).bpm - 64.0) < 1.5


# --- the song name from Windows ---------------------------------------------------------------

def test_app_names():
    assert app_name("Spotify.exe") == "Spotify"
    assert app_name("SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify") == "Spotify"
    assert app_name("chrome") == "Chrome"
    assert app_name("MSEdge") == "Edge"
    assert app_name("308046B0AF4A39CB") == "Firefox"
    assert app_name(r"C:\Apps\Foobar2000.exe") == "Foobar2000"
    assert NowPlaying("a", "b", "Chrome", True).source == "browser (Chrome)"
    assert NowPlaying("a", "b", "Spotify", True).source == "Spotify"


def test_choose_follows_the_one_playing():
    paused = NowPlaying("A", "Paused song", "Spotify", False)
    tab = NowPlaying("B", "Tab song", "Chrome", True)
    assert choose([paused, tab], current=paused) == tab
    assert choose([paused], current=paused) == paused        # paused: still say what is loaded
    assert choose([], current=None) is None
    assert choose([NowPlaying("", "", "Chrome", True)], None) is None


@pytest.mark.skipif(importlib.util.find_spec("winrt") is not None, reason="winrt is installed here")
def test_media_sessions_without_winrt_says_why():
    ms = MediaSessions()
    ms._run()  # winrt is not installed off Windows
    assert ms.current() is None and "media library" in ms.error


def test_library_bpm_index(tmp_path):
    db = tmp_path / "mixxxdb.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE library (id INTEGER, artist TEXT, title TEXT, bpm REAL, mixxx_deleted INTEGER)")
        conn.execute("INSERT INTO library VALUES (1, 'Bob Carlisle', 'Butterfly Kisses', 72.5, 0)")
        conn.execute("INSERT INTO library VALUES (2, 'Gone', 'Deleted', 99.0, 1)")
        conn.execute("INSERT INTO library VALUES (3, '', 'Perfect', 95.0, 0)")  # untagged: no title-only hints
    index = MixxxLibrary(db).bpm_index()
    assert index == {norm(C.track_key("Bob Carlisle", "Butterfly Kisses")): 72.5}
    assert MixxxLibrary(tmp_path / "none.sqlite").bpm_index() == {}


def test_title_only_candidates_can_be_left_out():
    keys = candidates("Ed Sheeran", "Perfect", title_only=False)
    assert "perfect" not in keys and keys[0] == "ed-sheeran-perfect"
    assert "perfect" in candidates("Ed Sheeran", "Perfect")


def test_media_answer_goes_stale():
    ms = MediaSessions(reader=lambda: None)
    ms._now, ms._at = NowPlaying("A", "B", "Spotify", True), time.monotonic() - 10
    assert ms.current() is None  # a hung reader never leaves the old song "playing"
    ms._at = time.monotonic()
    assert ms.current().title == "B"


# --- the show follows the speakers, and Mixxx when it plays -----------------------------------

class Rig:
    """A live show on a virtual clock: the speakers play `audio`, Windows names `song`.
    mixxx: None = Mixxx closed, "open" = open and paused (its mapping still ticks), "play"."""

    def __init__(self, song, audio, songs=None, bpms=None, watch=None):
        doc = C.defaults()
        doc["styles"] = {"father-daughter": {k: doc[k] for k in C.STYLE_KEYS}}
        doc["songs"] = songs if songs is not None else {C.track_key("Bob Carlisle - Butterfly Kisses"): "father-daughter"}
        show_settings.set_current(C.normalize(doc))
        self.media = MediaSessions(reader=lambda: None)
        self.set_song(song)
        self.capture = LoopbackCapture()
        self.show = Show(analyze=False, latency_ms=0)
        self.feed = SystemFeed(self.show, self.capture, self.media, use_audio=True, watch=watch)
        if bpms:
            self.feed.bpms = bpms
        self.audio, self.i, self.now = audio, 0, 0.0

    def set_song(self, song):
        self.song = song
        self.media._now, self.media._at = song, time.monotonic() + 1e6

    def play(self, seconds, mixxx=None):
        end = self.now + seconds
        while self.now < end:
            self.now += 1024 / SR
            chunk = self.audio[self.i:self.i + 1024]
            self.i += 1024
            self.capture.tracker.feed(chunk if len(chunk) == 1024 else np.zeros(1024, np.float32), self.now)
            if mixxx:
                if not self.show.state.decks.get(1):
                    self.show.on_midi(encode_track(1, SR, 200.0, 128.0), self.now)
                self.show.on_midi(encode_tick(1, mixxx == "play", True, 128.0, (self.now * 128 / 60) % 1,
                                              int(self.now * SR), 1.0, 0.8), self.now)
                self.feed.saw_mixxx(self.now)
            self.feed(self.now)
            self.show.control_tick(self.now)
            self.show.render(self.now)


@pytest.fixture(autouse=True)
def _settings():
    keep = show_settings.current()
    yield
    show_settings.set_current(keep)


def test_spotify_song_plays_its_style_and_follows_the_beat():
    rig = Rig(NowPlaying("Bob Carlisle", "Butterfly Kisses - Remastered 2011", "Spotify", True), drums(96, 20))
    rig.play(15)
    assert rig.show.state.followed == SYSTEM_DECK
    assert rig.show.looks.showing == "style:father-daughter"
    assert abs(rig.show.clock.bpm - 96) < 1.5
    pub = rig.feed.public()
    assert pub["source"] == "Spotify" and pub["title"].startswith("Butterfly Kisses")
    assert pub["style"] == "father-daughter" and pub["beat"] == "heard"
    assert rig.show.status(rig.now).startswith("Spotify: Bob Carlisle - Butterfly Kisses")
    assert rig.capture.want.is_set()


def test_takes_over_only_after_sustained_sound_and_shows_the_style_while_finding_the_beat():
    rig = Rig(NowPlaying("Bob Carlisle", "Butterfly Kisses", "Spotify", True), drums(96, 6))
    rig.play(1.0)
    assert rig.show.state.followed is None  # a second of sound is not enough yet
    rig.play(1.6)
    assert rig.show.state.followed == SYSTEM_DECK
    assert rig.show.looks.showing == "style:father-daughter"
    assert rig.feed.public()["beat"] == "finding"


def test_an_unknown_song_plays_the_default_show():
    rig = Rig(NowPlaying("Someone", "Another Song", "Chrome", True), drums(120, 10))
    rig.play(6)
    assert rig.show.state.followed == SYSTEM_DECK and rig.show.looks.showing == ""
    assert rig.feed.public()["source"] == "browser (Chrome)"


def test_sound_with_no_song_name_follows_the_speakers_when_mixxx_is_closed():
    rig = Rig(None, drums(120, 10))
    rig.play(6)
    assert rig.show.state.followed == SYSTEM_DECK and rig.feed.public()["source"] == "the speakers"


def test_a_muted_tab_saying_playing_never_starts_the_show():
    rig = Rig(NowPlaying("Someone", "Autoplay", "Chrome", True), np.zeros(int(8 * SR), np.float32))
    rig.play(6)
    assert rig.show.state.followed is None and rig.feed.source == ""


def test_mixxx_takes_over_while_it_plays_then_hands_back_to_spotify():
    rig = Rig(NowPlaying("Bob Carlisle", "Butterfly Kisses", "Spotify", True), drums(96, 40))
    rig.play(8)
    assert rig.show.state.followed == SYSTEM_DECK
    rig.play(3, mixxx="play")
    assert rig.show.state.followed == 1 and rig.feed.source == "Mixxx"
    assert rig.feed.public()["source"] == "Mixxx"
    assert not rig.capture.want.is_set()  # the loopback stream is closed while Mixxx plays
    rig.play(4, mixxx="open")  # paused, still open: Spotify is playing, so it gets the lights back
    assert rig.show.state.followed == SYSTEM_DECK and rig.feed.source == "Spotify"


def test_mixxx_open_and_paused_bare_sound_never_takes_the_lights():
    # the toasts: the MC's mic runs through Mixxx to the speakers, no other app plays
    rig = Rig(None, drums(120, 12))
    rig.play(8, mixxx="open")
    assert rig.show.state.followed != SYSTEM_DECK
    assert not rig.capture.want.is_set()  # and the loopback stream is not even opened


def test_pause_lets_go_after_the_hold():
    rig = Rig(NowPlaying("Bob Carlisle", "Butterfly Kisses", "Spotify", True), drums(96, 8))
    rig.play(7)
    rig.set_song(NowPlaying("Bob Carlisle", "Butterfly Kisses", "Spotify", False))
    rig.play(1.0)  # the audio ran out: silence, but inside the hold
    assert rig.show.state.followed == SYSTEM_DECK
    rig.play(4)
    assert rig.show.state.followed is None and rig.feed.public()["source"] == ""


def test_a_new_song_swaps_the_style():
    rig = Rig(NowPlaying("Someone", "Another Song", "Spotify", True), drums(120, 30))
    rig.play(4)
    assert rig.show.looks.showing == ""
    rig.set_song(NowPlaying("Bob Carlisle", "Butterfly Kisses", "Spotify", True))
    rig.play(1)
    assert rig.show.looks.showing == "style:father-daughter"


def test_the_beat_count_never_jumps_when_the_beat_is_found():
    rig = Rig(NowPlaying("Someone", "Song", "Spotify", True), drums(120, 20))
    sent = []
    on_midi = rig.show.on_midi

    def spy(msg, now=None):
        if msg[3] == 0x01 and msg[4] == SYSTEM_DECK and msg[5] & 1:
            bpm = sum((msg[6 + i] & 0x7F) << (7 * i) for i in range(3)) / 100
            pos = sum((msg[11 + i] & 0x7F) << (7 * i) for i in range(5))
            sent.append((now, pos / SR * bpm / 60))
        on_midi(msg, now)
    rig.show.on_midi = spy
    rig.play(12)  # free-running, then the beat is found around 5 s in
    steps = [b2 - b1 for (_, b1), (_, b2) in zip(sent, sent[1:])]
    # one tick is ~0.05 beat; taking the heard phase may move it once, by at most half a beat
    assert sent and max(abs(x) for x in steps) < 0.5 + 0.06


def test_library_bpm_settles_the_octave_through_the_feed():
    key = norm(C.track_key("Bob Carlisle", "Butterfly Kisses"))
    rig = Rig(NowPlaying("Bob Carlisle", "Butterfly Kisses (Live)", "Spotify", True), drums(128, 15), bpms={key: 64.0})
    rig.play(12)
    assert rig.feed.hint == 64.0 and abs(rig.show.clock.bpm - 64) < 1.5


def test_a_feed_error_never_ends_the_show(capsys):
    rig = Rig(NowPlaying("A", "B", "Spotify", True), drums(120, 4))
    rig.media.current = lambda: 1 / 0
    rig.play(0.5)  # no exception escapes
    assert "keeps running" in capsys.readouterr().out


def test_off_switch_and_no_mixxx_link_notes():
    rig = Rig(NowPlaying("Bob Carlisle", "Butterfly Kisses", "Spotify", True), drums(120, 8))
    rig.feed.use_audio, rig.feed.mixxx_link = False, False
    rig.play(4)
    assert rig.show.state.followed is None and not rig.capture.want.is_set()
    assert any("Mixxx isn't connected" in p for p in rig.feed.public()["problems"])


@pytest.mark.skipif(importlib.util.find_spec("soundcard") is not None, reason="soundcard is installed here")
def test_no_capture_library_still_names_the_song():
    cap = LoopbackCapture()
    cap._run()  # soundcard is not installed off Windows
    assert "capture library" in cap.error
    rig = Rig(NowPlaying("Bob Carlisle", "Butterfly Kisses", "Spotify", True), np.zeros(SR, np.float32))
    rig.capture = rig.feed.capture = cap
    rig.play(0.5)  # nothing to listen with: the app's name alone takes over at once, keeping time
    assert rig.show.state.followed == SYSTEM_DECK and rig.show.looks.showing == "style:father-daughter"


class Watch(MixxxWatch):
    """mixxx.exe running or not, set by the test."""

    def __init__(self, running):
        super().__init__(probe=lambda: running)
        self.running = running


def test_mixxx_starting_after_the_lights_closes_the_stream_at_once():
    watch = Watch(False)
    rig = Rig(None, drums(120, 20), watch=watch)
    rig.play(1.0)
    assert not rig.capture.want.is_set()  # the first seconds: Mixxx may still be starting
    rig.play(4)
    assert rig.capture.want.is_set() and rig.show.state.followed == SYSTEM_DECK
    watch.running = True  # he opens Mixxx (it has sent nothing yet)
    rig.play(0.1)
    assert not rig.capture.want.is_set()  # out of its way before it opens the sound device


def test_mixxx_running_but_silent_on_midi_still_counts_as_running():
    rig = Rig(None, drums(120, 12), watch=Watch(True))
    rig.play(8)  # no MIDI at all (controllers not set up yet), mic sound through the speakers
    assert rig.show.state.followed is None and not rig.capture.want.is_set()


def test_a_failing_capture_never_lets_a_name_take_over_while_mixxx_runs():
    rig = Rig(NowPlaying("Someone", "Muted tab", "Chrome", True), np.zeros(int(15 * SR), np.float32), watch=Watch(True))
    rig.capture.error, rig.capture.failing_since = "can't hear the speakers right now (device in use)", -60.0
    rig.play(6)
    assert rig.show.state.followed is None


def test_a_capture_failing_long_with_mixxx_closed_falls_back_to_names():
    rig = Rig(NowPlaying("Bob Carlisle", "Butterfly Kisses", "Spotify", True), np.zeros(SR, np.float32), watch=Watch(False))
    rig.capture.error, rig.capture.failing_since = "can't hear the speakers right now", 0.0  # the rig's clock
    rig.play(5)
    assert rig.show.state.followed is None  # failing, but not for 10 s yet: no
    rig.play(6)
    assert rig.show.state.followed == SYSTEM_DECK and rig.show.looks.showing == "style:father-daughter"


def test_a_notification_ding_does_not_start_the_show():
    ding = np.zeros(int(8 * SR), np.float32)
    for t in (1.0, 2.0, 3.0):  # three short dings, each 0.3 s, within the 1.5 s "playing" window
        i = int(t * SR)
        ding[i:i + int(0.3 * SR)] = 0.3 * np.sin(2 * np.pi * 880 * np.arange(int(0.3 * SR)) / SR)
    rig = Rig(None, ding, watch=Watch(False))
    rig.play(6)
    assert rig.feed.active is False and rig.show.state.followed is None


def test_a_media_blip_keeps_the_song_and_the_stream():
    rig = Rig(NowPlaying("Bob Carlisle", "Butterfly Kisses", "Spotify", True), drums(96, 20), watch=Watch(True))
    rig.play(8)
    assert rig.show.looks.showing == "style:father-daughter"
    rig.set_song(None)  # one poll with nothing (a track change, a slow answer)
    rig.play(1.5)
    assert rig.show.looks.showing == "style:father-daughter" and rig.capture.want.is_set()


def test_while_mixxx_runs_the_stream_closes_as_soon_as_the_other_app_stops():
    rig = Rig(NowPlaying("Bob Carlisle", "Butterfly Kisses", "Spotify", True), drums(96, 30), watch=Watch(True))
    rig.play(6)
    assert rig.capture.want.is_set()
    rig.set_song(NowPlaying("Bob Carlisle", "Butterfly Kisses", "Spotify", False))
    rig.play(6)  # past the 5 s song hold: Mixxx's Retry finds the device free
    assert not rig.capture.want.is_set()


def test_mixxx_quitting_kicks_a_held_capture_to_retry():
    watch = Watch(True)
    rig = Rig(None, drums(120, 10), watch=watch)
    rig.play(1)
    rig.capture.kick.clear()
    watch.running = False
    rig.play(0.1)
    assert rig.capture.kick.is_set()


def test_capture_failure_while_mixxx_held_the_device_does_not_count_toward_the_fallback():
    watch = Watch(True)
    rig = Rig(NowPlaying("Someone", "Muted tab", "Chrome", True), np.zeros(int(10 * SR), np.float32), watch=watch)
    rig.capture.error, rig.capture.failing_since = "can't hear the speakers right now (device in use)", -1000.0
    rig.play(2)
    watch.running = False  # Mixxx quits after holding the device for hours
    rig.play(2)
    assert rig.show.state.followed is None  # no instant takeover by the muted tab's name


def test_watch_keeps_its_last_answer_when_a_check_fails():
    answers = iter([True, None, None])
    w = MixxxWatch(probe=lambda: next(answers), every_s=0.0)
    for _ in range(3):
        found = w.probe()
        if found is not None:
            w.running = found
    assert w.running is True
