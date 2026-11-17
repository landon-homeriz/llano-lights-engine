"""BL #12518: every song's build and drop need not be the same blue, UV, white-strobe, dark-beat, white-burst.

His 11-17 notes: "blue lights followed by purple strobe followed by white strobe followed by drop ... it can't
be the same thing on every song"; save the blue drop for one or two special moments; bar-to-bar color
splits only as a light accent. A song's drop cue (settings_contract DROP_STYLES) picks its recipe."""
from __future__ import annotations

import colorsys

import pytest

from tools.gigbar_lights import cues as cues_mod, settings_contract as contract
from tools.gigbar_lights.looks import Frame, LooksEngine
from tools.gigbar_lights.rig import default_rig
from tools.gigbar_lights.show_script import Section, ShowScript

SONG = ShowScript([Section("verse", 0, 32, 0.5), Section("build", 32, 64, 0.6),
                   Section("drop", 64, 96, 1.0), Section("main", 96, 128, 0.9)])
RED, BLUE = "#ff0000", "#0000ff"


def render(beat, style=None, color=RED, color2=""):
    section, nxt = SONG.at(beat)
    cs = () if style is None else ({"at": 0.0, "do": "drop", "style": style, "color": color,
                                    **({"color2": color2} if color2 else {})},)
    f = Frame(beat, 128.0, True, level=0.8, section=section, next_section=nxt, track_key=3,
              secs=beat * 60 / 128, cues=cs)
    rig = default_rig()
    LooksEngine().render(f, rig)
    return rig


def strobing(rig) -> bool:
    return any(b.strobe_white > 0 or b.strobe_uv > 0 for b in rig.bars)


def hue(fx) -> float:
    return colorsys.rgb_to_hsv(fx.red, fx.green, fx.blue)[0]


def test_the_contract_keeps_a_drop_cue_and_refuses_a_made_up_style():
    assert contract.cue({"at": 0, "do": "drop", "style": "slam", "color": "#FF2D95"}) == \
        {"at": 0.0, "do": "drop", "style": "slam", "color": "#ff2d95"}
    assert contract.cue({"at": 0, "do": "drop", "style": "lasers"}) is None
    assert contract.cue({"at": 0, "do": "drop", "style": "trade", "color": "red"}) == \
        {"at": 0.0, "do": "drop", "style": "trade"}


def test_drop_at_reads_the_last_cue_and_the_first_covers_the_song_before_it():
    cs = ({"at": 12.0, "do": "drop", "style": "slam", "color": RED},
          {"at": 180.0, "do": "drop", "style": "classic"})
    assert cues_mod.drop_at(cs, 3.0)[0] == "slam"
    assert cues_mod.drop_at(cs, 100.0)[0] == "slam"
    assert cues_mod.drop_at(cs, 181.0)[0] == "classic"     # the last chorus saved for the big one
    assert cues_mod.drop_at(cs, None)[0] == "slam"
    assert cues_mod.drop_at((), 5.0) == ("classic", "", "")


def test_a_song_with_no_drop_cue_plays_the_classic_recipe_exactly_as_before():
    late_build = render(60.5)
    assert strobing(late_build)                                  # the white strobe ramp
    assert all(t.dim == 0 for t in render(63.5).tetras)          # one dark beat
    assert render(64.2).bars[0].strobe_white == 1.0              # the white burst


@pytest.mark.parametrize("style", ["slam", "color-strobe", "sweep", "trade", "swell"])
def test_no_other_recipe_uses_the_uv_and_white_strobe_ramp_or_the_white_burst(style):
    for beat in (50.0, 56.5, 60.5, 62.25, 64.2, 64.7):
        assert not strobing(render(beat, style)), (style, beat)


@pytest.mark.parametrize("style", ["slam", "color-strobe", "sweep", "swell"])
def test_the_builds_and_drops_play_in_the_songs_color_not_the_blue_palette(style):
    for beat in (50.0, 70.0):
        r = render(beat, style, RED)
        assert any(abs(hue(t)) < 0.1 or abs(hue(t) - 1) < 0.1 for t in r.tetras if t.dim > 0.05), (style, beat)


