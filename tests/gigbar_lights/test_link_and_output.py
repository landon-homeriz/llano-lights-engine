"""gigbar_lights: Mixxx wire protocol, library beat grids, beat clock, rig and DMX framing."""
import math
import random
import sqlite3
import struct

from tools.gigbar_lights import enttec, mixxx_db
from tools.gigbar_lights.beat_clock import BeatClock, TapTempo, TrackGrid, measured_beat
from tools.gigbar_lights.mixxx_link import MixxxState, encode_audio, encode_tick, encode_track
from tools.gigbar_lights.rig import default_rig


# --- wire protocol ------------------------------------------------------------------

def test_tick_round_trip():
    st = MixxxState()
    st.feed(encode_tick(2, True, True, 128.37, 0.6, 9_000_123, 0.75, 0.4), now=5.0)
    d = st.decks[2]
    assert d.playing and d.loaded
    assert abs(d.bpm - 128.37) < 0.006
    assert abs(d.beat_distance - 0.6) < 1e-4
    assert d.pos_frames == 9_000_123
    assert abs(d.weight - 0.75) < 0.01 and abs(d.level - 0.4) < 0.01
    assert all(b <= 0x7F for b in encode_tick(2, True, True, 128.37, 0.6, 9_000_123, 0.75)[1:-1])


def test_track_and_audio_messages():
    st = MixxxState()
    st.feed(encode_track(1, 48000, 312.45, 174.0))
    st.feed(encode_track(1, 48000, 312.45, 174.0))
    d = st.decks[1]
    assert (d.samplerate, d.duration, d.file_bpm) == (48000, 312.45, 174.0)
    assert d.track_serial == 1  # repeats of the same track don't count as a new track
    st.feed(encode_audio(23.2))
    assert st.output_latency_ms == 23.2


def test_rejects_foreign_and_malformed_sysex():
    st = MixxxState()
    assert st.feed([0xF0, 0x7E, 0x00, 0x06, 0x01, 0xF7]) is None
    assert st.feed(encode_tick(1, True, True, 120, 0.5, 0, 1)[:-2] + [0xF7]) is None
    assert st.feed([0xF0, 0x7D, 0x4C, 0x01, 9] + [0] * 13 + [0xF7]) is None  # deck 9
    assert st.decks == {}


def test_follows_loudest_deck_with_hysteresis():
    st = MixxxState()
    st.feed(encode_tick(1, True, True, 124, 0.1, 0, 0.9), now=1.0)
    st.feed(encode_tick(2, True, True, 124, 0.1, 0, 0.5), now=1.0)
    assert st.pick_followed(now=1.0).deck == 1
    st.feed(encode_tick(2, True, True, 124, 0.1, 0, 0.95), now=1.1)  # mid-blend, barely louder
    assert st.pick_followed(now=1.1).deck == 1
    st.feed(encode_tick(1, True, True, 124, 0.1, 0, 0.3), now=1.2)  # deck 1 faded down
    assert st.pick_followed(now=1.2).deck == 2
    assert st.pick_followed(now=9.0) is None  # nothing heard for a while


# --- beat clock ---------------------------------------------------------------------

def test_clock_smooths_buffer_jitter():
    """Mixxx reports once per ~11.6 ms buffer with delivery jitter; the clock stays tight."""
    rng = random.Random(7)
    bpm, clock, worst = 128.0, BeatClock(), 0.0
    t = 0.0
    while t < 20.0:
        true_beat = t * bpm / 60.0
        arrival = t + rng.uniform(0.0, 0.008)  # thread + MIDI delivery delay
        clock.update(true_beat, bpm, True, arrival)
        if t > 2.0:
            worst = max(worst, abs(clock.beat_at(arrival) - (arrival * bpm / 60.0 - 0.004 * bpm / 60.0)))
        t += 0.0116
    assert worst * 60.0 / bpm < 0.006  # under 6 ms of error once settled


def test_clock_snaps_on_seek_and_holds_when_stopped():
    clock = BeatClock()
    clock.update(10.0, 120, True, 0.0)
    clock.update(10.5, 120, True, 0.25)
    clock.update(42.0, 120, True, 0.30)  # cue jump
    assert abs(clock.beat_at(0.30) - 42.0) < 1e-9
    clock.update(43.0, 120, False, 1.0)
    assert clock.beat_at(5.0) == 43.0


def test_latency_pulls_lights_back_to_the_speakers():
    clock = BeatClock()
    clock.update(8.0, 120, True, 0.0)
    assert abs(clock.beat_at(0.0, latency_s=0.025) - (8.0 - 0.05)) < 1e-9


def test_measured_beat_anchors_bars_to_grid():
    grid = TrackGrid(44100, first_beat=22050.0, bpm=120.0)  # beat 0 at 0.5 s
    pos = 22050 + 4 * 22050 + 11025  # 4.5 beats after the first beat
    assert abs(measured_beat(pos, 0.5, 44100, 120.0, grid) - 4.5) < 1e-9
    # Without the grid: still ordered beats, counted from the start of the file.
    assert abs(measured_beat(pos, 0.5, 44100, 120.0) - 5.5) < 1e-9


