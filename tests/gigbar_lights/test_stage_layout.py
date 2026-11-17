"""The stage venue and the room he changes at the venue (Llano BL #12344, his 2026-11-14 ruling).

He puts the GigBARs on the front corners of a 20 ft stage, raised, turned in to the dance floor, and he
can't see the room until he arrives. Three numbers (stage width, dance floor depth, GigBAR height above
the dance floor) draw the room; at the venue he drags and sizes the dance floor, the booth, a stage, a
table area or a no-beam zone on the laptop, in feet, and saves it by name. The moving looks keep their
beams out of the table areas and no-beam zones.
"""
import io
import json
import math
import os

import pytest

from tools.gigbar_lights import venue
from tools.gigbar_lights.venue import FT, HEAD_CLEAR, STAGE_INSET, Layout, LayoutStore, Zone, presets, stage_layout


def _close(a, b, tol=0.02):
    return abs(a - b) <= tol


def test_three_numbers_put_the_bars_on_the_stage_corners_facing_the_floor_middle():
    lay = stage_layout(20 * FT, 22 * FT, 10 * FT)
    stage = next(z for z in lay.zones if z.kind == "stage")
    b1, b2 = lay.spots["bar1"], lay.spots["bar2"]
    # 2 ft in from the side and front edges, so the tripod legs sit on the stage
    assert _close(b1.x, stage.x + STAGE_INSET) and _close(b2.x, stage.x + stage.w - STAGE_INSET)
    assert _close(b1.y, stage.y + stage.d - STAGE_INSET) and _close(b2.y, b1.y)
    assert _close((b2.x - b1.x) / FT, 16, 0.1)   # the room's "about 16 ft between them"
    assert _close(b1.z, 10 * FT) and _close(b2.z, 10 * FT)
    # the stage is 20 ft wide and the floor is as wide as the stage, 22 ft deep, right in front of it
    assert _close(stage.w, 20 * FT) and _close(lay.floor.w, stage.w) and _close(lay.floor.d, 22 * FT)
    assert _close(lay.floor.y, stage.y + stage.d) and _close(lay.floor.cx, stage.cx)
    # each bar faces the middle of the dance floor, turned in about 30 degrees, mirror images
    for fid in ("bar1", "bar2"):
        s = lay.spots[fid]
        want = math.degrees(math.atan2(lay.floor.cx - s.x, lay.floor.cy - s.y))
        assert _close(lay.facing(fid), want, 1e-6)
    assert 25 < lay.facing("bar1") < 35 and _close(lay.facing("bar2"), -lay.facing("bar1"), 1e-6)
    # the booth is on the stage, every light inside the room, and Center sends the heads to the floor
    assert stage.has(lay.booth.cx, lay.booth.cy)
    for s in lay.spots.values():
        assert 0 <= s.x <= lay.room[0] and 0 <= s.y <= lay.room[1] and 0 <= s.z <= lay.room[2]
    for b in (1, 2):
        for m, head in enumerate(lay.heads(b)):
            pan, tilt = lay.aim(b, head, lay.ref_target("center"), m)
            hit = _land(lay, b, m, pan, tilt)
            assert _close(hit[0], lay.floor.cx, 0.05) and _close(hit[1], lay.floor.cy, 0.05)


def _land(lay, b, m, pan, tilt):
    head = lay.heads(b)[m]
    d = lay.beam(b, head, pan, tilt, m)
    t = -head[2] / d[2]
    return head[0] + d[0] * t, head[1] + d[1] * t


@pytest.mark.parametrize("args, words", [
    ((3 * FT, 22 * FT, 10 * FT), "stage width"),
    ((20 * FT, 0.0, 10 * FT), "dance floor depth"),
    ((20 * FT, 22 * FT, 40 * FT), "GigBAR height"),
    ((float("nan"), 22 * FT, 10 * FT), "stage width must be a number"),
    ((None, 22 * FT, 10 * FT), "stage width must be a number"),
    (("20", 22 * FT, 10 * FT), "stage width must be a number"),
])
def test_a_number_off_says_which_one_in_plain_words(args, words):
    with pytest.raises(ValueError, match=words):
        stage_layout(*args)


