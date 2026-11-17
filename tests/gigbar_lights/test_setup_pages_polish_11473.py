"""The Set up page and the Setup guide leave nothing silent or stuck (Llano BL #11473).

A helper clicked through 1.27.1 at 1366x768 and 1024x700 before his daughter's wedding and found
presses that said nothing, a Stop that needed a second click without saying so, banners that outlived
their run, a raw Python traceback in the log, and guide steps with no way forward. These pin the new
words and behaviour: string checks first, then the same flows in a real browser against the app.
"""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.gigbar_lights.test_shows import _call, lib, window  # noqa: E402,F401

SRC = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"
APP = (SRC / "app.html").read_text(encoding="utf-8")
GUIDE = (SRC / "guide.html").read_text(encoding="utf-8")


# --- the words, no browser needed --------------------------------------------------------------

def test_stop_says_click_again_and_goes_back():
    assert 'b.textContent = "Click again to stop"' in APP
    assert 'b.textContent = "Stop"' in APP
    assert "const STOP_ARM_MS = 4000;" in APP


def test_a_refusal_names_its_way_out():
    assert "is running. Press Stop at the top of this page twice, then start this." in APP
    assert "is running. Press Stop beside Running now, above the steps, then try again." in GUIDE
    # Stop does not end a check (App.stop answers "the check finishes in a moment"): never send him there
    assert "is running. It finishes by itself in a moment, then start this." in APP
    assert "is running. It finishes by itself in a moment, then try again." in GUIDE


def test_every_controls_bar_button_says_what_it_does():
    for title in ("Autoloops (A): short repeating patterns on the moving heads",
                  "Hold (H): keep the look that is showing now",
                  "Earlier ([): move the lights a little earlier against the beat",
                  "Later (]): move the lights a little later against the beat",
                  "Reset (0): put the lights back on the beat",
                  "Dimmer (-): every light a little dimmer", "Brighter (+): every light a little brighter",
                  "Previous look (P)", "Next look (N)", "Color (C)", "Strobe (S)", "Blackout (B)"):
        assert f'title="{title}' in APP, title


def test_the_three_new_messages():
    assert "Nothing is held: the show is already running its own looks." in APP
    assert "Type a name for this set of lights first." in APP
    assert "that is the most this app runs." in APP and "so there are none to take out." in APP
    # the old disabled Back to the show is gone: it answers instead
    assert '<button id="sceneback" disabled>' not in APP


def test_a_traceback_folds_behind_one_line():
    assert 'const TB_LINE = "A technical error was logged. Llano can read it here.";' in APP
    assert '<pre id="log">' not in APP and '<div id="log" role="log">' in APP


def test_guide_checks_answer_and_steps_offer_a_way_forward():
    assert '"Checking..."' in GUIDE and '"Checked just now, "' in GUIDE
    assert 'https://llano.app/gigbar-laptop-controller.html' in GUIDE
    assert ">I did this</button>" in GUIDE and ">Not done yet</button>" in GUIDE
    assert "Stopping the test..." in GUIDE


def _literal(page: str, anchor: str) -> str:
    """The whole string literal in the page source that holds `anchor` (quotes or backticks)."""
    i = page.index(anchor)
    start = max(page.rfind(q, 0, i) for q in ('"', "`"))
    q = page[start]
    return page[start + 1:page.index(q, i + len(anchor))]


@pytest.mark.parametrize("page,anchor", [
    (APP, "Click again to stop"), (APP, "Press Stop at the top of this page twice"),
    (APP, "It finishes by itself in a moment, then start this."), (APP, "Nothing is held: the show"),
    (APP, "Nothing is held, and nothing is running."), (APP, "Type a name for this set of lights first."),
    (APP, "A technical error was logged."), (APP, "that is the most this app runs."),
    (APP, "so there are none to take out."), (APP, "first to control a light by hand: press Stop"),
    (APP, "That press didn't reach the lights."), (APP, "Hold is on: the look"), (APP, "didn't start; the log is open below"),
    (APP, "short repeating patterns on the moving heads"), (APP, "move the lights a little earlier against the beat"),
    (GUIDE, "Press Stop beside Running now"), (GUIDE, "It finishes by itself in a moment, then try again."),
    (GUIDE, "Still checking..."), (GUIDE, "Checked just now, "), (GUIDE, "You marked this done on this page."),
    (GUIDE, "Open the download page"), (GUIDE, "Press Yes, it worked again in a moment."),
])
def test_no_dash_punctuation_in_the_new_words(page, anchor):
    msg = _literal(page, anchor)
    assert anchor in msg
    assert " - " not in msg and "\u2014" not in msg and "\u2013" not in msg, msg


