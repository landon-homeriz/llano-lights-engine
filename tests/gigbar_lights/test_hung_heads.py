"""The GigBAR's moving heads hang under the T-bar, base up (1.10.1).

Chauvet GigBAR MOVE manual Rev. 4, p. 8 (front panel drawing): both heads hang below the bar. A
yoke head hung like that points straight down at mid tilt and tilts 90 degrees either way to
level; it cannot point up. Until 1.10.1 venue.py, looks.py and the preview read tilt 0.5 as
level and 1 as straight up, so on the real lights every aim landed steeper than drawn and the
build's rise to "ceiling" swung the spots through straight down to the wall behind the bar.
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
from tools.gigbar_lights.venue import GUESS_TURN, HEAD_HOME, PAN_RANGE, HEAD_CLEAR, TILT_DOWN_AT_CENTER, presets  # noqa: E402

NAMED = ("home", "booth", "crowd", "fan", "cross", "ceiling", "sweep_left", "sweep_right", "center")


def ahead(lay, bar, d):
    """How far the beam runs out in front of the bar per unit length (its facing component)."""
    f = math.radians(lay.facing(f"bar{bar}"))
    return d[0] * math.sin(f) + d[1] * math.cos(f)


def test_mid_tilt_is_straight_down_and_full_tilt_is_level_toward_the_front():
    lay = presets()["small-room-front"]
    for bar, m, head in lay.all_heads():
        # pan 0.5 points along the bar (HEAD_HOME); the guess turns GUESS_TURN way as pan rises (1.31.1)
        front = 0.5 - HEAD_HOME[m] / (GUESS_TURN * PAN_RANGE)
        assert lay.beam(bar, head, front, TILT_DOWN_AT_CENTER) == pytest.approx((0.0, 0.0, -1.0), abs=1e-9)
        d = lay.beam(bar, head, front, 1.0)
        assert d[2] == pytest.approx(0.0, abs=1e-9) and ahead(lay, bar, d) == pytest.approx(1.0, abs=1e-9)
        # The other side of straight down is behind the bar, which no aim ever asks for.
        assert ahead(lay, bar, lay.beam(bar, head, front, 0.25)) < 0


def test_the_lineup_down_spot_is_mid_tilt():
    for lay in presets().values():
        assert all(t == pytest.approx(0.5) for _, t in lay.positions()["down"])


@pytest.mark.parametrize("name", list(presets()))
def test_every_named_position_lands_in_front_of_the_bar_and_never_above_level(name):
    lay = presets()[name]
    pos = lay.positions()
    for spot in NAMED:
        for (bar, _, head), (pan, tilt) in zip(lay.all_heads(), pos[spot]):
            assert TILT_DOWN_AT_CENTER < tilt <= 1.0, (spot, bar, tilt)
            d = lay.beam(bar, head, pan, tilt)
            assert ahead(lay, bar, d) > 0, (spot, bar)
            assert d[2] <= 1e-9, (spot, bar)


@pytest.mark.parametrize("name", list(presets()))
def test_ceiling_is_as_high_as_safe_over_the_dancers_heads(name):
    lay = presets()[name]
    for (bar, _, head), (pan, tilt) in zip(lay.all_heads(), lay.positions()["ceiling"]):
        d = lay.beam(bar, head, pan, tilt)
        assert d[2] < 0                           # never a level beam
        t = (lay.room[1] - head[1]) / d[1]        # where it reaches the back of the room
        assert head[2] + d[2] * t == pytest.approx(HEAD_CLEAR, abs=0.01)


def test_a_bar_hung_lower_than_head_clearance_aims_ceiling_at_the_far_floor():
    lay = presets()["small-room-front"]
    for b in ("bar1", "bar2"):
        lay.spots[b].z = 1.8
    fl = lay.floor
    assert all(y == fl.y + fl.d and z == 0.0 for _, y, z in lay.targets()["ceiling"])


def build_track(lay):
    """Every head's (tilt, beam) through the default show's first build (rise crowd -> ceiling)."""
    eng = LooksEngine(settings=contract.normalize({"crowd_safe": False}))
    if lay is not None:
        eng.apply_venue(lay)
    rig, secs, out = default_rig(), _sections(ss, SCRIPT), []
    build = next(s for s in secs if s.kind == "build")
    b = build.start_beat
    while b < build.end_beat - 1.0:            # the last beat before the drop is dark on purpose
        s, n = _at(secs, b)
        eng.render(Frame(b, 128.0, True, level=0.8, section=s, next_section=n, track_key=0), rig)
        out.append([m.tilt for bar in rig.bars for m in bar.movers])
        b += 0.25
    return out


@pytest.mark.parametrize("name", [None, *presets()])
def test_the_builds_rise_climbs_in_front_never_through_straight_down(name):
    lay = presets()[name] if name else None
    track = build_track(lay)
    for k in range(4):
        tilts = [frame[k] for frame in track]
        assert all(t > TILT_DOWN_AT_CENTER for t in tilts)
        assert all(b >= a - 1e-9 for a, b in zip(tilts, tilts[1:]))   # rising the whole way
        assert tilts[-1] - tilts[0] > 0.05


def test_without_a_layout_every_position_tilts_forward():
    for spot, heads in DEFAULT_POSITIONS.items():
        assert all(TILT_DOWN_AT_CENTER < t <= 1.0 for _, t in heads), spot
    assert DEFAULT_POSITIONS["ceiling"][0][1] > DEFAULT_POSITIONS["fan"][0][1] > DEFAULT_POSITIONS["crowd"][0][1]


@pytest.mark.parametrize("name", [None, "small-room-front"])
def test_a_figure_dipping_under_straight_down_holds_at_straight_down(name):
    # A big circle round the booth (just off straight down) would flick the beam behind the bar.
    secs = copy.deepcopy(contract.SECTION_DEFAULTS)
    for sec in secs.values():
        sec["move"] = {"shape": "circle", "from": "booth", "to": "booth", "size": 1.0, "beats": 4,
                       "spread": "parallel"}
    eng = LooksEngine(settings=contract.normalize({"sections": secs, "crowd_safe": False}))
    if name:
        eng.apply_venue(presets()[name])
        eng.positions["booth"] = [(p, 0.55) for p, _ in eng.positions["booth"]]   # a booth right under the bar
    rig, all_secs, low = default_rig(), _sections(ss, SCRIPT), []
    for i in range(64):
        b = 100.0 + i / 4
        s, n = _at(all_secs, b)
        eng.render(Frame(b, 128.0, True, level=0.8, section=s, next_section=n, track_key=0), rig)
        low.append(min(m.tilt for bar in rig.bars for m in bar.movers))
    assert min(low) == pytest.approx(TILT_DOWN_AT_CENTER, abs=1e-9)   # the circle reached it, held there