def test_the_stage_preset_is_his_wedding_and_round_trips():
    lay = presets()["stage"]
    assert lay.preset and "Stage" in lay.label
    again = Layout.from_dict(json.loads(json.dumps(lay.to_dict())))
    assert again.zones == lay.zones and again.floor == lay.floor
    assert [(s.x, s.y, s.z) for s in again.spots.values()] == [(s.x, s.y, s.z) for s in lay.spots.values()]


def test_saved_as_a_named_layout_with_its_room_elements(tmp_path):
    store = LayoutStore(tmp_path)
    lay = stage_layout(18 * FT, 20 * FT, 9 * FT)
    lay.zones.append(Zone(0.5, lay.floor.y, 2.5, 4.0, "tables", "Head table"))
    lay.label = "Rio Grande ballroom"
    saved = store.save(lay)
    store.use(saved.name)
    back = store.current()
    assert back.label == "Rio Grande ballroom" and not back.preset
    assert [(z.kind, z.label) for z in back.zones] == [("stage", "Stage"), ("tables", "Head table")]
    # the preset itself is never overwritten
    assert presets()["stage"].zones[0].w == pytest.approx(20 * FT, abs=0.01)


def test_a_layout_without_room_elements_reads_back_unchanged():
    d = presets()["wedding-hall-front"].to_dict()
    assert "zones" not in d
    assert Layout.from_dict(d).to_dict() == d


@pytest.mark.parametrize("zones, words", [
    ([{"kind": "pool", "x": 0, "y": 0, "w": 1, "d": 1}], "stage, tables or a no-beam zone"),
    ([{"kind": "tables", "x": 15, "y": 0, "w": 5, "d": 1}], "runs past the room's walls"),
    ([{"kind": "nobeam", "x": 0, "y": 0, "w": 0.1, "d": 1}], "no beams width"),
    ("tables", "zones must be a list"),
    ([{"kind": "tables", "x": 0, "y": 0, "w": 1, "d": 1}] * 13, "at most 12"),
])
def test_a_bad_room_element_is_refused_in_plain_words(zones, words):
    d = presets()["wedding-hall-front"].to_dict()
    d["zones"] = zones
    with pytest.raises(ValueError, match=words):
        Layout.from_dict(d)


def _with_tables_behind_the_floor():
    lay = stage_layout(20 * FT, 22 * FT, 10 * FT)
    fl = lay.floor
    lay.zones.append(Zone(0.0, fl.y + fl.d, lay.room[0], lay.room[1] - fl.y - fl.d, "tables"))
    return lay


def test_ceiling_crosses_the_room_without_tables_and_stops_at_the_floor_with_them():
    plain = stage_layout(20 * FT, 22 * FT, 10 * FT)
    assert all(_close(p[1], plain.room[1]) and _close(p[2], HEAD_CLEAR) for p in plain.targets()["ceiling"])
    lay = _with_tables_behind_the_floor()
    fl = lay.floor
    for p in lay.targets()["ceiling"]:
        assert _close(p[1], fl.y + fl.d) and p[2] == 0.0 and fl.x <= p[0] <= fl.x + fl.w


def test_the_moving_looks_never_land_a_beam_on_the_tables():
    lay = _with_tables_behind_the_floor()
    lay.zones.append(Zone(0.0, lay.floor.y, lay.floor.x, lay.floor.d, "nobeam"))   # left of the floor
    pos, heads = lay.positions(), lay.all_heads()
    for name, poses in pos.items():
        for (b, m, head), (pan, tilt) in zip(heads, poses):
            x, y = _land(lay, b, m, pan, tilt)
            assert not any(z.has(x + 0.05, y - 0.05) and z.has(x - 0.05, y - 0.05) for z in lay.beam_free()), (name, b, m, x, y)