# --- the same in a real browser ----------------------------------------------------------------

@pytest.fixture
def win(window, monkeypatch):  # noqa: F811
    """The app window with its own settings file: a confirmed step never leaks into this machine's."""
    app, _url, _token, tmp = window
    monkeypatch.setattr(app, "prefs_file", tmp / "window.json")
    return window


def _browser(pw):
    try:
        return pw.chromium.launch()
    except Exception as e:  # noqa: BLE001 -- no browser on this machine
        pytest.skip(f"no headless chromium: {e}")


def _wait_idle(app, s=30):
    t0 = time.time()
    while app.running and time.time() - t0 < s:
        time.sleep(0.2)
    return not app.running


def test_setup_page_in_a_real_browser(win):
    pw = pytest.importorskip("playwright.sync_api")
    app, url, token, _tmp = win
    with pw.sync_playwright() as p:
        browser = _browser(p)
        try:
            page = browser.new_page(viewport={"width": 1024, "height": 700})
            page.goto(url + "setup")
            page.wait_for_selector(".mode[data-mode=test]")
            # nothing runs: the Control a light note does not ask to stop anything
            assert "first to control" not in page.inner_text("#mnote")
            # Back to the show with nothing held says so
            page.click("#sceneback")
            page.wait_for_function("document.querySelector('#status').innerText.startsWith('Nothing is held')")
            # Save with no name says what to do
            page.click("#rigsave")
            assert page.inner_text("#rignote") == "Type a name for this set of lights first."
            disabled = page.eval_on_selector_all("#rigcounts button", "bs => bs.filter(b => b.disabled).map(b => b.title)")
            assert all(t for t in disabled)
            # a run: Stop reads Click again to stop after one click, and goes back by itself
            assert _call(url + "api/run", {"mode": "test"}, token)[0] == 200
            page.wait_for_function("!document.querySelector('#stop').disabled")
            page.click("#stop")
            assert page.inner_text("#stop") == "Click again to stop"
            page.wait_for_function("document.querySelector('#stop').innerText === 'Stop'", timeout=6000)
            assert page.inner_text("#mnote").startswith("Stop Test each light first")
            # a second start is refused with the way out
            page.evaluate("post('/api/run', {mode: 'designer'})")
            page.wait_for_function("document.querySelector('#banners').innerText.includes('Press Stop at the top of this page twice')")
            assert "Test each light is running. Press Stop" in page.inner_text("#banners")
            # a heads-up about the run goes once the run ends
            app.warning = {"level": "warn", "text": "Heads up: the ENTTEC lights box isn't plugged in, so the test runs in the room picture only.", "lights": True}
            page.wait_for_function("document.querySelector('#banners').innerText.includes('Heads up')")
            page.click("#stop"); page.click("#stop")
            page.wait_for_function("document.querySelector('#nowtitle').innerText === 'Nothing running'", timeout=15000)
            page.wait_for_function("!document.querySelector('#banners').innerText.includes('Heads up')", timeout=5000)
            deadline = time.time() + 5
            while app.warning is not None and time.time() < deadline:
                time.sleep(0.1)
            assert app.warning is None
        finally:
            browser.close()


