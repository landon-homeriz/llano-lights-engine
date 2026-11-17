"""The laptop's wide top strip never cuts its words off on a laptop-sized window (Llano BL #12460).

At 1,174 px the held card's second line ("Held 0:15 · stays until you release it") was cut to an
ellipsis, and at 1,102 px the show card's title and the tabs hint were cut too: a 1366-wide laptop
window with the side panel open gets there. Those lines now wrap onto a second line instead.

Skipped like the repo's other browser tests when Playwright or a headless Chromium is missing.
"""
from __future__ import annotations

import pytest

from tests.gigbar_lights.test_phone_console_browser import _console, browser  # noqa: F401
from tests.gigbar_lights.test_shows import lib, window  # noqa: F401

# Every line in the wide top strip and the tabs row that holds words he reads.
LINES = [".lls-wide .lls-chip>span", ".lls-wide .lls-chip b", ".lls-wide .lls-tabs .hint"]

CUT = """(sels) => sels.flatMap(sel => [...document.querySelectorAll(sel)]
  .filter(el => el.offsetParent && el.textContent.trim() && el.scrollWidth > el.clientWidth + 1)
  .map(el => sel + ": " + el.textContent.trim() + " (" + el.scrollWidth + "/" + el.clientWidth + ")"))"""


@pytest.mark.parametrize("width", [1366, 1280, 1174, 1102, 1024])
def test_no_word_in_the_wide_top_strip_is_cut_off(browser, window, width):  # noqa: F811
    page = _console(browser, window, "wide", width, 768)
    # A held look 15 s old: the longest second line the held card shows.
    page.evaluate("""() => { const st = JSON.parse(JSON.stringify(window.ST));
      st.studio.look = {key: "scene:warm", name: "Warm wash", since: st.now - 15}; window.ST = st; }""")
    page.wait_for_function("document.querySelector('[data-t=heldsub]').textContent.startsWith('Held 0:1')",
                           timeout=5000)
    assert page.evaluate(CUT, LINES) == []
    # Wrapping costs at most two lines of height: 96 px unwrapped, 134 px at its worst (1,102 wide),
    # so the room picture below keeps its room on a 768-tall laptop.
    assert page.evaluate("document.querySelector('.lls-wide>.lls-top').getBoundingClientRect().height") <= 140
