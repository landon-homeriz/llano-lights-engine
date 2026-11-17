"""gigbar_lights: song-section labels, the looks engine's SoundSwitch-matching behaviors, end-to-end timing."""
import math

import pytest

from tools.gigbar_lights import show_script
from tools.gigbar_lights.beat_clock import TrackGrid
from tools.gigbar_lights.looks import Frame, LooksEngine
from tools.gigbar_lights.mixxx_link import encode_audio, encode_tick, encode_track
from tools.gigbar_lights.rig import default_rig
from tools.gigbar_lights.show import DeckTrack, Show
from tools.gigbar_lights.show_script import ScriptCache, Section, ShowScript, label_phrases

SONG = ShowScript([Section("intro", 0, 32, 0.2), Section("build", 32, 64, 0.5),
                   Section("drop", 64, 96, 0.9), Section("main", 96, 128, 0.9),
                   Section("breakdown", 128, 160, 0.3), Section("outro", 160, 192, 0.2)])


def frame(beat, level=0.6, loop_beats=0.0, script=SONG, playing=True):
    section, nxt = script.at(beat) if script else (None, None)
    return Frame(beat, 128.0, playing, level=level, loop_beats=loop_beats,
                 section=section, next_section=nxt, track_key=3)


def emitting(rig) -> bool:
    """Is any light actually putting out light? (Parked movers and black derby slots don't.)"""
    for bar in rig.bars:
        if any(p.dim or p.strobe for p in bar.pars) or any(m.dim for m in bar.movers):
            return True
        if bar.strobe_white or bar.laser != "off" or any(d.color != "off" for d in bar.derbies):
            return True
    return any(fx.dim for fx in (*rig.tetras, *rig.sticks))


def render(engine, f):
    rig = default_rig()
    engine.render(f, rig)
    return rig


# --- section labels -----------------------------------------------------------------

def _bars(*phrases):
    """Each phrase: (loudness, bass) held for 8 bars."""
    loud, bass = [], []
    for e, b in phrases:
        loud += [e] * 8
        bass += [b] * 8
    return loud, bass


def test_labels_a_typical_dance_track():
    loud, bass = _bars((0.2, 0.1), (0.3, 0.3), (0.5, 0.5), (0.9, 0.9), (0.9, 0.9),
                       (0.25, 0.05), (0.5, 0.4), (0.95, 0.9), (0.3, 0.2))
    kinds = [s.kind for s in label_phrases(loud, bass)]
    assert kinds == ["intro", "build", "drop", "main", "breakdown", "build", "drop", "outro"]


def test_build_is_detected_by_rising_energy():
    loud = [0.2] * 8 + [0.1, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5] + [0.9] * 8
    bass = [0.1] * 8 + [0.0] * 8 + [0.9] * 8
    kinds = [s.kind for s in label_phrases(loud, bass)]
    assert kinds == ["intro", "build", "drop"]


def test_sections_are_on_phrase_boundaries_in_beats():
    loud, bass = _bars((0.2, 0.1), (0.9, 0.9))
    s = label_phrases(loud, bass)
    assert [(x.start_beat, x.end_beat) for x in s] == [(0, 32), (32, 64)]
    assert label_phrases([], []) == []


def test_bar_energies_and_analysis_on_synthetic_audio(monkeypatch, tmp_path):
    np = pytest.importorskip("numpy")
    rate, bpm = 8000, 120
    bar_frames = rate * 2  # 4 beats at 120 BPM
    t = np.arange(bar_frames * 24) / rate
    quiet = 0.05 * np.sin(2 * np.pi * 900 * t)
    kick = 0.8 * np.sin(2 * np.pi * 55 * t) * (np.mod(t, 0.5) < 0.12)
    loud_mask = (t >= 16 * 2.0)  # bars 16+ get the kick
    audio = quiet + kick * loud_mask
    monkeypatch.setattr(show_script, "load_mono", lambda path: (audio.astype(np.float32), rate))
    script = show_script.analyze_track(tmp_path / "x.wav", TrackGrid(rate, first_beat=0.0, bpm=bpm))
    kinds = [s.kind for s in script.sections]
    assert kinds[-1] == "drop" and script.sections[-1].start_beat == 64


def test_script_cache_round_trip_and_staleness(tmp_path):
    cache = ScriptCache(tmp_path)
    cache.put(7, SONG)
    assert cache.get(7).sections == SONG.sections
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"x")
    import os
    os.utime(audio, (2e9, 2e9))  # file changed after analysis
    assert cache.get(7, audio) is None
    assert cache.get(8) is None


# --- looks engine: SoundSwitch behaviors ------------------------------------------------

def test_drop_hits_on_beat_one_with_white_strobe():
    eng = LooksEngine()
    on_one = render(eng, frame(64.1))
    assert eng.mode == "scripted:drop"
    assert all(b.strobe_white == 1.0 for b in on_one.bars)
    after = render(eng, frame(65.2))
    assert all(b.strobe_white == 0.0 for b in after.bars)


def test_dark_beat_before_the_drop():
    eng = LooksEngine()
    assert not emitting(render(eng, frame(63.5)))
    assert emitting(render(eng, frame(61.0)))