def test_failed_start_opens_the_log_and_tracebacks_fold(win):
    pw = pytest.importorskip("playwright.sync_api")
    _app, url, _token, _tmp = win
    fake = {"log": ["06:00:00 Llano Lights", "06:03:43 ----------------------------------------",
                    "06:03:43 Exception occurred during processing of request from ('127.0.0.1', 34464)",
                    "06:03:43 Traceback (most recent call last):", '06:03:43   File "socketserver.py", line 840, in write',
                    "06:03:43     self._sock.sendall(b)", "06:03:43 BrokenPipeError: [Errno 32] Broken pipe",
                    "06:03:43 ----------------------------------------",
                    "06:04:00 Traceback (most recent call last):", '06:04:00   File "a.py", line 1, in f', "06:04:00 ValueError: one",
                    "06:04:00 During handling of the above exception, another exception occurred:",
                    "06:04:00 Traceback (most recent call last):", '06:04:00   File "a.py", line 3, in g', "06:04:00 KeyError: 'two'",
                    "06:05:00 Traceback (most recent call last):", '06:05:00   File "b.py", line 9, in h', "06:05:00 OSError: three",
                    "06:06:00 --- Find song sections in my Mixxx music ---",
                    "06:06:00 Working out song sections (intro, build, drop...) for the tracks in Mixxx.",
                    "06:06:00 Mixxx library not found at C:/Users/x/mixxxdb.sqlite",
                    "06:06:00 Find song sections in my Mixxx music: didn't start; the log below says why"],
            "last_run": "Find song sections in my Mixxx music: didn't start; the log below says why"}
    state = {"failed": False, "polls": 0}

    def patch(route):
        r = route.fetch()
        j = r.json()
        if state["failed"]:
            state["polls"] += 1
            j.update(fake)
            # a new line every poll, so the page redraws the log under the opened traceback
            j["log"] = fake["log"] + [f"06:07:{state['polls'] % 60:02d} still here {state['polls']}"]
        route.fulfill(response=r, body=json.dumps(j))

    with pw.sync_playwright() as p:
        browser = _browser(p)
        try:
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            page.route("**/api/app", patch)
            page.goto(url + "setup")
            page.wait_for_selector(".mode[data-mode=test]")
            assert not page.eval_on_selector("#logbox", "d => d.open")
            state["failed"] = True
            page.wait_for_function("document.querySelector('#logbox').open", timeout=5000)
            assert page.inner_text("#status") == ("Find song sections in my Mixxx music: didn't start: "
                                                  "Mixxx library not found at C:/Users/x/mixxxdb.sqlite")
            assert page.eval_on_selector_all("#log details.tb", "ds => ds.length") == 3
            text = page.inner_text("#log")
            assert "Traceback" not in text and "BrokenPipeError" not in text
            assert text.count("A technical error was logged. Llano can read it here.") == 3
            page.click("#log details.tb summary")
            n = state["polls"]
            page.wait_for_function("t => document.querySelector('#log').innerText.includes('still here ' + t)", arg=n + 2, timeout=8000)
            # the log redrew twice since, and the opened one is still open with the detail inside
            assert page.eval_on_selector_all("#log details.tb[open]", "ds => ds.length") == 1
            assert "BrokenPipeError" in page.inner_text("#log details.tb[open] pre")
        finally:
            browser.close()


def test_controls_bar_says_what_each_press_did(win):
    pw = pytest.importorskip("playwright.sync_api")
    app, url, token, _tmp = win
    with pw.sync_playwright() as p:
        browser = _browser(p)
        try:
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            page.goto(url + "setup")
            page.wait_for_selector(".mode[data-mode=demo]")
            assert _call(url + "api/run", {"mode": "demo", "song": ""}, token)[0] == 200
            page.wait_for_function("!document.querySelector('#controls button[data-k=b]').disabled", timeout=10000)
            said = {}
            for k in ("b", "b", "[", "+"):
                was = page.inner_text("#status")
                page.click(f'#controls button[data-k="{k}"]')
                page.wait_for_function("t => document.querySelector('#status').innerText !== t", arg=was, timeout=4000)
                said.setdefault(k, []).append(page.inner_text("#status"))
            assert said["b"] == ["Blackout is on", "Blackout is off"]
            assert said["["][0].startswith("Lights 5 ms earlier")
            assert said["+"][0].startswith("Brightness")
            page.click("#sceneback")
            page.wait_for_function("document.querySelector('#status').innerText === 'Nothing is held: the show is already running its own looks.'")
        finally:
            browser.close()


def test_guide_checking_and_a_confirm_that_stops_its_run(win):
    pw = pytest.importorskip("playwright.sync_api")
    app, url, token, _tmp = win
    with pw.sync_playwright() as p:
        browser = _browser(p)
        try:
            page = browser.new_page(viewport={"width": 1024, "height": 700})
            page.goto(url + "guide")
            page.wait_for_selector("li[data-key=lights]")
            page.click("#recheck")
            assert page.inner_text("#recheck") == "Checking..."
            page.wait_for_function("document.querySelector('#checkedall').innerText.startsWith('Checked just now, ')", timeout=20000)
            # step 1 offers the download page
            page.click("li[data-key=app] .head")
            assert page.get_attribute("li[data-key=app] button[data-act^='link:https://llano.app']", "data-act") == \
                "link:https://llano.app/gigbar-laptop-controller.html"
            # Yes, it worked while the light test runs: the test stops, the step counts, the next run starts
            assert _call(url + "api/run", {"mode": "test"}, token)[0] == 200
            page.wait_for_function("!document.querySelector('#running').hidden", timeout=5000)
            page.evaluate("openKey = 'lights'; render()")
            page.dblclick("li[data-key=lights] button[data-confirm]")
            page.wait_for_function("document.querySelector('li[data-key=lights]').classList.contains('ok')", timeout=20000)
            assert app.running in (None, "") and page.inner_text("#msg") == ""
            assert _call(url + "api/run", {"mode": "preview"}, token)[0] == 200
            assert _call(url + "api/stop", {}, token)[0] == 200
            _wait_idle(app)
        finally:
            browser.close()


