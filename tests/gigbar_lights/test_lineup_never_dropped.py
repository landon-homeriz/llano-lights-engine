"""Nothing in the app drops his saved line-up by surprise, and the last good one is kept (PM #23745).

His 11-14 9:42 PM video: Draw my room threw his line-up away, and with no line-up the heads fell back to a guess
that (until 1.31.1) turned head 1 of each bar to the wall. Every path that writes a room is covered here: Save
my layout from a page that sent the room without its line-up, Clear line-up (the one way to drop it, on purpose,
one bar at a time), a venue switch, Draw my room, a copy arriving from llano.app, and a laptop updated from
before 1.31.1 (no spare copy yet). Bring back my line-up puts the last one he saved on any room.
"""
from __future__ import annotations

import copy
import io
import json
import math
import sys
from pathlib import Path

import pytest

from tools.gigbar_lights.venue import FT, Layout, LayoutStore, has_lineup, stage_layout

HERE = Path(__file__).parent
LINED = json.loads((HERE / "his_room_lined_up_12400.json").read_text())
HEADS = [(b, m) for b in (1, 2) for m in (0, 1)]


def _no_lineup(d: dict) -> dict:
    d = copy.deepcopy(d)
    for b in ("bar1", "bar2"):
        d["fixtures"][b].pop("cal", None)
    return d


def _cals(lay: Layout, b: int) -> list:
    return [c.to_dict() for c in lay.spots[f"bar{b}"].cal]


def _faces_floor(lay: Layout, b: int, m: int) -> float:
    h, fl = lay.heads(b)[m], lay.floor
    d = lay.beam_of(b, m, *lay.aim(b, h, (fl.cx, fl.cy, 0.0), m))
    want = math.degrees(math.atan2(fl.cx - h[0], fl.cy - h[1]))
    return abs((math.degrees(math.atan2(d[0], d[1])) - want + 180) % 360 - 180)


def test_a_save_without_the_lineup_keeps_his_lineup_spots_and_all(tmp_path):
    store = LayoutStore(tmp_path)
    store.save(Layout.from_dict(LINED))
    was = {b: _cals(store.saved()[LINED["name"]], b) for b in (1, 2)}
    got = store.save(Layout.from_dict(_no_lineup(LINED)))
    assert got.kept_lineup == [1, 2]
    back = store.saved()[LINED["name"]]
    assert {b: _cals(back, b) for b in (1, 2)} == was   # the anchors (his confirmed spots) too


def test_clear_lineup_drops_only_the_bar_he_cleared(tmp_path):
    store = LayoutStore(tmp_path)
    store.save(Layout.from_dict(LINED))
    store.save(Layout.from_dict(_no_lineup(LINED)), cleared=[1])
    back = store.saved()[LINED["name"]]
    assert not has_lineup(back, 1) and has_lineup(back, 2)


def test_a_bar_moved_in_the_same_save_keeps_its_lineup_and_faces_the_floor(tmp_path):
    store = LayoutStore(tmp_path)
    store.save(Layout.from_dict(LINED))
    moved = _no_lineup(LINED)
    moved["fixtures"]["bar1"]["x"] = 1.5
    got = store.save(Layout.from_dict(moved))
    assert got.kept_lineup == [1, 2]
    back = store.saved()[LINED["name"]]
    assert _cals(back, 2) == _cals(Layout.from_dict(LINED), 2)   # the bar that stayed: exactly as saved
    for m in (0, 1):
        assert _faces_floor(back, 1, m) < 2.0


def test_every_save_with_a_lineup_keeps_a_spare_copy(tmp_path):
    store = LayoutStore(tmp_path)
    assert store.last_lineup() is None
    store.save(Layout.from_dict(LINED))
    last, at = store.last_lineup()
    assert last.name == LINED["name"] and at.endswith("Z")
    store.save(stage_layout(20 * FT, 22 * FT, 10 * FT))   # a room with none never replaces it
    assert store.last_lineup()[0].name == LINED["name"]


def test_a_laptop_updated_from_before_the_spare_copy_still_finds_his_lineup(tmp_path):
    # 1.31.0 and older kept no lineup_lastgood.json: his saved rooms are read instead
    (tmp_path / "layouts").mkdir()
    (tmp_path / "layouts" / f"{LINED['name']}.json").write_text(json.dumps(LINED))
    store = LayoutStore(tmp_path)
    assert not store.lastgood_file.exists()
    assert store.last_lineup()[0].name == LINED["name"]


