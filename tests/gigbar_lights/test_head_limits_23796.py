"""How far the heads go, and Full power (Llano PM #23796, his 11-16 asks for the A&J wedding).

Head limits: a box on the room plan (venue.Layout.limits) set on site; every show move, pad and Follow
someone stays inside it. Moves are squeezed into the box (a sweep still sweeps, smaller), never parked on
its edge; a spot he steers is held at the edge. The far edge is read over the dancers' heads, so the same
box stays right when the GigBARs hang higher or lower. Full power: with it on, a dancing section at full
wash and heads peaks at DMX 255 on every light; the soft parts of the night stay soft.

Measured on his own Stage room (his_stage_room_12400.json, the room he lined up on 11-14).
"""
import copy
import json
from pathlib import Path

import pytest

from tools.gigbar_lights import moments, settings_contract as contract, venue
from tools.gigbar_lights.looks import Frame, LooksEngine
from tools.gigbar_lights.rig import default_rig
from tools.gigbar_lights.show_script import Section, ShowScript
from tools.gigbar_lights.studio import Studio

HERE = Path(__file__).parent
SONG = ShowScript([Section("intro", 0, 32, 0.2), Section("verse", 32, 96, 0.5), Section("build", 96, 128, 0.6),
                   Section("drop", 128, 192, 0.9), Section("breakdown", 192, 224, 0.4), Section("outro", 224, 256, 0.2)])
FLOOR_BOX = {"x": 3.0, "y": 2.44, "w": 6.1, "d": 6.71}
TIGHT_BOX = {"x": 4.5, "y": 3.5, "w": 3.0, "d": 3.0, "over": False}


def _room(box=None) -> dict:
    raw = json.loads((HERE / "his_stage_room_12400.json").read_text())
    raw = raw.get("layout", raw)
    raw = copy.deepcopy(raw)
    if box is not None:
        raw["limits"] = box
    return raw


def _base(**kw):
    base = contract.normalize({})
    base.update(kw)
    return base


def _engine(lay, base, play=None):
    e = LooksEngine(settings=base, isolated=True, play=play)
    e.apply_venue(lay, base["rig"].get("counts"))
    return e


def _heads(rig):
    return [(m.pan, m.tilt, m.dim) for bar in rig.bars for m in bar.movers]


def _run(lay, base, play=None, held=False, beats=256):
    e = _engine(lay, base, play)
    out = []
    for q in range(beats * 4):
        b = q / 4
        sec, nxt = (None, None) if held else SONG.at(b)
        rig = default_rig()
        e.render(Frame(b, 124.0, True, level=0.7, section=sec, next_section=nxt, track_key=3), rig)
        out.append((sec.kind if sec else "held", _heads(rig)))
    return out


def _landing(lay, b, m, p, t):
    """Where the beam is when it comes down to the box's far-edge height (far_z) or the floor: (x, y)."""
    hx, hy, hz = lay.heads(b)[m]
    dx, dy, dz = lay.beam(b, lay.heads(b)[m], p, t, m)
    z = lay.far_z()
    if dz >= -1e-9:
        return (hx + dx * 1e3, hy + dy * 1e3)
    k = (hz - z) / -dz
    return hx + dx * k, hy + dy * k


def _inside(lay, frames, slack=1e-9, m_slack=0.1):
    lim = lay.limits
    for b, m, _ in lay.all_heads():
        k = (b - 1) * 2 + m
        plo, phi, tlo, thi = lay.head_box(b, m)
        for _, hs in frames:
            p, t, dim = hs[k]
            if dim > 0:
                assert plo - slack <= p <= phi + slack and tlo - slack <= t <= thi + slack, (b, m, p, t, (plo, phi, tlo, thi))
                # the beam itself: down at far-edge height inside the box (side edges read on the floor, so a beam
                # at far_z can sit a little past a side edge; m_slack covers that and the model's 8-bit steps)
                x, y = _landing(lay, b, m, p, t)
                assert lim.x - m_slack <= x <= lim.x + lim.w + m_slack and y <= lim.y + lim.d + m_slack, (b, m, x, y)


