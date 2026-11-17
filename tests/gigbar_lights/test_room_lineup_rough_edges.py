"""Rough edges on the room picture, Line up my lights and the patch sheet (Llano BL #11473). A helper
clicked through 1.27.1 at 1366x768 and 1024x700 before the 2026-11-25 wedding and found: Done looked dead
with the line-up not saved, "Lights on" read as a state, the Saved step never showed, Draw my room answered
a 0 in meters from the server, Save my layout saved under a made-up name, /preview and /patch.html had no
way back, new room elements landed on a stick one on top of another, and the patch sheet said "out" on one
row and "behind it" on another."""
from __future__ import annotations

import ast
import operator
import re
import sys
from pathlib import Path

import pytest

from tools.gigbar_lights import patch_sheet, settings_contract
from tools.gigbar_lights.venue import DEFAULT_LAYOUT, FT, STAGE_INSET, Layout, LayoutStore, presets, stage_layout

SRC = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"
PAGE = (SRC / "preview.html").read_text(encoding="utf-8")
NEED_NAME = "Type the venue's name first, for example the hall's name, then press Save my layout."


# --- the words on the page -------------------------------------------------------------------

def test_done_with_the_line_up_not_saved_offers_the_choice():
    for s in ("Your line-up is not saved yet.", "the lights go back to where they were lined up before.",
              '>Save and finish</button>', '>Finish without saving</button>', '>Keep lining up</button>',
              '>Leave anyway</button>', "Type the venue's name, then press Save and finish.", "if (finishing) return;"):
        assert s in PAGE, s
    assert "Line-up done. Save my layout to keep it at this venue.\" : \"Line-up done.\");\n  // back" not in PAGE


def test_the_lights_button_says_what_a_press_does_and_the_state_beside_it():
    for s in ('"Turn the lights off" : "Turn the lights on"', '"The lights are on." : "The lights are off."',
              'id="lulightsstate"', 'id="lightsstate"', 'setAttribute("aria-pressed", String(lightsOn))'):
        assert s in PAGE, s
    assert '? "Lights on" : "Lights off"' not in PAGE


def test_a_save_on_this_page_shows_the_saved_step_before_leaving():
    assert "Saved. This line-up is kept for this venue." in PAGE and "setTimeout(leaveLineup, 1500)" in PAGE
    assert 'data-panel="5"' in PAGE


def test_save_my_layout_never_makes_up_a_name():
    assert NEED_NAME in PAGE
    assert '(L.label + " (mine)")' not in PAGE   # the old made-up name
    assert '$("#sname").value = s.layout.preset ? "" : s.layout.label' in PAGE   # his own venue fills the box


def test_the_way_back_shows_outside_the_window_and_never_on_paper():
    assert 'id="backlink" href="/">&#8592; Back to Llano Lights</a>' in PAGE
    assert ".embed header" in PAGE and "@media print { #backlink { display:none; } }" in PAGE


def test_a_draw_my_room_refusal_never_says_not_applied():
    assert '"That did not change the room: "' in PAGE and "postLayout({action: \"stage\"" in PAGE
    assert "qsRefused);" in PAGE


def _qs_limits() -> dict:
    """The page's Draw my room limits, in meters, as numbers (FT and arithmetic only)."""
    ops = {ast.Add: operator.add, ast.Mult: operator.mul, ast.Sub: operator.sub}

    def ev(n):
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Name) and n.id == "FT":
            return FT
        if isinstance(n, ast.BinOp) and type(n.op) in ops:
            return ops[type(n.op)](ev(n.left), ev(n.right))
        raise ValueError(ast.dump(n))

    out = {}
    for box, lo, hi in re.findall(r"(qs[wdh]): \{what: [^}]*?lo: ([^,]+), hi: ([\d.]+)\}", PAGE):
        out[box] = (ev(ast.parse(lo, mode="eval").body), float(hi))
    return out


