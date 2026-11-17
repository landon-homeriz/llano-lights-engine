"""Both GigBARs' spots face the dance floor, never the wall behind the bar (1.9.0).

The report, 2026-11-08: the right-side GigBAR spots pointed backwards.
The show glides from the booth to the crowd with the mirror spread. The mirror flipped the
left head's change around the right head's own spot, so with a room layout head 2 of each bar
turned ~145 degrees round. Every look, scene, move shape and spread is played here through
every preset and checked against each bar's facing.
"""
import copy
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from show_frames import SCRIPT, _at, _sections  # noqa: E402

from tools.gigbar_lights import settings_contract as contract  # noqa: E402
from tools.gigbar_lights import show_script as ss  # noqa: E402
from tools.gigbar_lights.looks import DEFAULT_POSITIONS, Frame, LooksEngine  # noqa: E402
from tools.gigbar_lights.rig import default_rig  # noqa: E402
from tools.gigbar_lights.venue import HEAD_HOME, FORWARD_MAX, PAN_RANGE, Layout, _bar_turn, presets  # noqa: E402

POSITIONS = ("home", "booth", "crowd", "fan", "ceiling", "cross")
SHAPES = ("hold", "glide", "snap", "sweep", "rise", "circle", "eight", "line")


def off_facing(lay, bar, pan, m):
    """Degrees head m's beam turns off the bar's facing: its home heading along the bar
    (venue.HEAD_HOME), trims and a flip included."""
    s = lay.spots[f"bar{bar}"]
    turn = (pan - 0.5) * PAN_RANGE
    return (s.pan_trim + HEAD_HOME[m] + _bar_turn(s) * turn + 180.0) % 360.0 - 180.0   # the fixture's turn (1.31.1)


def worst(lay, raw, scene=None, scripted=True):
    eng = LooksEngine(settings=contract.normalize({**raw, "crowd_safe": False}))
    eng.apply_venue(lay)
    eng.overrides.scene = scene
    rig, secs, out = default_rig(), _sections(ss, SCRIPT), {}
    b = 0.0
    while b < (SCRIPT[-1][2] if scripted else 160):
        s, n = _at(secs, b) if scripted else (None, None)
        eng.render(Frame(b, 128.0, True, level=0.8, section=s, next_section=n, track_key=0), rig)
        for i, bar in enumerate(rig.bars):
            for h, m in enumerate(bar.movers):
                if m.dim > 0:
                    k = f"bar{i + 1} head{h + 1}"
                    out[k] = max(out.get(k, 0.0), abs(off_facing(lay, i + 1, m.pan, h)))
        b += 0.5
    return out


def his_show(spread="mirror", shape="glide", a="booth", b="crowd", size=0.5):
    secs = copy.deepcopy(contract.SECTION_DEFAULTS)
    for sec in secs.values():
        sec["move"] = {"shape": shape, "from": a, "to": b, "size": size, "beats": 32, "spread": spread}
    return {"sections": secs}


def test_his_show_aims_head_2_of_each_bar_as_far_forward_as_head_1():
    lay = presets()["small-room-front"]
    w = worst(lay, his_show())
    assert max(w.values()) < 80, w                       # was 146 degrees on head 2 of each bar
    assert w["bar1 head2"] == pytest.approx(w["bar2 head1"], abs=1)   # the two bars mirror each other
    assert w["bar1 head1"] == pytest.approx(w["bar2 head2"], abs=1)


def test_a_mirrored_head_lands_on_its_own_target():
    lay = presets()["small-room-front"]
    eng = LooksEngine(settings=contract.normalize(his_show()))
    eng.apply_venue(lay)
    # a glide of 32 beats from the booth reaches the crowd at beat 32 of the verse
    verse = ss.Section("verse", 0, 64, 0.8)
    rig = eng.render(Frame(32.0, 128.0, True, level=0.8, section=verse, track_key=0), default_rig())
    got = [(round(m.pan, 4), round(m.tilt, 4)) for bar in rig.bars for m in bar.movers]
    assert got == [(round(p, 4), round(t, 4)) for p, t in lay.positions()["crowd"]]


@pytest.mark.parametrize("name", list(presets()))
def test_every_named_position_aims_in_front_of_both_bars(name):
    lay = presets()[name]
    heads = lay.all_heads()
    for pos in POSITIONS:
        for (bar, m, _), (pan, _tilt) in zip(heads, lay.positions()[pos]):
            assert abs(off_facing(lay, bar, pan, m)) <= FORWARD_MAX, (name, pos, bar)


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("spread", ("parallel", "mirror", "serial"))
def test_no_move_turns_a_head_behind_its_bar(shape, spread):
    for lay in presets().values():
        for a, b in (("booth", "crowd"), ("crowd", "fan"), ("cross", "fan"), ("crowd", "ceiling")):
            w = worst(lay, his_show(spread, shape, a, b, size=1.0))
            assert max(w.values()) <= FORWARD_MAX + 1e-6, (lay.name, shape, spread, a, b, w)


@pytest.mark.parametrize("scene", (None, "calm", "party", "hype", "party-mode"))
def test_the_default_show_scenes_and_autoloops_face_forward(scene):
    for lay in presets().values():
        assert max(worst(lay, {}, scene).values()) <= FORWARD_MAX
        assert max(worst(lay, {}, scene, scripted=False).values()) <= FORWARD_MAX


def test_the_guard_respects_a_bar_trimmed_round_at_the_line_up_check():
    d = presets()["small-room-front"].to_dict()
    d["fixtures"]["bar2"]["pan_trim"] = 180.0          # its middle position faced the wall
    d["fixtures"]["bar2"]["pan_invert"] = True
    lay = Layout.from_dict(d)
    for pos in POSITIONS:
        for (bar, m, _), (pan, _t) in zip(lay.all_heads(), lay.positions()[pos]):
            assert lay.forward(bar, pan, m) == pytest.approx(pan)   # an aim in front is left alone
    assert max(worst(lay, his_show()).values()) < 80


def test_without_a_layout_the_mirror_still_mirrors_the_left_head():
    """No venue: the positions are mirror images, so the new mirror is the old one exactly."""
    for pos in POSITIONS:
        (lp, lt), (rp, rt) = DEFAULT_POSITIONS[pos]
        assert lp + rp == pytest.approx(1.0) and lt == rt


@pytest.mark.parametrize("name", list(presets()))
def test_booth_lights_the_dj_from_the_dance_floor_side(name):
    """The booth sits level with the bars that flank it; aiming at its middle ran the spots
    sideways along the wall behind the bars. "booth" now aims just in front of it."""
    lay = presets()[name]
    for t in lay.targets()["booth"]:
        assert t[1] > lay.booth.y + lay.booth.d and lay.booth.x <= t[0] <= lay.booth.x + lay.booth.w
    for (bar, m, _), (pan, _t) in zip(lay.all_heads(), lay.positions()["booth"]):
        assert abs(off_facing(lay, bar, pan, m)) < 60, (name, bar)
