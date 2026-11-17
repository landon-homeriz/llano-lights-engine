"""Photo mode holds steady until he picks something else (1.19.1, Llano BL #12093).

His report on 1.17.1, 2026-11-12: picked Photo mode on the laptop's Moments tab; the lights pulsed
up and down, then it "timed out" and went into a fast party scene. Two causes, both covered here:

- a still moment played through the pretend song's sections: the intro breathed on a sine, each
  build ramped and went dark a beat before its drop, and the drop played at the look's drop level;
- the no-music pretend song was one 288-beat pass (2:15 at 128 BPM); at its end the engine fell to
  the autoloops (chase, sweep, rainbow, color pulse) while the window still said Photo mode.
"""
import inspect
import time

from tools.gigbar_lights import __main__ as gl
from tools.gigbar_lights import looks, moments, show_settings, settings_contract as contract
from tools.gigbar_lights.show import Show


def _run(key: str, seconds: float, loop: bool = True, step: float = 0.1):
    """(modes seen, distinct DMX frames) for moment `key` held over `seconds` of pretend song."""
    show = Show(analyze=False)
    feed = gl.FakeMixxx(show, 128.0, loop=loop)
    show_settings.set_play(moments.style(key), time.time() + 6 * 3600, label=key)
    try:
        modes, frames = set(), set()
        t0 = 1000.0
        for i in range(int(seconds / step)):
            now = t0 + i * step
            feed(now)
            show.control_tick(now)
            frame = show.render(now)
            if i * step > 3:   # past the heads' first glide to their spot
                frames.add(frame)
            modes.add(show.looks.mode)
        return modes, frames
    finally:
        show_settings.clear_play()


def test_photo_mode_is_one_steady_frame_past_the_pretend_songs_end():
    modes, frames = _run("photo", 300)   # more than two passes of the 2:15 pretend song
    assert modes == {"still"}
    assert len(frames) == 1, f"photo mode changed {len(frames)} times"


def test_a_steady_cue_never_falls_into_the_autoloops_even_on_a_song_that_ends():
    # a real song that ends (no loop) leaves the still look held, not dancing
    modes, frames = _run("photo", 160, loop=False)
    assert not any(m.startswith("autoloop") for m in modes)
    assert len(frames) == 1


def test_a_moving_moment_with_no_music_keeps_playing_its_own_look():
    modes, _ = _run("party", 300, step=0.25)
    assert not any(m.startswith("autoloop") for m in modes), modes
    assert any(m.startswith("scripted:") for m in modes)


def test_which_looks_hold_still():
    still = {m["key"] for m in moments.MOMENTS if looks.LooksEngine.is_still(moments.style(m["key"]))}
    assert {"photo", "toast"} <= still
    assert not still & {"party", "reveal", "dinner", "first-dance", "spotlight", "last-dance", "entrance"}
    assert not looks.LooksEngine.is_still(contract.style_of(contract.defaults()))


def test_photo_mode_is_lit_warm_and_the_heads_hold_dark():
    show = Show(analyze=False)
    show_settings.set_play(moments.style("photo"), time.time() + 3600, label="Photo mode")
    try:
        rig = show.looks.render(looks.Frame(10.0, 128.0, True, level=0.9), show.rig)
    finally:
        show_settings.clear_play()
    assert all(t.dim > 0.5 for t in rig.tetras) and all(s.dim > 0.5 for s in rig.sticks)
    assert all(m.dim == 0 for bar in rig.bars for m in bar.movers)   # movers 0: no beams on the guests
    assert all(bar.strobe_white == 0 and bar.laser == "off" for bar in rig.bars)


def test_scenes_mode_runs_the_looping_pretend_song():
    from tools.gigbar_lights.windows.src import gigbar_app  # noqa: PLC0415
    assert "loop=True" in inspect.getsource(gigbar_app.mode_scenes)


def test_photo_mode_holds_in_a_live_show_whatever_the_song_does():
    """Over real music the same: a song with no section script (unanalyzed, Spotify), the
    autoloop key, a hard stop in the music, a build's last beat and a drop all leave it as is."""
    from tools.gigbar_lights.rig import default_rig  # noqa: PLC0415
    from tools.gigbar_lights.show_script import Section  # noqa: PLC0415
    build, drop = Section("build", 0, 32, 0.5), Section("drop", 32, 64, 0.9)
    frames = [
        looks.Frame(10.0, 128.0, True, level=0.7),                                       # no script
        looks.Frame(31.5, 128.0, True, level=0.7, section=build, next_section=drop),     # dark beat
        looks.Frame(40.0, 128.0, True, level=0.9, section=drop),                         # drop level
        looks.Frame(40.0, 128.0, True, level=0.0, section=drop),                         # silence
        looks.Frame(40.0, 128.0, False),                                                 # stopped
    ]
    show_settings.set_play(moments.style("photo"), time.time() + 3600, label="Photo mode")
    try:
        out = set()
        for override in (False, True):
            eng = looks.LooksEngine()
            eng.overrides.autoloop_override = override
            for f in frames:
                rig = eng.render(f, default_rig())
                assert eng.mode == "still"
                out.add(bytes(rig.render()))
    finally:
        show_settings.clear_play()
    assert len(out) == 1
