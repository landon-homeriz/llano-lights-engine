"""The phone's Live screen is the party first (Llano BL #12419).

The 2026-11-14 recording of the phone console (the same console the web page draws): the
layout was inefficient on a phone, with a lot of scrolling.
What is on, Next, Tonight, the pads, the hold buttons and STOP stay open. The moving heads with their
picture, Brightness and speed, and Touch a light each sit in a fold under the pads, shut until he
opens one, each title saying what it is set to now, so a shut fold hides a control but never a state.

- Shut by default; the pads, Blackout and STOP are on the page; the Live column is far shorter.
- A spot turning on opens the heads fold, so the picture he steers on is never shut away.
- "Touch a light" (the button in the heads bar) opens its fold.
- Each title says the state: heads Stopped, brightness under 100%, lights changed by hand.
- With every fold open, no control is under 44 px.
- The laptop's wide layout has no folds: its tabs and panels are as they were.
- STOP still goes out with the heads fold shut and the room glowing. Shut, the picture has no size, and
  drawing its glow into that threw before STOP was sent (llano.app's e2e caught it on 1.33.0): the
  console now sends STOP before it draws anything, skips a picture with no size, and draws it when the
  fold opens.

Skipped like the repo's other browser tests when Playwright or a headless Chromium is missing.
"""
from __future__ import annotations

from tests.gigbar_lights.test_hover_floor_12383 import PLAN
from tests.gigbar_lights.test_phone_console_browser import browser  # noqa: F401
from tests.gigbar_lights.test_phone_tap_browser import MOUNT, _page, _state
from tests.gigbar_lights.test_shows import lib, window  # noqa: F401

STATE_FOLDS = ["heads", "levels", "lights"]   # the folds whose title warns when he changed something
FOLDS = STATE_FOLDS + ["timeline"]   # the Cue timeline fold since 1.36.0 (PM #23787)
# Measured at 412 x 915 with the test state: 3,751 px of console before the folds, 2,213 with them shut
# (the now cards 203, Tonight with Next and the mood swatches 740, the pads and Blackout 883).
MAX_PHONE_HEIGHT = 2400


def _open(page):
    return page.evaluate("[...document.querySelectorAll('.lls-livefold')].map(d => [d.dataset.fold, d.open])")


def _height(page):
    return page.evaluate("document.getElementById('host').scrollHeight")


def test_the_live_screen_is_the_party_first_and_the_rest_is_folded(browser, window):  # noqa: F811
    page, errors = _page(browser, window)
    assert _open(page) == [[f, False] for f in FOLDS]
    for sel in (".lls-pads .lls-pad", ".lls-nextbtn", ".lls-steps", '.lls-hits .lls-hit.r', ".lls-stop"):
        assert page.locator(sel).first.is_visible(), sel
    for sel in (".lls-stage", '[data-panel="levels"]', '[data-panel="lights"]', '[data-panel="spot"]'):
        assert not page.locator(sel).first.is_visible(), f"{sel} should be folded away"
    # Show settings keeps its own fold, still the first .lls-fold in the page
    assert page.evaluate("document.querySelector('.lls-fold').closest('[data-panel]').dataset.panel") == "settings"
    # folded order: the pads, then the three folds, then Show settings
    tops = page.evaluate("""['.lls-bot', '[data-fold=heads]', '[data-fold=levels]', '[data-fold=lights]', '.lls-fold']
      .map(s => document.querySelector(s).getBoundingClientRect().top)""")
    assert tops == sorted(tops), tops
    h = _height(page)
    assert h < MAX_PHONE_HEIGHT, f"the phone's Live column is {h} px"
    page.evaluate("document.querySelectorAll('.lls-livefold').forEach(d => d.open = true)")
    full = _height(page)
    assert full > h * 1.5, f"shut {h} px vs open {full} px: the folds hold a third of the screen or more"
    assert errors == []


def test_a_spot_turning_on_opens_the_heads_fold(browser, window):  # noqa: F811
    page, _ = _page(browser, window, spots=True)
    assert dict(_open(page))["heads"] is True, "a spot already on at load"
    assert page.locator(".lls-stagebox").is_visible()
    page2, _ = _page(browser, window)
    assert dict(_open(page2))["heads"] is False
    page2.evaluate("""() => { const sp = window.ST.studio.spots; sp.on = true; sp.count = 1; sp.sel = 0;
      sp.at = [[5, 4]]; sp.going = [null]; sp.dark = [false]; window.ST = JSON.parse(JSON.stringify(window.ST)); }""")
    page2.wait_for_function("document.querySelector('[data-fold=heads]').open", timeout=4000)


