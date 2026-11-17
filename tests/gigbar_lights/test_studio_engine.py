"""The Light studio's engine (1.20.0, Llano PM #23195): the layers, and that nothing ends on a timer.

His asks, 2026-11-12: looks that HOLD until he changes them (static always-on, slow pulse, color
rotation), buttons that say what they do, one or two spotlights he steers smoothly with the arrow
keys (and, his margin note, by hovering the trackpad pointer), and state at a glance. These are the
recorded tests for the engine half: every claim a pad makes is measured on the frames it sends.
"""
import json
import math

import pytest

from tools.gigbar_lights import __main__ as gl
from tools.gigbar_lights import show_settings, studio, tonight, venue
from tools.gigbar_lights.show import Show


def make(live=True, path=None, layout=True):
    show = Show(analyze=False, venue=next(iter(venue.presets().values())) if layout else None)
    show.studio = studio.Studio(path=path, live=live)
    show.studio.fade_s = 0.0
    return show


def run(show, seconds, step=0.05, t0=1000.0, each=None, feed=None):
    """Render `seconds` of the pretend song; returns the frames past the heads' first glide."""
    feed = feed or gl.FakeMixxx(show, 128.0, loop=True)
    frames = []
    for i in range(int(seconds / step)):
        now = t0 + i * step
        feed(now)
        show.control_tick(now)
        frame = show.render(now)
        if each:
            each(now, i)
        if i * step > 3:
            frames.append(frame)
    return frames


@pytest.fixture(autouse=True)
def _clean():
    yield
    show_settings.clear_play()
    show_settings.clear_scene()


# --- a studio nobody touched changes nothing -----------------------------------------------------

def test_an_untouched_studio_never_touches_a_frame():
    show = make(live=False)
    assert show.studio.idle()
    show.studio.post = lambda *a, **k: (_ for _ in ()).throw(AssertionError("post ran on an idle studio"))
    run(show, 12)
    assert show.looks.overrides.simple is None and show.looks.overrides.color is None


# --- held looks ---------------------------------------------------------------------------------------

def test_steady_is_one_frame_for_twenty_minutes_whatever_the_music_does():
    show = make()
    show.studio.command({"op": "look", "key": "simple:steady"})
    frames = run(show, 20 * 60, step=0.5)
    assert show.looks.mode == "simple:steady"
    assert len(set(frames)) == 1, f"Steady changed {len(set(frames))} times"
    assert show.rig.tetras[0].dim > 0.5 and show.rig.sticks[0].dim > 0.5


def test_slow_pulse_breathes_every_six_seconds_on_the_clock_not_the_beat():
    def breath(bpm):
        show = make()
        show.studio.command({"op": "look", "key": "simple:pulse"})
        dims = []
        run(show, 30, step=0.05, each=lambda now, i: dims.append(show.rig.tetras[0].dim), feed=gl.FakeMixxx(show, bpm, loop=True))
        return dims[100:]
    slow, fast = breath(70.0), breath(160.0)
    assert max(slow) - min(slow) > 0.3, "the pulse barely breathes"
    assert slow == pytest.approx(fast, abs=1e-9), "the pulse followed the song's tempo"
    peaks = [i for i in range(1, len(slow) - 1) if slow[i - 1] < slow[i] >= slow[i + 1]]
    gaps = [(b - a) * 0.05 for a, b in zip(peaks, peaks[1:])]
    assert gaps and all(abs(g - 6.0) < 0.2 for g in gaps), gaps


def test_color_fade_drifts_through_colors_and_holds_its_level():
    show = make()
    show.studio.command({"op": "look", "key": "simple:fade"})
    seen, dims = set(), set()
    run(show, 90, step=0.5, each=lambda now, i: (seen.add(tuple(round(c, 2) for c in (show.rig.tetras[0].red, show.rig.tetras[0].green, show.rig.tetras[0].blue))),
                                                  dims.add(round(show.rig.tetras[0].dim, 4))))
    assert len(seen) > 10, "the color never drifted"
    assert len(dims) == 1, "Color fade changed brightness"


def test_a_held_look_never_ends_on_a_timer():
    # the longest timer in the old paths was 6 hours (a laptop moment); 10 and 30 minutes from the phone
    show = make()
    show.studio.command({"op": "look", "key": "moment:toast"})
    modes = set()
    run(show, 7 * 3600, step=20.0, each=lambda now, i: modes.add(show.looks.mode))
    assert modes == {"still"}, modes
    assert show.studio.look["key"] == "moment:toast"


