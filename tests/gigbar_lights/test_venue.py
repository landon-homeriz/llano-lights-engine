"""Show Designer: room layouts, aim from where the lights sit, chase order, save/load."""
import json
import math

import pytest

from tools.gigbar_lights.looks import Frame, LooksEngine
from tools.gigbar_lights.rig import default_rig
from tools.gigbar_lights.show_script import Section
from tools.gigbar_lights.venue import FIXTURE_IDS, Layout, LayoutStore, presets

DROP = Section("drop", 64, 96, 0.9)


def drop_frame(beat):
    return Frame(beat, 128.0, True, level=0.8, section=DROP, track_key=3)


def render(eng, f):
    return eng.render(f, default_rig())


def test_every_preset_places_all_12_lights_inside_the_room():
    ps = presets()
    assert len(ps) >= 4
    for lay in ps.values():
        assert set(lay.spots) == set(FIXTURE_IDS)
        w, d, h = lay.room
        for s in lay.spots.values():
            assert 0 <= s.x <= w and 0 <= s.y <= d and 0 <= s.z <= h
        assert Layout.from_dict(lay.to_dict()).to_dict() == lay.to_dict()


def test_layout_never_changes_the_address_plan():
    before = [(f.name, f.address) for f in default_rig().fixtures]
    for lay in presets().values():
        eng = LooksEngine()
        eng.apply_venue(lay)
        rig = render(eng, drop_frame(70.3))
        assert [(f.name, f.address) for f in rig.fixtures] == before
        assert "address" not in json.dumps(lay.to_dict())


@pytest.mark.parametrize("name", list(presets()))
def test_aim_points_each_head_at_its_target(name):
    lay = presets()[name]
    for (bar, _, head), target in zip(lay.all_heads(), lay.targets()["crowd"]):
        pan, tilt = lay.aim(bar, head, target)
        d = lay.beam(bar, head, pan, tilt)
        want = [t - h for t, h in zip(target, head)]
        n = math.sqrt(sum(v * v for v in want))
        assert sum(a * b / n for a, b in zip(d, want)) > 0.9999  # same direction


def test_moving_a_bar_changes_its_aim_and_trim_shifts_it():
    lay = presets()["small-room-front"]
    a = lay.positions()["booth"][0]
    lay.spots["bar1"].x = 0.5
    b = lay.positions()["booth"][0]
    assert a != b
    lay.spots["bar1"].pan_trim = 10.0
    c = lay.positions()["booth"][0]
    assert abs(c[0] - b[0]) == pytest.approx(10 / 540, abs=1e-6)   # ten degrees of trim, one step of 1/540 each


def test_heads_aim_down_at_the_floor_and_highest_for_ceiling():
    # The heads hang under the bar: 0.5 is straight down, 1 is level (test_hung_heads.py).
    lay = presets()["wedding-hall-walls"]
    pos = lay.positions()
    assert all(0.5 < t < 0.9 for _, t in pos["crowd"])
    assert all(c < t <= 1.0 for (_, c), (_, t) in zip(pos["crowd"], pos["ceiling"]))


def test_chase_runs_left_to_right_by_where_tetras_stand():
    lay = presets()["small-room-front"]
    eng = LooksEngine()
    eng.apply_venue(lay)
    # A beat just after the downbeat: the leftmost Tetra's pulse is freshest (brightest).
    rig = render(eng, drop_frame(66.02))
    left = min(range(6), key=lambda i: lay.spots[f"tetra{i + 1}"].x)
    assert rig.tetras[left].dim == max(t.dim for t in rig.tetras)
    # Swap the leftmost and rightmost Tetra on the floor: the chase follows the lights.
    right = max(range(6), key=lambda i: lay.spots[f"tetra{i + 1}"].x)
    sl, sr = lay.spots[f"tetra{left + 1}"], lay.spots[f"tetra{right + 1}"]
    sl.x, sr.x = sr.x, sl.x
    eng.apply_venue(lay)
    rig = render(eng, drop_frame(66.02))
    assert rig.tetras[right].dim == max(t.dim for t in rig.tetras)


def test_wall_uplights_chase_wall_by_wall():
    lay = presets()["small-room-walls"]
    order = lay.order("tetra")
    left_wall = [order[i] for i in range(6) if lay.spots[f"tetra{i + 1}"].x < 4]
    right_wall = [order[i] for i in range(6) if lay.spots[f"tetra{i + 1}"].x > 4]
    assert len(set(left_wall)) == 1 and len(set(right_wall)) == 1
    assert left_wall[0] < right_wall[0]


def test_sticks_alternate_left_and_right_of_the_floor():
    lay = presets()["wedding-hall-walls"]
    sides = lay.sides("stick")
    for i, side in enumerate(sides):
        assert side == (0.0 if lay.spots[f"stick{i + 1}"].x < lay.floor.cx else 0.5)
    for s in lay.spots.values():  # all on one side: still alternate, by position
        s.x = 1.0
    assert sorted(lay.sides("stick")) == [0.0, 0.0, 0.5, 0.5]