def test_keep_out_moves_only_a_floor_level_target_inside_a_beam_free_zone():
    lay = _with_tables_behind_the_floor()
    fl = lay.floor
    assert lay.keep_out((1.0, fl.y + fl.d + 1.0, 0.0)) == (fl.x, fl.y + fl.d, 0.0)
    assert lay.keep_out((fl.cx, fl.cy, 0.0)) == (fl.cx, fl.cy, 0.0)            # on the floor: kept
    high = (1.0, fl.y + fl.d + 1.0, HEAD_CLEAR)
    assert lay.keep_out(high) == high                                          # over their heads: kept
    stage_only = stage_layout(20 * FT, 22 * FT, 10 * FT)                        # a stage is not beam-free
    assert stage_only.keep_out((stage_only.booth.cx, 0.5, 0.0)) == (stage_only.booth.cx, 0.5, 0.0)


def test_a_steered_spot_and_the_line_up_still_go_where_he_puts_them():
    """A spotlight on the cake table is his call: aim() itself never moves a target."""
    lay = _with_tables_behind_the_floor()
    t = (2.0, lay.floor.y + lay.floor.d + 1.5, 0.0)
    pan, tilt = lay.aim(1, lay.heads(1)[0], t, 0)
    x, y = _land(lay, 1, 0, pan, tilt)
    assert _close(x, t[0], 0.05) and _close(y, t[1], 0.05)


# --- the laptop app: Stage setup posts three numbers, and the room is changed by dragging -------------

class _Req:
    def __init__(self, body: dict):
        raw = json.dumps(body).encode()
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = io.BytesIO(raw)


@pytest.fixture
def gigbar_app():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/gigbar_lights/windows/src"))
    import gigbar_app as mod
    return mod


def test_stage_setup_on_the_laptop_aims_the_show_from_it_without_saving(tmp_path, gigbar_app):
    pv = gigbar_app.Preview("", LayoutStore(tmp_path))
    try:
        code, out = pv.layout_post(_Req({"action": "stage", "stage_w": 20 * FT, "floor_d": 22 * FT, "bar_h": 10 * FT}))
        assert code == 200 and pv.tried and pv.layout.zones[0].kind == "stage"
        assert out["layout"]["zones"][0]["kind"] == "stage" and "derived" in out["layout"]
        assert not (tmp_path / "layouts").exists()   # nothing saved until he presses Save my layout
        code, out = pv.layout_post(_Req({"action": "stage", "stage_w": "wide", "floor_d": 6, "bar_h": 3}))
        assert code == 400 and "stage width must be a number" in out["error"]
    finally:
        pv.close()


