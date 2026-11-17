"""Scene pads and crowd-safe strobe (1.6.0, Llano PM #22309).

A scene (calm, party, hype, party mode, a held white-out, blackout) plays over the show until
"back to the show"; one pressed in this window wins over one from Llano. Crowd-safe strobe keeps
every strobe channel at the slow end of its range, whatever a look, the strobe key or a drop asks.
"""
import time

from tools.gigbar_lights import __main__ as gl
from tools.gigbar_lights import looks, settings_contract as contract, show_settings
from tools.gigbar_lights.rig import default_rig
from tools.gigbar_lights.show_script import Section

DROP = Section("drop", 0, 64, 0.9)


def _render(scene=None, *, settings=None, section=DROP, beat=8.5, strobe_key=False):
    eng = looks.LooksEngine(settings=contract.normalize(settings or {}))
    eng.overrides.scene, eng.overrides.strobe = scene, strobe_key
    rig = default_rig()
    eng.render(looks.Frame(beat, 128.0, True, level=0.9, section=section), rig)
    return eng, rig


def _strobes(rig):
    out = [fx.strobe for fx in (*rig.tetras, *rig.sticks)]
    for bar in rig.bars:
        out += [p.strobe for p in bar.pars] + [m.strobe for m in bar.movers] + [d.strobe for d in bar.derbies]
        out.append(bar.strobe_speed)
    return out


def test_blackout_and_whiteout_scenes():
    eng, rig = _render("blackout")
    assert eng.mode == "scene:blackout"
    assert all(fx.dim == 0 for fx in (*rig.tetras, *rig.sticks))
    assert all(p.dim == 0 for bar in rig.bars for p in (*bar.pars, *bar.movers)) and all(b.strobe_white == 0 for b in rig.bars)
    eng, rig = _render("whiteout")
    assert eng.mode == "scene:whiteout"
    assert all(fx.dim == 1.0 and fx.red == fx.green == fx.blue == 1.0 for fx in (*rig.tetras, *rig.sticks))


def test_each_look_scene_plays_over_the_section_and_party_mode_steps_every_8_bars():
    for name in ("calm", "party", "hype"):
        eng, rig = _render(name)
        assert eng.mode == f"scene:{name}" and any(rig.render())
    _, calm = _render("calm")
    assert not any(bar.laser != "off" for bar in calm.bars)
    seen = set()
    for bar in range(0, 48, 8):
        eng, _ = _render("party-mode", beat=bar * 4 + 1)
        seen.add(eng.mode)
    assert len(seen) >= 3 and all(m.startswith("scene:party-mode:") for m in seen)


def test_a_window_scene_pressed_after_llanos_wins_and_a_lapsed_scene_is_the_show_again():
    try:
        show_settings.set_scene("calm", time.time() + 60)
        eng, _ = _render(None)
        assert eng.mode == "scene:calm"
        eng = looks.LooksEngine()
        gl.handle_key("scene:hype", type("S", (), {"looks": eng}))   # pressed in the window, after Llano's
        eng.render(looks.Frame(8.5, 128.0, True, level=0.8, section=DROP, track_key=1), default_rig())
        assert eng.mode == "scene:hype"
        assert show_settings.scene() is None   # Llano's older calm is over on this laptop
        show_settings.set_scene("calm", time.time() + 60)
        show_settings.set_scene("calm", time.time() - 1)
        eng, _ = _render(None)
        assert eng.mode.startswith("scripted:drop")
    finally:
        show_settings.clear_scene()


def test_crowd_safe_caps_every_strobe_even_the_strobe_key_and_off_lets_it_run():
    _, rig = _render(None, strobe_key=True)
    assert max(_strobes(rig)) <= contract.SAFE_STROBE_MAX and max(_strobes(rig)) > 0
    _, rig = _render(None, strobe_key=True, settings={"crowd_safe": False})
    assert max(_strobes(rig)) > contract.SAFE_STROBE_MAX


def test_window_keys_set_and_clear_a_scene():
    eng = looks.LooksEngine()

    class S:
        looks = eng

    gl.handle_key("scene:party", S)
    assert eng.overrides.scene == "party"
    gl.handle_key("scene:", S)
    assert eng.overrides.scene is None
    gl.handle_key("scene:disco", S)
    assert eng.overrides.scene is None


# --- the newest press wins, window or Llano (whole-app audit before the wedding, 2026-11-12) ------

class _Show:
    def __init__(self, eng):
        self.looks = eng


def _mode(eng):
    eng.render(looks.Frame(8.5, 128.0, True, level=0.8, section=DROP, track_key=1), default_rig())
    return eng.mode


def test_back_to_the_show_in_the_window_never_brings_back_an_old_phone_pad():
    """Party pressed on the phone, calm in the window, then Back to the show in the window: the room
    used to go back to the phone's party, which could linger all night."""
    show_settings.clear_scene()
    eng = looks.LooksEngine()
    show_settings.set_scene("party", time.time() + 3600)
    assert _mode(eng) == "scene:party"
    gl.handle_key("scene:calm", _Show(eng))
    assert _mode(eng) == "scene:calm"
    gl.handle_key("scene:", _Show(eng))
    assert show_settings.scene() is None
    assert not _mode(eng).startswith("scene:")


def test_a_phone_pad_pressed_after_the_window_pad_plays_and_back_to_the_show_ends_both():
    """Calm in the window, then party on llano.app: party used to do nothing at all."""
    show_settings.clear_scene()
    eng = looks.LooksEngine()
    gl.handle_key("scene:calm", _Show(eng))
    show_settings.set_scene("party", time.time() + 3600)
    assert _mode(eng) == "scene:party"
    show_settings.clear_scene()   # Back to the show on the phone
    assert not _mode(eng).startswith("scene:")   # never the window's older calm


def test_a_held_white_out_from_the_phone_covers_the_window_pad_only_while_held():
    show_settings.clear_scene()
    eng = looks.LooksEngine()
    gl.handle_key("scene:calm", _Show(eng))
    show_settings.set_scene("whiteout", time.time() + 8)
    assert _mode(eng) == "scene:whiteout"
    show_settings.clear_scene()   # let go
    assert _mode(eng) == "scene:calm"


def test_picking_a_moment_in_the_window_ends_a_phone_pad():
    """pick_moment sends "scene:" so the moment is not hidden; a phone pad must not hide it either."""
    show_settings.clear_scene()
    eng = looks.LooksEngine()
    show_settings.set_scene("hype", time.time() + 3600)
    gl.handle_key("scene:", _Show(eng))
    assert not _mode(eng).startswith("scene:")
