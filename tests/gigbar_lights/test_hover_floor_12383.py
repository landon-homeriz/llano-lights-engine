"""Hover follow follows the pointer only over the dance floor (Llano BL #12383).

The report, 2026-11-15: with Follow someone on hover, moving the pointer off the dance floor
(say, quickly, to type somewhere else) kept the beams chasing the pointer, which looked
silly. Before the fix the console sent the spot every
pointer place on the whole room picture (clamped to the room), and on leaving it the newest pointer
sample, still waiting in the 45 ms throttle, went out AFTER the hold, so a fast exit dragged the
beam to the edge.

Now, in the one console every screen draws (studio_console.js): off the floor the spot holds where
the pointer last rested on the floor (the quick stroke out is trimmed), and back on the floor it
follows again only once the pointer has been there a moment.
"""
from __future__ import annotations

import json

import pytest

from tests.gigbar_lights.test_part_mood import CONSOLE
from tests.gigbar_lights.test_shows import lib, window  # noqa: F401

# A plain room for the plan the phone layout draws: 10 x 8 m, the dance floor 4 x 3 m in the middle.
PLAN = {"room": [10.0, 8.0], "floor": [3.0, 2.5, 4.0, 3.0], "booth": [4.0, 0.2, 2.0, 1.0], "bars": [[3.0, 1.0], [7.0, 1.0]]}

MOUNT = """(st) => { window.SENT = [];
  const host = document.getElementById("host");
  LlanoStudio.mount(host, {layout: "phone", screen: "phone", pollMs: 60000,
    transport: {state: () => Promise.resolve(st), stop: () => Promise.resolve({ok: true}),
                send: (cmd) => { SENT.push(JSON.parse(JSON.stringify(cmd))); return Promise.resolve({ok: true}); }}}); }"""

# Where a place in the room is drawn on the plan canvas (studio_console.js planMetrics/planPt, turn 0).
TO_PX = """([x, y]) => { const c = document.querySelector(".lls canvas"), r = c.getBoundingClientRect();
  const RW = 10, RD = 8, pad = 14, k = Math.min((c.clientWidth - 2 * pad) / RW, (c.clientHeight - 2 * pad) / RD);
  return [r.left + c.clientWidth / 2 + (x - RW / 2) * k, r.top + c.clientHeight / 2 + (y - RD / 2) * k]; }"""


def on_floor(x, y):
    f = PLAN["floor"]
    return f[0] - 1e-6 <= x <= f[0] + f[2] + 1e-6 and f[1] - 1e-6 <= y <= f[1] + f[3] + 1e-6


@pytest.fixture()
def console(window):  # noqa: F811
    pw = pytest.importorskip("playwright.sync_api")
    app, _url, _token, _tmp = window
    state = json.loads(json.dumps(app.studio_state()))
    sp = state["studio"]["spots"]
    sp.update({"on": True, "hover": True, "count": 1, "sel": 0, "plan": PLAN, "at": [[5.0, 4.0]], "going": [None],
               "dark": [False], "marks": [], "size": PLAN["room"]})
    sp["views"] = {"laptop": {"from": "floor", "turn": 0}, "phone": {"from": "floor", "turn": 0}}
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            page = browser.new_page(viewport={"width": 390, "height": 900})
            page.set_content('<div id="host"></div>')
            page.add_script_tag(content=CONSOLE.read_text(encoding="utf-8"))
            page.evaluate(MOUNT, state)
            page.wait_for_selector(".lls canvas")
            page.wait_for_function("document.querySelector('.lls canvas').clientWidth > 100")
            page.evaluate("document.querySelector('.lls canvas').scrollIntoView({block: 'center'})")
            mid = page.evaluate(TO_PX, [5.0, 4.0])
            assert page.evaluate("([x, y]) => document.elementFromPoint(x, y).tagName", mid) == "CANVAS"

            def go(x, y, steps=1):
                px, py = page.evaluate(TO_PX, [x, y])
                page.mouse.move(px, py, steps=steps)

            def walk(x0, x1, y, n=10):   # following someone: a small step every frame or so
                for i in range(1, n + 1):
                    go(x0 + (x1 - x0) * i / n, y)
                    page.wait_for_timeout(20)

            yield page, go, walk
        finally:
            browser.close()


def goals(page):
    return [c for c in page.evaluate("SENT") if c.get("op") == "spot_goal"]


def test_hover_follows_over_the_floor_and_a_fast_exit_holds_where_he_was_following(console):
    page, go, walk = console
    go(1.0, 1.0)                     # off the floor, on the picture: nothing moves
    page.wait_for_timeout(200)
    assert goals(page) == []
    go(4.6, 4.0)                     # following someone in the middle of the floor, slowly
    page.wait_for_timeout(200)
    walk(4.6, 5.2, 4.0)
    page.wait_for_timeout(200)
    follow = goals(page)
    assert follow and all(g.get("hover") is True for g in follow)
    assert follow[-1]["x"] == pytest.approx(5.2, abs=0.05), "the spot should be following the pointer"
    page.wait_for_timeout(900)        # the pointer rests on the couple a while
    page.evaluate("SENT.length = 0")
    # he flicks off the floor to type somewhere else: one fast stroke out the right side and on
    go(9.5, 4.0, steps=6)
    page.wait_for_timeout(150)
    for x in (9.0, 8.0, 9.4):        # and wanders around off the floor
        go(x, 6.5, steps=3)
        page.wait_for_timeout(40)
    page.mouse.move(1, 1)            # and off the picture
    page.wait_for_timeout(300)
    sent = goals(page)
    assert sent, "leaving the floor should pin the spot where he was following"
    assert all(on_floor(g["x"], g["y"]) for g in sent), f"a spot was sent off the dance floor: {sent}"
    assert sent[-1]["x"] == pytest.approx(5.2, abs=0.2) and sent[-1]["y"] == pytest.approx(4.0, abs=0.2), \
        f"the fast stroke out dragged the spot toward the edge: {sent[-1]}"
    assert len(sent) == 1, f"one hold, nothing after it: {sent}"


