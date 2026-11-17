"""Wedding moments hold their own look in a live show (1.19.2, Llano BL #12095).

Follow-up to BL #12093 (Photo mode and Toast hold one steady frame). Still open after it:

- a moving or breathing cue that is one look in every section (Cake cutting, Spotlight, Two
  spotlights) played through the live song: dark a beat before each drop, the drop's level, a
  blackout in a hard stop, and the autoloops (chase, rainbow) on a song with no section script
  (unanalyzed, Spotify, the system deck) or with the autoloop key on;
- Grand entrance (a cue with its own build and drop) fell to the autoloops on a song with no script;
- a moment sent from the phone (try it, Play on laptop) is Llano's draft: the laptop stopped it after
  ten minutes and went back to the saved show. It now holds like a moment picked in the window.
"""
import time

import pytest

from tools.gigbar_lights import looks, moments, show_settings
from tools.gigbar_lights.rig import default_rig
from tools.gigbar_lights.show_script import Section
try:   # the Llano link; the open-source engine ships without it
    from tools.gigbar_lights import llano_sync
except ImportError:   # ok: those tests skip
    llano_sync = None
needs_sync = pytest.mark.skipif(llano_sync is None, reason="the Llano link is not in this edition")

BUILD, DROP, INTRO = Section("build", 0, 32, 0.5), Section("drop", 32, 64, 0.9), Section("intro", 0, 32, 0.2)
ONE_LOOK = ("cake", "spotlight", "two-spotlights")


def _frames(beat: float, **kw):
    """The song moments that knocked a cue off its look, at the same beat."""
    return {
        "no script": looks.Frame(beat, 128.0, True, level=0.7, **kw),
        "dark beat": looks.Frame(beat, 128.0, True, level=0.7, section=BUILD, next_section=DROP, **kw),
        "drop": looks.Frame(beat, 128.0, True, level=0.9, section=DROP, **kw),
        "silence": looks.Frame(beat, 128.0, True, level=0.0, section=DROP, **kw),
        "intro": looks.Frame(beat, 128.0, True, level=0.3, section=INTRO, **kw),
    }


def _render(key: str, f: looks.Frame, autoloop_key: bool = False):
    eng = looks.LooksEngine()
    eng.overrides.autoloop_override = autoloop_key
    rig = eng.render(f, default_rig())
    return eng.mode, bytes(rig.render())


def _playing(key: str):
    show_settings.set_play(moments.style(key), time.time() + 3600, label=key)


def test_which_cues_are_one_look():
    one = {m["key"] for m in moments.MOMENTS if looks.LooksEngine.is_one_look(moments.style(m["key"]))}
    assert set(ONE_LOOK) <= one
    assert not one & {"party", "reveal", "last-dance", "entrance"}


def test_a_one_look_cue_plays_the_same_whatever_the_song_does():
    """At one beat, every song moment gives the same frame: the cue's own look, never the
    section's, the dark beat, the drop's level, a blackout or an autoloop. Autoloop key too."""
    try:
        for key in ONE_LOOK:
            _playing(key)
            for beat in (31.5, 40.0, 77.25):
                out = {}
                for name, f in _frames(beat).items():
                    for autoloop_key in (False, True):
                        mode, frame = _render(key, f, autoloop_key)
                        assert mode == "held:main", (key, name, autoloop_key, mode)
                        out[(name, autoloop_key)] = frame
                assert len(set(out.values())) == 1, (key, beat, sorted(out))
    finally:
        show_settings.clear_play()


def test_a_one_look_cue_keeps_moving_and_stays_lit():
    """Holding its look is not freezing it: the spotlight roams on the beat, lit, never dark."""
    try:
        for key in ("spotlight", "two-spotlights"):
            _playing(key)
            aims, lit = set(), True
            for i in range(64):
                f = looks.Frame(i * 0.5, 128.0, True, level=0.0 if i % 8 == 0 else 0.8,
                                section=DROP if i % 2 else BUILD, next_section=DROP)
                eng = looks.LooksEngine()
                rig = eng.render(f, default_rig())
                aims.add(tuple(round(m.pan, 3) for bar in rig.bars for m in bar.movers))
                lit &= all(m.dim > 0.3 for bar in rig.bars for m in bar.movers)
            assert len(aims) > 8, key
            assert lit, key
    finally:
        show_settings.clear_play()


