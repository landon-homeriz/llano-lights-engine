"""The console in a real browser: the cases a string check cannot prove (Llano BL #11473, lead review).

- STOP is sent while the screen says the laptop is not answering ("lost" is a guess from the clock;
  a slow laptop still takes the press), on the phone and on the laptop's Live screen.
- A hit held when the laptop goes quiet is let go: the off is sent on lifting the finger, and again
  when the laptop answers.
- A phone waking from a locked screen does not dim or close an open Name box.
- Enter on a Tonight row's Go here now goes there, never Next.
- A laptop that sends the headers and then stalls does not hang the phone page for ever.

Skipped like the repo's other browser tests when Playwright or a headless Chromium is missing.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tests.gigbar_lights.test_part_mood import CONSOLE
from tests.gigbar_lights.test_shows import lib, window  # noqa: F401

REMOTE = Path(CONSOLE).with_name("remote.html")

# A console whose laptop can go quiet (UP = false: every state request hangs, as a laptop that left
# the Wi-Fi does) and whose presses are recorded.
# LOG keeps each send with the time it went; HANG_NEXT makes the next send hang for ever; NSTATE counts
# state requests; STOP_ANSWER is what the laptop says to STOP.
MOUNT = """([st, layout]) => { window.ST = st; window.UP = true; window.SENT = []; window.LOG = []; window.STOPS = 0;
  window.NSTATE = 0; window.HANG_NEXT = false; window.STOP_ANSWER = {ok: true};
  const hang = () => new Promise(() => {});
  LlanoStudio.mount(document.getElementById("host"), {layout, screen: layout === "wide" ? "laptop" : "phone", pollMs: 200,
    keys: layout === "wide",
    transport: {state: () => { NSTATE++; return UP ? Promise.resolve(window.ST) : hang(); },
                send: (cmd) => { SENT.push(JSON.parse(JSON.stringify(cmd))); LOG.push([performance.now(), JSON.parse(JSON.stringify(cmd))]);
                                 if (HANG_NEXT) { HANG_NEXT = false; return hang(); } return UP ? Promise.resolve({ok: true}) : hang(); },
                stop: () => { STOPS++; return UP ? Promise.resolve(window.STOP_ANSWER) : hang(); },
                run: (mode) => { SENT.push({run: mode}); return Promise.resolve({ok: true}); }},
    caps: {}}); }"""


def _tap_hit(page, name, hold_ms=60):
    hit = page.locator(f'[data-hit="{name}"]')
    hit.scroll_into_view_if_needed()
    box = hit.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.wait_for_timeout(hold_ms)
    page.mouse.up()


def _top(page):
    return page.inner_text(".lls-chip.show").replace("\n", " ")


@pytest.fixture()
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            yield b
        finally:
            b.close()


def _console(browser, window, layout, w=412, h=915):  # noqa: F811
    app = window[0]
    state = json.loads(json.dumps(app.studio_state()))
    page = browser.new_page(viewport={"width": w, "height": h})
    page.set_content('<html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>'
                     '<body style="margin:0"><div id="host"' + (' style="height:100vh"' if layout == "wide" else "") + '></div></body></html>')
    page.add_script_tag(content=CONSOLE.read_text(encoding="utf-8"))
    page.evaluate(MOUNT, [state, layout])
    page.wait_for_selector(".lls-step")
    return page


def _go_quiet(page):
    page.evaluate("window.UP = false")
    page.wait_for_selector(".lls.lls-lost", timeout=9000)


@pytest.mark.parametrize("layout", ["phone", "wide"])
def test_stop_is_sent_while_the_laptop_seems_not_to_answer(browser, window, layout):  # noqa: F811
    page = _console(browser, window, layout, *((412, 915) if layout == "phone" else (1366, 768)))
    _go_quiet(page)
    stop = page.locator(".lls-stop")
    assert float(page.evaluate("getComputedStyle(document.querySelector('.lls-stop')).opacity")) == 1
    stop.click()
    assert page.evaluate("STOPS") == 1, "STOP must always take a press"
    page.wait_for_function("!document.querySelector('.lls-toast').hidden")
    assert "STOP was sent. If the lights are still on, press Stop on the laptop." in page.inner_text(".lls-toast")
    # everything else still takes no taps
    page.locator(".lls-pad").first.click(force=True)
    assert not [c for c in page.evaluate("SENT") if c.get("op") == "look"]


def test_a_hit_held_when_the_laptop_goes_quiet_is_sent_off_again_once_it_answers(browser, window):  # noqa: F811
    page = _console(browser, window, "phone")
    hit = page.locator('[data-hit="strobe"]')
    hit.scroll_into_view_if_needed()
    box = hit.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.wait_for_function("SENT.some(c => c.op === 'hit' && c.on)")
    _go_quiet(page)
    page.mouse.up()
    back = page.evaluate("(() => { window.UP = true; return performance.now(); })()")   # the laptop answers again
    page.wait_for_function("!document.querySelector('.lls').classList.contains('lls-lost')", timeout=9000)
    # the off sent on lifting the finger went into a quiet laptop (its chain gives up after 4.5 s): the
    # one that counts is an off sent AFTER the laptop answered
    page.wait_for_function(f"LOG.some(([t, c]) => t > {back} && c.op === 'hit' && c.name === 'strobe' && c.on === false)", timeout=9000)


def test_one_stalled_send_never_holds_back_later_hits_and_their_offs(browser, window):  # noqa: F811
    page = _console(browser, window, "phone")
    page.evaluate("window.HANG_NEXT = true")
    _tap_hit(page, "whiteout")            # its on hangs for ever
    _tap_hit(page, "burst")
    page.wait_for_function("SENT.some(c => c.op === 'hit' && c.name === 'burst' && c.on === false)", timeout=15000)
    sent = [c for c in page.evaluate("SENT") if c.get("op") == "hit"]
    assert {"op": "hit", "name": "whiteout", "on": False} in sent, "the off behind the stalled send never went"


def test_a_phone_waking_from_a_locked_screen_does_not_dim(browser, window):  # noqa: F811
    page = _console(browser, window, "phone")
    page.locator('[data-page="mine"]').click()
    # the screen was locked a minute: nothing was polled meanwhile (a request is still out), the wall
    # clock jumps, the page shows again, and the laptop answers as soon as it is asked
    page.evaluate("window.UP = false")
    page.wait_for_timeout(400)
    page.evaluate("""() => { const real = Date.now.bind(Date), jump = 60000; Date.now = () => real() + jump;
      window.UP = true; document.dispatchEvent(new Event('visibilitychange')); }""")
    for _ in range(10):
        assert not page.evaluate("document.querySelector('.lls').classList.contains('lls-lost')"), "a wake dimmed the screen"
        page.wait_for_timeout(150)


def test_enter_on_go_here_now_goes_there_and_never_fires_next(browser, window):  # noqa: F811
    page = _console(browser, window, "wide", 1366, 768)
    page.locator('[data-step="2"]').click()
    go = page.locator(".lls-steppress button")
    go.focus()
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    sent = page.evaluate("SENT")
    assert {"op": "goto", "i": 2} in sent, sent
    assert not [c for c in sent if c.get("op") == "next"], "Enter on Go here now advanced the night"
    page.locator('[data-step="3"]').focus()
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    assert not [c for c in page.evaluate("SENT") if c.get("op") == "next"]


def test_a_stalled_answer_does_not_hang_the_phone_page(browser, window):  # noqa: F811
    """The laptop sends the headers and then nothing: the phone gives up after its timeout and the
    next poll goes, so the page comes up instead of waiting for ever."""
    state = json.dumps(json.loads(json.dumps(window[0].studio_state()))).encode()
    asked = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                body, ctype = REMOTE.read_bytes(), "text/html"
            elif path == "/studio_console.js":
                body, ctype = CONSOLE.read_bytes(), "text/javascript"
            elif path == "/api/state":
                asked.append(time.monotonic())
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(state)))
                self.end_headers()
                if len(asked) == 1:   # the first answer stalls after the headers
                    self.wfile.write(state[:10]); self.wfile.flush()
                    time.sleep(20)
                    return
                self.wfile.write(state)
                return
            else:
                body, ctype = b"{}", "application/json"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        page = browser.new_page(viewport={"width": 412, "height": 915})
        page.goto(f"http://127.0.0.1:{srv.server_port}/#k=a-key-for-this-test-only")
        page.wait_for_function("document.querySelector('#connecting') && document.querySelector('#connecting').hidden "
                               "&& document.querySelector('.lls-step')", timeout=12000)
        assert len(asked) >= 2 and asked[1] - asked[0] < 6, "the stalled request was not given up"
    finally:
        srv.shutdown()
        srv.server_close()


def test_two_wakes_back_to_back_leave_one_poll_loop(browser, window):  # noqa: F811
    """A phone unlocking fires visibilitychange and focus together: still one loop, not two."""
    page = _console(browser, window, "phone")
    page.wait_for_timeout(500)
    n0 = page.evaluate("NSTATE"); page.wait_for_timeout(3000); base = page.evaluate("NSTATE") - n0
    for _ in range(5):
        page.evaluate("() => { document.dispatchEvent(new Event('visibilitychange')); window.dispatchEvent(new Event('focus')); }")
    page.wait_for_timeout(300)
    n1 = page.evaluate("NSTATE"); page.wait_for_timeout(3000); after = page.evaluate("NSTATE") - n1
    assert after <= base * 1.3 + 2, f"{after} state requests in 3 s after the wakes, {base} before: a second loop runs"


def test_stop_says_stopping_then_stopped_once_a_poll_shows_the_room_dark(browser, window):  # noqa: F811
    page = _console(browser, window, "phone")
    page.evaluate("window.ST = Object.assign({}, window.ST, {running: 'scenes'})")
    page.wait_for_timeout(500)
    page.locator(".lls-stop").click()
    assert "Stopping..." in _top(page)
    page.evaluate("window.ST = Object.assign({}, window.ST, {running: null})")
    page.wait_for_function("document.querySelector('.lls-chip.show').innerText.includes('Stopped. The lights are off.')", timeout=3000)


def test_stop_with_the_lights_still_on_says_so_and_clears_on_live_show(browser, window):  # noqa: F811
    page = _console(browser, window, "phone")
    page.evaluate("window.ST = Object.assign({}, window.ST, {running: 'scenes'})")
    page.wait_for_timeout(500)
    page.locator(".lls-stop").click()
    page.wait_for_function("document.querySelector('.lls-chip.show').innerText.includes('STOP was sent but the lights are still on.')", timeout=6000)
    page.locator('[data-act="run"][data-mode="live"]').click()
    page.wait_for_timeout(500)
    assert "still on" not in _top(page), "the still-on line stayed after he started Live show"


def test_a_stop_the_laptop_refuses_tells_one_story(browser, window):  # noqa: F811
    page = _console(browser, window, "phone")
    page.evaluate("window.ST = Object.assign({}, window.ST, {running: 'scenes'}); window.STOP_ANSWER = {ok: false, error: 'refused (test)'}")
    page.wait_for_timeout(500)
    page.locator(".lls-stop").click()
    page.wait_for_function("document.querySelector('.lls-chip.show').innerText.includes('STOP did not reach the laptop.')", timeout=3000)
    assert "Press STOP again, or use Stop on the laptop." in _top(page)
    page.wait_for_timeout(3500)
    assert "STOP was sent" not in _top(page) and "refused (test)" not in page.inner_text(".lls-toast")


def test_enter_on_a_button_tabbed_to_presses_it_and_after_a_click_is_next(browser, window):  # noqa: F811
    page = _console(browser, window, "wide", 1366, 768)
    page.locator(".lls-pad").first.click()   # a mouse click: Enter afterwards is Next, the design
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    assert [c for c in page.evaluate("SENT") if c.get("op") == "next"], "Enter after a click is Next"
    page.evaluate("SENT.length = 0; window.STOPS = 0")
    page.evaluate("document.activeElement.blur()")
    for _ in range(80):   # Tab to STOP for real, so it has keyboard focus (:focus-visible)
        page.keyboard.press("Tab")
        if page.evaluate("document.activeElement && document.activeElement.classList.contains('lls-stop')"):
            break
    assert page.evaluate("document.activeElement.classList.contains('lls-stop')"), "could not Tab to STOP"
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    assert page.evaluate("STOPS") == 1 and not [c for c in page.evaluate("SENT") if c.get("op") == "next"], "Enter on STOP sent Next"