def test_guide_i_did_this_on_a_step_the_app_cannot_check(win):
    pw = pytest.importorskip("playwright.sync_api")
    _app, url, _token, _tmp = win

    def cant_tell(route):   # the loopMIDI step reads "Can't tell here" whatever this machine has
        r = route.fetch()
        j = r.json()
        for st in j["steps"]:
            if st["key"] == "loopmidi":
                st["ok"] = None
        route.fulfill(response=r, body=json.dumps(j))

    with pw.sync_playwright() as p:
        browser = _browser(p)
        try:
            page = browser.new_page(viewport={"width": 1024, "height": 700})
            page.route("**/api/guide", cant_tell)
            page.goto(url + "guide")
            page.wait_for_selector("li[data-key=loopmidi].unknown")
            done = page.inner_text("#count")
            page.evaluate("openKey = 'loopmidi'; render()")
            assert page.eval_on_selector_all("li.step:not(.unknown) button[data-did]", "bs => bs.length") == 0
            page.click("li[data-key=loopmidi] button[data-did]")
            assert page.inner_text("li[data-key=loopmidi] .state") == "Done (you said so)"
            assert page.inner_text("#count") != done
            page.wait_for_timeout(2300)   # a poll later the mark holds
            assert page.inner_text("li[data-key=loopmidi] .state") == "Done (you said so)"
            page.evaluate("openKey = 'loopmidi'; render()")
            page.click("li[data-key=loopmidi] button[data-undid]")
            assert page.inner_text("li[data-key=loopmidi] .state") == "Can't tell here"
            assert page.inner_text("#count") == done
        finally:
            browser.close()


# --- the lead's review round (PR #150) ---------------------------------------------------------

def test_a_held_key_makes_only_a_handful_of_state_reads(win):
    pw = pytest.importorskip("playwright.sync_api")
    _app, url, token, _tmp = win
    with pw.sync_playwright() as p:
        browser = _browser(p)
        try:
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            page.goto(url + "setup")
            page.wait_for_selector(".mode[data-mode=demo]")
            assert _call(url + "api/run", {"mode": "demo", "song": ""}, token)[0] == 200
            page.wait_for_function("!document.querySelector('#controls button[data-k=b]').disabled", timeout=10000)
            reads, keys = [], []
            page.on("request", lambda r: reads.append(r.url) if r.url.endswith("/api/app") else
                    keys.append(r.url) if "/key?k=" in r.url else None)
            page.focus("body")
            t0 = time.time()
            page.keyboard.down("-")
            for _ in range(19):   # 20 keydowns in all: the first plus 19 auto-repeats
                page.keyboard.down("-")
                page.wait_for_timeout(33)
            page.keyboard.up("-")
            page.wait_for_function("document.querySelector('#status').innerText.startsWith('Brightness')", timeout=5000)
            page.wait_for_timeout(600)
            secs = time.time() - t0
            assert len(keys) == 20, "one POST per keydown, as before"
            polls = secs / 0.5 + 2   # the page's own poll runs every 500 ms during a show
            assert len(reads) <= polls + 6, (len(reads), round(secs, 2))
        finally:
            browser.close()


def _fake_runs(state):
    """Patch /api/app with the run state the test sets in `state` (running, last_run, warning, log)."""
    def patch(route):
        r = route.fetch()
        j = r.json()
        j.update({k: v for k, v in state.items() if k in ("running", "last_run", "warning", "log")})
        route.fulfill(response=r, body=json.dumps(j))
    return patch


FAILED_ANALYZE = "Find song sections in my Mixxx music: didn't start; the log below says why"


def _failed_log(stamp):
    return [f"{stamp} --- Find song sections in my Mixxx music ---",
            f"{stamp} Following the show 'X': each of its songs plays its look.",
            f"{stamp} {FAILED_ANALYZE}"]


