"""Browse and Enter while songs are still being added (Llano BL #12438).

While one add runs, the page disables its add buttons (one add at a time). Browse
and Enter in the Folder box used to start their add by calling click() on
#addfolder, and a disabled button ignores click(): he picked his folder and the
page did nothing and said nothing. Every path now calls the guarded add itself,
so it says 'Still adding the last songs...' and adds nothing twice; Browse is
disabled with the other add buttons while an add runs.

Real browser: the page's own requests are held open with Playwright routes, so
an add is provably still running when Browse's picker returns and when Enter is
pressed."""
from __future__ import annotations

import pytest

from tests.gigbar_lights.test_shows import lib, window  # noqa: F401

STILL = "Still adding the last songs. Wait for them, then add more."


def _wedding(tmp):
    src = tmp / "Wedding"
    (src / "3 - Dancing").mkdir(parents=True)
    for name in ("Dua Lipa - Levitating", "Journey - Faithfully"):
        (src / "3 - Dancing" / f"{name}.mp3").write_bytes(b"x")
    return src


def _until(page, ok, secs=5.0):
    for _ in range(int(secs * 10)):
        if ok():
            return
        page.wait_for_timeout(100)   # routes are handled while Playwright waits
    raise AssertionError("timed out")


def test_browse_and_enter_while_an_add_is_running_say_so_and_add_nothing_twice(window, monkeypatch):  # noqa: F811
    pw = pytest.importorskip("playwright.sync_api")
    app, url, token, tmp = window
    import gigbar_app
    src = _wedding(tmp)
    monkeypatch.setattr(gigbar_app.folder_picker, "pick", lambda title, start: (str(src), ""))
    held = {"pick": [], "folder": []}
    reads = []

    def hold(kind):
        def handler(route):
            if kind == "folder":
                reads.append(route.request.post_data)
            held[kind].append(route)
        return handler

    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            page = browser.new_page()
            page.goto(url + "shows")
            page.wait_for_selector("#save")
            page.click('[data-tab="folder"]')
            page.route("**/api/shows-pick-folder", hold("pick"))
            page.route("**/api/shows-folder", hold("folder"))

            # Browse first: the picker is open (its request held) ...
            page.click("#browse")
            page.wait_for_function("document.querySelector('#browse').textContent === 'Choosing...'", timeout=5000)
            # ... and meanwhile Enter in the Folder box starts an add, which is held open too
            page.fill("#folder", str(src))
            page.press("#folder", "Enter")
            page.wait_for_function("document.querySelector('#addfolder').disabled", timeout=5000)
            _until(page, lambda: held["folder"])   # the folder read is on its way, and held

            # Enter again while it runs: said, not silent, and no second read
            page.press("#folder", "Enter")
            page.wait_for_function("t => document.querySelector('#msg').innerText.includes(t)", arg=STILL, timeout=3000)

            # the picker hands back the folder while the add still runs: said, not silent
            page.evaluate("() => { document.querySelector('#msg').textContent = ''; }")
            held["pick"].pop().continue_()
            page.wait_for_function("t => document.querySelector('#msg').innerText.includes(t)", arg=STILL, timeout=5000)
            # Browse is off with the other add buttons while the add runs
            assert page.is_disabled("#browse") and page.is_disabled("#addfolder")
            assert len(held["folder"]) == 1 and len(reads) == 1

            # let the one add finish: two songs, added once, and every add button back on
            held["folder"].pop().continue_()
            page.wait_for_function("document.body.innerText.includes('Added 2 songs from the folder')", timeout=8000)
            page.wait_for_function("!document.querySelector('#addfolder').disabled", timeout=20000)
            assert not page.is_disabled("#browse")
            assert page.evaluate("() => show.songs.length") == 2 and len(reads) == 1
        finally:
            browser.close()


def test_an_add_that_ends_while_the_picker_is_open_leaves_browse_off_until_the_picker_closes(window, monkeypatch):  # noqa: F811
    """The lead's review of PR 160: once the add buttons' state owned #browse, an add
    ending with the picker still open turned Browse back on while it read 'Choosing...';
    a second press then kept 'Choosing...' as its label for good."""
    pw = pytest.importorskip("playwright.sync_api")
    app, url, token, tmp = window
    import gigbar_app
    src = _wedding(tmp)
    monkeypatch.setattr(gigbar_app.folder_picker, "pick", lambda title, start: (str(src), ""))
    held = []
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            page = browser.new_page()
            page.goto(url + "shows")
            page.wait_for_selector("#save")
            page.click('[data-tab="folder"]')
            page.route("**/api/shows-pick-folder", lambda route: held.append(route))
            page.click("#browse")
            _until(page, lambda: held)
            # an add starts and FINISHES while the picker is still open
            page.fill("#folder", str(src))
            page.press("#folder", "Enter")
            page.wait_for_function("document.body.innerText.includes('Added 2 songs from the folder')", timeout=8000)
            page.wait_for_function("!document.querySelector('#addfolder').disabled", timeout=20000)
            assert page.is_disabled("#browse") and page.inner_text("#browse") == "Choosing..."
            # the picker closes: Browse is back, with its own label
            held.pop().continue_()
            page.wait_for_function("!document.querySelector('#browse').disabled", timeout=8000)
            assert page.inner_text("#browse") == "Browse..."
        finally:
            browser.close()
