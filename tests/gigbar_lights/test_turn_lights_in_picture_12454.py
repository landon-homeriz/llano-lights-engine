"""Turn a light in the room picture (Llano BL #12454, the 11-14 video: a light drawn
catty-cornered needed a way to rotate it; the 11-15 correction: the drawing only, not how the lights aim).

Every light is drawn square to the way it faces, with a tick on its front. Selected under Move lights it can be
turned: 45 and 90 snap to the next eighth or quarter turn, 1 degree and a box for the fine adjust, Square up goes
back. The turn is saved with the room as `drawn`; nothing that aims reads it.
"""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import pytest

from tools.gigbar_lights.looks import Frame, LooksEngine
from tools.gigbar_lights.rig import default_rig
from tools.gigbar_lights.show_script import Section
from tools.gigbar_lights.venue import FT, Layout, LayoutStore, stage_layout

HERE = Path(__file__).parent
LINED = json.loads((HERE / "his_room_lined_up_12400.json").read_text())
SHOTS = os.environ.get("LLANO_LIGHTS_SHOTS")   # a folder: the before and after pictures land there


def _turned(d: dict) -> dict:
    d = copy.deepcopy(d)
    for i, fid in enumerate(d["fixtures"]):
        d["fixtures"][fid]["drawn"] = (i * 37) % 180 - 90
    return d


def _bytes(layout: dict) -> list:
    eng, rig = LooksEngine(), default_rig()
    eng.apply_venue(Layout.from_dict(layout))
    sec = Section("verse", 0, 100000, 1.0)
    out = []
    for i in range(400):
        eng.render(Frame(i / 40 * 2, 120.0, True, level=0.6, section=sec, track_key=7, now=i / 40), rig)
        out.append([(round(h.pan * 255), round(h.tilt * 255)) for bar in rig.bars for h in bar.movers])
    return out


@pytest.mark.parametrize("room", ["his lined-up room", "Draw my room, no line-up"])
def test_a_turn_in_the_picture_never_changes_what_the_heads_are_sent(room):
    base = LINED if room == "his lined-up room" else stage_layout(20 * FT, 22 * FT, 10 * FT).to_dict()
    assert _bytes(_turned(base)) == _bytes(base)
    a, b = Layout.from_dict(base), Layout.from_dict(_turned(base))
    assert a.positions() == b.positions()


def test_the_turn_is_saved_with_the_room_and_read_back(tmp_path):
    store = LayoutStore(tmp_path)
    store.save(Layout.from_dict(_turned(LINED)))
    back = json.loads((tmp_path / "layouts" / f"{LINED['name']}.json").read_text())
    assert back["fixtures"]["bar1"]["drawn"] == _turned(LINED)["fixtures"]["bar1"]["drawn"]
    assert "drawn" not in Layout.from_dict(LINED).to_dict()["fixtures"]["bar1"]   # untouched rooms stay as they were
    with pytest.raises(ValueError, match="drawn turn"):
        Layout.from_dict({**LINED, "fixtures": {**LINED["fixtures"], "bar1": {**LINED["fixtures"]["bar1"], "drawn": "x"}}})


@pytest.fixture
def gigbar_app():
    sys.path.insert(0, str(HERE.parents[1] / "tools/gigbar_lights/windows/src"))
    import gigbar_app as mod
    return mod


def test_turning_a_gigbar_and_a_tetra_in_a_real_browser(tmp_path, gigbar_app):
    pw = pytest.importorskip("playwright.sync_api")
    store = LayoutStore(tmp_path)
    store.save(Layout.from_dict(stage_layout(20 * FT, 22 * FT, 10 * FT).to_dict() | {"name": "barn", "label": "Barn"}))
    store.use("barn")
    pv = gigbar_app.Preview("", store)
    aims_before = json.dumps(gigbar_app.layout_payload(pv.layout)["derived"]["aims"])
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
                if SHOTS:
                    page.locator("#top").screenshot(path=os.path.join(SHOTS, "before.png"))

                def at(x, y):
                    # the designer is taller than the window since the head-limits controls (1.37.0), and typing in
                    # the angle box scrolls the page: bring the room picture back into view before each click
                    return page.evaluate("""([x, y]) => { TOP.scrollIntoView({block: "start"}); const r = TOP.getBoundingClientRect(), t = topScale(r.width, r.height);
                        return [r.left + t.ox + x * t.s, r.top + t.oy + y * t.s]; }""", [x, y])

                # pick GigBAR 1 (a click on it, no move) and turn it
                b1 = page.evaluate("() => L.fixtures.bar1")
                page.mouse.click(*at(b1["x"], b1["y"]))
                page.wait_for_function("() => document.querySelector('#selname').textContent === 'GigBAR 1'")
                assert page.is_visible("#selturn") and page.is_visible("#selturnhint")
                start = page.evaluate("() => drawnAngle('bar1')")
                assert 25 < start < 35   # square to its facing: turned in to the floor's middle
                assert page.input_value("#selang") == str(round(start))
                page.click("#selturn [data-turn='-45']")   # snaps to the eighth turn below: straight out
                page.wait_for_function("() => L.fixtures.bar1.drawn === 0")
                page.click("#selturn [data-turn='90']")
                page.wait_for_function("() => L.fixtures.bar1.drawn === 90")
                page.click("#selturn [data-turn='-90']")
                page.click("#selturn [data-turn='1']")
                page.wait_for_function("() => L.fixtures.bar1.drawn === 1")
                page.fill("#selang", "-3"); page.press("#selang", "Enter")
                page.wait_for_function("() => L.fixtures.bar1.drawn === -3")
                page.click("#undo")
                page.wait_for_function("() => L.fixtures.bar1.drawn === 1")
                page.fill("#selang", "0"); page.press("#selang", "Enter")
                page.wait_for_function("() => L.fixtures.bar1.drawn === 0")
                # a Tetra: square to its facing by default, a quarter turn, then Square up
                t3 = page.evaluate("() => L.fixtures.tetra3")
                page.mouse.click(*at(t3["x"], t3["y"]))
                page.wait_for_function("() => document.querySelector('#selname').textContent === 'Tetra 3'")
                page.click("#selturn [data-turn='90']")
                page.wait_for_function("() => typeof L.fixtures.tetra3.drawn === 'number'")
                page.click("#selsquare")
                page.wait_for_function("() => L.fixtures.tetra3.drawn === undefined")
                # GigBAR 2 square to the booth too, then save
                b2 = page.evaluate("() => L.fixtures.bar2")
                page.mouse.click(*at(b2["x"], b2["y"]))
                page.wait_for_function("() => document.querySelector('#selname').textContent === 'GigBAR 2'")
                page.fill("#selang", "0"); page.press("#selang", "Enter")
                page.wait_for_function("() => L.fixtures.bar2.drawn === 0")
                page.click("#save")
                page.wait_for_function("() => /Saved as/.test(document.querySelector('#dmsg').textContent)")
                if SHOTS:
                    page.locator("#top").screenshot(path=os.path.join(SHOTS, "after.png"))
                assert not errors, errors
            finally:
                browser.close()
        aims_after = json.dumps(gigbar_app.layout_payload(pv.layout)["derived"]["aims"])
    finally:
        pv.close()
    saved = json.loads((tmp_path / "layouts" / "barn.json").read_text())
    assert saved["fixtures"]["bar1"]["drawn"] == 0 and saved["fixtures"]["bar2"]["drawn"] == 0
    assert "drawn" not in saved["fixtures"]["tetra3"]
    assert aims_after == aims_before   # the heads aim exactly as before the turn
