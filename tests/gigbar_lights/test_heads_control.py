"""The moving heads' one control: Stop heads, Take over, Back to auto (Llano BL #12339).

The ask, 2026-11-14: the heads move on their own in the dances, with a way to stop them
or take over. One clear control on every screen (the laptop, the phone, llano.app/lights; they
all draw studio_console.js and send studio.Studio commands):

  Stop heads     every moving head dark and still until he resumes them
  Take over      Follow someone or a Spotlight pad steers the heads instead of the show
  Back to auto   the spots off, a Spotlight pad let go, Stop let go: the show moves them again

These are measured on the frames the show sends, and in the console in a real browser.
"""
from __future__ import annotations

import json

import pytest

from tests.gigbar_lights.test_part_mood import mount_console
from tests.gigbar_lights.test_shows import lib, window  # noqa: F401
from tests.gigbar_lights.test_studio_engine import make, run
from tools.gigbar_lights import show_settings, studio


@pytest.fixture(autouse=True)
def _clean():
    yield
    show_settings.clear_play()
    show_settings.clear_scene()


def heads(show):
    return [(h.dim, h.strobe, round(h.pan, 4), round(h.tilt, 4)) for bar in show.rig.bars for h in bar.movers]


def lit(show) -> float:
    return max(h.dim for bar in show.rig.bars for h in bar.movers)


def party(show):
    """A look whose heads move and shine on their own (the Party pad over the pretend song)."""
    show.studio.command({"op": "look", "key": "scene:party"})


def test_stop_heads_darkens_and_holds_every_head_until_resume():
    show = make()
    st = show.studio
    party(show)
    run(show, 4)
    assert lit(show) > 0 and st.heads_mode()["mode"] == "auto"
    st.command({"op": "heads", "do": "stop"})
    assert st.heads_mode()["mode"] == "stop" and not st.idle()
    poses = []
    run(show, 6, t0=1004.0, each=lambda now, i: poses.append(heads(show)))
    poses = poses[5:]   # the frames after the press
    assert all(d == 0 and s == 0 for p in poses for d, s, _pan, _tilt in p), "a head stayed lit"
    assert len({tuple((pan, tilt) for _d, _s, pan, tilt in p) for p in poses}) == 1, "a stopped head moved"
    wash = max(fx.dim for fx in (*show.rig.tetras, *show.rig.sticks))
    assert wash > 0, "only the heads stop: the rest of the look plays on"
    st.command({"op": "heads", "do": "resume"})
    run(show, 4, t0=1010.0)
    assert lit(show) > 0 and st.heads_mode()["mode"] == "auto"


def test_take_over_with_follow_someone_lights_stopped_heads_and_back_to_auto_lets_go():
    show = make()
    st = show.studio
    party(show)
    st.command({"op": "heads", "do": "stop"})
    run(show, 4)
    assert lit(show) == 0
    st.command({"op": "spots", "on": True})   # Take over: Follow someone
    assert st.heads_mode()["mode"] == "yours" and not st.heads_stop
    run(show, 3, t0=1004.0)
    assert lit(show) > 0, "the spot he steers is lit"
    st.command({"op": "heads", "do": "auto"})
    assert not st.spots["on"] and st.heads_mode()["mode"] == "auto"
    assert st.look and st.look["key"] == "scene:party", "Back to auto lets go of the heads, not of the look he holds"


def test_take_over_with_a_spotlight_pad_and_back_to_auto_releases_only_that_pad():
    show = make()
    st = show.studio
    st.command({"op": "heads", "do": "stop"})
    st.command({"op": "look", "key": "moment:spotlight"})
    assert not st.heads_stop and st.heads_mode()["mode"] == "yours"
    run(show, 4)
    assert lit(show) > 0
    st.command({"op": "heads", "do": "auto"})
    assert st.look is None and st.heads_mode()["mode"] == "auto"
    st.command({"op": "look", "key": "moment:two-spotlights"})
    assert st.heads_mode()["mode"] == "yours"


