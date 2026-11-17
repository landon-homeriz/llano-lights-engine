"""Spotlight moves (1.16.0, Llano PM #22505): every head on one spot that roams the floor, so the
four beams read as one spotlight, or one spot per GigBAR (spotlights), mirrored across the floor.
They aim through the venue, so after Line up my lights they land together on the real floor."""
import math

import pytest

from tools.gigbar_lights import settings_contract as contract
from tools.gigbar_lights.looks import Frame, LooksEngine
from tools.gigbar_lights.rig import default_rig
from tools.gigbar_lights.show_script import Section
from tools.gigbar_lights.venue import presets


def _engine(spread, shape="circle", venue=True, frm="crowd", to="fan"):
    eng = LooksEngine()
    eng.settings = contract.normalize({"sections": {"drop": {"move": {"shape": shape, "from": frm, "to": to, "size": 0.6,
                                                                       "beats": 16, "spread": spread}}}})
    lay = presets()["small-room-front"]
    if venue:
        eng.apply_venue(lay)
    return eng, lay


def _lands(lay, b, m, head):
    o = lay.heads(b)[m]
    d = lay.beam(b, o, head.pan, head.tilt, m)
    t = -o[2] / d[2]
    return o[0] + d[0] * t, o[1] + d[1] * t


def _frame(beat):
    return Frame(beat, 128.0, True, level=0.9, section=Section("drop", 0, 256, 0.9))


def test_the_contract_knows_both_spotlight_spreads():
    assert {"spotlight", "spotlights"} <= set(contract.SPREADS)
    doc = contract.normalize({"sections": {"drop": {"move": {"spread": "spotlight"}}}})
    assert doc["sections"]["drop"]["move"]["spread"] == "spotlight"


@pytest.mark.parametrize("shape", ["circle", "sweep", "eight", "glide"])
def test_spotlight_puts_every_head_on_one_roaming_spot(shape):
    eng, lay = _engine("spotlight", shape)
    seen = []
    for beat in (0.0, 3.0, 6.5, 11.0):
        rig = default_rig()
        eng.render(_frame(beat), rig)
        hits = [_lands(lay, b + 1, m, h) for b, bar in enumerate(rig.bars) for m, h in enumerate(bar.movers)]
        cx, cy = sum(h[0] for h in hits) / 4, sum(h[1] for h in hits) / 4
        assert max(math.hypot(x - cx, y - cy) for x, y in hits) < 0.25, (shape, beat, hits)
        fl = lay.floor
        assert fl.x - 0.3 <= cx <= fl.x + fl.w + 0.3 and fl.y - 0.3 <= cy <= fl.y + fl.d + 0.3
        seen.append((cx, cy))
    assert max(math.dist(seen[0], p) for p in seen[1:]) > 0.5   # it roams


def test_spotlights_gives_each_gigbar_its_own_spot_mirrored_across_the_floor():
    eng, lay = _engine("spotlights", "circle")
    rig = default_rig()
    eng.render(_frame(5.0), rig)
    hits = {b + 1: [_lands(lay, b + 1, m, h) for m, h in enumerate(bar.movers)] for b, bar in enumerate(rig.bars)}
    for b in (1, 2):
        assert math.dist(*hits[b]) < 0.25   # the bar's two heads together
    (x1, y1), (x2, y2) = hits[1][0], hits[2][0]
    assert x1 + x2 == pytest.approx(2 * lay.floor.cx, abs=0.3) and y1 == pytest.approx(y2, abs=0.3)


def test_without_a_layout_a_spotlight_plays_as_parallel():
    a, _ = _engine("spotlight", venue=False)
    b, _ = _engine("parallel", venue=False)
    ra, rb = default_rig(), default_rig()
    a.render(_frame(4.0), ra)
    b.render(_frame(4.0), rb)
    assert ra.render() == rb.render()