def test_a_room_keeps_its_box_through_save_and_reload():
    lay = venue.Layout.from_dict(_room(FLOOR_BOX))
    assert lay.limits is not None and lay.limits.over
    again = venue.Layout.from_dict(lay.to_dict())
    assert again.limits == lay.limits
    assert "limits" not in venue.Layout.from_dict(_room()).to_dict()   # a room with no box reads back unchanged
    tight = venue.Layout.from_dict(_room(TIGHT_BOX))
    assert tight.to_dict()["limits"]["over"] is False


@pytest.mark.parametrize("bad", [{"x": 3, "y": 2, "w": 0.2, "d": 3}, {"x": 11, "y": 2, "w": 3, "d": 3}, "box"])
def test_a_bad_box_is_refused_in_words(bad):
    with pytest.raises(ValueError):
        venue.Layout.from_dict(_room(bad))


def test_the_contract_carries_a_room_with_a_box_through_llano():
    doc = contract.normalize({"layouts": {"in_use": "stage", "saved": {"stage": _room(FLOOR_BOX)}}})
    assert doc["layouts"]["saved"]["stage"]["limits"] == FLOOR_BOX


@pytest.mark.parametrize("box", [FLOOR_BOX, TIGHT_BOX])
def test_every_section_and_the_spotlight_pad_stay_inside_the_box(box):
    lay, base = venue.Layout.from_dict(_room(box)), _base()
    _inside(lay, _run(lay, base))
    _inside(lay, _run(lay, base, moments.style("spotlight"), held=True, beats=64))
    _inside(lay, _run(lay, base, moments.style("two-spotlights"), held=True, beats=64))


def test_a_move_still_moves_inside_a_tight_box_never_parked_on_an_edge():
    lay, base = venue.Layout.from_dict(_room(TIGHT_BOX)), _base()
    free = venue.Layout.from_dict(_room())
    for kind in ("verse", "drop"):
        before = [hs for k, hs in _run(free, base) if k == kind]
        after = [hs for k, hs in _run(lay, base) if k == kind]
        for k in range(4):
            span0 = max(h[k][0] for h in before) - min(h[k][0] for h in before)
            span1 = max(h[k][0] for h in after) - min(h[k][0] for h in after)
            assert span1 > 0.15 * span0 > 0, (kind, k, span0, span1)   # still sweeps, smaller
            b, m = k // 2 + 1, k % 2
            plo, phi, tlo, thi = lay.head_box(b, m)
            tilts = [h[k][1] for h in after]
            assert sum(abs(t - thi) < 1e-6 for t in tilts) < len(tilts) / 2   # not parked on the top edge


def test_the_box_lowers_the_highest_beam_on_his_room():
    base = _base()
    free, lay = venue.Layout.from_dict(_room()), venue.Layout.from_dict(_room(FLOOR_BOX))
    top0 = max(h[1] for _, hs in _run(free, base) for h in hs if h[2] > 0)
    top1 = max(h[1] for _, hs in _run(lay, base) for h in hs if h[2] > 0)
    assert top1 < top0


def test_the_far_edge_is_read_over_heads_so_a_higher_bar_tilts_lower():
    low, high = _room(FLOOR_BOX), _room(FLOOR_BOX)
    for raw, z in ((low, 2.6), (high, 3.4)):
        for b in ("bar1", "bar2"):
            raw["fixtures"][b]["z"] = z
            raw["fixtures"][b].pop("cal", None)   # the guessed model: only the height differs
    lo, hi = venue.Layout.from_dict(low), venue.Layout.from_dict(high)
    # the same far edge over heads: from higher up the beam points further down (nearer straight down, tilt 0.5)
    assert abs(hi.head_box(1, 0)[3] - 0.5) < abs(lo.head_box(1, 0)[3] - 0.5)
    # a bar hung under head height reads the far edge on the floor, for the whole rig (one rule, the page's)
    raw = _room(FLOOR_BOX)
    raw["fixtures"]["bar2"]["z"] = 1.8
    assert venue.Layout.from_dict(raw).far_z() == 0.0
    raw["fixtures"]["bar2"]["out"] = True   # ... unless that bar sits out tonight
    assert venue.Layout.from_dict(raw).far_z() == venue.HEAD_CLEAR
    assert hi.far_z() == venue.HEAD_CLEAR


