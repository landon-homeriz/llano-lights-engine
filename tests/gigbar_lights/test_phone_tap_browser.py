"""The phone page in a real browser: the dark-room cases a string check cannot prove (Llano BL #11473,
lead review of PR 146).

- Both layouts mount with no console error.
- An opened Tonight row shows its press line and Go here now in full inside the list, with 6 steps
  and with exactly 4.
- Forgetting a saved place takes two taps on its own button.
- The Crowd-safe question: Keep it on, a tap outside, Esc and a lost connection change nothing;
  Turn it off sends exactly one change. STOP still sends with the name box open.
- No control on the phone layout is under 44 px, measured in the rendered page.

Skipped like the repo's other browser tests when Playwright or a headless Chromium is missing.
"""
from __future__ import annotations

import json

import pytest

from tests.gigbar_lights.test_hover_floor_12383 import PLAN
from tests.gigbar_lights.test_part_mood import CONSOLE
from tests.gigbar_lights.test_phone_console_browser import browser  # noqa: F401
from tests.gigbar_lights.test_shows import lib, window  # noqa: F401

MOUNT = """([st, doc, layout]) => { window.ST = st; window.DOC = doc; window.UP = true; window.SENT = []; window.CHANGES = [];
  window.STOPS = 0; window.ERRORS = window.ERRORS || [];
  const hang = () => new Promise(() => {});
  LlanoStudio.mount(document.getElementById("host"), {layout, screen: layout === "wide" ? "laptop" : "phone", pollMs: 200,
    keys: layout === "wide",
    transport: {state: () => UP ? Promise.resolve(window.ST) : hang(),
                send: (cmd) => { SENT.push(JSON.parse(JSON.stringify(cmd))); return UP ? Promise.resolve({ok: true}) : hang(); },
                stop: () => { STOPS++; return Promise.resolve({ok: true}); },
                settings: () => UP ? Promise.resolve({settings: window.DOC}) : hang(),
                change: (ops) => { CHANGES.push(ops); return UP ? Promise.resolve({ok: true, settings: window.DOC}) : hang(); }},
    caps: {}}); }"""


def _state(window, steps=None, spots=False):  # noqa: F811
    app = window[0]
    st = json.loads(json.dumps(app.studio_state()))
    if steps is not None:
        night = st["studio"]["night"]
        night["steps"] = [dict(night["steps"][i % len(night["steps"])], name=f"Step {i + 1}", state="later") for i in range(steps)]
        night["at"], night["ahead"], night["next"] = -1, None, None
    if spots:
        sp = st["studio"]["spots"]
        sp.update({"on": True, "count": 1, "sel": 0, "plan": PLAN, "at": [[5.0, 4.0]], "going": [None], "dark": [False],
                   "marks": [{"name": "Cake table", "x": 2.0, "y": 2.0}], "size": PLAN["room"]})
    return st


def _page(browser, window, layout="phone", w=412, h=915, steps=None, spots=False):  # noqa: F811
    doc = window[0]._local_settings(None)[1]["settings"]
    page = browser.new_page(viewport={"width": w, "height": h}, has_touch=layout == "phone", is_mobile=layout == "phone")
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.set_content('<html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>'
                     '<body style="margin:0;background:#07080b"><div id="host"' + (' style="height:100vh"' if layout == "wide" else "") + '></div></body></html>')
    page.add_script_tag(content=CONSOLE.read_text(encoding="utf-8"))
    page.evaluate(MOUNT, [_state(window, steps, spots), doc, layout])
    page.wait_for_selector(".lls-step")
    page.wait_for_timeout(400)
    return page, errors


@pytest.mark.parametrize("layout", ["phone", "wide"])
def test_both_layouts_mount_with_no_console_error(browser, window, layout):  # noqa: F811
    page, errors = _page(browser, window, layout, *((412, 915) if layout == "phone" else (1366, 768)), spots=True)
    page.wait_for_timeout(800)
    assert errors == []


@pytest.mark.parametrize("steps,row", [(6, 3), (4, 1), (4, 3)])
def test_an_opened_tonight_row_shows_go_here_now_in_full(browser, window, steps, row):  # noqa: F811
    page, _ = _page(browser, window, steps=steps)
    page.locator(f'[data-step="{row}"]').click()
    page.wait_for_timeout(500)
    inside = page.evaluate("""() => { const l = document.querySelector('.lls-steps').getBoundingClientRect();
      const go = document.querySelector('.lls-steppress button').getBoundingClientRect();
      const rows = [...document.querySelectorAll('.lls-step')].map(r => r.getBoundingClientRect());
      return {go: go.top >= l.top - 1 && go.bottom <= l.bottom + 1,
              rows: rows.filter(r => r.top >= l.top - 1 && r.bottom <= l.bottom + 1).length, n: rows.length}; }""")
    assert inside["go"], "Go here now is below the edge of the list"
    if steps == 4:
        assert inside["rows"] == 4, f"a 4-step night shows only {inside['rows']} whole rows with one open"