def test_a_slam_goes_black_for_the_whole_last_bar_then_lands_full_in_color():
    assert any(t.dim > 0 for t in render(59.5, "slam").tetras)
    for beat in (60.1, 61.5, 63.9):
        r = render(beat, "slam")
        assert all(t.dim == 0 for t in r.tetras) and all(p.dim == 0 for b in r.bars for p in b.pars)
    r = render(64.3, "slam")
    assert all(t.dim == 1.0 and t.red == 1.0 and t.blue == 0.0 for t in r.tetras)
    assert all(m.dim == 1.0 for b in r.bars for m in b.movers)


def test_a_swell_never_goes_dark_before_the_drop():
    assert all(t.dim > 0.5 for t in render(63.7, "swell").tetras)


def test_a_color_strobe_chops_the_washes_in_color():
    on, off = render(60.05, "color-strobe"), render(60.18, "color-strobe")
    assert on.tetras[0].dim > 3 * off.tetras[0].dim
    assert on.tetras[0].red == 1.0 and on.tetras[0].blue == 0.0


def test_a_sweep_lights_the_rig_unevenly_and_moves():
    a, b = render(64.1, "sweep"), render(64.6, "sweep")
    da, db = [t.dim for t in a.tetras], [t.dim for t in b.tetras]
    assert max(da) - min(da) > 0.3 and da != db


def test_a_trade_swaps_two_colors_on_the_beat_and_splits_the_bars_only_as_an_accent():
    a, b = render(64.2, "trade", RED, BLUE), render(65.2, "trade", RED, BLUE)
    assert a.tetras[0].red == 1.0 and b.tetras[0].blue == 1.0
    split = [render(64 + x + 0.2, "trade", RED, BLUE) for x in range(16)]
    accents = [r for r in split if r.bars[0].pars[0].red != r.bars[1].pars[0].red]
    assert 1 <= len(accents) <= 2                                # one beat in eight, not the pattern


def test_the_six_recipes_look_different_from_each_other():
    def sig(style):
        out = []
        for beat in (44.0, 52.5, 58.25, 60.5, 62.1, 63.5, 64.1, 64.6, 66.2, 69.0):
            r = render(beat, None if style == "classic" else style, RED, BLUE if style == "trade" else "")
            out.append(tuple(round(x, 2) for x in (r.tetras[0].dim, r.tetras[-1].dim, r.tetras[0].red,
                                                   r.tetras[0].blue, r.bars[0].strobe_white)))
        return tuple(out)
    sigs = {s: sig(s) for s in contract.DROP_STYLES}
    assert len(set(sigs.values())) == len(contract.DROP_STYLES)


def _show(titles):
    return {"songs": [{"artist": "A", "title": "Slow", "part": "dancing", "moment": "first-dance"},
                      {"artist": "A", "title": "Dinner", "part": "dinner"},
                      *({"artist": "A", "title": t, "part": "dancing"} for t in titles)]}


def _cues(styles):
    return {contract.track_key("A", t): [{"at": 0.0, "do": "drop", "style": st, **({"color": c} if c else {})}]
            for t, (st, c) in styles.items()}


def test_the_drop_plan_skips_soft_songs_and_the_first_dance():
    from tools.gigbar_lights import shows
    plan = shows.drop_plan(_show(["One", "Two"]), _cues({"One": ("slam", RED)}))
    assert [(p["title"], p["style"]) for p in plan] == [("One", "slam"), ("Two", "classic")]


def test_the_duplicate_check_flags_neighbours_overuse_and_too_much_classic():
    from tools.gigbar_lights import shows
    ok = {"A1": ("slam", RED), "A2": ("trade", RED), "A3": ("slam", RED), "A4": ("sweep", BLUE)}
    assert shows.drop_repeats(shows.drop_plan(_show(list(ok)), _cues(ok))) == []
    bad = {**ok, "A5": ("slam", BLUE), "A6": ("slam", RED)}
    found = shows.drop_repeats(shows.drop_plan(_show(list(bad)), _cues(bad)))
    assert any("neighbours" in x and "A5" in x and "A6" in x for x in found)
    assert any("slam drop in #ff0000 plays on 3 songs" in x for x in found)
    classic = ["C1", "x", "C2", "y", "C3"]
    cs = _cues({"x": ("slam", RED), "y": ("swell", RED)})
    assert any("classic blue drop plays on 3" in x for x in shows.drop_repeats(shows.drop_plan(_show(classic), cs)))