def test_the_newest_press_wins_and_release_gives_the_show_back():
    show = make()
    st = show.studio
    st.command({"op": "look", "key": "simple:steady"})
    st.command({"op": "look", "key": "scene:party"})
    run(show, 5)
    assert show.looks.mode.startswith("scene:party") and show.looks.overrides.simple is None
    st.command({"op": "look", "key": "moment:photo"})
    run(show, 5)
    assert show.looks.mode == "still" and show.looks.overrides.scene is None
    st.command({"op": "release"})
    run(show, 5)
    assert show.looks.overrides.scene is None and show_settings.playing() is None
    assert show.looks.mode.split(":")[0] in ("scripted", "autoloop", "idle", "look", "silence")


def test_a_color_turns_any_look_that_color():
    show = make()
    st = show.studio
    st.command({"op": "look", "key": "simple:steady"})
    st.command({"op": "color", "color": "#0000ff"})
    run(show, 4)
    t = show.rig.tetras[0]
    assert (t.red, t.green, t.blue) == (0.0, 0.0, 1.0)
    st.command({"op": "look", "key": "moment:toast"})
    run(show, 4)
    t = show.rig.tetras[0]
    assert t.blue > 0.9 and t.red < 0.6, "the moment kept its own color"
    st.command({"op": "color", "color": ""})
    run(show, 4)
    assert show.rig.tetras[0].red > show.rig.tetras[0].blue, "the look's own warm color did not come back"


def test_still_motion_freezes_a_moving_moment():
    show = make()
    st = show.studio
    st.command({"op": "look", "key": "moment:first-dance"})
    st.command({"op": "motion", "motion": "still"})
    frames = run(show, 60, step=0.25)
    assert show.looks.mode == "still" and len(set(frames)) == 1


def test_an_older_screens_scene_pad_and_blackout_are_the_studios_when_it_is_the_front_page():
    show = make()
    gl.handle_key("scene:hype", show)
    assert show.studio.look["key"] == "scene:hype"
    gl.handle_key("b", show)
    assert show.studio.blackout is True
    gl.handle_key("scene:", show)
    assert show.studio.look is None and show.studio.blackout is False
    classic = make(live=False)
    gl.handle_key("scene:hype", classic)
    assert classic.studio.look is None and classic.looks.overrides.scene == "hype"


def test_lining_up_the_lights_sets_the_studio_aside():
    show = make()
    show.studio.command({"op": "look", "key": "simple:house"})
    show.looks.overrides.lineup = (0, "center")
    run(show, 4)
    assert show.looks.mode.startswith("line-up") and show.rig.tetras[0].dim == 0.0
    show.looks.overrides.lineup = None
    run(show, 4)
    assert show.looks.mode == "simple:house"


# --- brightness, fade time, the buttons he holds ----------------------------------------------------

def test_zone_brightness_dims_one_zone_only():
    show = make()
    st = show.studio
    st.command({"op": "look", "key": "simple:steady"})
    run(show, 4)
    wash, stick, head = show.rig.tetras[0].dim, show.rig.sticks[0].dim, show.rig.bars[0].movers[0].dim
    st.command({"op": "master", "zone": "heads", "value": 0.0})
    run(show, 1)
    assert show.rig.bars[0].movers[0].dim == 0.0
    assert (show.rig.tetras[0].dim, show.rig.sticks[0].dim) == (wash, stick)
    st.command({"op": "master", "zone": "heads", "value": 1.0})
    st.command({"op": "master", "zone": "main", "value": 0.5})
    run(show, 1)
    assert show.rig.tetras[0].dim == pytest.approx(wash * 0.5) and show.rig.bars[0].movers[0].dim == pytest.approx(head * 0.5)


def test_effects_off_means_no_derby_laser_or_strobe():
    show = make()
    st = show.studio
    st.command({"op": "look", "key": "scene:hype"})
    st.command({"op": "master", "zone": "fx", "value": 0.0})
    def check(now, i):
        for bar in show.rig.bars:
            assert bar.laser == "off" and all(d.color == "off" for d in bar.derbies) and bar.strobe_white == 0.0
    run(show, 40, step=0.1, each=check)


def test_a_change_melts_over_the_fade_time_and_snaps_at_zero():
    show = make()
    st = show.studio
    st.fade_s = 2.0
    st.command({"op": "look", "key": "simple:glow"})
    run(show, 6)
    low = show.rig.tetras[0].dim
    st.command({"op": "look", "key": "simple:house"})
    seen = []
    run(show, 3, step=0.05, t0=2000.0, each=lambda now, i: seen.append(show.rig.tetras[0].dim))
    assert seen[0] < low + 0.1, "the change jumped"
    assert low < seen[20] < 1.0, "one second in, it should be part way"
    assert seen[-1] == 1.0
    assert all(b >= a - 1e-9 for a, b in zip(seen, seen[1:])), "the fade went backwards"
    st.fade_s = 0.0
    st.command({"op": "look", "key": "simple:glow"})
    show.render(3000.0)
    assert show.rig.tetras[0].dim == pytest.approx(low)


