"""Head limits on the laptop's screens, in headless Chromium (Llano PM #23796).

The path he takes: in the room designer, Add > Head limits puts the amber box over the dance floor, he drags
its corner and saves; at the venue, Line up my lights > Set how far the heads go steers every beam to the
highest, lowest, left and right he allows, keeps each and saves them with the room. The box is drawn on
the view from above, and the show aims from it at once.
"""
import io
import json
import sys
from pathlib import Path

import pytest

from tools.gigbar_lights.venue import LayoutStore

FT = 0.3048


@pytest.fixture
def gigbar_app():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/gigbar_lights/windows/src"))
    import gigbar_app as mod
    return mod


class _Req:
    def __init__(self, body: dict):
        raw = json.dumps(body).encode()
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = io.BytesIO(raw)


def test_spotaim_takes_a_height_for_the_highest_edge(tmp_path, gigbar_app):
    pv = gigbar_app.Preview("", LayoutStore(tmp_path))
    try:
        lay = pv.layout.to_dict()
        code, low = pv.layout_post(_Req({"action": "spotaim", "layout": lay, "target": {"x": 4.0, "y": 6.0}}))
        code2, high = pv.layout_post(_Req({"action": "spotaim", "layout": lay, "target": {"x": 4.0, "y": 6.0, "z": 2.0}}))
        assert code == code2 == 200 and low["poses"] != high["poses"]
        code, out = pv.layout_post(_Req({"action": "spotaim", "layout": lay, "target": {"x": 4.0, "y": 6.0, "z": 99}}))
        assert code == 400 and "outside the room" in out["error"]
    finally:
        pv.close()


def _browser(pw):
    try:
        return pw.chromium.launch()
    except Exception as e:  # noqa: BLE001 -- no browser on this machine
        pytest.skip(f"no headless chromium: {e}")


def test_the_box_is_added_dragged_and_saved_in_the_room_designer(tmp_path, gigbar_app):
    pw = pytest.importorskip("playwright.sync_api")
    pv = gigbar_app.Preview("", LayoutStore(tmp_path))
    try:
        with pw.sync_playwright() as p:
            browser = _browser(p)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 1400})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.add_init_script("try { localStorage.setItem('llano-units', 'ft'); } catch (e) {}")
                page.goto(pv.url + "preview?embed=1#designer")
                page.wait_for_function("() => typeof L !== 'undefined' && L && L.fixtures")
                page.click("#addlimits")
                page.wait_for_function("() => L.limits && L.limits.w > 0")
                assert page.text_content("#selname") == "Head limits"
                assert "Head limits added" in page.text_content("#dmsg")
                fl = page.evaluate("() => L.floor")
                assert page.evaluate("() => L.limits") == {k: fl[k] for k in ("x", "y", "w", "d")}

                def at(x, y):
                    return page.evaluate("""([x, y]) => { const r = TOP.getBoundingClientRect(), t = topScale(r.width, r.height);
                        return [r.left + t.ox + x * t.s, r.top + t.oy + y * t.s]; }""", [x, y])
                lm = page.evaluate("() => L.limits")
                a = at(lm["x"] + lm["w"], lm["y"] + lm["d"])
                b = at(lm["x"] + lm["w"], lm["y"] + lm["d"] - 4 * FT)
                page.mouse.move(a[0] + 7, a[1] + 7); page.mouse.down(); page.mouse.move(b[0] + 7, (a[1] + b[1]) / 2 + 7)
                page.mouse.move(b[0] + 7, b[1] + 7); page.mouse.up()
                d = page.evaluate("() => L.limits.d")
                assert abs(d - (lm["d"] - 4 * FT)) < FT, (lm, d)   # the grid snaps to whole feet
                page.fill("#sname", "Barn venue")
                page.click("#save")
                page.wait_for_function("() => document.querySelector('#dmsg').textContent.startsWith('Saved as')")
                saved = json.loads(next((tmp_path / "layouts").glob("*.json")).read_text())
                assert abs(saved["limits"]["d"] - d) < 0.02
                assert pv.layout.limits is not None   # the show aims from the box now
                # Remove takes it away again
                page.click("#addlimits")
                page.click("#seldel")
                page.wait_for_function("() => !L.limits")
                assert not errors, errors
            finally:
                browser.close()
    finally:
        pv.close()


