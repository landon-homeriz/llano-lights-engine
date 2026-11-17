"""Drops land with the music (Llano PM #23787, his report 2026-11-15: on I Gotta Feeling the drop lit a
second or two before the music).

Measured on his own video of it (20261115_202131.mp4) and his own file:

- The rig's speakers played 0.98 s after Mixxx's position (the on-screen clock against the song heard
  in the room), and the lights followed Mixxx's position exactly: an output delay nothing on the
  laptop can see (a Bluetooth link). rig.sync_ms is that delay, saved with the rig and set by tapping
  along to a click; every light waits for it.
- A cut Build the night makes (1.34.0) counted its 8-bar phrases from the cut's own first beat, which
  on I Gotta Feeling sat a bar before the song's phrases: every section and drop 1.875 s early. A cut
  now says where its original's 0:00 is, and its phrases are counted from there (show_script.phrase_phase).
"""
from __future__ import annotations

import json
import math

import pytest

from tools.gigbar_lights import settings_contract as contract
from tools.gigbar_lights import show_settings
from tools.gigbar_lights.beat_clock import TrackGrid
from tests.gigbar_lights.test_shows import lib, window  # noqa: F401

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")

from tools.gigbar_lights import set_cuts as sc  # noqa: E402
from tools.gigbar_lights import show_script as ss  # noqa: E402

RATE = 22050
BPM = 128.0
BEAT = 60.0 / BPM


def _song(intro_bars=48, drop_bars=32, first_beat_s=0.1):
    """A song whose quiet intro runs 48 bars (6 phrases) into a loud drop with a kick on every beat:
    the drop starts exactly at bar 48, on the grid that starts at its first beat."""
    n_beats = (intro_bars + drop_bars) * 4
    total = first_beat_s + n_beats * BEAT + 1.0
    t = np.arange(int(total * RATE)) / RATE
    x = 0.02 * np.sin(2 * np.pi * 440 * t)
    for k in range(n_beats):
        at = first_beat_s + k * BEAT
        loud = k >= intro_bars * 4
        i = int(at * RATE)
        n = int(0.12 * RATE)
        env = np.exp(-np.arange(n) / (0.03 * RATE))
        kick = np.sin(2 * np.pi * 55 * np.arange(n) / RATE) * env * (0.9 if loud else 0.05)
        x[i:i + n] += kick[: len(x) - i]
        if loud:
            x[i:i + n] += 0.3 * np.sin(2 * np.pi * 880 * np.arange(n) / RATE)[: len(x) - i] * env
    return x.astype(np.float32), first_beat_s + intro_bars * 4 * BEAT


def _mixxx_grid(first_sound_beat_s):
    """Mixxx's constant grid: its first beat slid to the earliest beat in the file."""
    return TrackGrid(samplerate=RATE, bpm=BPM, first_beat=math.fmod(first_sound_beat_s, BEAT) * RATE)


def _drop_start_s(script, grid):
    d = next(s for s in script.sections if s.kind == "drop")
    return grid.first_beat / RATE + d.start_beat * BEAT


def _cut(tmp_path, x, start_s, tag=True):
    """The cut set_cuts.render writes: the lead, then the song from start_s."""
    lead = int(sc.LEAD_S * RATE)
    body = x[int(start_s * RATE):]
    y = np.concatenate([np.full(lead, 0.001, dtype=np.float32), body])
    y = np.stack([y, y], axis=1)
    path = tmp_path / "cut.flac"
    sc.write(path, y, RATE, "Black Eyed Peas", "I Gotta Feeling", "A&J",
             zero_s=round(sc.LEAD_S - start_s, 3) if tag else None)
    return path


def test_the_original_song_keeps_its_phrases(tmp_path):
    x, drop_s = _song()
    p = tmp_path / "song.flac"
    sf.write(str(p), x, RATE)
    grid = _mixxx_grid(0.1)
    script = ss.analyze_track(p, grid)
    assert ss.source_zero_s(p) is None
    assert abs(_drop_start_s(script, grid) - drop_s) < 0.01


def test_a_cut_that_skips_part_of_a_phrase_still_drops_on_the_drop(tmp_path):
    x, drop_s = _song()
    # Build the night starts I Gotta Feeling 0.25 s before a downbeat 2 beats short of a phrase (29.21 s)
    start = 0.1 + (15 * 4 + 2) * BEAT - 0.25
    p = _cut(tmp_path, x, start)
    assert ss.source_zero_s(p) == pytest.approx(sc.LEAD_S - start, abs=0.001)
    first = sc.LEAD_S + 0.25          # the cut's first beat that is a beat of the song
    grid = _mixxx_grid(first)
    script = ss.analyze_track(p, grid)
    drop_in_source = _drop_start_s(script, grid) - sc.LEAD_S + start
    assert abs(drop_in_source - drop_s) < 0.01, f"drop {drop_in_source - drop_s:+.3f} s from the song's"