def test_white_out_is_on_only_while_held_and_blackout_wins():
    show = make()
    st = show.studio
    st.command({"op": "look", "key": "simple:glow"})
    run(show, 4)
    low = show.rig.tetras[0].dim
    st.command({"op": "hit", "name": "whiteout", "on": True})
    run(show, 1)
    assert show.rig.tetras[0].dim == 1.0 and show.rig.tetras[0].blue == 1.0
    st.command({"op": "hit", "name": "whiteout", "on": False})
    run(show, 1)
    assert show.rig.tetras[0].dim == pytest.approx(low)
    st.command({"op": "touch", "id": "tetra1", "color": "#ff0000"})
    st.command({"op": "blackout", "on": True})
    run(show, 1)
    assert all(t.dim == 0.0 for t in show.rig.tetras), "a touched light stayed on in a blackout"
    st.command({"op": "blackout", "on": False})
    run(show, 1)
    assert show.rig.tetras[0].red == 1.0 and show.rig.tetras[0].green == 0.0


def test_the_strobe_button_never_passes_the_crowd_safe_limit():
    show = make()
    show.studio.command({"op": "look", "key": "simple:steady"})
    show.studio.command({"op": "hit", "name": "strobe", "on": True})
    from tools.gigbar_lights import settings_contract as contract
    def check(now, i):
        assert all(t.strobe <= contract.SAFE_STROBE_MAX for t in show.rig.tetras)
        assert all(b.strobe_speed <= contract.SAFE_STROBE_MAX for b in show.rig.bars)
    run(show, 6, each=check)
    assert show.looks.overrides.strobe is True
    show.studio.command({"op": "hit", "name": "strobe", "on": False})
    run(show, 1)
    assert show.looks.overrides.strobe is False


def test_freeze_holds_the_exact_look_until_released():
    show = make()
    st = show.studio
    st.command({"op": "look", "key": "scene:party"})
    run(show, 6)
    st.command({"op": "freeze", "on": True})
    frames = run(show, 20, step=0.1, t0=3000.0)
    assert len(set(frames)) == 1
    st.command({"op": "freeze", "on": False})
    assert len(set(run(show, 20, step=0.1, t0=4000.0))) > 5


# --- hands on one light ------------------------------------------------------------------------------

def test_touch_give_back_and_a_pin_that_survives_a_restart(tmp_path):
    f = tmp_path / "studio.json"
    show = make(path=f)
    st = show.studio
    st.command({"op": "look", "key": "simple:steady"})
    st.command({"op": "touch", "id": "stick2", "color": "#00ff00", "dim": 0.4})
    run(show, 4)
    s2 = show.rig.sticks[1]
    assert (s2.red, s2.green, s2.blue, s2.dim) == (0.0, 1.0, 0.0, 0.4)
    assert show.rig.sticks[0].green < 1.0
    st.command({"op": "give_back", "id": "stick2"})
    run(show, 1)
    assert show.rig.sticks[1].red > 0.5
    st.command({"op": "pin", "id": "tetra3", "off": True})
    run(show, 1)
    assert show.rig.tetras[2].dim == 0.0 and show.rig.tetras[1].dim > 0.5
    st.reset()
    assert "tetra3" in st.pins, "Stop dropped a pin"
    again = studio.Studio(path=f, live=True)
    assert again.pins == {"tetra3": {"color": "#ffffff", "dim": 1.0, "off": True}}
    assert json.loads(f.read_text())["pins"]["tetra3"]["off"] is True


def test_find_a_light_blinks_it_for_three_seconds_then_stops():
    show = make()
    st = show.studio
    st.command({"op": "look", "key": "simple:glow"})
    run(show, 4)
    st.command({"op": "find", "id": "tetra2"})
    seen = []
    run(show, 5, step=0.05, t0=1004.0, each=lambda now, i: seen.append(show.rig.tetras[1].dim))
    assert 1.0 in seen[:40] and 0.0 in seen[:40], "it never blinked"
    assert seen[-1] == pytest.approx(0.3) and st.find is None


# --- spotlights ----------------------------------------------------------------------------------------

def spot_show():
    show = make()
    st = show.studio
    st.command({"op": "look", "key": "simple:glow"})
    run(show, 4)
    st.command({"op": "spots", "on": True})
    run(show, 2, t0=1004.0)
    return show, st


def test_spots_take_the_heads_dim_the_room_and_meet_on_the_floor():
    show, st = spot_show()
    lay = show.looks.venue
    f = st.followers[0]
    assert (f.x, f.y) == pytest.approx((lay.floor.cx, lay.floor.cy))
    assert all(h.dim == 1.0 for bar in show.rig.bars for h in bar.movers)
    assert show.rig.tetras[0].dim == pytest.approx(0.3 * 0.2)   # the room dips to 20% round the spot (PM #23789)
    # every head's beam lands on the person at the spot, at chest/face height (through the layout's own model)
    for b, bar in enumerate(show.rig.bars):
        for m, h in enumerate(bar.movers):
            o = lay.heads(b + 1)[m]
            assert lay.spot_target(f.x, f.y, o) == pytest.approx((f.x, f.y, 1.5))
            want = lay.aim(b + 1, o, (f.x, f.y, 1.5), m)
            assert (h.pan, h.tilt) == pytest.approx(want, abs=0.02)


