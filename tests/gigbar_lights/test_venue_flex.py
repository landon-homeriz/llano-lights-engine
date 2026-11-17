"""Venue flexibility (Llano BL #11766, his 11-10 asks): the lights rarely stand exactly where the plan says.

"Do we need measurements that we can adjust? I need to be able to refresh the show quickly with new lights
or a new layout, or reset things if a light is lost." So each light has a position he can read and edit as a
tape measure would (from the DJ booth's center), the plan is kept for Reset to plan, a lost light is marked
out and the rest of its row closes the gap, a GigBAR's line-up can be cleared on its own, and a layout he
edits on his phone re-aims the show on the laptop straight away.
"""
import json
import sys
import types
from pathlib import Path

import pytest

from tools.gigbar_lights import settings_contract as contract
from tools.gigbar_lights.venue import FIXTURE_IDS, HeadCal, Layout, LayoutStore, presets

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
import gigbar_app  # noqa: E402


def room() -> Layout:
    return Layout.from_dict({**presets()["small-room-front"].to_dict(), "name": "his-room", "preset": False})


def by_id(lay):
    return {r["id"]: r for r in lay.measurements()}


def test_every_light_has_a_measured_position_from_the_booth_center():
    m = by_id(room())
    assert list(m) == list(FIXTURE_IDS)                       # both GigBARs, all 6 Tetras, all 4 sticks
    # booth 3.0..5.0 x 0.3..1.3: center (4.0, 0.8). GigBAR 1 stands at (2.3, 0.8), 2.4 m up.
    assert (m["bar1"]["right"], m["bar1"]["out"], m["bar1"]["distance"], m["bar1"]["height"]) == (-1.7, 0.0, 1.7, 2.4)
    assert m["bar2"]["right"] == 1.7
    assert m["bar1"]["spacing"] == m["bar2"]["spacing"] == 3.4               # to the nearest of its kind
    assert [m[f"tetra{i}"]["spacing"] for i in range(1, 7)] == [1.0] * 6
    assert [m[f"stick{i}"]["spacing"] for i in range(1, 5)] == [5.0] * 4
    assert all(r["moved"] == 0 and not r["is_out"] for r in m.values())


def test_editing_a_position_keeps_the_plan_and_reset_puts_it_back():
    lay = room()
    lay.set_position("bar1", right=-1.2, out=0.4, height=2.1, facing=15)
    m = by_id(lay)["bar1"]
    assert (m["right"], m["out"], m["height"], m["facing"]) == (-1.2, 0.4, 2.1, 15.0)
    assert m["moved"] == pytest.approx(0.64, abs=0.01)
    assert lay.planned("bar1") == {"x": 2.3, "y": 0.8, "z": 2.4, "facing": None}
    lay.set_position("bar1", right=-1.0)                   # a second edit never moves the plan
    assert lay.planned("bar1")["x"] == 2.3
    lay.reset_to_plan("bar1")
    assert (lay.spots["bar1"].x, lay.spots["bar1"].y, lay.spots["bar1"].z, lay.spots["bar1"].facing) == (2.3, 0.8, 2.4, None)


def test_reset_everything_brings_lost_lights_back_and_keeps_line_ups():
    lay = room()
    lay.spots["bar2"].cal[0] = HeadCal(center=(0.3, 0.8))
    lay.set_position("tetra3", right=0.0, out=2.0)
    lay.spots["stick2"].out = True
    lay.reset_to_plan()
    assert lay.spots["tetra3"].x == 3.5 and not lay.spots["stick2"].out
    assert lay.spots["bar2"].cal[0].center is not None


def test_positions_outside_the_room_are_refused_in_plain_words():
    with pytest.raises(ValueError, match="across the room"):
        room().set_position("tetra1", right=9.0)
    with pytest.raises(ValueError, match="no light named"):
        room().set_position("bar3", right=0.0)


def test_facing_auto_goes_back_to_facing_the_floor():
    lay = room()
    lay.set_position("bar2", facing=-30)
    lay.set_position("bar2", facing="auto")
    assert lay.spots["bar2"].facing is None


def test_plan_and_out_survive_saving_and_older_layouts_read_back_unchanged():
    plain = room().to_dict()
    assert "plan" not in plain and all("out" not in f for f in plain["fixtures"].values())
    lay = room()
    lay.set_position("stick4", right=2.0, out=5.0)
    lay.spots["tetra2"].out = True
    back = Layout.from_dict(json.loads(json.dumps(lay.to_dict())))
    assert back.planned("stick4") == {"x": 6.5, "y": 7.5, "z": 0.0, "facing": None}
    assert back.spots["tetra2"].out and back.spots["stick4"].x == 6.0
    with pytest.raises(ValueError, match="plan"):
        Layout.from_dict({**lay.to_dict(), "plan": {"bar9": {"x": 1, "y": 1}}})