def test_a_beam_turned_to_the_side_tilts_less_high_than_one_straight_out():
    """The reviewer's case: the widest pan and the highest tilt together point past a side edge. The tilt the box
    allows falls toward the sides, so the show's wall moves (sweep_left / sweep_right) come down inside it."""
    lay = venue.Layout.from_dict(_room(FLOOR_BOX))
    for b, m, _ in lay.all_heads():
        cv = lay.tilt_curve(b, m)
        assert len(cv) > 8
        his = [abs(h - 0.5) for _, _, h in cv]
        assert max(his) - min(his) > 0.02, (b, m)   # not one flat ceiling across every pan
    free = venue.Layout.from_dict(_room())
    e, e0 = _engine(lay, _base()), _engine(free, _base())
    for name in ("sweep_left", "sweep_right", "fan"):
        for k, (b, m, _) in enumerate(lay.all_heads()):
            p, t = venue.squeeze_pose(e._box[k], *e0.positions[name][k])
            x, y = _landing(lay, b, m, p, t)
            assert lay.limits.x - 0.1 <= x <= lay.limits.x + lay.limits.w + 0.1, (name, b, m, x, y)


def test_two_spotlights_meet_on_one_point_each_inside_the_box():
    lay, base = venue.Layout.from_dict(_room(TIGHT_BOX)), _base()
    for key, pairs in (("spotlight", False), ("two-spotlights", True)):
        e = _engine(lay, base, moments.style(key))
        for q in range(0, 128, 8):
            rig = default_rig()
            e.render(Frame(q / 4, 124.0, True, level=0.7, track_key=3), rig)
            pts = [_landing(lay, b + 1, m, h.pan, h.tilt) for b, bar in enumerate(rig.bars) for m, h in enumerate(bar.movers)]
            groups = [pts[:2], pts[2:]] if pairs else [pts]
            for g in groups:   # the heads of one spot land together (within the model's 8-bit steps)
                for (x, y) in g:
                    assert abs(x - g[0][0]) < 0.6 and abs(y - g[0][1]) < 0.6, (key, q, pts)
            lim = lay.limits
            for x, y in pts:
                assert lim.x - 0.4 <= x <= lim.x + lim.w + 0.4 and lim.y - 0.4 <= y <= lim.y + lim.d + 0.4, (key, x, y)


def test_no_box_plays_exactly_as_before():
    lay, base = venue.Layout.from_dict(_room()), _base()
    assert lay.limit_maps() == []
    a = _run(lay, base, beats=64)
    e = _engine(lay, base)
    assert e._box == []
    assert a == _run(lay, base, beats=64)


def test_the_line_up_screens_go_past_the_box():
    lay, base = venue.Layout.from_dict(_room(TIGHT_BOX)), _base()
    e = _engine(lay, base)
    e.overrides.aim_set = {"poses": {(1, 0): (0.2, 0.95)}, "focus": None, "others": 0.0}
    rig = default_rig()
    e.render(Frame(0.0, 124.0, True), rig)
    assert (rig.bars[0].movers[0].pan, rig.bars[0].movers[0].tilt) == (0.2, 0.95)


def test_a_dark_beat_holds_the_squeezed_aim_without_squeezing_twice():
    lay, base = venue.Layout.from_dict(_room(TIGHT_BOX)), _base()
    e = _engine(lay, base)
    rig = default_rig()
    e.render(Frame(124.0, 124.0, True, level=0.7, section=SONG.at(124.0)[0], next_section=SONG.at(124.0)[1]), rig)
    lit = [(m.pan, m.tilt) for bar in rig.bars for m in bar.movers]
    e.overrides.blackout = True
    for _ in range(3):
        rig = default_rig()
        e.render(Frame(124.0, 124.0, True, level=0.7), rig)
        assert [(m.pan, m.tilt) for bar in rig.bars for m in bar.movers] == lit