def test_beat_map_grid():
    grid = TrackGrid(44100, beats=(0, 20000, 41000, 63000))
    assert grid.beat_position(30500) == 1.5


def test_tap_tempo():
    tap = TapTempo()
    assert tap.tap(0.0) is None
    tap.tap(0.5)
    assert abs(tap.tap(1.0) - 120.0) < 1e-9
    assert tap.tap(10.0) is None  # long gap starts over


def test_the_show_stops_when_mixxx_goes_quiet_mid_song():
    # His 11-09 wedding check: Mixxx crashing or freezing mid-song sends no pause, and the show
    # used to fall back to its no-Mixxx free run and dance on at the last tempo in silence.
    from tools.gigbar_lights.show import Show
    show = Show(analyze=False)
    show.on_midi(encode_track(1, 44100, 240.0, 124.0), 0.0)
    t = 0.0
    while t < 5.0:
        show.on_midi(encode_tick(1, True, True, 124.0, (t * 124 / 60) % 1, int(t * 44100), 1.0, 0.7), t)
        t += 0.025
    assert show.frame(t).playing
    assert not show.frame(t + 3.0).playing            # Mixxx gone 3 s: the music stopped, so did the show
    assert not show.frame(t + 30.0).playing
    show.tap_tempo(t + 31.0)
    show.tap_tempo(t + 31.5)
    show.tap_tempo(t + 32.0)
    assert show.frame(t + 32.1).playing                # a tap still starts a free run


# --- Mixxx library ------------------------------------------------------------------

def _varint(v):
    out = bytearray()
    v &= 0xFFFFFFFFFFFFFFFF
    while True:
        b = v & 0x7F
        v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v:
            return bytes(out)


def _len_field(num, payload):
    return _varint(num << 3 | 2) + _varint(len(payload)) + payload


def _beat(frame):
    return _varint(1 << 3) + _varint(frame)


def test_parse_beatgrid_proto_legacy_and_map():
    bpm_msg = bytes([0x09]) + struct.pack("<d", 126.0)
    blob = _len_field(1, bpm_msg) + _len_field(2, _beat(1234))
    g = mixxx_db.parse_beats("BeatGrid-2.0", blob, 44100)
    assert (g.bpm, g.first_beat) == (126.0, 1234.0)
    legacy = mixxx_db.parse_beats("BeatGrid-1.0", struct.pack("<dd", 100.0, 50.0), 44100)
    assert (legacy.bpm, legacy.first_beat) == (100.0, 50.0)
    bmap = b"".join(_len_field(1, _beat(f)) for f in (100, 22150, 44200))
    assert mixxx_db.parse_beats("BeatMap-1.0", bmap, 44100).beats == (100, 22150, 44200)
    assert mixxx_db.parse_beats("BeatGrid-2.0", b"\xff\xff", 44100) is None