def test_a_lost_light_drops_out_and_its_row_closes_the_gap():
    lay = room()
    before = lay.order("tetra")
    assert before == pytest.approx([i / 6 for i in range(6)])
    lay.spots["tetra3"].out = True
    after = lay.order("tetra")
    assert after[2] == 0.0
    rest = [after[i] for i in (0, 1, 3, 4, 5)]
    # the five left (x 1.5, 2.5, 4.5, 5.5, 6.5) chase as a row of five, spaced by where they stand
    assert rest == pytest.approx([0.0, 0.16, 0.48, 0.64, 0.8])
    lay.spots["stick1"].out = lay.spots["stick3"].out = True     # every stick left of the floor's middle lost
    sides = lay.sides("stick")
    assert {sides[1], sides[3]} == {0.0, 0.5}                     # the two left alternate instead


def test_clearing_one_bars_line_up_leaves_the_other():
    lay = room()
    for b in (1, 2):
        lay.spots[f"bar{b}"].cal = [HeadCal(center=(0.3, 0.8)), HeadCal(center=(0.4, 0.8))]
    lay.spots["bar1"].pan_trim = 12.0
    lay.clear_lineup(1)
    assert [c.center for c in lay.spots["bar1"].cal] == [None, None] and lay.spots["bar1"].pan_trim == 0.0
    assert lay.spots["bar2"].cal[0].center is not None


def test_llano_keeps_a_layout_with_positions_plan_and_spots_whole():
    """The phone saves layouts.saved.<name> whole; the shared contract stores it as is, under its size cap."""
    lay = room()
    lay.set_position("bar1", right=-1.4)
    lay.spots["tetra6"].out = True
    for b in (1, 2):
        lay.spots[f"bar{b}"].cal = [HeadCal(center=(0.3, 0.8), anchors=[(1.0 + i, 3.0, 0.3, 0.8) for i in range(8)])
                                    for _ in range(2)]
    doc, _ = contract.apply_ops(contract.defaults(), [{"path": "layouts.saved.his-room", "value": lay.to_dict()}])
    kept = doc["layouts"]["saved"]["his-room"]
    assert kept["plan"]["bar1"]["x"] == 2.3 and kept["fixtures"]["tetra6"]["out"] is True
    assert len(kept["fixtures"]["bar2"]["cal"][1]["anchors"]) == 8
    assert Layout.from_dict(kept).spots["bar1"].x == pytest.approx(2.6)


def test_a_position_edited_on_his_phone_re_aims_the_show_now(tmp_path):
    """The layout in use changed on llano.app: the laptop writes it AND hands it to the running show,
    not only when he switches to a different layout."""
    store = LayoutStore(tmp_path)
    lay = store.save(room())
    store.use(lay.name)
    handed = []
    preview = types.SimpleNamespace(layout=lay, on_layout=handed.append)
    app = types.SimpleNamespace(layouts=store, preview=preview)
    old = contract.normalize({"layouts": {"in_use": lay.name, "saved": {lay.name: lay.to_dict()}}})
    moved = room()
    moved.name = lay.name
    moved.set_position("bar2", right=1.1)
    new = contract.normalize({"layouts": {"in_use": lay.name, "saved": {lay.name: moved.to_dict()}}})
    gigbar_app.App._settings_from_llano(app, new, old)
    assert handed and handed[-1].spots["bar2"].x == pytest.approx(5.1)
    assert store.current().spots["bar2"].x == pytest.approx(5.1)
    handed.clear()
    gigbar_app.App._settings_from_llano(app, new, new)    # nothing changed: the show is left alone
    assert handed == []


def test_a_phone_edit_never_replaces_a_line_up_he_has_not_saved(tmp_path):
    store = LayoutStore(tmp_path)
    lay = store.save(room())
    store.use(lay.name)
    handed = []
    preview = types.SimpleNamespace(layout=lay, on_layout=handed.append, tried=True)   # mid line-up on the laptop
    app = types.SimpleNamespace(layouts=store, preview=preview)
    old = contract.normalize({"layouts": {"in_use": lay.name, "saved": {lay.name: lay.to_dict()}}})
    moved = room()
    moved.name = lay.name
    moved.set_position("bar2", right=1.1)
    new = contract.normalize({"layouts": {"in_use": lay.name, "saved": {lay.name: moved.to_dict()}}})
    gigbar_app.App._settings_from_llano(app, new, old)
    assert handed == [] and preview.layout is lay                       # his unsaved line-up stays on screen
    assert store.current().spots["bar2"].x == pytest.approx(5.1)        # the phone's copy is saved for later