def test_follow_someone_is_held_at_the_edge_not_squeezed():
    lay, base = venue.Layout.from_dict(_room(FLOOR_BOX)), _base()
    e = _engine(lay, base)
    rig = default_rig()
    e.render(Frame(40.0, 124.0, True, level=0.7, section=SONG.at(40.0)[0]), rig)
    # a spot steered far outside the box (the studio aims the heads itself), then the guards again
    for b, bar in enumerate(rig.bars):
        for m, head in enumerate(bar.movers):
            head.pan, head.tilt = lay.aim(b + 1, lay.heads(b + 1)[m], (11.0, 12.0, 1.5), m)
    e.guard(rig)
    for b, bar in enumerate(rig.bars):
        for m, head in enumerate(bar.movers):
            assert (head.pan, head.tilt) == pytest.approx(venue.hold_pose(e._box[b * 2 + m], head.pan, head.tilt))
            plo, phi, tlo, thi = lay.head_box(b + 1, m)
            assert plo - 1e-9 <= head.pan <= phi + 1e-9 and tlo - 1e-9 <= head.tilt <= thi + 1e-9
    # inside the box, a steered spot lands exactly where he points
    rig = default_rig()
    e.render(Frame(40.0, 124.0, True, level=0.7, section=SONG.at(40.0)[0]), rig)
    want = lay.aim(1, lay.heads(1)[0], (6.0, 4.5, 1.5), 0)
    plo, phi, tlo, thi = lay.head_box(1, 0)
    assert plo <= want[0] <= phi and tlo <= want[1] <= thi   # a person well inside the box
    rig.bars[0].movers[0].pan, rig.bars[0].movers[0].tilt = want
    e.guard(rig)
    assert (rig.bars[0].movers[0].pan, rig.bars[0].movers[0].tilt) == pytest.approx(want)


def test_the_studio_follow_spot_stays_in_the_box():
    lay = venue.Layout.from_dict(_room(TIGHT_BOX))
    st = Studio()
    st.layout = lay
    x0, y0, x1, y1 = st._bounds()
    lim = lay.limits
    assert (x0, y0, x1, y1) == pytest.approx((lim.x, lim.y, lim.x + lim.w, lim.y + lim.d))
    st.layout = venue.Layout.from_dict(_room())
    assert st._bounds() == (0.0, 0.0, st.layout.room[0], st.layout.room[1])


# --- Full power ---------------------------------------------------------------------------------

DIM = {"head": [25, 31, 65, 71], "tetra": [84, 94, 104, 114, 124, 134], "stick": [150, 160, 170, 180]}


def _peaks(base, play=None, lo=32, hi=96, held=False):
    lay = venue.Layout.from_dict(_room())
    e = _engine(lay, base, play)
    best = {k: 0 for k in DIM}
    for q in range(lo * 8, hi * 8):
        b = q / 8
        sec, nxt = (None, None) if held else SONG.at(b)
        rig = default_rig()
        e.render(Frame(b, 124.0, True, level=0.7, section=sec, next_section=nxt, track_key=3), rig)
        u = rig.render(base["rig"])
        for k, slots in DIM.items():
            best[k] = max(best[k], *(u[s] for s in slots))
    return best


def test_full_power_is_off_by_default_and_a_verse_stays_as_written():
    base = _base()
    assert base["full_power"] is False
    p = _peaks(base)
    assert p["head"] == 153 and p["tetra"] == 230   # 60% heads, 90% Tetras: the verse as written


def test_full_power_puts_every_light_at_255_in_a_verse_a_build_and_a_groove_drop():
    base = _base(full_power=True)
    assert _peaks(base) == {"head": 255, "tetra": 255, "stick": 255}           # verse
    assert min(_peaks(base, lo=96, hi=127).values()) >= 250   # the build's last bar, just before the dark beat
    assert max(_peaks(_base(), lo=96, hi=127).values()) <= 235   # was 211 to 232
    groove = contract.look_style("groove", base["styles"], base, {})
    assert _peaks(_base(), groove, 128, 192)["head"] == 204                     # Groove's drop at 80% ...
    assert _peaks(base, groove, 128, 192) == {"head": 255, "tetra": 255, "stick": 255}   # ... full with Full power


def test_full_power_leaves_the_soft_looks_and_held_moments_soft():
    base = _base(full_power=True)
    slow = contract.look_style("slow-dance", base["styles"], base, {})
    assert _peaks(base, slow) == _peaks(_base(), slow)            # a section set below full stays as set
    toast = moments.style("toast")
    assert _peaks(base, toast, 0, 32, held=True) == _peaks(_base(), toast, 0, 32, held=True)


def test_full_power_never_lifts_master():
    base = _base(full_power=True, master=0.5)
    assert _peaks(base)["head"] == 128


def test_full_power_is_a_setting_llano_can_change():
    doc, applied = contract.apply_ops({}, [{"path": "full_power", "value": True}])
    assert doc["full_power"] is True and applied
