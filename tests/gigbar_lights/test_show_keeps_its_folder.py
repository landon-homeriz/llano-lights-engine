"""The check for Llano BL #12426: a saved show opens with its song folder, lengths and needs after the app
comes back on another port.

Found in the Nov 15 click-through of 1.28.0: the app restarted on another port of 8765-8784, the saved show
was reopened, and step 2's folder box was empty and the "no moment yet" needs line was gone, because the
show's night plan lived only in the window's localStorage, which a browser keeps per origin (per port).

This loads his folder's shape in one app copy, saves the show, then opens it from a NEW browser context
(empty storage) against a SECOND app copy on a different port that shares the same settings folder. It
fails on main 7d941ea/c26f528 (empty folder box, no unplaced line) and passes with the app keeping the plan.
One test, so the file holds two of CI's twenty preview ports for as short a time as it can.
"""
import argparse

import pytest

pytest.importorskip("numpy")
pytest.importorskip("soundfile")

from tests.gigbar_lights.test_compilation_fill_11473 import _compilation  # noqa: E402
from tests.gigbar_lights.test_shows import lib, window  # noqa: E402,F401


def _second_copy(tmp_path, lib):  # noqa: F811
    """Another Llano Lights on the same laptop: the same settings folder, the next free port."""
    import gigbar_app   # on sys.path from the window fixture
    from tools.gigbar_lights.venue import LayoutStore
    opts = argparse.Namespace(seconds=0.0, bpm=128.0, no_browser=True, no_window=True, updated=False, update_failed=False)
    app = gigbar_app.App(opts, gigbar_app.LogBuffer(tmp_path / "log2.txt"))
    app.preview = gigbar_app.Preview("", LayoutStore(tmp_path / "layouts"), app=app)
    return app


def test_the_saved_show_opens_with_its_folder_on_another_port(window, lib):  # noqa: F811
    pw = pytest.importorskip("playwright.sync_api")
    app1, url1, _token, tmp = window
    root = _compilation(tmp / "A&J songs")
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        app2 = None
        try:
            # the first window: his folder in, the show saved under his own name (an & and a slash)
            page = browser.new_context().new_page()
            page.goto(url1 + "shows")
            page.wait_for_selector("#save")
            page.wait_for_function("N.moments.length > 0", timeout=10000)
            page.fill("#title", "A&J Wedding / reception")
            page.fill("#folder", str(root))
            page.click("#addfolder")
            page.wait_for_function("document.querySelectorAll('#songs select[data-part]').length === 10", timeout=10000)
            page.wait_for_function("!document.querySelector('#design').disabled", timeout=30000)
            page.fill("#nt-dinner", "6:15")
            page.dispatch_event("#nt-dinner", "change")
            page.click("#save")
            page.wait_for_function("show.name !== ''", timeout=10000)
            name = page.evaluate("show.name")
            page.wait_for_timeout(800)          # the plan's send goes a moment after the last change
            page.close()                        # and the window closes, as a restart would

            # the app comes back on another port; its window has none of the first one's storage
            app2 = _second_copy(tmp, lib)
            url2 = app2.preview.url
            assert url2 != url1
            fresh = browser.new_context().new_page()
            fresh.goto(url2 + "shows")
            fresh.wait_for_selector("#saved button")
            fresh.wait_for_function("N.moments.length > 0", timeout=10000)
            assert fresh.evaluate("localStorage.length") == 0
            fresh.click("#saved button")
            fresh.wait_for_function(f"show.name === {name!r} && show.songs.length === 10", timeout=10000)

            assert fresh.input_value("#nightfolder") == str(root)                       # Build the night's folder box
            assert fresh.input_value("#nt-dinner") == "6:15"
            secs = fresh.evaluate("show.songs.map(s => s.secs || 0)")
            assert len(secs) == 10 and sum(1 for x in secs if x > 0) == 9, secs           # one file holds no length
            fresh.wait_for_function("document.querySelector('#nopart li[data-kind=unplaced]')", timeout=10000)
            lines = fresh.eval_on_selector_all("#nopart li[data-kind=unplaced]", "els => els.map(e => e.innerText)")
            assert any("Our Own Song" in t and "no moment is known" in t for t in lines), lines

            # the folder renamed on disk: said in words, never a silent empty box
            root.rename(root.with_name("A&J songs moved"))
            fresh.dispatch_event("#nt-dinner", "change")
            fresh.wait_for_function("document.querySelector('#nopart li[data-kind=folder]')", timeout=10000)
            assert "can't be found on this laptop (moved or renamed?): press Browse in step 2" in fresh.inner_text("#nopart li[data-kind=folder]")
        finally:
            browser.close()
            if app2 is not None:
                app2.stop()
                if app2.runner:
                    app2.runner.join(timeout=8)
                app2.preview.close()