def test_an_untagged_cut_is_counted_from_its_own_first_beat_as_before(tmp_path):
    """The bug, kept as a fact: without the tag the phrases are a bar and a half off (the old cut files)."""
    x, drop_s = _song()
    start = 0.1 + (15 * 4 + 2) * BEAT - 0.25
    p = _cut(tmp_path, x, start, tag=False)
    grid = _mixxx_grid(sc.LEAD_S + 0.25)
    assert ss.phrase_phase(grid, ss.source_zero_s(p)) == 0


def test_phrase_phase_on_a_beat_map_and_garbage():
    g = TrackGrid(samplerate=RATE, beats=[(0.3 + k * BEAT) * RATE for k in range(200)])
    # the original's 0:00 sits 4 beats and a hair before the cut's 5th beat: phrases from beat 5... mod 32
    assert ss.phrase_phase(g, 0.3 + 5 * BEAT - 0.01) == 5
    assert ss.phrase_phase(g, -27.962) == 0     # before the map's first beat: from its first
    assert ss.phrase_phase(TrackGrid(samplerate=RATE, bpm=0.0), -3.0) == 0
    assert ss.phrase_phase(_mixxx_grid(1.25), None) == 0


def test_i_gotta_feeling_cut_counts_from_the_bar_mixxx_misses():
    """His file, by the numbers measured on it: 128 BPM, cut start 28.962 s with a 0.25 s fade, so the
    cut's first grid beat is 0.3125 s and its phrases now start 4 beats (one bar) later."""
    grid = TrackGrid(samplerate=44100, bpm=128.0, first_beat=0.3125 * 44100)
    assert ss.phrase_phase(grid, round(sc.LEAD_S - 28.962, 3)) == 4


def test_a_cuts_script_cached_by_the_old_analysis_is_worked_out_again(tmp_path):
    """A night's cut analyzed by 1.34 counted from the wrong bar: redone. Since version 3 (refine_drops, PM
    #23869) a whole song's older analysis is redone too, once, so the drop fix reaches every song; from then
    on it is kept."""
    x, _drop = _song(intro_bars=8, drop_bars=8)
    cut = _cut(tmp_path, x, 4.0)
    whole = tmp_path / "whole.flac"
    sf.write(str(whole), x, RATE)
    cache = ss.ScriptCache(tmp_path / "cache")
    old = ss.ShowScript([ss.Section("drop", 0, 32, 0.9)])            # version 1
    cache.put(7, old)
    cache.put(8, old)
    assert cache.get(7, cut) is None
    assert cache.get(8, whole) is None                              # pre-3 drops could sit early: redone
    now = ss.ShowScript([ss.Section("drop", 0, 32, 0.9)], ss.SCRIPT_VERSION)
    cache.put(8, now)
    assert cache.get(8, whole).sections == now.sections             # and then kept
    cache.put(7, ss.ShowScript([ss.Section("drop", 4, 36, 0.9)], ss.SCRIPT_VERSION))
    assert cache.get(7, cut).sections[0].start_beat == 4


def test_unreadable_or_foreign_comments_are_no_tag(tmp_path):
    p = tmp_path / "x.flac"
    with sf.SoundFile(str(p), "w", samplerate=RATE, channels=1, format="FLAC") as f:
        f.comment = "Llano cut: the original's 0:00 is at nan s"
        f.write(np.zeros(RATE, dtype=np.float32))
    assert ss.source_zero_s(p) is None
    with sf.SoundFile(str(p), "w", samplerate=RATE, channels=1, format="FLAC") as f:
        f.comment = "ripped by someone"
        f.write(np.zeros(RATE, dtype=np.float32))
    assert ss.source_zero_s(p) is None
    assert ss.source_zero_s(tmp_path / "missing.flac") is None


# --- Speaker sync -----------------------------------------------------------------------------------

def test_sync_is_a_rig_setting_clamped_to_three_seconds():
    assert contract.normalize({})["rig"]["sync_ms"] == 0
    for given, kept in ((980, 980), (-50, 0), (99999, 3000), (True, 0), ("980", 0), (float("nan"), 0), (979.6, 980)):
        assert contract.normalize({"rig": {"sync_ms": given}})["rig"]["sync_ms"] == kept, given
    doc, applied = contract.apply_ops({}, [{"path": "rig.sync_ms", "value": 980}])
    assert doc["rig"]["sync_ms"] == 980 and applied
    assert "rig.sync_ms" in contract.FIELDS