def test_touch_a_light_opens_its_fold(browser, window):  # noqa: F811
    page, _ = _page(browser, window)
    page.locator("[data-fold=heads]>summary").click()
    page.locator('.lls-stagebar [data-panelbtn="lights"]').click()
    page.wait_for_function("document.querySelector('[data-fold=lights]').open", timeout=3000)
    assert page.locator('[data-panel="lights"] .lls-light').first.is_visible()


def test_each_fold_title_says_what_it_is_set_to(browser, window):  # noqa: F811
    page, _ = _page(browser, window)
    now = lambda k: page.inner_text(f"[data-fold={k}] .lls-foldnow")  # noqa: E731
    assert now("heads") == "Auto"
    assert now("levels").startswith("100%")
    assert now("lights") == ""
    page.evaluate("""() => { const s = window.ST.studio; s.heads = {mode: 'stop', line: ''}; s.masters.main = 0.6;
      const id = Object.keys(s.touch || {})[0] || 'tetra1'; s.touch = {[id]: {color: '#ff0000', dim: 1}};
      window.ST = JSON.parse(JSON.stringify(window.ST)); }""")
    page.wait_for_function("document.querySelector('[data-fold=heads] .lls-foldnow').textContent === 'Stopped'", timeout=4000)
    assert now("levels").startswith("60%")
    assert now("lights") == "1 changed by hand"
    for k in STATE_FOLDS:
        assert "warn" in page.get_attribute(f"[data-fold={k}] .lls-foldnow", "class"), k


def test_with_every_fold_open_no_phone_control_is_under_44_px(browser, window):  # noqa: F811
    page, _ = _page(browser, window, spots=True)
    page.evaluate("document.querySelectorAll('.lls-livefold, .lls-fold').forEach(d => d.open = true)")
    page.wait_for_timeout(500)
    small = page.evaluate("""() => [...document.querySelectorAll('#host button, #host a, #host select, #host input, #host summary')]
      .filter(e => { const r = e.getBoundingClientRect(), cs = getComputedStyle(e); return r.width && r.height && cs.visibility !== 'hidden' && (r.height < 43.5 || r.width < 43.5); })
      .map(e => (e.innerText || e.getAttribute('aria-label') || e.className).trim().slice(0, 24) + ' ' + Math.round(e.getBoundingClientRect().width) + 'x' + Math.round(e.getBoundingClientRect().height))""")
    assert small == [], small


def test_the_laptop_wide_layout_has_no_folds(browser, window):  # noqa: F811
    page, errors = _page(browser, window, layout="wide", w=1366, h=768)
    assert page.locator(".lls-livefold").count() == 0
    assert page.locator(".lls-side .lls-ptabs").is_visible()
    assert page.evaluate("document.querySelector('[data-panel=levels]').parentElement.classList.contains('lls-side')")
    assert page.locator(".lls-stage").is_visible()
    assert errors == []


GLOW = """(plan) => { const s = window.ST.studio; s.spots.plan = plan; s.spots.size = plan.room;
  window.ST.glow = {pools: [[5, 4, 1.5, 'ff3300', 1], [3, 2, 1.2, '33aaff', 0.8]], beams: [], lamps: [[5, 4, 't', 'ff3300', 1]], bars: []};
  window.ST = JSON.parse(JSON.stringify(window.ST)); }"""


def test_stop_goes_out_with_the_heads_fold_shut_and_the_room_glowing(browser, window):  # noqa: F811
    page, errors = _page(browser, window)
    page.evaluate(GLOW, PLAN)
    page.wait_for_timeout(600)
    assert dict(_open(page))["heads"] is False
    page.locator('[data-hit="whiteout"]').click()
    page.wait_for_timeout(300)
    page.locator(".lls-stop").click()
    page.wait_for_function("window.STOPS === 1", timeout=3000)
    assert errors == []


def test_stop_goes_out_even_when_drawing_the_page_fails(browser, window):  # noqa: F811
    page, _ = _page(browser, window)
    page.evaluate("() => { HTMLCanvasElement.prototype.getContext = () => { throw new Error('no canvas'); }; }")
    page.locator(".lls-stop").click()
    page.wait_for_function("window.STOPS === 1", timeout=3000)


def test_opening_the_heads_fold_draws_the_picture(browser, window):  # noqa: F811
    page, errors = _page(browser, window)
    page.evaluate(GLOW, PLAN)
    page.wait_for_timeout(600)
    page.locator("[data-fold=heads]>summary").click()
    page.wait_for_function("(() => { const c = document.querySelector('.lls-stagebox canvas'); return c && c.width > 0; })()", timeout=3000)
    assert errors == []


assert MOUNT and _state  # imported for the shared page; kept so a rename there fails loudly here