def test_the_room_is_changed_by_dragging_in_a_real_browser(tmp_path, gigbar_app):
    """The path he takes at the venue, in headless Chromium: Show Designer, Stage setup from three numbers,
    Add a table area, drag the dance floor's corner to size it, drag a GigBAR, type a bar's height in feet,
    Save as a named layout. Nothing typed into a file."""
    pw = pytest.importorskip("playwright.sync_api")
    pv = gigbar_app.Preview("", LayoutStore(tmp_path))
    try:
        with pw.sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception as e:  # noqa: BLE001 -- no browser on this machine
                pytest.skip(f"no headless chromium: {e}")
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 1400})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.add_init_script("try { localStorage.setItem('llano-units', 'ft'); } catch (e) {}")
                page.goto(pv.url + "preview?embed=1#designer")
                page.wait_for_function("() => typeof L !== 'undefined' && L && L.fixtures")
                assert page.is_checked("#edit")

                # 1. Stage setup: 20 ft stage, 22 ft floor, bars 10 ft up
                page.fill("#qsw", "20"); page.fill("#qsd", "22"); page.fill("#qsh", "10")
                page.click("#qsgo")
                page.wait_for_function("() => L.zones && L.zones.some(z => z.kind === 'stage')")
                assert "16 ft apart at 10 ft" in page.text_content("#dmsg")
                assert pv.layout.zones[0].kind == "stage"   # the show aims from it now

                # 2. Add a table area
                page.click("[data-add=tables]")
                page.wait_for_function("() => L.zones.some(z => z.kind === 'tables')")
                assert page.is_visible("#selrow") and page.text_content("#selname") == "Tables"

                def at(x, y):   # a room point (meters) as a page point on the view from above
                    return page.evaluate("""([x, y]) => { const r = TOP.getBoundingClientRect(), t = topScale(r.width, r.height);
                        return [r.left + t.ox + x * t.s, r.top + t.oy + y * t.s]; }""", [x, y])

                def drag(a, b):
                    page.mouse.move(*a); page.mouse.down(); page.mouse.move((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                    page.mouse.move(*b); page.mouse.up()

                # 3. the dance floor's corner, dragged 4 ft further out: it gets deeper
                fl = page.evaluate("() => L.floor")
                grab = at(fl["x"] + fl["w"], fl["y"] + fl["d"])
                grab = [grab[0] + 7, grab[1] + 7]   # the handle sits just outside the corner (HANDLE)
                to = at(fl["x"] + fl["w"], fl["y"] + fl["d"] + 4 * FT)
                drag(grab, [to[0] + 7, to[1] + 7])
                d_after = page.evaluate("() => L.floor.d")
                assert _close(d_after, fl["d"] + 4 * FT, 0.1), (fl, d_after)
                assert page.text_content("#selname") == "Dance floor"
                assert page.input_value("#seld") == "26"

                # 4. type the floor's width in feet
                page.fill("#selw", "18"); page.press("#selw", "Enter")
                page.wait_for_function("() => Math.abs(L.floor.w - 18 * 0.3048) < 0.01")

                # 4b. a Freedom Stick standing on the floor's corner is still dragged as a light, not a resize
                s4 = page.evaluate("() => L.fixtures.stick4")
                drag(at(s4["x"], s4["y"]), at(s4["x"] + 2 * FT, s4["y"]))
                assert page.text_content("#selname") == "Freedom Stick 4"
                assert _close(page.evaluate("() => L.floor.w"), 18 * FT)

                # 5. drag GigBAR 2 a foot toward the middle, then type its height
                b2 = page.evaluate("() => L.fixtures.bar2")
                drag(at(b2["x"], b2["y"]), at(b2["x"] - FT, b2["y"]))
                assert _close(page.evaluate("() => L.fixtures.bar2.x"), b2["x"] - FT, 0.1)
                assert page.text_content("#selname") == "GigBAR 2" and page.is_visible("#selh")
                page.fill("#selh", "9"); page.press("#selh", "Enter")
                page.wait_for_function("() => Math.abs(L.fixtures.bar2.z - 9 * 0.3048) < 0.01")

                # 6. Undo puts the height back
                page.click("#undo")
                page.wait_for_function(f"() => Math.abs(L.fixtures.bar2.z - {10 * FT}) < 0.01")

                # 7. save as a named layout
                page.fill("#sname", "Rio Grande ballroom")
                page.click("#save")
                page.wait_for_function("() => /Saved as/.test(document.querySelector('#dmsg').textContent)")
                assert not errors, errors
            finally:
                browser.close()
    finally:
        pv.close()
    files = list((tmp_path / "layouts").glob("*.json"))
    assert len(files) == 1
    saved = json.loads(files[0].read_text(encoding="utf-8"))
    assert saved["label"] == "Rio Grande ballroom"
    assert sorted(z["kind"] for z in saved["zones"]) == ["stage", "tables"]
    assert _close(saved["floor"]["w"], 18 * FT) and _close(saved["floor"]["d"], 26 * FT, 0.1)
    assert _close(saved["fixtures"]["bar2"]["z"], 10 * FT)
    assert json.loads((tmp_path / "venue.json").read_text())["current"] == files[0].stem
