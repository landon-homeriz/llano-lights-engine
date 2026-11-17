"""1.4.0: the show described on llano.app/lights, played by the looks engine.

Per section: wash/mover levels, pulse depth, strobe, derby and laser, bars per color change,
and the move (shape, from, to, size, beats, spread) over named positions a venue re-aims.
Per song: a track filed under a saved style plays it. A draft Llano asked to play wins over
both until it runs out. The intro/verse/breakdown/outro palette and saturation pickers work.
"""
import copy
import math
import time

import pytest

from tools.gigbar_lights import settings_contract as contract, show_settings
from tools.gigbar_lights.looks import Frame, LooksEngine
from tools.gigbar_lights.mixxx_db import TrackInfo
from tools.gigbar_lights.rig import default_rig
from tools.gigbar_lights.show import DeckTrack
from tools.gigbar_lights.show_script import Section
from tools.gigbar_lights.venue import presets

SONG = [Section("intro", 0, 96, 0.2), Section("verse", 96, 160, 0.5), Section("build", 160, 192, 0.5),
        Section("drop", 192, 256, 0.9), Section("main", 256, 320, 0.9), Section("breakdown", 320, 352, 0.3),
        Section("outro", 352, 384, 0.2)]
START = {s.kind: s.start_beat for s in reversed(SONG)}


@pytest.fixture(autouse=True)
def _no_draft():
    show_settings.clear_play()
    yield
    show_settings.clear_play()


def cfg(sections=None, **top):
    """A settings doc with some sections changed: sections={"verse": {"wash": 0.5}}."""
    d = contract.defaults()
    for kind, change in (sections or {}).items():
        mv = change.pop("move", None)
        d["sections"][kind].update(change)
        if mv:
            d["sections"][kind]["move"].update(mv)
    d.update(top)
    return contract.normalize(d)


def frame(beat, song="", level=0.8, playing=True, loop_beats=0.0):
    sec = next((s for s in SONG if s.start_beat <= beat < s.end_beat), None)
    nxt = SONG[SONG.index(sec) + 1] if sec and SONG.index(sec) + 1 < len(SONG) else None
    return Frame(beat, 128.0, playing, level=level, loop_beats=loop_beats, section=sec, next_section=nxt,
                 track_key=3, song=song)


def render(settings, beat, eng=None, **kw):
    eng = eng or LooksEngine(settings=settings)
    rig = default_rig()
    eng.render(frame(beat, **kw), rig)
    return rig


def heads(rig):
    return [(round(h.pan, 6), round(h.tilt, 6)) for bar in rig.bars for h in bar.movers]


def move(kind, **mv):
    return cfg({kind: {"move": mv}})


P = {k: v for k, v in LooksEngine().positions.items()}   # the default named positions


# --- levels -----------------------------------------------------------------------------------

def test_wash_and_mover_levels_scale_the_built_in_look():
    b = START["verse"] + 4.3
    full, half = render(cfg(), b), render(cfg({"verse": {"wash": 0.5, "movers": 0.0}}), b)
    assert half.tetras[0].dim == pytest.approx(full.tetras[0].dim * 0.5)
    assert half.sticks[0].dim == pytest.approx(full.sticks[0].dim * 0.5)
    assert all(m.dim == 0 for bar in half.bars for m in bar.movers)
    assert all(m.dim > 0 for bar in full.bars for m in bar.movers)


def test_pulse_zero_is_steady_and_one_is_the_built_in_pulse():
    beats = [START["drop"] + 8 + x / 8 for x in range(8)]   # a whole beat, past the burst
    steady = {round(render(cfg({"drop": {"pulse": 0.0}}), b).tetras[0].dim, 6) for b in beats}
    built = {round(render(cfg(), b).tetras[0].dim, 6) for b in beats}
    assert len(steady) == 1 and len(built) > 4
    half = [render(cfg({"drop": {"pulse": 0.5}}), b).tetras[0].dim for b in beats]
    assert max(half) - min(half) == pytest.approx((max(map(float, built)) - min(map(float, built))) / 2, rel=0.05)


def test_section_strobe_scales_the_burst_and_the_build_ramp():
    burst = START["drop"] + 0.1
    assert render(cfg(), burst).bars[0].strobe_white == 1.0
    assert render(cfg({"drop": {"strobe": 0.0}}), burst).bars[0].strobe_white == 0.0
    ramp = START["build"] + 29.0      # last quarter of the build, on the hit
    full = render(cfg(), ramp).bars[0].strobe_white
    assert full > 0 and render(cfg({"build": {"strobe": 0.5}}), ramp).bars[0].strobe_white == pytest.approx(full / 2)


# --- derby and laser ---------------------------------------------------------------------------