def test_the_page_limits_are_the_servers():
    lim = _qs_limits()
    assert set(lim) == {"qsw", "qsd", "qsh"}
    assert lim["qsw"][0] == pytest.approx(2 * STAGE_INSET + 1.0)
    good = {"qsw": 8 * FT, "qsd": 7 * FT, "qsh": 4 * FT}
    names = {"qsw": "stage_w", "qsd": "floor_d", "qsh": "bar_h"}
    for box, (lo, hi) in lim.items():
        for v in (lo, hi):
            stage_layout(**{**{names[k]: g for k, g in good.items()}, names[box]: v})   # the server takes both ends
        for v in (lo - 0.01, hi + 0.01):
            with pytest.raises(ValueError, match="must be between"):
                stage_layout(**{**{names[k]: g for k, g in good.items()}, names[box]: v})


# --- the patch sheet ---------------------------------------------------------------------------

def test_in_front_of_and_behind_the_booths_center_on_every_row():
    lay = presets()["small-room-front"]
    lay.spots["tetra1"].y = lay.booth.y + lay.booth.d / 2 - 3 * FT   # 3 ft behind the booth's center
    rs = {r["id"]: r for r in patch_sheet.rows(settings_contract.defaults()["rig"], lay)}
    assert rs["stick3"]["where"].endswith("22 ft in front of the booth's center")
    assert rs["tetra1"]["where"].endswith("3 ft behind the booth's center")
    words = " ".join(r["where"] for r in rs.values())
    assert " out" not in words and "behind it" not in words


def test_the_patch_sheet_has_the_way_back_and_prints_without_it():
    page = patch_sheet.sheet_html(patch_sheet.rows(settings_contract.defaults()["rig"]))
    assert '<a class=b id=backlink href="/">Back to Llano Lights</a>' in page
    assert "@media print{body{margin:10mm} .p,.b{display:none}}" in page
    assert 'has("embed")' in page


# --- in a real browser --------------------------------------------------------------------------

class FakeApp:
    def __init__(self):
        self.doctor = None

    def touch(self):
        pass

    def layout_changed(self, lay, saved, use=True):
        pass

    def layout_removed(self, name):
        pass


@pytest.fixture
def preview(tmp_path):
    sys.path.insert(0, str(SRC))
    import gigbar_app
    store = LayoutStore(tmp_path / "profile")
    store.use("small-room-front")
    p = gigbar_app.Preview("", store, app=FakeApp())
    yield p
    p.close()


@pytest.fixture
def page(preview):
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            pg = browser.new_page(viewport={"width": 1024, "height": 700})
            pg.add_init_script("try { localStorage.setItem('llano-units', 'ft'); } catch (e) {}")
            yield pg
        finally:
            browser.close()


def _open(pg, url):
    pg.goto(url)
    pg.wait_for_function("() => typeof L !== 'undefined' && L && L.fixtures")


def test_room_picture_checks_boxes_refuses_no_name_and_places_zones(preview, page):
    _open(page, preview.url + "preview")
    assert page.is_visible("#backlink")
    page.evaluate("""() => { window.__sent = 0; const f = window.fetch; window.fetch = (u, o) => {
        if (o && o.body && String(o.body).includes('"stage"')) window.__sent++; return f(u, o); }; }""")
    for bad in ("0", "", "9999"):
        page.fill("#qsw", bad)
        page.click("#qsgo")
        assert page.text_content("#qswerr") == "Type the stage's width in feet, between 8 and 98."
    page.select_option("#units", "m")
    page.fill("#qsw", "0")
    page.click("#qsgo")
    assert page.text_content("#qswerr") == "Type the stage's width in meters, between 2.3 and 30."
    assert page.evaluate("window.__sent") == 0
    page.select_option("#units", "ft")

    before = sorted(preview.store.saved())
    assert page.input_value("#sname") == ""
    page.click("#save")
    page.wait_for_timeout(300)
    assert page.text_content("#dmsg") == NEED_NAME and page.evaluate("document.activeElement.id") == "sname"
    assert sorted(preview.store.saved()) == before

    for k in ("stage", "tables", "nobeam"):
        page.click(f"[data-add={k}]")
    zs, lights, fl = page.evaluate("""() => [L.zones.slice(-3), Object.entries(L.fixtures).filter(([id]) => present(id))
        .map(([, f]) => [f.x, f.y]), L.floor]""")
    hit = lambda a, c: a["x"] < c["x"] + c["w"] and c["x"] < a["x"] + a["w"] and a["y"] < c["y"] + c["d"] and c["y"] < a["y"] + a["d"]
    assert not any(hit(zs[i], zs[j]) for i in range(3) for j in range(i + 1, 3))
    assert not any(z["x"] <= x <= z["x"] + z["w"] and z["y"] <= y <= z["y"] + z["d"] for z in zs for x, y in lights)
    assert not any(hit(z, fl) for z in zs)   # the dance floor is drawn over room elements

    _open(page, preview.url + "preview?embed=1")
    assert not page.is_visible("#backlink")