def test_library_finds_track_read_only(tmp_path):
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
    """)
    blob = _len_field(1, bytes([0x09]) + struct.pack("<d", 124.0)) + _len_field(2, _beat(500))
    conn.execute("INSERT INTO library VALUES (1,'Artist A','Song',201.5,124.0,44100,?,'BeatGrid-2.0',0,1,'2026-11-01')",
                 (blob,))
    conn.execute("INSERT INTO library VALUES (2,'Artist B','Same length',201.5,124.0,44100,NULL,NULL,0,2,'2026-11-02')")
    conn.execute("INSERT INTO track_locations VALUES (1,'C:/Music/song.mp3'), (2,'C:/Music/other.mp3')")
    conn.execute("INSERT INTO Playlists VALUES (1,'2026-11-06',2)")
    conn.execute("INSERT INTO PlaylistTracks VALUES (1,1,1,1,'2026-11-06 21:00:00')")
    conn.commit()
    conn.close()
    lib = mixxx_db.MixxxLibrary(db)
    info = lib.find_track(44100, 201.5, 124.0)
    assert info.label == "Artist A - Song"  # the one in tonight's history wins the tie
    assert info.grid.first_beat == 500.0
    assert info.location.name == "song.mp3"
    assert [t.track_id for t in lib.analyzable_tracks()] == [1]  # only tracks with a grid
    assert lib.find_track(44100, 90.0, 124.0) is None
    assert mixxx_db.MixxxLibrary(tmp_path / "missing.sqlite").find_track(44100, 1, 1) is None


# --- rig and DMX framing ------------------------------------------------------------

def test_address_plan_fits_without_overlap():
    rig = default_rig()
    taken = set()
    for fx in rig.fixtures:
        span = set(range(fx.address, fx.address + fx.footprint))
        assert not span & taken, fx.name
        taken |= span
    assert max(taken) == 188 and len(rig.fixtures) == 12


def test_render_places_channels_at_planned_addresses():
    rig = default_rig()
    rig.bars[1].movers[0].pan = 1.0
    rig.tetras[2].red, rig.tetras[2].dim = 1.0, 1.0
    rig.sticks[3].blue, rig.sticks[3].dim = 1.0, 0.5
    u = rig.render()
    assert u[41 + 24 - 2] == 255           # bar 2 starts at 41; mover 1 pan is its ch24
    assert u[101 - 1] == 255 and u[101 + 4 - 1] == 255  # Tetra #3 red + dimmer
    assert u[181 - 1] == 128 and u[181 + 3 - 1] == 255  # Stick #4 dimmer + blue
    assert u[188:] == bytes(512 - 188)


def test_strobe_ranges_respect_fixture_bands():
    rig = default_rig()
    par = rig.bars[0].pars[0]
    par.dim = 1.0
    assert par.channels()[4] == 127        # dimmer band tops out at 127
    par.strobe = 0.01
    assert 128 <= par.channels()[4] <= 239  # any strobe moves into the strobe band


def test_enttec_packet_framing():
    pkt = enttec.dmx_packet(bytes(range(10)))
    assert pkt[:2] == bytes([0x7E, 6]) and pkt[-1] == 0xE7
    length = pkt[2] | pkt[3] << 8
    assert length == 25 and pkt[4] == 0 and pkt[5:15] == bytes(range(10))  # padded to 24 slots
    full = enttec.dmx_packet(bytes(512))
    assert (full[2] | full[3] << 8) == 513 and len(full) == 513 + 5
    assert enttec.RIG_SLOTS >= max(f.address + f.footprint - 1 for f in default_rig().fixtures)


def test_output_loop_sends_frames_and_final_blackout():
    out = enttec.NullOutput()
    loop = enttec.OutputLoop(out, lambda now: bytes([255]) * 512, hz=200)
    loop.start()
    import time
    time.sleep(0.1)
    loop.stop(final_frame=bytes(512))
    assert out.frames >= 5 and out.last == bytes(512)


# --- review fixes -------------------------------------------------------------------

def test_no_grid_beat_count_does_not_flip_on_rounding_edge():
    """First beat half a beat into the file + a lagging play position: count stays steady."""
    rate, bpm = 44100, 120.0
    fpb = rate * 60 / bpm
    clock, beats = BeatClock(), []
    for k in range(200):
        t = k * 0.0116
        true = t * bpm / 60 - 0.55            # Mixxx's beats, offset by the first beat
        if true < 0:
            continue
        lagged_pos = int(math.floor(t * 15) / 15 * rate)  # playposition steps ~15x a second
        predicted = clock.predict(t) if clock.running else None
        b = measured_beat(lagged_pos, true % 1, rate, bpm, None, predicted)
        clock.update(b, bpm, True, t)
        beats.append(b)
    steps = [b2 - b1 for b1, b2 in zip(beats, beats[1:])]
    assert all(-0.01 < s < 0.1 for s in steps)  # never jumps a whole beat


def test_measured_beat_without_grid_still_follows_a_seek():
    assert abs(measured_beat(44100 * 60, 0.25, 44100, 120.0, None, predicted=10.2) - 120.25) < 1e-9


def test_library_matches_on_duration_when_saved_bpm_is_stale(tmp_path):
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
        INSERT INTO library VALUES (1,'New','Import',180.0,0,44100,NULL,NULL,0,NULL,'2026-11-06');
    """)
    conn.commit()
    conn.close()
    assert mixxx_db.MixxxLibrary(db).find_track(44100, 180.0, 128.0).title == "Import"


def test_disabled_and_duplicate_beats():
    disabled = _varint(1 << 3) + _varint(22150) + _varint(2 << 3) + _varint(0)
    bmap = (_len_field(1, _beat(100)) + _len_field(1, disabled) + _len_field(1, _beat(44200))
            + _len_field(1, _beat(66250)))
    assert mixxx_db.parse_beats("BeatMap-1.0", bmap, 44100).beats == (100, 44200, 66250)
    assert TrackGrid(44100, beats=(0, 100, 100, 300)).beat_position(100) is not None


def test_failed_lookup_is_retried():
    from tools.gigbar_lights.show import RETRY_LOOKUP_S, Show

    class FlakyLibrary:
        calls = 0

        def find_track(self, *a):
            self.calls += 1
            return None

    lib = FlakyLibrary()
    show = Show(lib, analyze=False)
    show.on_midi(encode_track(1, 44100, 200.0, 124.0), 0.0)
    show.on_midi(encode_tick(1, True, True, 124, 0.1, 0, 0.9), 0.0)
    show.control_tick(0.0)
    show.control_tick(1.0)
    assert lib.calls == 1
    show.control_tick(RETRY_LOOKUP_S + 0.5)
    assert lib.calls == 2