def test_an_arrow_key_eases_in_glides_and_eases_out_with_no_jerk():
    show, st = spot_show()
    f = st.followers[0]
    x0 = f.x
    xs = []
    st.command({"op": "spot_key", "dx": 1, "dy": 0})
    run(show, 1.5, step=0.025, t0=2000.0, each=lambda now, i: xs.append(f.x))
    st.command({"op": "spot_key", "dx": 0, "dy": 0})
    run(show, 1.0, step=0.025, t0=2001.5, each=lambda now, i: xs.append(f.x))
    v = [(b - a) / 0.025 for a, b in zip(xs, xs[1:])]
    top = studio.PACES["walk"]
    assert v[0] < top * 0.3, "it jumped to full speed on the first frame"
    assert max(v) == pytest.approx(top, rel=0.03)
    assert v[14] == pytest.approx(top, rel=0.05), "walking speed should be reached in about a quarter second"
    assert all(abs(b - a) <= top / studio.EASE_IN_S * 0.025 * 1.05 for a, b in zip(v, v[1:])), "a jerk: speed changed faster than the ease"
    assert v[-1] == pytest.approx(0.0, abs=1e-6) and all(s >= -1e-9 for s in v), "it overshot or rolled back"
    assert f.x > x0 + 1.0


def test_shift_is_slow_and_ctrl_is_fast():
    show, st = spot_show()
    f = st.followers[0]
    def travel(pace, t0):
        a = f.x
        st.command({"op": "spot_key", "dx": 1, "dy": 0, "pace": pace})
        run(show, 1.0, step=0.025, t0=t0)
        st.command({"op": "spot_key", "dx": 0, "dy": 0})
        run(show, 1.0, step=0.025, t0=t0 + 1.0)
        return f.x - a
    slow = travel("slow", 2000.0)
    st.command({"op": "spot_goal", "x": 1.0, "y": 3.0, "drag": True})
    run(show, 4, t0=2010.0)
    fast = travel("fast", 2020.0)
    assert 0.2 < slow < 0.5 and fast > 4 * slow


def test_the_spot_never_leaves_the_room():
    show, st = spot_show()
    f = st.followers[0]
    w, d = show.looks.venue.room[0], show.looks.venue.room[1]
    st.command({"op": "spot_key", "dx": 1, "dy": 1, "pace": "fast"})
    run(show, 30, step=0.05, t0=2000.0)
    assert (f.x, f.y) == pytest.approx((w, d))
    st.command({"op": "spot_goal", "x": -50, "y": 1e9})
    assert st.followers[0].goal is None or 0 <= st.followers[0].goal[0] <= w


def test_hover_follow_moves_only_while_it_is_on_and_freezes_when_it_is_off():
    show, st = spot_show()
    f = st.followers[0]
    here = (f.x, f.y)
    st.command({"op": "spot_goal", "x": here[0] + 1.0, "y": here[1], "hover": True})
    run(show, 2, t0=2000.0)
    assert (f.x, f.y) == pytest.approx(here), "the pointer moved the spot with hover follow off"
    st.command({"op": "spots", "hover": True})
    st.command({"op": "spot_goal", "x": here[0] + 1.0, "y": here[1], "hover": True})
    xs = []
    run(show, 0.5, step=0.025, t0=2010.0, each=lambda now, i: xs.append(f.x))
    assert xs[0] - here[0] < 0.05 and xs[-1] > here[0] + 0.2, "hover should ease in, the same as the arrows"
    st.command({"op": "spots", "hover": False})     # he reaches for another button
    stopped = f.x
    run(show, 1.0, step=0.025, t0=2011.0)
    # it eases to a stop (no jerk): at most the ease-out distance, v * EASE_OUT_S / 2
    assert f.goal is None and f.x - stopped <= studio.GOAL_SPEED * studio.EASE_OUT_S / 2 + 0.01, \
        "the spot kept chasing after hover follow went off"
    resting = f.x
    run(show, 2.0, step=0.025, t0=2013.0)
    assert f.x == resting