def test_a_broken_spare_copy_falls_back_and_never_raises(tmp_path):
    store = LayoutStore(tmp_path)
    store.save(Layout.from_dict(LINED))
    store.lastgood_file.write_text("{not json")
    assert store.last_lineup()[0].name == LINED["name"]


# --- through the laptop app's handlers --------------------------------------------------------------

class _Req:
    def __init__(self, body: dict):
        raw = json.dumps(body).encode()
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = io.BytesIO(raw)


@pytest.fixture
def app_mod():
    sys.path.insert(0, str(HERE.parents[1] / "tools/gigbar_lights/windows/src"))
    import gigbar_app
    return gigbar_app


def test_switching_to_a_venue_never_lined_up_brings_his_lineup_along(tmp_path, app_mod):
    store = LayoutStore(tmp_path)
    store.save(Layout.from_dict(LINED))
    pv = app_mod.Preview("", store)
    try:
        code, out = pv.layout_post(_Req({"action": "use", "name": "wedding-hall-front"}))
        assert code == 200 and out["carried"] == 4, out.get("error")
        assert all(_faces_floor(pv.layout, b, m) < 2.0 for b, m in HEADS)
        assert out["last_lineup"]["name"] == LINED["name"]
    finally:
        pv.close()


def test_draw_my_room_uses_the_spare_copy_when_no_saved_room_has_a_lineup(tmp_path, app_mod):
    store = LayoutStore(tmp_path)
    store.save(Layout.from_dict(LINED))
    store.save(Layout.from_dict(_no_lineup(LINED)), cleared=[1, 2])   # his only lined-up room, cleared
    assert not any(has_lineup(l) for l in store.saved().values())
    pv = app_mod.Preview("", store)
    try:
        code, out = pv.layout_post(_Req({"action": "stage", "stage_w": 20 * FT, "floor_d": 22 * FT, "bar_h": 10 * FT}))
        assert code == 200 and out["carried"] == 4
    finally:
        pv.close()


def test_bring_back_my_lineup_puts_it_on_the_room_on_screen(tmp_path, app_mod):
    store = LayoutStore(tmp_path)
    pv = app_mod.Preview("", store)
    try:
        room = stage_layout(20 * FT, 22 * FT, 10 * FT).to_dict()
        code, out = pv.layout_post(_Req({"action": "restore_lineup", "layout": room}))
        assert code == 400 and "no saved line-up" in out["error"]
        store.save(Layout.from_dict(LINED))
        code, out = pv.layout_post(_Req({"action": "restore_lineup", "layout": room}))
        assert code == 200 and out["restored"] == [1, 2]
        assert all(_faces_floor(pv.layout, b, m) < 2.0 for b, m in HEADS)
        assert pv.tried   # on screen, not saved until he saves
    finally:
        pv.close()


def test_save_through_the_app_says_it_kept_the_lineup_and_clear_still_clears(tmp_path, app_mod):
    store = LayoutStore(tmp_path)
    store.save(Layout.from_dict(LINED))
    pv = app_mod.Preview("", store)
    try:
        code, out = pv.layout_post(_Req({"action": "save", "layout": _no_lineup(LINED)}))
        assert code == 200 and out["kept_lineup"] == [1, 2]
        code, out = pv.layout_post(_Req({"action": "save", "layout": _no_lineup(LINED), "cleared": [2]}))
        assert code == 200 and out["kept_lineup"] == [1]   # bar 1 kept from the file, bar 2 cleared on purpose
        back = store.saved()[LINED["name"]]
        assert has_lineup(back, 1) and not has_lineup(back, 2)
        code, out = pv.layout_post(_Req({"action": "save", "layout": LINED, "cleared": [3]}))
        assert code == 400
    finally:
        pv.close()


def test_a_copy_from_llano_without_the_lineup_leaves_it_restorable(tmp_path, app_mod):
    store = LayoutStore(tmp_path)
    store.save(Layout.from_dict(LINED))
    store.lastgood_file.unlink()

    class _App:   # just what _settings_from_llano reads
        layouts, preview = store, None
    stripped = _no_lineup(LINED)
    new = {"layouts": {"in_use": "", "saved": {LINED["name"]: stripped}}}
    old = {"layouts": {"in_use": "", "saved": {LINED["name"]: LINED}}}
    app_mod.App._settings_from_llano(_App(), new, old)
    assert not has_lineup(store.saved()[LINED["name"]])   # the phone's copy (a Clear there arrives this way)
    last, _ = store.last_lineup()
    assert has_lineup(last) and last.name == LINED["name"]   # Bring back my line-up has his