def test_the_lights_wait_for_the_speakers(monkeypatch):
    from tools.gigbar_lights import show as show_mod
    sh = show_mod.Show(latency_ms=23.0)
    old = show_settings.current()
    try:
        show_settings.set_current({"rig": {"sync_ms": 980}})
        assert sh.latency_ms == pytest.approx(1003.0)
        # the beat the lights show is the beat the room hears: 0.98 s more is 2.09 beats at 128 BPM
        sh.clock.free_run(128.0, 100.0, 50.0)
        assert sh.clock.beat_at(50.0, sh.latency_ms / 1000) == pytest.approx(100.0 - 1.003 * 128 / 60)
        monkeypatch.setenv("LLANO_LIGHTS_SYNC", "0")
        assert sh.latency_ms == pytest.approx(23.0)
    finally:
        show_settings.set_current(old)


def test_the_console_carries_the_sync_block_on_every_screen():
    from tests.gigbar_lights.test_part_mood import CONSOLE
    js = CONSOLE.read_text(encoding="utf-8")
    assert "rig.sync_ms" in js and 'data-act="sync-start"' in js
    # the phone can't play the click through the rig: grayed there, with the reason
    assert "Tap along on the laptop: the click has to come out of the rig's own speakers." in js


# The tap-along in a real browser: a fake AudioContext (no sound card on CI) whose clock starts at 0,
# so the high clicks go out at a known time; the taps are pressed 980 ms after each one, the way his
# Bluetooth speaker played them. One stray tap on a low click is dropped.
SYNC_MOUNT = """(st) => { window.OPS = []; window.CT = null;
  window.AudioContext = function () { window.CT = performance.now(); this.currentTime = 0; this.destination = {};
    const node = () => ({connect() {}, start() {}, stop() {}, frequency: {}, gain: {setValueAtTime() {}, linearRampToValueAtTime() {}, exponentialRampToValueAtTime() {}}});
    this.createOscillator = node; this.createGain = node; this.close = () => {}; };
  let doc = {rig: {sync_ms: 0, counts: {bars: 2, tetras: 6, sticks: 4}}, master: 1, strobe: {intensity: 1, speed: 1}, drop: {intensity: 1, burst: true},
             crowd_safe: true, section_palette: {}, palettes: {}};
  LlanoStudio.mount(document.getElementById("host"), {layout: "wide", screen: "laptop", pollMs: 200, keys: true,
    transport: {state: () => Promise.resolve(st), send: () => Promise.resolve({ok: true}), stop: () => Promise.resolve({ok: true}),
                settings: () => Promise.resolve({settings: doc}),
                change: (ops) => { OPS.push(ops); ops.forEach(o => { if (o.path === "rig.sync_ms") doc = Object.assign({}, doc, {rig: Object.assign({}, doc.rig, {sync_ms: o.value})}); });
                                   return Promise.resolve({ok: true, settings: doc}); }},
    caps: {}}); }"""


@pytest.mark.slow
def test_tapping_along_measures_the_speakers_and_saves_it(window):  # noqa: F811
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            from tests.gigbar_lights.test_part_mood import CONSOLE
            page = b.new_page(viewport={"width": 1366, "height": 900})
            page.set_content('<html><body style="margin:0"><div id="host" style="height:100vh"></div></body></html>')
            page.add_script_tag(content=CONSOLE.read_text(encoding="utf-8"))
            page.evaluate(SYNC_MOUNT, json.loads(json.dumps(window[0].studio_state())))
            page.wait_for_selector(".lls-step")
            page.locator('[data-panelbtn="levels"]').click()
            page.wait_for_selector('[data-act="sync-start"]')
            assert "Not set" in page.inner_text(".lls")
            page.locator('[data-act="sync-start"]').click()
            page.wait_for_selector('[data-act="sync-tap"]')
            # 7 taps 980 ms after each high click (the first high click goes out 400 ms after the start),
            # and one stray tap on a low click in between
            page.evaluate("""() => { const hi0 = CT + 400, tap = () => document.querySelector('[data-act="sync-tap"]').click();
              for (let k = 0; k < 7; k++) setTimeout(tap, hi0 + k * 2400 + 980 - performance.now());
              setTimeout(tap, hi0 + 2 * 2400 + 980 + 600 - performance.now()); }""")
            page.wait_for_selector("text=Your speakers play", timeout=25000)
            text = page.inner_text(".lls")
            ms = int(page.locator("[data-syncsave]").inner_text().split()[1])
            assert 950 <= ms <= 1010, text
            page.locator("[data-syncsave]").click()
            page.wait_for_function("OPS.length === 1")
            assert page.evaluate("OPS")[0] == [{"path": "rig.sync_ms", "value": ms}]
            page.wait_for_selector(f"text=The lights wait {ms} ms")
        finally:
            b.close()