def test_a_long_jump_goes_dark_moves_then_appears_and_a_short_one_glides():
    show, st = spot_show()
    f = st.followers[0]
    st.command({"op": "mark_save", "name": "Cake table"})
    st.command({"op": "spot_goal", "x": f.x + 3.0, "y": f.y, "drag": True})
    run(show, 5, t0=2000.0)
    far = f.x
    st.command({"op": "mark_go", "name": "Cake table"})
    log = []
    run(show, 3, step=0.025, t0=2010.0, each=lambda now, i: log.append((f.x, show.rig.bars[0].movers[0].dim)))
    moved = next(i for i, (x, _) in enumerate(log) if abs(x - far) > 0.01)
    assert log[moved][1] == 0.0, "the beam was lit while it crossed the room"
    assert log[-1][1] == 1.0 and log[-1][0] == pytest.approx(far - 3.0)
    st.command({"op": "spot_goal", "x": f.x + 0.5, "y": f.y})     # short: no dark
    dims = []
    run(show, 2, step=0.025, t0=2020.0, each=lambda now, i: dims.append(show.rig.bars[0].movers[0].dim))
    assert min(dims) == 1.0


def test_two_spots_one_per_gigbar_and_tab_picks_which_the_arrows_move():
    show, st = spot_show()
    st.command({"op": "spots", "count": 2})
    run(show, 2, t0=2000.0)
    a, b = st.followers
    assert a.x < b.x
    st.command({"op": "spots", "sel": 1})
    bx, ax = b.x, a.x
    st.command({"op": "spot_key", "dx": 0, "dy": 1})
    run(show, 1, t0=2010.0)
    st.command({"op": "spot_key", "dx": 0, "dy": 0})
    assert b.y > a.y and a.x == ax and b.x == bx
    lay = show.looks.venue
    h = show.rig.bars[1].movers[0]
    assert (h.pan, h.tilt) == pytest.approx(lay.aim(2, lay.heads(2)[0], (b.x, b.y, 1.5), 0), abs=0.03)


def test_releasing_the_spots_gives_the_heads_back_to_the_look():
    show, st = spot_show()
    st.command({"op": "spots", "on": False})
    run(show, 3, t0=2000.0)
    assert show.rig.bars[0].movers[0].dim == 0.0          # Soft glow keeps the heads dark
    assert show.rig.tetras[0].dim == pytest.approx(0.3)


def test_a_steered_spot_follows_closer_than_the_shows_slow_moves():
    show, st = spot_show()
    ax = show.glide._heads[(0, 0)]
    assert ax[0].steps == studio.spot_gate_steps() and ax[0].slide == 0.0
    st.command({"op": "spots", "on": False})
    run(show, 1, t0=2000.0)
    from tools.gigbar_lights import glide
    assert ax[0].steps == glide.GATE_STEPS


# --- tonight -----------------------------------------------------------------------------------------

REPORT = {"title": "Avery", "built": "2026-11-12 18:00", "steps": [
    {"kind": "music", "key": "cocktail", "name": "Cocktail hour", "look": "", "songs": [{"artist": "George Strait", "title": "Check Yes or No"}]},
    {"kind": "hold", "key": "entrance", "name": "Grand entrance", "look": "entrance", "songs": []},
    {"kind": "song", "key": "first-dance", "name": "First dance", "look": "first-dance", "songs": [{"artist": "Randy Travis", "title": "Forever and Ever, Amen"}]},
    {"kind": "music", "key": "dinner", "name": "Dinner", "look": "", "songs": [{"artist": "Alan Jackson", "title": "Remember When"}]},
    {"kind": "hold", "key": "toasts", "name": "Toasts", "look": "toast", "songs": []}]}


def test_the_night_follows_mixxx_and_next_runs_ahead_until_mixxx_arrives():
    from tools.gigbar_lights import run_of_show as ros, song_match, wedding_night
    show = make()
    st = show.studio
    st.night = night = tonight.Tonight.from_report(REPORT)
    assert night.follows and [s["name"] for s in night.public()["steps"]][:2] == ["Cocktail hour", "Grand entrance"]
    night.see(st, song_match.candidates("George Strait", "Check Yes or No"), 0.0)
    assert night.public()["steps"][0]["state"] == "now" and night.public()["next"]["name"] == "Grand entrance"
    st.command({"op": "next"})                    # ahead of Mixxx: the entrance look is held
    assert st.look == {"key": "moment:entrance", "since": st.look["since"], "night": True} and night.ahead == 1
    assert night.public()["steps"][1]["state"] == "now"
    night.see(st, song_match.candidates(wedding_night.HOLD_ARTIST, ros.hold_title("Grand entrance")), 0.0)
    assert st.look is None and night.ahead is None and night.at == 1, "Mixxx arrived: the show has the look now"
    st.command({"op": "look", "key": "simple:steady"})     # a pad he pressed himself is never taken back
    night.see(st, song_match.candidates("Randy Travis", "Forever and Ever, Amen"), 0.0)
    assert st.look["key"] == "simple:steady" and night.at == 2
    st.command({"op": "undo"})