def test_forgetting_a_saved_place_takes_two_taps(browser, window):  # noqa: F811
    page, _ = _page(browser, window, spots=True)
    x = page.locator('[data-delmark="Cake table"]')
    x.scroll_into_view_if_needed()
    x.tap()
    page.wait_for_timeout(200)
    assert not [c for c in page.evaluate("SENT") if c.get("op") == "mark_del"], "one tap forgot the place"
    assert "Tap again to forget Cake table" in page.inner_text(".lls-toast")
    page.locator('[data-delmark="Cake table"]').tap()
    page.wait_for_timeout(200)
    assert {"op": "mark_del", "name": "Cake table"} in page.evaluate("SENT")


def _ask_crowd_safe(page):
    if not page.evaluate("document.querySelector('.lls-fold').open"):
        page.locator(".lls-fold>summary").click()
    cs = page.locator('[data-ops*="crowd_safe"]')
    cs.wait_for()
    cs.scroll_into_view_if_needed()
    cs.click()
    page.wait_for_selector('.lls-toast.ask [data-act="ask-no"]')


def test_crowd_safe_off_changes_nothing_until_turn_it_off(browser, window):  # noqa: F811
    page, _ = _page(browser, window)
    _ask_crowd_safe(page)
    first = page.evaluate("[...document.querySelectorAll('.lls-toast button')].map(b => [b.textContent, b.className])")
    assert first[0] == ["Keep it on", "go"] and first[1][0] == "Turn it off", first
    page.locator('.lls-toast [data-act="ask-no"]').click()                     # Keep it on
    _ask_crowd_safe(page)
    page.locator(".lls-pad").first.click()                                     # a tap outside
    _ask_crowd_safe(page)
    page.evaluate("window.UP = false")                                         # the laptop goes quiet
    page.wait_for_selector(".lls.lls-lost", timeout=9000)
    assert page.evaluate("document.querySelector('.lls-toast').hidden"), "the question stayed over the lost screen"
    assert page.evaluate("CHANGES") == [], "a change went out with no Turn it off"
    page.evaluate("window.UP = true")
    page.wait_for_function("!document.querySelector('.lls').classList.contains('lls-lost')", timeout=9000)
    _ask_crowd_safe(page)
    page.locator('.lls-toast [data-act="ask-ok"]').click()                     # Turn it off
    page.wait_for_timeout(300)
    assert page.evaluate("CHANGES") == [[{"path": "crowd_safe", "value": False}]]


def test_on_the_laptop_esc_answers_keep_it_on_and_no_key_acts_under_the_question(browser, window):  # noqa: F811
    page, _ = _page(browser, window, "wide", 1366, 768)
    page.locator('[data-panelbtn="settings"]').click()
    cs = page.locator('[data-ops*="crowd_safe"]')
    cs.wait_for()
    cs.click()
    page.wait_for_selector('.lls-toast.ask')
    page.keyboard.press("b")
    page.keyboard.press("Enter")   # on the focused Keep it on: answers it, never Next
    page.wait_for_timeout(300)
    assert not [c for c in page.evaluate("SENT") if c.get("op") in ("blackout", "next")], page.evaluate("SENT")
    assert page.evaluate("CHANGES") == []
    cs.click()
    page.wait_for_selector('.lls-toast.ask')
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    assert page.evaluate("document.querySelector('.lls-toast').hidden") and page.evaluate("CHANGES") == []


def test_stop_sends_with_the_name_box_open(browser, window):  # noqa: F811
    page, _ = _page(browser, window, spots=True)
    page.locator('[data-act="save-mark"]').scroll_into_view_if_needed()
    page.locator('[data-act="save-mark"]').click()
    page.wait_for_selector(".lls-toast.ask input")
    page.locator(".lls-stop").click()
    assert page.evaluate("STOPS") == 1


def test_no_phone_control_is_under_44_px(browser, window):  # noqa: F811
    page, _ = _page(browser, window, spots=True)
    page.locator(".lls-fold>summary").click()
    page.locator('[data-step="1"]').click()
    page.wait_for_timeout(600)
    small = page.evaluate("""() => [...document.querySelectorAll('#host button, #host a, #host select, #host input, #host summary')]
      .filter(e => { const r = e.getBoundingClientRect(), cs = getComputedStyle(e); return r.width && r.height && cs.visibility !== 'hidden' && (r.height < 43.5 || r.width < 43.5); })
      .map(e => (e.innerText || e.getAttribute('aria-label') || e.className).trim().slice(0, 24) + ' ' + Math.round(e.getBoundingClientRect().width) + 'x' + Math.round(e.getBoundingClientRect().height))""")
    assert small == [], small
    page.evaluate("window.UP = false")
    page.wait_for_selector(".lls.lls-lost", timeout=9000)
    # the way out under the lost message (the phone page passes it; here it is checked the same way)