def test_derby_and_laser_switch_per_section():
    v = START["verse"] + 3
    assert render(cfg(), v).bars[0].derbies[0].color == "white"
    assert render(cfg({"verse": {"derby": False}}), v).bars[0].derbies[0].color == "off"
    i = START["intro"] + 3
    assert render(cfg(), i).bars[0].derbies[0].color == "off"
    assert render(cfg({"intro": {"derby": True}}), i).bars[0].derbies[0].color == "white"
    d = START["drop"] + 5
    assert render(cfg(), d).bars[0].laser == "both"
    off = render(cfg({"drop": {"laser": False}}), d).bars[0]
    assert off.laser == "off" and off.laser_rotate == 0
    assert render(cfg({"breakdown": {"laser": True}}), START["breakdown"] + 2).bars[0].laser == "green"


# --- color timing ------------------------------------------------------------------------------

def hue_at(settings, beat):
    t = render(settings, beat).tetras[0]
    return (round(t.red, 4), round(t.green, 4), round(t.blue, 4))


def test_color_bars_sets_how_often_the_palette_steps():
    d = START["drop"]
    once = cfg({"drop": {"color_bars": 0}})
    assert len({hue_at(once, d + 2 + 8 * k) for k in range(7)}) == 1
    every2 = cfg({"drop": {"color_bars": 2}})
    assert len({hue_at(every2, d + 2 + 8 * k) for k in range(7)}) > 1
    v = START["verse"]
    assert hue_at(cfg({"verse": {"color_bars": 2}}), v + 2) != hue_at(cfg({"verse": {"color_bars": 2}}), v + 10)
    assert hue_at(cfg({"verse": {"color_bars": 0}}), v + 2) == hue_at(cfg({"verse": {"color_bars": 0}}), v + 50)


def test_intro_verse_breakdown_outro_palette_and_saturation_pickers_work():
    """1.3.x read the built-in palettes for these sections, so the page's pickers did nothing."""
    for kind in ("intro", "verse", "breakdown", "outro"):
        b = START[kind] + 2
        plain = render(cfg(), b).tetras[0]
        mono = cfg(palettes={"mono": [[0.33, 0.33]]}, section_palette={kind: "mono"})
        green = render(mono, b).tetras[0]
        assert (green.red, green.green, green.blue) == pytest.approx((0.0, 1.0, 0.0), abs=0.05), kind
        pale = render(cfg(saturation={kind: 0.3}), b).tetras[0]
        assert min(pale.red, pale.green, pale.blue) > min(plain.red, plain.green, plain.blue), kind


# --- moves -------------------------------------------------------------------------------------

def test_hold_sits_at_from():
    s = move("verse", shape="hold", **{"from": "ceiling"})
    for b in (100.0, 113.7, 140.2):
        assert heads(render(s, b)) == [P["ceiling"][k % 2] for k in range(4)]


def test_glide_eases_from_to_and_back():
    s = move("verse", shape="glide", **{"from": "booth", "to": "crowd"}, beats=8)
    assert heads(render(s, 96.0)) == [P["booth"][k % 2] for k in range(4)]       # 96 = 12 passes of 8
    assert heads(render(s, 104.0)) == [P["crowd"][k % 2] for k in range(4)]
    mid = heads(render(s, 100.0))[0]
    assert P["booth"][0][1] < mid[1] < P["crowd"][0][1]


def test_snap_jumps_every_beats():
    s = move("verse", shape="snap", **{"from": "fan", "to": "cross"}, beats=2)
    assert heads(render(s, 96.5)) == [P["fan"][k % 2] for k in range(4)]
    assert heads(render(s, 98.5)) == [P["cross"][k % 2] for k in range(4)]
    assert heads(render(s, 100.5)) == [P["fan"][k % 2] for k in range(4)]


def test_sweep_swings_through_the_middle():
    s = move("verse", shape="sweep", **{"from": "fan", "to": "cross"}, beats=16)
    centre = heads(render(s, 96.0))[0]           # sin(96/16*pi) = 0: mix 0.5
    assert centre[0] == pytest.approx((P["fan"][0][0] + P["cross"][0][0]) / 2, abs=1e-6)
    assert heads(render(s, 104.0))[0][0] == pytest.approx(P["cross"][0][0], abs=1e-6)   # sin = 1


def test_rise_follows_the_sections_progress():
    s = move("breakdown", shape="rise", **{"from": "crowd", "to": "ceiling"})
    first, last = heads(render(s, 320.0))[0], heads(render(s, 351.9))[0]
    assert first == P["crowd"][0] and last[1] == pytest.approx(P["ceiling"][0][1], abs=0.01)


