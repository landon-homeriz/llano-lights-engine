"""The arrival line-up check and open-space layouts (1.7.0, his recording 5:02 and 3:14).

Line-up: one GigBAR alone aims at a known spot (the middle of the dance floor, the booth,
straight down), head 1 red and head 2 blue; he nudges the bar's pan/tilt trim, or flips a bar
hung the other way round, until the heads land where the picture says, and saves it with the
venue. Open space: no walls or ceiling, so "ceiling" aims at the sky and nothing else changes.
"""
import math

from tools.gigbar_lights import __main__ as gl
from tools.gigbar_lights.looks import Frame, LooksEngine
from tools.gigbar_lights.rig import default_rig
from tools.gigbar_lights.show_script import Section
from tools.gigbar_lights.venue import HEAD_CLEAR, Layout, presets

DROP = Section("drop", 0, 64, 0.9)


def _lineup(lay, bar, spot):
    eng = LooksEngine()
    eng.apply_venue(lay)
    eng.overrides.lineup = (bar, spot)
    rig = default_rig()
    eng.render(Frame(8.5, 128.0, True, level=0.9, section=DROP), rig)
    return eng, rig


def _lands(lay, bar, m, head):
    """Where a head's beam meets the floor, from the pan/tilt the show sent (venue.beam)."""
    o = lay.heads(bar)[m]
    d = lay.beam(bar, o, head.pan, head.tilt)
    t = -o[2] / d[2]
    return o[0] + d[0] * t, o[1] + d[1] * t


def test_lineup_lights_only_the_chosen_bar_as_white_spots():
    lay = presets()["small-room-front"]
    eng, rig = _lineup(lay, 2, "center")
    assert eng.mode.startswith("line-up: GigBAR 2")
    lit, dark = rig.bars[1], rig.bars[0]
    assert [m.dim for m in lit.movers] == [1.0, 1.0]
    assert [(m.color, m.gobo) for m in lit.movers] == [(0, 0), (0, 0)]   # white, open (1.12.3)
    assert all(m.strobe == 0 for m in lit.movers) and lit.strobe_white == 0
    assert all(m.dim == 0 for m in dark.movers)
    assert all(fx.dim == 0 for fx in (*rig.tetras, *rig.sticks))
    assert all(p.dim == 0 for bar in rig.bars for p in bar.pars)


def test_both_heads_land_on_the_spot_they_are_aimed_at():
    lay = presets()["small-room-front"]
    for bar in (1, 2):
        _, rig = _lineup(lay, bar, "center")
        for m, head in enumerate(rig.bars[bar - 1].movers):
            x, y = _lands(lay, bar, m, head)
            assert math.hypot(x - lay.floor.cx, y - lay.floor.cy) < 0.15


def test_a_trim_moves_where_the_heads_point_and_a_flipped_bar_still_lands_on_the_spot():
    base = presets()["small-room-front"].to_dict()
    plain = Layout.from_dict(base)
    _, r0 = _lineup(plain, 1, "booth")
    trimmed = Layout.from_dict({**base, "fixtures": {**base["fixtures"], "bar1": {**base["fixtures"]["bar1"], "pan_trim": 10.0}}})
    _, r1 = _lineup(trimmed, 1, "booth")
    assert r1.bars[0].movers[0].pan != r0.bars[0].movers[0].pan
    flipped = Layout.from_dict({**base, "fixtures": {**base["fixtures"], "bar1": {**base["fixtures"]["bar1"], "pan_invert": True}}})
    _, rf = _lineup(flipped, 1, "center")
    for m, head in enumerate(rf.bars[0].movers):
        x, y = _lands(flipped, 1, m, head)
        assert math.hypot(x - flipped.floor.cx, y - flipped.floor.cy) < 0.15
    # a flip turns the other way: the same pan lands somewhere else
    assert rf.bars[0].movers[0].pan != _lineup(plain, 1, "center")[1].bars[0].movers[0].pan


def test_the_flip_and_open_space_save_with_the_venue_and_old_layouts_read_back_unchanged():
    old = presets()["small-room-front"].to_dict()
    assert "open" not in old and all("pan_invert" not in f for f in old["fixtures"].values())
    assert Layout.from_dict(old).to_dict() == old
    new = {**old, "open": True, "fixtures": {**old["fixtures"], "bar2": {**old["fixtures"]["bar2"], "pan_invert": True}}}
    back = Layout.from_dict(new)
    assert back.open and back.spots["bar2"].pan_invert and not back.spots["bar1"].pan_invert
    assert back.to_dict() == new


def test_open_space_aims_ceiling_over_the_heads_and_has_a_preset():
    # Hung heads can't reach a ceiling or the sky (1.10.1): "ceiling" is the far edge of the area
    # drawn, over the dancers' heads, in a room and outdoors alike.
    for name in ("open-space", "small-room-front"):
        lay = presets()[name]
        assert all(y == lay.room[1] and z == HEAD_CLEAR for _, y, z in lay.targets()["ceiling"])
    assert presets()["open-space"].open


def test_window_keys_start_and_end_the_lineup():
    class S:
        looks = LooksEngine()
    gl.handle_key("lineup:1:down", S)
    assert S.looks.overrides.lineup == (1, "down")
    gl.handle_key("lineup:3:down", S)   # no such bar: ends it rather than guess
    assert S.looks.overrides.lineup is None
    gl.handle_key("lineup:2:booth", S)
    gl.handle_key("lineup:", S)
    assert S.looks.overrides.lineup is None
