"""The night tells him what to press, and the phone never lies about its connection (Llano BL #11473).

What can be checked without a browser: the words every screen shows, and the timings that decide
when the phone says the laptop is not answering and how often an unpaired phone asks again. The
headless Playwright run (412x915, 360x640, 915x412, 1366x768) is in the PR body.
"""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"
JS = (SRC / "studio_console.js").read_text(encoding="utf-8")
REMOTE = (SRC / "remote.html").read_text(encoding="utf-8")
STUDIO = (SRC / "studio.html").read_text(encoding="utf-8")


def test_the_now_box_says_the_step_its_wait_and_what_to_press():
    assert 'data-t="nowbox"' in JS and "function drawNow(night)" in JS
    assert "sx.wait" in JS
    # before Mixxx has been seen, a built night says how to start it
    # Mixxx 2.5.4 shows no "Enable Auto DJ" words, only an icon (the lead's proof run, 2026-11-15)
    assert ("Mixxx plays the music. Start it there: click <span>Auto DJ</span> in Mixxx\\'s list on the left, "
            "then the first button at the top of that page. This list then follows along.") in JS
    assert "sx.press ?" in JS and "night.press ||" not in JS, "the box says the press line of the step it names"


def test_a_hold_row_says_it_stops_until_fade_now_and_a_tap_shows_its_press_line():
    assert '"Stop: waits for Fade Now"' in JS
    # a tap opens the row (its own press line and Go here now); it never jumps the night by itself
    assert 'data-step="' in JS and "openStep = openStep === si ? -1 : si" in JS
    assert ">Go here now</button>" in JS and 'cmdAttr({op: "goto", i: i})' in JS
    assert "Then press: " in JS


def test_the_live_screen_reaches_shows_and_the_phone_does_not():
    assert 'data-t="shows"' in JS and "E.shows.href = opts.links.shows" in JS
    assert 'links: {setup: "/setup", shows: "/shows"}' in STUDIO
    assert "links:" not in REMOTE


def test_the_phone_says_when_the_laptop_is_not_answering_within_ten_seconds():
    lost_ms = int(re.search(r"LOST_MS = (\d+)", JS).group(1))
    ask_ms = int(re.search(r"const ASK_MS = (\d+)", REMOTE).group(1))
    assert lost_ms + 1000 <= 10000, "judged by time since the last answer, checked every 500 ms"
    assert ask_ms < 10000 and "AbortController" in REMOTE, "a hanging request gives up instead of waiting for TCP"
    assert ("Llano Lights on the laptop is not answering. Check that Llano Lights is still open on the laptop, "
            "and that this phone is on the laptop's Wi-Fi. This screen comes back by itself.") in REMOTE
    assert "dot(!lost, opts.link()" in JS, "the Wi-Fi dot turns red"
    # a tap while lost sends nothing, except STOP (and the way out under the message); the browser tests
    # in test_phone_console_browser.py press them for real
    assert 'if (lost && !e.target.closest(".lls-stop") && !e.target.closest(".lls-lostmsg"))' in JS
    assert ":not(.lls-stop):not(.lls-health)" in JS, "STOP and the red dot are never dimmed"
    assert "If this phone has left the laptop's Wi-Fi: use the internet instead." in REMOTE
    assert "Connecting to the laptop..." in REMOTE
    assert "Is this phone on the same Wi-Fi" not in REMOTE, "the old words blamed the Wi-Fi"


def test_an_unpaired_phone_shows_one_screen_and_asks_at_most_every_five_seconds():
    assert "const RETRY_MS = 5000;" in REMOTE
    assert ("This phone is not connected to the laptop yet. On the laptop open Llano Lights, press Set up, "
            "find Llano Lights on your phone, and point this phone's camera at the code.") in REMOTE
    assert "The code changed: scan it again." in REMOTE
    assert "body.unpaired #note, body.unpaired #studio, body.unpaired .away, body.unpaired #connecting { display:none; }" in REMOTE
    assert "s.status === 403" in REMOTE and "studio.destroy()" in REMOTE
    assert 'addEventListener("hashchange"' in REMOTE, "a code scanned while the page is open pairs it"


def test_stop_and_blackout_answer_back_and_the_held_card_never_claims_a_look_in_blackout():
    assert '"Stopped. The lights are off."' in JS and '"Press Live show to start again."' in JS
    assert '"Stopping..."' in JS and '"STOP was sent but the lights are still on."' in JS
    assert '"Press STOP again, or use Stop on the laptop."' in JS
    assert '"Blackout is on."' in JS and '"Press Blackout again to bring the lights back."' in JS
    assert "E.rel.style.display = (look || s.frozen) && !s.blackout" in JS


def test_stop_has_its_own_bar_on_the_phone_so_it_covers_nothing():
    assert '<div class="lls-bar"></div>' in JS
    assert ".lls-phone{min-height:100%;padding:64px 0 28px" in JS, "the layout reserves the bar"
    assert re.search(r"\.lls-phone \.lls-stop\{[^}]*height:48px", JS)
    assert "scroll-padding-top" in REMOTE


def test_no_dash_used_as_punctuation_in_the_phone_page():
    assert "—" not in REMOTE and "–" not in REMOTE
    for words in ("Stop: waits for Fade Now", "Then press: ", "Nothing to press here.", "Go here now"):
        assert words in JS