def test_build_rises_and_subdivides():
    eng = LooksEngine()
    early = render(eng, frame(33.0)).bars[0].movers[0].tilt
    late = render(eng, frame(60.0)).bars[0].movers[0].tilt
    assert late > early  # beams climb through the build
    # Last quarter: the pulse hits on every quarter beat, not just on the beat.
    on_quarter = render(eng, frame(58.25)).sticks[0].dim
    between = render(eng, frame(58.40)).sticks[0].dim
    assert on_quarter > between * 1.5


def test_palette_changes_at_phrase_starts_not_mid_phrase():
    # 1.2.3: intro color steps every 4 bars (intro color_bars 4), so it holds within beats 0-15
    # and changes at beat 16 (before 1.2.3 it held for 8 bars, beats 2 and 20 matched).
    eng = LooksEngine()
    rgb = lambda t: (t.red, t.green, t.blue)
    a = rgb(render(eng, frame(2.0)).tetras[0])
    b = rgb(render(eng, frame(14.0)).tetras[0])
    c = rgb(render(eng, frame(18.0)).tetras[0])
    assert a == b
    assert a != c


def test_groups_do_different_things_in_a_drop():
    rig = render(LooksEngine(), frame(70.3))
    tetra_dims = [t.dim for t in rig.tetras]
    assert max(tetra_dims) - min(tetra_dims) > 0.2  # a chase, not everything at once


def test_loop_auto_strobe_only_for_half_beat_or_shorter():
    eng = LooksEngine()
    assert render(eng, frame(70.3, loop_beats=0.25)).tetras[0].strobe > 0
    assert eng.mode.endswith("+strobe")
    assert render(eng, frame(70.3, loop_beats=4)).tetras[0].strobe == 0


def test_autoloops_cycle_every_8_bars_and_hold():
    eng = LooksEngine()
    names = [eng.autoloop_name(frame(b * 4, script=None)) for b in (0, 7, 8, 16)]
    assert names[0] == names[1] != names[2] != names[3]
    render(eng, frame(4.0, script=None))
    assert eng.mode.startswith("autoloop:")
    eng.overrides.hold_loop = True
    assert eng.autoloop_name(frame(0, script=None)) == eng.autoloop_name(frame(400, script=None))


def test_autoloop_override_beats_the_script():
    eng = LooksEngine()
    eng.overrides.autoloop_override = True
    render(eng, frame(70.0))
    assert eng.mode.startswith("autoloop:")


def test_blackout_master_and_silence():
    eng = LooksEngine()
    eng.overrides.blackout = True
    assert not emitting(render(eng, frame(70.0)))
    eng.overrides.blackout = False
    eng.overrides.master = 0.5
    full = render(LooksEngine(), frame(80.0)).tetras[0].dim
    assert abs(render(eng, frame(80.0)).tetras[0].dim - full * 0.5) < 1e-9
    eng.overrides.master = 1.0
    assert not emitting(render(eng, frame(80.0, level=0.0)))  # hard stop goes dark
    assert eng.mode == "silence"


def test_derbies_off_means_black_slot():
    rig = render(LooksEngine(), frame(2.0))  # intro: no effects
    assert rig.render()[10] < 25  # derby 1 color channel in the blackout band


def test_color_hold_pins_every_wash():
    eng = LooksEngine()
    eng.overrides.color_hold = 0.0  # red
    rig = render(eng, frame(70.0))
    assert all((t.red, t.green, t.blue) == (1.0, 0.0, 0.0) for t in rig.tetras)


# --- end to end: Mixxx messages to DMX on time --------------------------------------------

def test_drop_strobe_lands_with_the_speakers():
    """Feed the show like Mixxx would (11.6 ms buffers, jitter), find when the strobe fires."""
    import random
    rng = random.Random(3)
    bpm, rate, latency_ms = 128.0, 44100, 23.2
    show = Show(analyze=False)
    show.on_midi(encode_track(1, rate, 300.0, bpm), 0.0)
    show.on_midi(encode_audio(latency_ms), 0.0)
    show.tracks[1] = DeckTrack(serial=1, script=SONG)
    drop_audible_at = 64 * 60 / bpm + latency_ms / 1000  # engine time + output latency
    t, fired = 0.0, None
    while t < drop_audible_at + 0.2:
        show.on_midi(encode_tick(1, True, True, bpm, (t * bpm / 60) % 1, int(t * rate), 0.9, 0.8),
                     t + rng.uniform(0, 0.006))
        for k in range(3):  # render at ~4 ms steps between buffers
            now = t + k * 0.0039
            universe = show.render(now)
            if fired is None and universe[20] == 255:  # GigBAR 1 white strobe at full (ch21)
                fired = now
        t += 512 / rate
    assert fired is not None
    assert abs(fired - drop_audible_at) < 0.015  # within 15 ms of the drop leaving the speakers


def test_master_at_zero_cuts_laser_and_derbies():
    eng = LooksEngine()
    eng.overrides.master = 0.0
    assert not emitting(render(eng, frame(70.0)))
