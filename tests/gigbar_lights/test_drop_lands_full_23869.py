"""A drop lands where the song reaches its full level, never earlier (Llano PM #23869).

His report 2026-11-17: on Justin Bieber's Sorry the drop fires early; the real one is at 1:08. Measured on
his file (100 BPM, first beat 0.55 s): the 8-bar phrase from 0:39 was labeled the drop because the loud
pre-chorus lifted it over the line; the chorus reaches full level at bar 28 (1:07.75), after a one-bar dip.
The bars below are Sorry's own normalized levels (loudness, bass) for bars 0..35.
"""
from tools.gigbar_lights import show_script as ss

SORRY = [(0, 0), (0, 0), (.04, 0), (0, .1), (.53, .68), (.36, .64), (.5, .68), (.21, .52), (.53, .69),
         (.33, .63), (.43, .67), (.38, .6), (.5, .67), (.38, .63), (.51, .68), (.4, .66), (.5, .68), (.41, .65),
         (.47, .65), (.44, .67), (.76, .78), (.73, .85), (.73, .78), (.83, .8), (.78, .78), (.86, .86), (.87, .9),
         (.6, .63), (.97, 1), (.9, 1), (.99, 1), (.98, .94), (1, 1), (.99, 1), (.83, .82), (.8, .82)]


def _labeled(bars):
    """label_phrases' sections before the refinement, and the normalized levels it hands over."""
    loud, bass = [b[0] for b in bars], [b[1] for b in bars]
    raw = ss.refine_drops
    try:
        ss.refine_drops = lambda s, e, b: s
        before = ss.label_phrases(loud, bass)
    finally:
        ss.refine_drops = raw
    return before, ss._normalize(loud), ss._normalize(bass)


def _copy(secs):
    return [ss.Section(s.kind, s.start_beat, s.end_beat, s.energy) for s in secs]


def test_sorry_drop_moves_to_the_chorus_bar():
    before, _, _ = _labeled(SORRY)
    assert [s.start_beat // 4 for s in before if s.kind == "drop"] == [16]   # 0:39, 29 s early
    after = ss.label_phrases([b[0] for b in SORRY], [b[1] for b in SORRY])
    drops = [s for s in after if s.kind == "drop"]
    assert [d.start_beat // 4 for d in drops] == [28]   # 0.55 + 28 * 2.4 = 67.75 s, his 1:08
    build = next(s for s in after if s.end_beat == drops[0].start_beat)
    assert build.kind == "build" and build.start_beat // 4 == 20   # the pre-chorus at 0:48.5 builds
    # every beat is still covered, in order, with no gaps
    assert after[0].start_beat == 0 and all(a.end_beat == b.start_beat for a, b in zip(after, after[1:]))


def test_a_drop_already_at_full_level_stays():
    bars = [(.2, .1)] * 8 + [(.5, .5)] * 8 + [(.95, .95)] * 16 + [(.2, .1)] * 8
    before, e, b = _labeled(bars)
    assert ss.refine_drops(_copy(before), e, b) == before


def test_a_drop_a_hair_under_the_line_is_not_moved():
    # I Gotta Feeling's second drop: its first bar a hair under the line, the stretch at full after it
    bars = [(.3, .3)] * 16 + [(.86, .86)] + [(.97, .97)] * 15
    before, e, b = _labeled(bars)
    assert [s.start_beat for s in ss.refine_drops(_copy(before), e, b) if s.kind == "drop"] == \
        [s.start_beat for s in before if s.kind == "drop"]


def test_a_drop_is_never_moved_earlier():
    after = ss.label_phrases([b[0] for b in SORRY], [b[1] for b in SORRY])
    before, _, _ = _labeled(SORRY)
    for d0, d1 in zip([s for s in before if s.kind == "drop"], [s for s in after if s.kind == "drop"]):
        assert d1.start_beat >= d0.start_beat


def test_old_scripts_are_worked_out_again(tmp_path):
    cache = ss.ScriptCache(tmp_path)
    cache.put(3, ss.ShowScript([ss.Section("drop", 0, 32, 0.9)], 2))
    assert cache.get(3) is None
    cache.put(3, ss.ShowScript([ss.Section("drop", 0, 32, 0.9)], ss.SCRIPT_VERSION))
    assert cache.get(3) is not None


def test_the_rollback_switch_gives_the_old_labels(monkeypatch):
    monkeypatch.setenv("LLANO_LIGHTS_DROP_REFINE", "0")
    after = ss.label_phrases([b[0] for b in SORRY], [b[1] for b in SORRY])
    assert [s.start_beat // 4 for s in after if s.kind == "drop"] == [16]