def test_cake_cutting_never_goes_dark():
    try:
        _playing("cake")
        for f in _frames(31.5).values():
            eng = looks.LooksEngine()
            rig = eng.render(f, default_rig())
            assert all(t.dim > 0.2 for t in rig.tetras), eng.mode
            assert all(bar.strobe_white == 0 and bar.laser == "off" for bar in rig.bars)
    finally:
        show_settings.clear_play()


def test_grand_entrance_plays_its_walk_in_on_a_song_with_no_script():
    """No section script (Spotify, an unanalyzed song) or the autoloop key: the entrance's own
    walk-in look, not the autoloops. With a script it still opens up on the drop, as written."""
    try:
        _playing("entrance")
        for f, key in ((looks.Frame(40.0, 128.0, True, level=0.8), False),
                       (looks.Frame(40.0, 128.0, True, level=0.8, section=DROP), True)):
            mode, _ = _render("entrance", f, key)
            assert mode == "held:verse"
        mode, _ = _render("entrance", looks.Frame(40.0, 128.0, True, level=0.8, section=DROP))
        assert mode == "scripted:drop"
    finally:
        show_settings.clear_play()


def test_the_house_show_still_autoloops_a_song_with_no_script():
    show_settings.clear_play()
    mode, _ = _render("", looks.Frame(40.0, 128.0, True, level=0.8))
    assert mode.startswith("autoloop:")


# --- a moment sent from the phone holds like one picked on the laptop -----------------------------

def _iso(t):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


def _link(tmp_path):
    return llano_sync.LlanoLink(show_settings.SettingsFile(tmp_path / "settings.json"), version="9.9.9",
                                url="http://127.0.0.1:9/", on_doc=lambda new, old: None,
                                status=lambda watch: {}, universe=lambda: bytes(192))


@needs_sync
def test_a_phone_moment_holds_for_the_night_not_ten_minutes(tmp_path):
    link = _link(tmp_path)
    link.token = "t"
    show_settings.clear_play()
    try:
        cake = moments.style("cake")
        link._play({"token": "1|a", "style": cake, "until": _iso(time.time() + 6 * 3600),
                    "moment": "Cake cutting"})
        assert show_settings.play_until() - time.time() > llano_sync.PLAY_MAX * 10
        assert show_settings.play_until() - time.time() <= llano_sync.PLAY_MOMENT + 1
        assert show_settings.play_label() == "Cake cutting"     # Back to the show and Stop end it
        pub = link.public()
        assert "Cake cutting" in pub["line"] and pub["draft"]["playing"] is True
        # Stop on the page ends it, as it ends any draft Llano sent
        link._play({"token": "", "style": None, "until": None})
        assert show_settings.playing() is None and link.play_moment == ""
        # a plain draft is still a ten-minute try
        link._play({"token": "2|b", "style": cake, "until": _iso(time.time() + 6 * 3600)})
        assert show_settings.play_until() - time.time() <= llano_sync.PLAY_MAX + 1
        assert show_settings.play_label() == ""
    finally:
        show_settings.clear_play()


@needs_sync
def test_a_moment_picked_in_the_window_after_a_phone_moment_is_his(tmp_path):
    link = _link(tmp_path)
    link.token = "t"
    show_settings.clear_play()
    try:
        link._play({"token": "1|a", "style": moments.style("cake"), "until": _iso(time.time() + 3600),
                    "moment": "Cake cutting"})
        show_settings.set_play(moments.style("photo"), time.time() + 6 * 3600, label="Photo mode")
        link._play({"token": "", "style": None, "until": None})   # Llano's Stop of its own moment
        assert show_settings.play_label() == "Photo mode"
    finally:
        show_settings.clear_play()


def test_the_autoloop_key_still_autoloops_a_saved_shows_one_look_song():
    """Only a moment he picked holds over the autoloop key; a saved show's look keeps the key's meaning."""
    show_settings.clear_play()
    show_settings.set_show_looks({"perfect": "slow-dance"})
    try:
        eng = looks.LooksEngine()
        f = looks.Frame(40.0, 70.0, True, level=0.6, section=DROP, song="perfect", song_keys=("perfect",))
        eng.render(f, default_rig())
        if looks.LooksEngine.is_one_look(eng._cfg):
            assert eng.mode == "held:main"
        eng.overrides.autoloop_override = True
        eng.render(f, default_rig())
        assert eng.mode.startswith("autoloop:")
    finally:
        show_settings.set_show_looks(None)