def test_the_limits_are_set_on_site_with_the_real_beams(tmp_path, gigbar_app):
    pw = pytest.importorskip("playwright.sync_api")
    pv = gigbar_app.Preview("", LayoutStore(tmp_path))
    sent = []
    try:
        with pw.sync_playwright() as p:
            browser = _browser(p)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 1000})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("request", lambda r: sent.append(r.post_data) if r.url.endswith("/aim") else None)
                page.goto(pv.url + "lineup.html")
                page.wait_for_function("() => typeof L !== 'undefined' && L && L.fixtures")
                page.click("#lulimits")
                page.wait_for_function("() => lu.step === 6 && lim.box")
                assert page.is_visible("[data-limedge=far]")
                box0 = page.evaluate("() => ({...lim.box})")
                page.click("[data-limedge=far]")
                page.wait_for_function("() => lim.pt && !lu.busy")
                assert "head height" in page.text_content("#limsay")
                for _ in range(3):   # the highest edge comes in: three presses down, toward the bars
                    page.keyboard.press("ArrowDown")
                    page.wait_for_function("() => !lu.busy")
                page.click("#limkeep")   # kept: the next edge (the lowest) is picked for him
                page.wait_for_function("() => lim.edge === 'near' && lim.pt && !lu.busy")
                page.click("#limkeep")
                page.wait_for_function("() => lim.edge === 'left' && !lu.busy")
                page.keyboard.press("Shift+ArrowRight")
                page.wait_for_function("() => !lu.busy")
                page.click("#limkeep")
                page.wait_for_function("() => lim.edge === 'right' && !lu.busy")
                page.click("#limkeep")
                assert "All four kept" in page.text_content("#limsay")
                box = page.evaluate("() => ({...lim.box})")
                assert abs(box["y1"] - (box0["y1"] - 3 * 0.15)) < 0.01 and abs(box["x0"] - (box0["x0"] + 5 * 0.15)) < 0.01
                aims = [json.loads(s) for s in sent if s]
                assert any(a.get("poses") and len(a["poses"]) == 4 for a in aims)   # every head was lit on the point
                page.click("#limsave")
                page.wait_for_function("() => L.limits && lu.step === 1")
                page.wait_for_function("() => document.querySelector('#lusay').textContent.startsWith('Saved for this venue')")
                saved = json.loads(next((tmp_path / "layouts").glob("*.json")).read_text())
                assert abs(saved["limits"]["y"] + saved["limits"]["d"] - box["y1"]) < 0.02
                assert abs(saved["limits"]["x"] - box["x0"]) < 0.02
                assert pv.layout.limits is not None
                assert json.loads(sent[-1] or "{}") == {}   # leaving the step lets the heads go back to the show
                assert not errors, errors
            finally:
                browser.close()
    finally:
        pv.close()


def test_a_save_that_fails_says_so_and_keeps_his_edges(tmp_path, gigbar_app):
    pw = pytest.importorskip("playwright.sync_api")
    pv = gigbar_app.Preview("", LayoutStore(tmp_path))
    try:
        with pw.sync_playwright() as p:
            browser = _browser(p)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 1000})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(pv.url + "lineup.html")
                page.wait_for_function("() => typeof L !== 'undefined' && L && L.fixtures")
                page.click("#lulimits")
                page.wait_for_function("() => lu.step === 6 && lim.box")
                page.click("[data-limedge=far]")
                page.wait_for_function("() => lim.pt && !lu.busy")
                page.keyboard.press("ArrowDown"); page.wait_for_function("() => !lu.busy")
                page.click("#limkeep")
                page.wait_for_function("() => lim.edge === 'near' && !lu.busy")
                kept = page.evaluate("() => ({...lim.box})")

                def refuse(route):
                    body = json.loads(route.request.post_data or "{}")
                    if body.get("action") == "save":
                        return route.fulfill(status=400, content_type="application/json", body=json.dumps({"error": "disk full"}))
                    return route.continue_()
                page.route("**/layout", refuse)
                page.click("#limsave")
                page.wait_for_function("() => document.querySelector('#limsay').textContent.startsWith('Not saved')")
                assert "disk full" in page.text_content("#limsay")
                assert page.evaluate("() => lu.step") == 6 and page.evaluate("() => ({...lim.box})") == kept
                assert page.evaluate("() => L.limits") is None   # the room on screen is put back
                assert not list((tmp_path / "layouts").glob("*.json")) if (tmp_path / "layouts").exists() else True
                page.unroute("**/layout")
                page.click("#limsave")   # the app answers again: it saves
                page.wait_for_function("() => L.limits && lu.step === 1")
                assert not errors, errors
            finally:
                browser.close()
    finally:
        pv.close()