def test_sweep_look_swings_beams_from_the_left_of_the_floor_to_the_right():
    lay = presets()["small-room-front"]
    eng = LooksEngine()
    eng.apply_venue(lay)
    eng.overrides.autoloop_override = eng.overrides.hold_loop = True
    eng.overrides.loop_shift = eng.AUTOLOOPS.index("sweep")

    def hit_x(beat):
        rig = render(eng, Frame(beat, 128.0, True, level=0.8))
        xs = []
        for (bar, k, head), (b, m) in zip(lay.all_heads(), [(0, 0), (0, 1), (1, 0), (1, 1)]):
            mv = rig.bars[b].movers[m]
            d = lay.beam(bar, head, mv.pan, mv.tilt)
            t = -head[2] / d[2]  # down to the floor
            xs.append(head[0] + d[0] * t)
        return sum(xs) / len(xs)

    lo, hi = hit_x(12.0), hit_x(4.0)  # sin(-pi/2) = sweep_left, sin(pi/2) = sweep_right
    assert lo < lay.floor.x + lay.floor.w * 0.3 < lay.floor.x + lay.floor.w * 0.7 < hi


def test_no_venue_keeps_the_old_looks():
    a, b = LooksEngine(), LooksEngine()
    for beat in (2.0, 40.0, 70.3, 90.1):
        f = drop_frame(beat)
        assert render(a, f).render() == render(b, f).render()
    rig = render(a, drop_frame(66.02))
    assert rig.tetras[0].dim == max(t.dim for t in rig.tetras)


def test_store_saves_uses_and_never_overwrites_a_preset(tmp_path):
    store = LayoutStore(tmp_path)
    assert store.current_name() == "small-room-front"
    lay = Layout.from_dict({**presets()["small-room-walls"].to_dict(), "label": "Rio Grande ballroom"})
    saved = store.save(lay)
    assert saved.name == "rio-grande-ballroom" and not saved.preset
    store.use(saved.name)
    assert LayoutStore(tmp_path).current().label == "Rio Grande ballroom"
    clash = store.save(Layout.from_dict(presets()["small-room-front"].to_dict()))
    assert clash.name not in presets() and (tmp_path / "layouts" / f"{clash.name}.json").exists()
    assert presets()["small-room-front"].preset
    (tmp_path / "layouts" / "broken.json").write_text("{not json")
    assert "broken" not in store.saved()
    (tmp_path / "venue.json").write_text('{"current": "gone"}')
    assert store.current_name() == "small-room-front"
    with pytest.raises(ValueError):
        store.use("nope")


@pytest.mark.parametrize("breakit, why", [
    (lambda d: d["fixtures"].pop("tetra3"), "missing tetra3"),
    (lambda d: d["fixtures"]["bar1"].update(x=99.0), "bar1 x"),
    (lambda d: d["fixtures"]["bar1"].update(x="left"), "bar1 x must be a number"),
    (lambda d: d["fixtures"]["stick1"].update(y=float("nan")), "stick1 y must be a number"),
    (lambda d: d["room"].update(w=True), "room w must be a number"),
    (lambda d: d["booth"].update(x=7.5), "booth runs past"),
    (lambda d: d.pop("floor"), "floor missing"),
])
def test_bad_layouts_are_refused_with_a_plain_reason(breakit, why):
    d = presets()["small-room-front"].to_dict()
    breakit(d)
    with pytest.raises(ValueError, match=why):
        Layout.from_dict(d)
    with pytest.raises(ValueError):
        Layout.from_dict([])


def test_a_hand_broken_saved_file_never_stops_the_app(tmp_path):
    (tmp_path / "layouts").mkdir()
    for i, junk in enumerate(['{"room": [1, 2]}', '{"room": "big"}', '[]', '{"fixtures": 3}', "\x00"]):
        (tmp_path / "layouts" / f"junk{i}.json").write_text(junk)
    store = LayoutStore(tmp_path)
    assert store.saved() == {}
    assert store.current().name == "small-room-front"
    with pytest.raises(ValueError, match="room missing"):
        Layout.from_dict({**presets()["small-room-front"].to_dict(), "room": [1, 2]})


def test_saving_never_overwrites_a_different_layout_and_avoids_windows_device_names(tmp_path):
    store = LayoutStore(tmp_path)
    base = presets()["small-room-walls"].to_dict()
    a = store.save(Layout.from_dict({**base, "name": "Hall A", "label": "Hall A"}))
    b = store.save(Layout.from_dict({**base, "name": "hall-a", "label": "hall  a!"}))
    assert a.name == "hall-a" and b.name == "hall-a-2"
    assert {l.label for l in store.saved().values()} == {"Hall A", "hall  a!"}
    again = store.save(Layout.from_dict({**base, "name": "Hall A", "label": "Hall A"}))
    assert again.name == "hall-a"  # same label: updates its own file
    assert store.save(Layout.from_dict({**base, "name": "con", "label": "con"})).name == "con-layout"