def test_a_slow_walk_off_the_edge_holds_at_the_edge(console):
    page, go, walk = console
    go(6.0, 4.0)
    page.wait_for_timeout(200)
    walk(6.0, 6.95, 4.0)
    walk(6.95, 7.3, 4.0, n=4)         # just over the floor's right edge, slowly
    go(8.5, 4.0, steps=3)
    page.wait_for_timeout(300)
    last = goals(page)[-1]
    assert on_floor(last["x"], last["y"]) and last["x"] == pytest.approx(6.95, abs=0.1), last


def test_brushing_past_a_corner_of_the_floor_does_not_move_the_spot(console):
    page, go, walk = console
    go(2.0, 2.0)
    page.wait_for_timeout(100)
    go(3.4, 2.9, steps=2)             # across the floor's corner and straight back off it, quickly
    go(2.0, 3.6, steps=2)
    page.wait_for_timeout(300)
    assert goals(page) == [], "a pass across the corner jerked the beam"
    go(4.0, 3.5)                      # onto the floor and staying put: it follows after the settle
    page.wait_for_timeout(400)
    sent = goals(page)
    assert sent and sent[-1]["x"] == pytest.approx(4.0, abs=0.05) and sent[-1]["y"] == pytest.approx(3.5, abs=0.05)


def test_a_quick_move_to_someone_else_on_the_floor_still_lands_there(console):
    page, go, walk = console
    go(3.5, 3.0)
    page.wait_for_timeout(300)
    page.evaluate("SENT.length = 0")
    go(6.5, 5.0, steps=4)             # a quick move across the floor that stops on the floor
    page.wait_for_timeout(300)
    sent = goals(page)
    assert sent and sent[-1]["x"] == pytest.approx(6.5, abs=0.05) and sent[-1]["y"] == pytest.approx(5.0, abs=0.05), sent


def test_on_the_laptop_room_picture_a_flick_off_the_floor_holds_the_real_spot(window):  # noqa: F811
    """The laptop's Live screen steers on the room picture (an embedded page that tells the console
    where the pointer is). Over the floor the real spot follows; a flick off it holds the spot where
    he was following, and wandering over the rest of the picture never moves it."""
    import time
    pw = pytest.importorskip("playwright.sync_api")
    app, url, _token, _tmp = window
    st = app.studio
    st.command({"op": "spots", "on": True, "count": 1})
    st.command({"op": "spots", "hover": True})
    seen = []
    real = st.command
    st.command = lambda cmd, *a, **k: (seen.append(dict(cmd)), real(cmd, *a, **k))[1]
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.goto(url + "studio")
            page.wait_for_selector(".lls-stage iframe, .lls iframe")
            el = page.locator(".lls iframe").first
            el.scroll_into_view_if_needed()
            fr = el.element_handle().content_frame()
            fr.wait_for_function("typeof L !== 'undefined' && L && L.floor && document.getElementById('top').clientWidth > 100")
            box = el.bounding_box()
            floor = fr.evaluate("() => [L.floor.x, L.floor.y, L.floor.w, L.floor.d, L.room.w, L.room.d]")

            def px(x, y):
                fx, fy = fr.evaluate("""([x, y]) => { const c = document.getElementById('top'), r = c.getBoundingClientRect();
                  const g = stageGeo(r.width, r.height), q = stagePt(g, x, y); return [r.left + q[0], r.top + q[1]]; }""", [x, y])
                return box["x"] + fx, box["y"] + fy

            def at():   # where the real spot is headed (no show runs here to glide it)
                f = st.followers[0]
                return f.goal if f.goal is not None else (f.x, f.y)

            fx, fy, fw, fd, rw, rd = floor
            cy = fy + fd * 0.6
            start, rest = fx + fw * 0.25, fx + fw * 0.4
            page.mouse.move(*px(start, cy))
            time.sleep(0.4)
            for i in range(1, 11):            # following someone toward the middle of the floor
                page.mouse.move(*px(start + (rest - start) * i / 10, cy))
                time.sleep(0.03)
            time.sleep(0.4)
            assert at() == pytest.approx((rest, cy), abs=0.15), f"the spot did not follow over the floor: {at()}"
            out = min(rw - 0.05, fx + fw + 1.5)
            page.mouse.move(*px(out, cy), steps=5)   # the flick off the floor, still on the picture
            for x, y in ((out, min(rd - 0.1, fy + fd + 1.0)), (max(0.1, fx - 1.0), cy)):
                page.mouse.move(*px(x, y), steps=4)  # and around the rest of the picture
                time.sleep(0.05)
            time.sleep(0.5)
            x, y = at()
            assert x == pytest.approx(rest, abs=0.2) and y == pytest.approx(cy, abs=0.2), \
                f"the spot chased the pointer off the floor: at {(x, y)}, he was following at {(rest, cy)}"
        finally:
            browser.close()


def test_a_long_fast_chase_across_the_floor_still_follows_while_it_moves(console):
    page, go, walk = console
    go(3.2, 3.0)
    page.wait_for_timeout(300)
    page.evaluate("SENT.length = 0")
    for i in range(1, 25):            # sweeping back and forth fast for half a second, never resting
        go(3.2 + 3.6 * ((i % 8) / 8 if (i // 8) % 2 == 0 else 1 - (i % 8) / 8), 4.0)
        page.wait_for_timeout(20)
    assert goals(page), "a long chase should follow while it moves, not only when it stops"