def test_the_same_failure_twice_reopens_the_log_and_a_non_reason_is_not_named(win):
    pw = pytest.importorskip("playwright.sync_api")
    _app, url, _token, _tmp = win
    state = {"running": None, "last_run": "", "log": ["06:00:00 Llano Lights"]}
    with pw.sync_playwright() as p:
        browser = _browser(p)
        try:
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            page.route("**/api/app", _fake_runs(state))
            page.goto(url + "setup")
            page.wait_for_selector(".mode[data-mode=test]")
            page.wait_for_timeout(1200)
            for stamp in ("06:01:00", "06:02:00"):   # the same words both times
                state.update(running="analyze")
                page.wait_for_function("document.querySelector('#nowtitle').innerText.includes('is running')", timeout=5000)
                state.update(running=None, last_run=FAILED_ANALYZE, log=state["log"] + _failed_log(stamp))
                page.wait_for_function("document.querySelector('#logbox').open", timeout=5000)
                # "Following the show" is not a reason: the status line does not name it as one
                assert page.inner_text("#status") == "Find song sections in my Mixxx music: didn't start; the log is open below"
                page.click("#logbox summary")   # he closes it, and tries again
                page.wait_for_function("!document.querySelector('#logbox').open")
        finally:
            browser.close()


def test_a_heads_up_from_a_failed_start_stays_for_his_ok(win):
    pw = pytest.importorskip("playwright.sync_api")
    _app, url, _token, _tmp = win
    warn = {"level": "warn", "text": "Heads up: Mixxx isn't open.", "lights": False}
    state = {"running": None, "last_run": "", "warning": None, "log": ["06:00:00 Llano Lights"]}
    with pw.sync_playwright() as p:
        browser = _browser(p)
        try:
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            page.route("**/api/app", _fake_runs(state))
            page.goto(url + "setup")
            page.wait_for_selector(".mode[data-mode=test]")
            state.update(running="live", warning=warn)
            page.wait_for_function("document.querySelector('#banners').innerText.includes('Mixxx isn')", timeout=5000)
            state.update(running=None, last_run="Live show: lights follow Mixxx, Spotify or YouTube Music: didn't start; the log below says why",
                         log=state["log"] + ["06:01:00 --- Live show: lights follow Mixxx, Spotify or YouTube Music ---",
                                             "06:01:00 Live show: lights follow Mixxx, Spotify or YouTube Music: didn't start; the log below says why"])
            page.wait_for_function("document.querySelector('#nowtitle').innerText === 'Nothing running'", timeout=5000)
            page.wait_for_timeout(6500)
            assert "Heads up: Mixxx isn't open." in page.inner_text("#banners")
        finally:
            browser.close()


def test_a_refusal_while_check_my_setup_runs_says_it_finishes_by_itself(win):
    pw = pytest.importorskip("playwright.sync_api")
    _app, url, _token, _tmp = win

    def refuse(route):
        route.fulfill(status=409, content_type="application/json",
                      body=json.dumps({"error": "'Check my setup' is running; stop it first"}))

    with pw.sync_playwright() as p:
        browser = _browser(p)
        try:
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            page.route("**/api/run", refuse)
            page.goto(url + "setup")
            page.wait_for_selector(".mode[data-mode=test]")
            page.click(".mode[data-mode=test]")
            page.wait_for_function("document.querySelector('#banners').innerText.includes('Check my setup is running')", timeout=5000)
            txt = page.inner_text("#banners")
            assert "Check my setup is running. It finishes by itself in a moment, then start this." in txt
            assert "Press Stop" not in txt
            g = browser.new_page()
            g.route("**/api/run", refuse)
            g.goto(url + "guide")
            g.wait_for_selector("li[data-key=lights]")
            g.evaluate("openKey = 'lights'; render()")
            g.click("li[data-key=lights] button[data-act='run:test']")
            g.wait_for_function("document.querySelector('#msg').innerText.includes('finishes by itself')", timeout=5000)
            assert g.inner_text("#msg") == "Check my setup is running. It finishes by itself in a moment, then try again."
        finally:
            browser.close()


@pytest.mark.parametrize("key", ["Enter", " "])
def test_stop_works_from_the_keyboard(win, key):
    pw = pytest.importorskip("playwright.sync_api")
    app, url, token, _tmp = win
    with pw.sync_playwright() as p:
        browser = _browser(p)
        try:
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            page.goto(url + "setup")
            page.wait_for_selector(".mode[data-mode=test]")
            assert _call(url + "api/run", {"mode": "test"}, token)[0] == 200
            page.wait_for_function("!document.querySelector('#stop').disabled", timeout=8000)
            page.focus("#stop")
            page.keyboard.press(key)
            assert page.inner_text("#stop") == "Click again to stop"
            page.keyboard.press(key)
            page.wait_for_function("document.querySelector('#nowtitle').innerText === 'Nothing running'", timeout=15000)
            assert _wait_idle(app)
        finally:
            browser.close()