def test_done_with_the_line_up_not_saved_saves_and_finishes_or_not(preview, page):
    _open(page, preview.url + "lineup.html")
    page.evaluate("dirty = true")   # what Mirror or a failed keep leaves
    page.click("#ludone")
    assert page.is_visible("#luchoice") and page.url.endswith("/lineup.html")
    page.click("#lusavefinish")
    page.wait_for_timeout(300)
    assert page.text_content("#luchoiceerr") == "Type the venue's name, then press Save and finish." and not preview.store.saved()
    page.fill("#lusavename", "Rio Grande ballroom")
    page.click("#lusavefinish")
    page.wait_for_selector("#lusaved", state="visible")
    page.wait_for_url(preview.url, timeout=5000)
    assert [lay.label for lay in preview.store.saved().values()] == ["Rio Grande ballroom"]

    _open(page, preview.url + "lineup.html?embed=1")
    assert page.text_content("#lulights") == "Turn the lights off" and page.text_content("#lulightsstate") == "The lights are on."
    page.click("#lulights")
    assert page.text_content("#lulights") == "Turn the lights on" and page.text_content("#lulightsstate") == "The lights are off."
    page.evaluate("dirty = true")
    page.click("#ludone")
    assert page.input_value("#lusavename") == "Rio Grande ballroom"
    page.click("#lunosave")
    page.wait_for_url(preview.url + "preview?embed=1", timeout=5000)
    assert len(preview.store.saved()) == 1


def test_a_late_try_reply_never_undoes_a_drag(preview, page):
    """test_stage_layout's drag test missed about 1 run in 8 on main, always by half the drag: the try that
    Add sends 120 ms later went out mid-drag with the half-dragged floor, and its reply, landing after the
    drag, put that stale copy back. Here that reply is held so it always lands last."""
    page.set_viewport_size({"width": 1280, "height": 1400})   # the whole view from above on screen
    _open(page, preview.url + "preview#designer")
    page.evaluate("""() => { const f = window.fetch; let held = false; window.fetch = (u, o) => {
        const slow = !held && o && o.body && String(o.body).includes('"action":"try"');
        if (slow) held = true;   // only the first try (Add's): its reply lands after the drag's own try
        return slow ? new Promise(r => setTimeout(() => r(f(u, o)), 700)) : f(u, o); }; }""")
    page.click("[data-add=tables]")
    fl = page.evaluate("() => L.floor")

    def at(x, y):
        return page.evaluate("""([x, y]) => { const r = TOP.getBoundingClientRect(), t = topScale(r.width, r.height);
            return [r.left + t.ox + x * t.s, r.top + t.oy + y * t.s]; }""", [x, y])
    a = at(fl["x"] + fl["w"], fl["y"] + fl["d"]); a = [a[0] + 7, a[1] + 7]
    b = at(fl["x"] + fl["w"], fl["y"] + fl["d"] + 4 * FT); b = [b[0] + 7, b[1] + 7]
    page.mouse.move(*a); page.mouse.down(); page.mouse.move(a[0], (a[1] + b[1]) / 2)
    page.wait_for_timeout(200)          # the try from Add goes out now, with the half-dragged floor
    page.mouse.move(*b); page.mouse.up()
    page.wait_for_timeout(1500)         # every held reply is back
    d = page.evaluate("() => L.floor.d")   # 4 ft further, snapped to whole feet; half the drag was the old miss
    assert abs(d - round((fl["d"] + 4 * FT) / FT) * FT) < 0.02, (fl["d"], d)