def test_with_no_night_built_the_list_is_a_plain_order_stepped_by_hand(tmp_path):
    night = tonight.Tonight.load(tmp_path)
    assert not night.follows and len(night.steps) > 6
    st = studio.Studio(live=True)
    st.night = night
    st.command({"op": "next"})
    assert night.at == 0
    for _ in range(len(night.steps) - 1):
        st.command({"op": "next"})
    with pytest.raises(studio.CommandError, match="last step"):
        st.command({"op": "next"})


# --- commands from any screen are checked ---------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    {}, {"op": "nope"}, {"op": "__init__"}, {"op": "look", "key": "simple:nope"}, {"op": "look", "key": "mine:gone"},
    {"op": "color", "color": "red"}, {"op": "master", "zone": "main", "value": float("nan")},
    {"op": "master", "zone": "roof", "value": 1}, {"op": "speed", "value": 3}, {"op": "fade", "seconds": -1},
    {"op": "spot_key", "dx": 1}, {"op": "spot_goal", "x": 1, "y": 1}, {"op": "touch", "id": "tetra99"},
    {"op": "hit", "name": "laser"}, {"op": "spots", "count": 3}, {"op": "motion", "motion": "wild"},
    {"op": "pad_save", "name": "x"}, {"op": "goto", "i": 2}, "look", None])
def test_a_bad_command_is_refused_with_words_and_changes_nothing(cmd):
    st = studio.Studio(live=True)
    before = json.dumps(st.public(), sort_keys=True, default=str)
    with pytest.raises(studio.CommandError):
        st.command(cmd)
    assert json.dumps(st.public(), sort_keys=True, default=str) == before


def test_a_saved_pad_keeps_its_color_and_motion_and_comes_back(tmp_path):
    f = tmp_path / "studio.json"
    st = studio.Studio(path=f, live=True)
    st.command({"op": "look", "key": "moment:first-dance"})
    st.command({"op": "color", "color": "#ffb8cf"})
    st.command({"op": "motion", "motion": "slow"})
    st.command({"op": "pad_save", "name": "Avery's dance"})
    again = studio.Studio(path=f, live=True)
    assert [p["name"] for p in again.catalog()["pages"][-1]["pads"]] == ["Avery's dance"]
    again.command({"op": "look", "key": "mine:Avery's dance"})
    assert again.held() == ("moment", "first-dance", pytest.approx((1.0, 184 / 255, 207 / 255)), "slow")
    again.command({"op": "pad_del", "name": "Avery's dance"})
    assert again.look is None and again.pads == []


def test_undo_puts_back_what_was_live_before_the_last_press():
    st = studio.Studio(live=True)
    st.command({"op": "look", "key": "simple:steady"})
    st.command({"op": "look", "key": "scene:hype"})
    st.command({"op": "blackout", "on": True})
    st.command({"op": "undo"})
    assert st.blackout is False and st.look["key"] == "scene:hype"
    st.command({"op": "undo"})
    assert st.look["key"] == "simple:steady"


def test_every_pad_says_what_it_does():
    cat = studio.Studio(live=True).catalog()
    pads = [p for page in cat["pages"] for p in page["pads"]]
    assert len(pads) >= 18
    for p in pads:
        assert p["name"] and len(p["line"]) > 20 and p["tags"], p
    assert math.isclose(studio.PACES["walk"], 0.9)


# --- View from (his ask, 2026-11-13) and the phone's picture of the room's light -------------------

def test_the_view_is_from_the_dj_booth_until_he_changes_it_and_is_kept_per_venue_and_screen(tmp_path):
    from tools.gigbar_lights import studio as sm
    st = sm.Studio(path=tmp_path / "studio.json", live=True)
    st.venue = "rio-grande"
    assert st.stage()["views"] == {"laptop": {"from": "booth", "turn": 0}, "phone": {"from": "booth", "turn": 0}}
    st.command({"op": "view", "screen": "phone", "from": "floor"})
    st.command({"op": "view", "screen": "laptop", "turn": 1})
    assert st.stage()["views"] == {"laptop": {"from": "booth", "turn": 1}, "phone": {"from": "floor", "turn": 0}}
    st.command({"op": "view", "screen": "laptop", "from": "floor"})   # picking a side starts from no turn
    assert st.stage()["views"]["laptop"] == {"from": "floor", "turn": 0}
    for bad in ({"op": "view", "screen": "tv", "from": "floor"}, {"op": "view", "screen": "phone", "from": "ceiling"},
                {"op": "view", "screen": "phone", "turn": 4}, {"op": "view", "screen": "phone", "turn": True}):
        with pytest.raises(sm.CommandError):
            st.command(bad)
    # another venue starts from the booth again; this one is remembered on the next launch
    st.venue = "the-barn"
    assert st.stage()["views"]["phone"] == {"from": "booth", "turn": 0}
    again = sm.Studio(path=tmp_path / "studio.json", live=True)
    again.venue = "rio-grande"
    assert again.stage()["views"] == {"laptop": {"from": "floor", "turn": 0}, "phone": {"from": "floor", "turn": 0}}


