"""The phone page is safe and easy to tap in a dark room (Llano BL #11473).

What can be checked without a browser: the fold that keeps the show settings shut, the Crowd-safe
question, the tap sizes the phone layout asks for, the name box's place and the hit buttons sending
on and off in order. The headless Playwright run (heights, truncation, a tap sequence down the page)
is in the PR body.
"""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"
JS = (SRC / "studio_console.js").read_text(encoding="utf-8")
REMOTE = (SRC / "remote.html").read_text(encoding="utf-8")


def css(selector_part):
    """Every CSS rule (from the console's CSS list) whose selector contains selector_part."""
    rules = [r + "}" for line in re.findall(r'"([^"]*\{[^"]*\})"', JS) for r in line.split("}") if "{" in r]
    return [r for r in rules if selector_part in r.split("{")[-2 if r.count("{") > 1 else 0]]


def test_show_settings_sit_in_a_fold_shut_by_default_on_the_phone():
    assert ('<details class="lls-fold"><summary>Show settings: change these at home, not during the party'
            '</summary><div></div></details>') in JS
    assert "<details class=\"lls-fold\" open" not in JS, "shut by default"
    assert ".lls-fold:not([open])>div{display:none}" in JS, "shut, nothing in it can be tapped"
    assert "SB.innerHTML = h" in JS and "P.settings.innerHTML = h" not in JS, "the settings draw inside the fold"


def test_turning_crowd_safe_off_asks_first():
    assert '"Turn Crowd-safe off? Strobes can then flash faster and brighter."' in JS
    assert 'o.path === "crowd_safe" && o.value === false' in JS


def test_every_phone_control_asks_for_44_px():
    for sel in (".lls-phone .lls-mini", ".lls-phone .lls-step", ".lls-phone .lls-btn", ".lls-phone .lls-tabs .t",
                ".lls-phone .lls-pad .del", ".lls-phone .lls-heads"):
        rules = [r for r in css(sel) if re.search(r"min-height:4[4-9]px", r)]
        assert rules, f"{sel} has no 44 px floor"
    assert any("width:44px;height:44px" in r for r in css(".lls-phone .lls-dot"))
    assert any("width:44px;height:44px" in r for r in css(".lls-phone .lls-mood .sw button"))
    assert any("width:44px;height:44px" in r for r in css(".lls-phone .lls-count button"))
    assert re.search(r"\.away a \{[^}]*min-height:44px", REMOTE)


def test_take_over_reads_as_a_label_and_hover_follow_stays_grayed_with_its_reason_in_words():
    """His rule of 2026-11-12: what this path cannot do stays in place, grayed, with the reason on it.
    A phone has no hover, so the reason is words beside the button, not a title."""
    assert '<span class="lls-lbl" title="Steer the heads yourself instead of the show">Take over:</span>' in JS
    assert "lls-hoverbtn{display:none" not in JS
    assert "(c.hover && !wide ? '<span class=\"why lls-whynote\">' + esc(c.hover)" in JS


def test_the_name_box_opens_near_the_top_and_closes_when_he_moves_on():
    assert any("top:calc(var(--lls-stop-top,0px) + 74px" in r and "bottom:auto" in r for r in css(".lls-toast.ask"))
    assert "if (asking && !E.toast.contains(t)) askDone(false);" in JS


def test_a_quick_tap_on_a_hold_button_never_leaves_it_on():
    """On and off a few ms apart, sent side by side, could land off first and leave a strobe on."""
    assert "function hitSend(cmd)" in JS
    assert 'hitSend({op: "hit", name: name, on: true})' in JS and 'hitSend({op: "hit", name: name, on: false})' in JS


def test_a_warning_never_pushes_the_controls_down():
    assert any("position:fixed" in r for r in css(".lls-phone .lls-banner"))
    assert any("position:absolute" in r for r in css(".lls-wide>.lls-banner"))


def test_button_words_are_never_cut_off():
    assert not any("-webkit-line-clamp" in r for r in css(".lls-pad p")), "a pad says its whole line"
    assert ".lls .lls-light{white-space:normal" in JS, "Freedom Stick 1 to 4 keep their numbers"
    assert '"Steering all heads"' in JS and '"Not lined up here yet"' in JS