# --- the lead's review of PR #152: the server read back after each way out --------------------------

import copy  # noqa: E402
import json  # noqa: E402
import urllib.request  # noqa: E402


def _venue(label):
    return Layout.from_dict({**copy.deepcopy(presets()[DEFAULT_LAYOUT]).to_dict(), "name": label, "label": label, "preset": False})


def _post(pv, msg):
    req = urllib.request.Request(pv.url + "layout", json.dumps(msg).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Llano-Token": pv.token})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _change_and_try(pg, pv):
    """He changes the room on the line-up page: the show plays it (a try), nothing saved."""
    pg.evaluate("() => { L = JSON.parse(JSON.stringify(L)); L.fixtures.bar1.x = Math.round((L.fixtures.bar1.x + 0.5) * 100) / 100; dirty = true; tryLive(); }")
    for _ in range(50):
        if pv.tried:
            return
        pg.wait_for_timeout(50)
    raise AssertionError("the try never reached the app")


def _finish_without_saving(pg, pv, embed=False):
    pg.click("#ludone")
    pg.wait_for_selector("#luchoice", state="visible")
    pg.click("#lunosave")
    pg.wait_for_url(pv.url + ("preview?embed=1" if embed else ""), timeout=5000)


def test_finish_without_saving_puts_back_the_saved_venue_that_was_in_use(preview, page):
    rio = preview.store.save(_venue("Rio Grande ballroom")).name
    preview.store.use(rio)
    preview.layout, preview.tried = preview.store.current(), False
    was = preview.layout.to_dict()
    _open(page, preview.url + "lineup.html")
    _change_and_try(page, preview)
    assert preview.layout.to_dict() != was
    _finish_without_saving(page, preview)
    assert preview.layout.to_dict() == was and not preview.tried
    assert preview.store.current_name() == rio and list(preview.store.saved()) == [rio]


def test_finish_without_saving_after_draw_my_room_keeps_the_drawn_room_and_saves_nothing(preview, page):
    """Draw my room's try is named "stage", like a ready-made room: put back by name, it swapped that room in."""
    _post(preview, {"action": "stage", "stage_w": 6.1, "floor_d": 6.7, "bar_h": 3.0})
    drawn, current = preview.layout.to_dict(), preview.store.current_name()
    assert preview.tried and drawn != presets()["stage"].to_dict()
    _open(page, preview.url + "lineup.html?embed=1")
    _change_and_try(page, preview)
    _finish_without_saving(page, preview, embed=True)
    assert preview.layout.to_dict() == drawn and preview.tried            # his drawn room still plays, as a try
    assert preview.store.current_name() == current and not preview.store.saved()   # nothing saved, no new venue


def test_a_save_whose_reload_fails_still_shows_saved_and_leaves(preview, page):
    _open(page, preview.url + "lineup.html")
    page.evaluate("""() => { dirty = true; let saved = false; const f = window.fetch; window.fetch = (u, o) => {
        if (o && o.body && String(o.body).includes('"action":"save"')) saved = true;
        else if (saved && String(u).startsWith('/layout') && !(o && o.method === 'POST')) return Promise.reject(new TypeError('app restarting'));
        return f(u, o); }; }""")
    page.click("#ludone")
    page.fill("#lusavename", "Rio Grande ballroom")
    page.click("#lusavefinish")
    page.wait_for_selector("#lusaved", state="visible", timeout=4000)
    page.wait_for_url(preview.url, timeout=5000)
    assert [lay.label for lay in preview.store.saved().values()] == ["Rio Grande ballroom"]


def test_a_failed_finish_without_saving_offers_leave_anyway(preview, page):
    _open(page, preview.url + "lineup.html")
    page.evaluate("""() => { dirty = true; const f = window.fetch; window.fetch = (u, o) =>
        String(u).startsWith('/layout') && o && o.method === 'POST' ? Promise.reject(new TypeError('no answer')) : f(u, o); }""")
    page.click("#ludone")
    page.click("#lunosave")
    page.wait_for_selector("#luleave", state="visible")
    assert page.text_content("#luchoiceerr").startswith("That did not finish:") and page.url.endswith("/lineup.html")
    page.click("#luleave")
    page.wait_for_url(preview.url, timeout=5000)


def test_the_line_up_is_ended_with_keepalive_when_the_page_leaves(preview, page):
    for how in ("nothing to save", "finish without saving"):
        _open(page, preview.url + "lineup.html")
        page.evaluate("""(dirtyNow) => { localStorage.setItem('sent', '[]'); if (dirtyNow) dirty = true;
            const f = window.fetch; window.fetch = (u, o) => {
              const log = JSON.parse(localStorage.getItem('sent')); log.push([String(u), !!(o && o.keepalive)]);
              localStorage.setItem('sent', JSON.stringify(log)); return f(u, o); }; }""", how != "nothing to save")
        page.click("#ludone")
        if how != "nothing to save":
            page.click("#lunosave")
        page.wait_for_url(preview.url, timeout=5000)
        sent = json.loads(page.evaluate("localStorage.getItem('sent')"))
        ends = [k for u, k in sent if u.startswith("/lineup?")]
        assert ends and ends[-1], (how, sent)


def test_done_while_the_line_up_is_still_saving_makes_one_venue(preview, page):
    _open(page, preview.url + "lineup.html")
    page.evaluate("""() => { const f = window.fetch; window.fetch = (u, o) =>
        o && o.body && String(o.body).includes('"action":"save"') ? new Promise(r => setTimeout(() => r(f(u, o)), 700)) : f(u, o);
        dirty = true; keepCal(); }""")   # what luSolve leaves: unsaved, its keep under way
    page.click("#ludone")
    page.wait_for_timeout(200)
    assert page.is_hidden("#luchoice")                       # Done waits for the save, no choice
    page.wait_for_selector("#lusaved", state="visible", timeout=4000)
    page.wait_for_url(preview.url, timeout=5000)
    assert len(preview.store.saved()) == 1


def test_enter_in_the_choice_belongs_to_the_choice_and_keep_lining_up_changes_nothing(preview, page):
    _open(page, preview.url + "lineup.html")
    page.evaluate("() => { lu.step = 3; dirty = true; window.__next = 0; const n = luNext; luNext = () => { window.__next++; }; }")
    page.click("#ludone")
    page.focus("#lukeep")
    page.keyboard.press("Enter")
    assert page.evaluate("window.__next") == 0 and page.is_hidden("#luchoice") and page.url.endswith("/lineup.html")
    page.click("#ludone")
    page.fill("#lusavename", "")
    page.press("#lusavename", "Enter")                       # Enter in the box presses Save and finish
    page.wait_for_timeout(300)
    assert page.text_content("#luchoiceerr") == "Type the venue's name, then press Save and finish."
    assert not preview.store.saved()


def test_draw_my_room_ranges_in_feet_and_meters_are_ones_the_server_takes(preview, page):
    _open(page, preview.url + "preview")
    names = {"qsw": "stage_w", "qsd": "floor_d", "qsh": "bar_h"}
    good = {"stage_w": 6.1, "floor_d": 6.7, "bar_h": 3.0}
    for unit, per in (("ft", FT), ("m", 1.0)):
        page.select_option("#units", unit)
        for box in names:
            lo, hi = page.evaluate("(b) => qsRange(b)", box)
            for v in (lo, hi):
                stage_layout(**{**good, names[box]: v * per})          # each end he is told, the server takes
            words = page.evaluate("(b) => qsWords(b)", box)
            assert f"between {lo:g} and {hi:g}." in words and ("feet" if unit == "ft" else "meters") in words
            page.fill("#" + box, str(hi * 10))
            page.click("#qsgo")
            assert page.text_content(f"#{box}err") == words
            page.fill("#" + box, str(lo))