@pytest.mark.parametrize("shape", ["circle", "eight", "line"])
def test_figures_loop_around_from_once_per_beats(shape):
    s = move("verse", shape=shape, **{"from": "home"}, size=0.8, beats=4)
    track = [heads(render(s, 100.0 + x / 4))[0] for x in range(16)]
    assert heads(render(s, 104.0))[0] == pytest.approx(track[0], abs=1e-6)    # one loop per 4 beats
    pans, tilts = [p for p, _ in track], [t for _, t in track]
    r = 0.8 * 0.25
    # The same angle both ways (1.9.0): pan spans 540 degrees to tilt's 180.
    assert (max(pans) - min(pans)) * 540 == pytest.approx(2 * r * 180, abs=2)
    if shape == "line":
        assert len(set(tilts)) == 1
    else:
        assert max(tilts) - min(tilts) == pytest.approx(2 * r, abs=0.01)
    if shape == "eight":   # the tilt goes round twice per pan swing
        off = [heads(render(s, 100.1 + x / 4))[0][1] for x in range(16)]   # off the zero points
        mid = P["home"][0][1]
        crossings = sum(1 for a, b in zip(off, off[1:] + off[:1]) if (a - mid) * (b - mid) < 0)
        assert crossings == 4


def test_figures_stay_inside_the_pan_tilt_range():
    s = move("verse", shape="circle", **{"from": "ceiling"}, size=1.0, beats=4)
    for x in range(16):
        for pan, tilt in heads(render(s, 100.0 + x / 4)):
            assert 0.0 <= pan <= 1.0 and 0.0 <= tilt <= 1.0


def test_spread_parallel_mirror_serial():
    base = {"shape": "circle", "from": "home", "size": 0.6, "beats": 8}
    par = heads(render(move("verse", **base, spread="parallel"), 101.0))
    assert par[0] == par[1] == par[2] == par[3]
    mir = heads(render(move("verse", **base, spread="mirror"), 101.0))
    assert mir[1] == pytest.approx((1 - mir[0][0], mir[0][1])) and mir[0] == par[0]
    ser = heads(render(move("verse", **base, spread="serial"), 101.0))
    assert ser[0] == par[0] and len(set(ser)) == 4
    # head 2 of 4 runs half a loop behind: 101 - 4 beats on the parallel track
    assert ser[2] == pytest.approx(heads(render(move("verse", **base, spread="parallel"), 97.0))[0], abs=1e-6)


def test_a_venue_layout_re_aims_the_named_positions():
    lay = next(iter(presets().values()))
    s = move("verse", shape="hold", **{"from": "crowd"})
    eng = LooksEngine(settings=s)
    eng.apply_venue(lay)
    got = heads(render(s, 120.0, eng=eng))
    want = [(round(p, 6), round(t, 6)) for p, t in lay.positions()["crowd"]]
    assert got == [want[k % len(want)] for k in range(4)]


def test_a_held_long_intro_grooves_like_the_verse_but_a_moving_one_keeps_its_move():
    late = 80.0                                   # past 16 bars of the intro
    groove = heads(render(cfg(), late))
    assert groove == heads(render(cfg(), late))
    assert groove != [P["booth"][k % 2] for k in range(4)]
    assert render(cfg(), late).bars[0].derbies[0].color == "white"
    circling = move("intro", shape="circle", **{"from": "booth"}, beats=8)
    early, late_c = heads(render(circling, 8.0)), heads(render(circling, 72.0))
    assert early == late_c        # same phase of the same circle, 64 beats apart


# --- per song and the draft --------------------------------------------------------------------

def styled():
    d = contract.defaults()
    calm = contract.normalize_style({"sections": {"drop": {"laser": False, "wash": 0.3}},
                                     "palettes": {"mono": [[0.62, 0.62]]},
                                     "section_palette": {"drop": "mono"}, "note": "low key"})
    d["styles"] = {"low-key": calm}
    d["songs"] = {contract.track_key("Fisher", "Losing It"): "low-key"}
    return contract.normalize(d)


def test_a_song_filed_under_a_style_plays_it_offline_and_others_play_the_saved_show():
    s = styled()
    eng = LooksEngine(settings=s)
    b = START["drop"] + 5
    rig = render(s, b, eng=eng, song="fisher-losing-it")
    assert rig.bars[0].laser == "off" and eng.showing == "style:low-key"
    assert rig.tetras[0].blue == pytest.approx(1.0) and rig.tetras[0].red == pytest.approx(0.0, abs=0.05)
    other = render(s, b, eng=eng, song="someone-else-tune")
    assert other.bars[0].laser == "both" and eng.showing == ""
    assert render(s, b, eng=eng).bars[0].laser == "both"
    # master, layouts and autoloops stay the saved show's
    assert eng.show_for(s, "fisher-losing-it")[0]["master"] == s["master"]