def test_stop_wins_over_a_pad_pressed_after_it_that_is_not_a_take_over():
    show = make()
    st = show.studio
    st.command({"op": "heads", "do": "stop"})
    party(show)   # a look pad: the heads stay stopped (only Follow someone or a Spotlight pad takes them)
    run(show, 4)
    assert st.heads_stop and lit(show) == 0


def test_the_heads_command_refuses_nonsense_and_a_run_ending_lets_stop_go():
    st = studio.Studio(live=True)
    with pytest.raises(studio.CommandError):
        st.command({"op": "heads", "do": "spin"})
    st.command({"op": "heads", "do": "stop"})
    assert st.public()["heads"]["mode"] == "stop"
    st.reset()
    assert not st.heads_stop and st.public()["heads"]["mode"] == "auto"


def test_the_control_in_a_real_browser(window):  # noqa: F811
    """The console draws one Heads control under the stage on every screen: its state, Stop heads,
    Take over (Follow someone, Spotlight, Two spotlights) and Back to auto, each sending one command."""
    pw = pytest.importorskip("playwright.sync_api")
    app, _url, _token, _tmp = window
    state = json.loads(json.dumps(app.studio_state()))
    assert state["studio"]["heads"]["mode"] == "auto"
    stopped = json.loads(json.dumps(state))
    stopped["studio"]["heads"] = {"mode": "stop", "line": "Stopped"}
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            page = browser.new_page()
            mount_console(page, state)
            page.wait_for_selector(".lls-heads")
            assert "Auto" in page.inner_text(".lls-heads")
            bar = page.locator(".lls-stagebar")
            for label, want in (("Stop heads", {"op": "heads", "do": "stop"}),
                                ("Follow someone", {"op": "spots", "on": True}),
                                ("Spotlight", {"op": "look", "key": "moment:spotlight"}),
                                ("Two spotlights", {"op": "look", "key": "moment:two-spotlights"})):
                page.evaluate("SENT.length = 0")
                bar.get_by_role("button", name=label, exact=True).click()
                page.wait_for_function("SENT.length === 1")
                assert page.evaluate("SENT[0]") == want, label
            assert bar.get_by_role("button", name="Back to auto").count() == 0, "nothing to go back from"
            mount_console(page, stopped)
            page.wait_for_selector(".lls-heads.stop")
            assert "Stopped" in page.inner_text(".lls-heads")
            for label, want in (("Resume heads", {"op": "heads", "do": "resume"}),
                                ("Back to auto", {"op": "heads", "do": "auto"})):
                page.evaluate("SENT.length = 0")
                page.locator(".lls-stagebar").get_by_role("button", name=label, exact=True).click()
                page.wait_for_function("SENT.length === 1")
                assert page.evaluate("SENT[0]") == want, label
            # the phone draws the same control
            page.set_viewport_size({"width": 390, "height": 844})
            page.set_content('<div id="host"></div>')
            page.add_script_tag(path=str(__import__("tests.gigbar_lights.test_part_mood", fromlist=["CONSOLE"]).CONSOLE))
            page.evaluate("""(st) => { window.SENT = [];
              LlanoStudio.mount(document.getElementById("host"), {layout: "phone", screen: "phone", pollMs: 60000,
                transport: {state: () => Promise.resolve(st), stop: () => Promise.resolve({ok: true}),
                            send: (cmd) => { SENT.push(cmd); return Promise.resolve({ok: true}); }}}); }""", state)
            # on the phone the control sits in the shut "Moving heads" fold, its state in the title
            # (Llano BL #12419): one tap opens it
            page.wait_for_selector("[data-fold=heads] .lls-foldnow:has-text('Auto')")
            page.locator("[data-fold=heads]>summary").click()
            page.wait_for_selector(".lls-heads")
            stop = page.locator(".lls-stagebar").get_by_role("button", name="Stop heads", exact=True)
            assert stop.is_visible()
            stop.click()
            page.wait_for_function("SENT.length === 1")
            assert page.evaluate("SENT[0]") == {"op": "heads", "do": "stop"}
        finally:
            browser.close()
