"""The moving heads' color dots light their own color (Llano BL #12147).

His report on the real GigBAR Move heads, 2026-11-13, pressing each spot color dot: white -> white,
red -> dark blue, orange -> orange, yellow -> red, green -> light blue, blue -> yellow,
purple -> green, light blue/turquoise -> purple. The app sent slot i for the i-th dot of a guessed
rainbow wheel. These tests pin the wheel he saw and make every screen use it.
"""
import json
import re
from pathlib import Path

from tools.gigbar_lights import rig, stage_glow, studio

SRC = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"

# What each slot really showed on the units: (the slot the old dot sent, what he saw).
SEEN = {0: "White", 1: "Dark blue", 2: "Orange", 3: "Red", 4: "Light blue", 5: "Yellow", 6: "Green", 7: "Purple"}


def test_the_wheel_is_the_one_he_saw_on_the_real_heads():
    assert {i: n for i, (n, _hx) in enumerate(rig.HEAD_WHEEL)} == SEEN
    assert sorted(rig.HEAD_DOT_ORDER) == list(range(8))


def test_each_named_color_sends_its_own_slot_band():
    for name, slot, dmx_lo in (("white", 0, 0), ("dark blue", 1, 32), ("orange", 2, 64), ("red", 3, 96),
                               ("light blue", 4, 128), ("yellow", 5, 160), ("green", 6, 192), ("purple", 7, 224)):
        assert rig.head_slot(name) == slot
        m = rig.Mover(color=slot)
        v = m.channels()[4]
        assert dmx_lo <= v < dmx_lo + 32, (name, v)   # QLC+/Chauvet 35CH: 32-wide bands, slot 0 open


def _console_dots():
    js = (SRC / "studio_console.js").read_text(encoding="utf-8")
    body = re.search(r"var WHEEL = (\[\[.*?\]\]);", js, re.S).group(1)
    return [tuple(d) for d in json.loads(body)]


def test_every_dot_on_the_console_lands_on_the_color_it_is_named_and_painted():
    dots = _console_dots()
    assert [slot for _n, _hx, slot in dots] == list(rig.HEAD_DOT_ORDER)
    for name, hx, slot in dots:
        assert (name, hx) == rig.HEAD_WHEEL[slot], name
    # the press sends the dot's slot, never its place in the row (the 1.19 bug)
    js = (SRC / "studio_console.js").read_text(encoding="utf-8")
    assert 'cmdAttr({op: "spots", color: w[2]})' in js and "color: i}" not in js


def test_pressing_each_dot_puts_its_own_color_band_on_every_head(tmp_path):
    """End to end: the console's dot -> the studio command -> the frame the show sends."""
    import tools.gigbar_lights.__main__ as gl
    from tools.gigbar_lights import show_settings, venue
    from tools.gigbar_lights.show import Show
    show = Show(analyze=False, venue=next(iter(venue.presets().values())))
    show.studio = studio.Studio(path=tmp_path / "studio.json", live=True)
    show.studio.fade_s = 0.0
    feed = gl.FakeMixxx(show, 128.0, loop=True)
    try:
        show.studio.command({"op": "spots", "on": True})
        t = 1000.0
        for name, _hx, slot in _console_dots():
            show.studio.command({"op": "spots", "color": slot})
            for _ in range(4):
                t += 0.05
                feed(t)
                show.control_tick(t)
                show.render(t)
            for bar in show.rig.bars:
                for head in bar.movers:
                    assert rig.HEAD_WHEEL[(head.channels()[4] - 4) // 32][0] == name
    finally:
        show_settings.clear_play()
        show_settings.clear_scene()


def test_the_room_pictures_and_setup_list_draw_the_same_wheel():
    by_slot = [hx for _n, hx in rig.HEAD_WHEEL]
    assert ["#" + h for h in stage_glow.WHEEL] == by_slot
    html = (SRC / "preview.html").read_text(encoding="utf-8")
    assert json.loads(re.search(r"const WHEEL = (\[.*?\]);", html).group(1)) == by_slot
    app = (SRC / "app.html").read_text(encoding="utf-8")
    pairs = json.loads(re.search(r"head_color: (\[\[.*?\]\]),", app).group(1))
    assert [slot for slot, _n in pairs] == list(rig.HEAD_DOT_ORDER)
    for slot, label in pairs:
        assert label.startswith(rig.HEAD_WHEEL[slot][0]), (slot, label)