def test_a_spot_told_to_hold_stops_short_of_where_it_was_going():
    from tools.gigbar_lights import studio as sm
    st = sm.Studio(live=True)
    st.command({"op": "spots", "on": True, "dark_jump": False})
    st.command({"op": "spot_goal", "x": 7.0, "y": 4.0})
    f = st.followers[0]
    for i in range(12):
        f.step(0.025, sm.PACES["walk"], st._bounds(), i * 0.025)
    assert f.goal is not None and 4.0 < f.x < 6.9
    st.command({"op": "spot_hold"})
    for i in range(80):
        f.step(0.025, sm.PACES["walk"], st._bounds(), 1 + i * 0.025)
    assert f.goal is None and not f.moving() and f.x < 6.5, "it eased to a stop where it was"


def test_the_phones_picture_of_the_light_is_made_from_the_frame_that_was_sent():
    from tools.gigbar_lights import stage_glow, studio as sm, studio_peek
    from tools.gigbar_lights.venue import LayoutStore
    lay = LayoutStore().get("small-room-front")
    peek = studio_peek.Peek(sm.Studio(live=True), "simple:house", lay)
    u = [peek.render(100.0 + i * 0.025) for i in range(40)][-1]
    sc = stage_glow.scene(u, lay)
    assert len(sc["lamps"]) == 10 and all(lamp[3] == "ffffff" and lamp[4] == 1.0 for lamp in sc["lamps"])
    assert len(sc["bars"]) == 2 and len(sc["beams"]) == 4
    for x0, y0, x1, y1, col, k in sc["beams"]:   # each beam starts at a head and lands inside the room
        assert 0 <= x1 <= lay.room[0] and 0 <= y1 <= lay.room[1] and k > 0.9 and col == "ffffff"
    assert {(p[0], p[1]) for p in sc["pools"]} >= {(lamp[0], lamp[1]) for lamp in sc["lamps"]}
    # tonight's lights only, and a dark frame draws lamps with no light
    assert len(stage_glow.scene(u, lay, {"bars": 1, "tetras": 3, "sticks": 0})["lamps"]) == 3
    dark = stage_glow.scene(bytes(512), lay)
    assert dark["pools"] == [] and dark["beams"] == [] and len(dark["lamps"]) == 10
    assert stage_glow.scene(u, None) is None and stage_glow.scene(b"", lay) is None


# --- from the independent review, 2026-11-13 ------------------------------------------------------------

def test_a_studio_that_is_off_changes_no_frame_whatever_a_test_build_left_in_the_file(tmp_path):
    """A test build saved a 3 s crossfade and a pinned light. On a stable copy, or with the kill
    switch, the studio is off: it must stay idle (so no frame changes), and must not throw the
    saved things away either."""
    import time as _t
    from tools.gigbar_lights import studio as sm
    f = tmp_path / "studio.json"
    live = sm.Studio(path=f, live=True)
    live.command({"op": "pin", "id": "tetra2", "color": "#ff0000"})
    live.command({"op": "fade", "seconds": 3})
    assert not live.idle()
    off = sm.Studio(path=f, live=False)
    assert off.idle() and off.pins == {} and off.fade_s == 0.0
    off.venue = "the-barn"
    off.command({"op": "view", "screen": "laptop", "from": "floor"})   # a save from the off studio...
    again = sm.Studio(path=f, live=True)                                # ...loses nothing the Live screen saved
    assert again.pins["tetra2"]["color"] == "#ff0000" and again.fade_s == 3.0
    assert again.views["the-barn"]["laptop"]["from"] == "floor"
    # a pin is for tonight: the next night's launch lets it go
    doc = json.loads(f.read_text())
    doc["pinned"]["tetra2"] = _t.time() - sm.PIN_S - 60
    f.write_text(json.dumps(doc))
    assert sm.Studio(path=f, live=True).pins == {}