def test_the_song_key_comes_from_mixxx_artist_and_title():
    t = DeckTrack(serial=1, info=TrackInfo(9, "FISHER", "Losing It (Original Mix)", None))
    assert t.song == "fisher-losing-it-original-mix" == contract.track_key("FISHER", "Losing It (Original Mix)")
    assert DeckTrack(serial=2).song == ""


def test_a_draft_wins_until_it_runs_out_then_the_saved_show_is_back():
    s = styled()
    eng = LooksEngine(settings=s)
    b = START["drop"] + 5
    show_settings.set_play({"sections": {"drop": {"laser": False, "derby": False}}}, time.time() + 60)
    rig = render(s, b, eng=eng, song="fisher-losing-it")
    assert eng.showing == "draft" and rig.bars[0].laser == "off" and rig.bars[0].derbies[0].color == "off"
    assert rig.tetras[0].dim > 0.3               # the draft's drop, not the song style's dimmed one
    show_settings.set_play({"sections": {"drop": {"laser": False}}}, time.time() - 1)
    assert render(s, b, eng=eng).bars[0].laser == "both" and eng.showing == ""
    show_settings.clear_play()
    assert render(s, b, eng=eng, song="fisher-losing-it").bars[0].laser == "off"
    assert eng.showing == "style:low-key"


def test_the_show_merge_is_cached_until_the_settings_change():
    s = styled()
    eng = LooksEngine(settings=s)
    a, _ = eng.show_for(s, "fisher-losing-it")
    assert eng.show_for(s, "fisher-losing-it")[0] is a
    s2 = copy.deepcopy(s)
    assert eng.show_for(s2, "fisher-losing-it")[0] is not a


def test_mirror_runs_each_right_head_between_its_own_spots_under_a_venue():
    """1.9.0: flipping the left head's change around the right head's spot sent the right head
    the wrong way when a venue aims both heads the same way (his report: spots pointed backwards)."""
    s = move("verse", shape="glide", **{"from": "crowd", "to": "fan"}, beats=8, spread="mirror")
    eng = LooksEngine(settings=s)
    eng.positions = {**eng.positions, "crowd": [(0.30, 0.6), (0.80, 0.6)]}   # an off-centre bar
    h = heads(render(s, 98.0, eng=eng))
    par = heads(render(move("verse", shape="glide", **{"from": "crowd", "to": "fan"}, beats=8), 98.0, eng=eng))
    assert h[0] == par[0] and h[1] == pytest.approx(par[1], abs=1e-6)   # a glide: its own path
    end = heads(render(s, 104.0, eng=eng))                               # 8 beats in: at "fan"
    assert end[1] == pytest.approx(P["fan"][1], abs=1e-6)
    hs = move("verse", shape="hold", **{"from": "crowd"}, spread="mirror")
    still = LooksEngine(settings=hs)
    still.positions = eng.positions
    hold = heads(render(hs, 98.0, eng=still))
    assert hold[1] == pytest.approx((0.8, 0.6), abs=1e-6)   # at rest each head sits on its own spot


def test_loop_auto_strobe_keeps_the_sections_strobe_but_the_button_does_not():
    s = cfg({"breakdown": {"strobe": 0.0}})
    b = START["breakdown"] + 2
    assert render(s, b, loop_beats=0.25).bars[0].strobe_white == 0.0
    eng = LooksEngine(settings=s)
    eng.overrides.strobe = True
    assert render(s, b, eng=eng).bars[0].strobe_white == 1.0


# --- a song's look plays even before its sections are known (whole-app audit, 2026-11-12) ---------

@pytest.mark.parametrize("look", ["slow-dance", "warm-up", "groove", "peak", "sing-along"])
def test_a_song_with_a_look_and_no_sections_plays_its_look_never_the_autoloops(look):
    """A first dance tied to slow-dance that Mixxx had not analyzed played chase and rainbow."""
    show_settings.set_show_looks({"perfect": look})
    try:
        eng = LooksEngine(settings=cfg())
        for i in range(0, 400, 3):
            eng.render(Frame(i / 2, 70.0, True, level=0.6, track_key=1, song="perfect", song_keys=("perfect",)),
                       default_rig())
            # its own look, never the autoloops (a one-look-everywhere look holds as held:main, BL #12095)
            assert eng.mode in ("look:verse", "held:main") and eng.showing == f"show:{look}", (i, eng.mode)
        eng.render(Frame(10.0, 70.0, True, level=0.6, track_key=2, song="other", song_keys=("other",)), default_rig())
        assert eng.mode.startswith("autoloop:")   # the house show with no sections keeps its autoloops
        eng.overrides.autoloop_override = True    # and the autoloop key still means autoloops
        eng.render(Frame(10.0, 70.0, True, level=0.6, track_key=1, song="perfect", song_keys=("perfect",)), default_rig())
        assert eng.mode.startswith("autoloop:")
    finally:
        show_settings.set_show_looks(None)