def test_what_is_read_back_from_the_file_is_checked_like_a_command(tmp_path):
    import time as _t
    from tools.gigbar_lights import studio as sm
    f = tmp_path / "studio.json"
    f.write_text(json.dumps({
        "pads": [{"name": "Mine", "look": "simple:steady", "color": '"><img src=x onerror=alert(1)>', "motion": "sideways"},
                 {"name": "bad:name", "look": "simple:steady"}, {"name": "Gone", "look": "simple:nope"}],
        "marks": {"barn": {"Cake": [1.5, 2.5], "Nan": [float("nan"), 1], "Far": [1e12, 1], "Bool": [True, 1], "Short": [1]}},
        "pins": {"tetra1": {"color": "#00ff00", "dim": 0.5}, "tetra2": {"dim": "bright"}, "tetra3": "x", "nope9": {"dim": 1},
                 "stick1": {"color": "<b>", "dim": 2}},
        "pinned": {"tetra1": _t.time(), "tetra2": _t.time(), "tetra3": _t.time(), "stick1": _t.time()},
        "views": {"barn": {"laptop": {"from": "floor", "turn": True}, "phone": {"from": "floor", "turn": 1}, "tv": {"from": "floor", "turn": 0}}},
        "fade_s": 99}).replace("NaN", "NaN"))
    st = sm.Studio(path=f, live=True)
    assert st.pads == [{"name": "Mine", "look": "simple:steady", "color": "", "motion": ""}]
    assert st.marks == {"barn": {"Cake": [1.5, 2.5]}}
    assert st.pins == {"tetra1": {"color": "#00ff00", "dim": 0.5}}
    assert st.views == {"barn": {"phone": {"from": "floor", "turn": 1}}}
    assert st.fade_s == 3.0, "an out-of-range fade falls back to the default"


@pytest.mark.parametrize("cmd", [
    {"op": "master", "zone": [], "value": 1}, {"op": "master", "zone": "main", "value": 10 ** 400},
    {"op": "spots", "on": True, "pace": []}, {"op": "spots", "count": True}, {"op": "spots", "count": 1.0},
    {"op": "spots", "sel": True}, {"op": "spots", "color": 2.0}, {"op": "spot_goal", "x": 10 ** 400, "y": 1},
    {"op": "spot_key", "dx": 10 ** 400, "dy": 0}, {"op": "spot_goal", "x": [], "y": {}},
    {"op": "look", "key": []}, {"op": "color", "color": 5}, {"op": "motion", "motion": ["still"]}, {"op": "hit", "name": []},
    {"op": "speed", "value": []}, {"op": "goto", "i": 10 ** 400}, {"op": "touch", "id": [], "dim": 1},
    {"op": "pad_save", "name": {"a": 1}}, {"op": "mark_go", "name": []}, {"op": "view", "screen": [], "from": "floor"},
])
def test_odd_json_types_are_refused_with_words_never_a_crash(cmd):
    from tools.gigbar_lights import studio as sm
    st = sm.Studio(live=True)
    st.command({"op": "spots", "on": True})
    before = json.dumps(st.public(), sort_keys=True, default=str)
    with pytest.raises(sm.CommandError):
        st.command(cmd)
    after = st.public()
    after["rev"] = json.loads(before)["rev"]
    assert json.dumps(after, sort_keys=True, default=str) == before, "a refused command changes nothing"


def test_a_spots_command_with_one_bad_field_changes_none_of_them():
    from tools.gigbar_lights import studio as sm
    st = sm.Studio(live=True)
    st.command({"op": "spots", "on": True})
    with pytest.raises(sm.CommandError):
        st.command({"op": "spots", "count": 2, "gobo": 9})
    assert st.spots["count"] == 1 and len(st.followers) == 1


def test_find_it_blinks_from_the_first_frame_even_when_nothing_was_running():
    from tools.gigbar_lights import studio as sm
    show = Show(analyze=False)
    st = show.studio = sm.Studio(live=True)
    st.fade_s = 0.0
    st.command({"op": "find", "id": "tetra1"})          # pressed with nothing running: the clock is stale
    feed = gl.FakeMixxx(show, 128.0, loop=True)
    seen = set()
    for i in range(int(sm.FIND_S / 0.025) + 20):
        now = 5000.0 + i * 0.025
        feed(now)
        show.control_tick(now)
        u = show.render(now)
        if i < int(sm.FIND_S / 0.025) - 2:
            seen.add(u[84] in (0, 255) and (u[80], u[81], u[82]) == (255, 255, 255))
            assert st.find is not None
    assert seen == {True} and st.find is None, "it blinked white for its 3 seconds, then let go"


def test_blackout_is_at_once_and_coming_back_fades_in():
    from tools.gigbar_lights import studio as sm
    show = Show(analyze=False)
    st = show.studio = sm.Studio(live=True)
    st.command({"op": "fade", "seconds": 3})
    st.command({"op": "look", "key": "simple:house"})
    feed = gl.FakeMixxx(show, 128.0, loop=True)

    def frames(t0, n):
        out = None
        for i in range(n):
            now = t0 + i * 0.025
            feed(now); show.control_tick(now); out = show.render(now)
        return out
    assert frames(7000.0, 200)[84] == 255            # the look has faded all the way in
    st.command({"op": "blackout", "on": True})
    assert frames(7005.0, 3)[84] == 0, "dark on the next frames, never a 3 second melt"
    st.command({"op": "blackout", "on": False})
    assert 0 < frames(7005.2, 20)[84] < 255, "and it comes back with the fade"
