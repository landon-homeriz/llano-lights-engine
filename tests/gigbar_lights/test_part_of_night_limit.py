"""The part-of-the-night limit (1.20.0, Llano PM #23195).

His rule, 2026-11-13: cocktail hour and dinner are a soft warm wash ONLY. No moving heads aimed at
people, no spotlights, no strobe, no laser. Dancing is the full show; a moment plays that moment's
look. These are hard limits no design button can override: so the tests give a cocktail-hour song
the wildest look there is, play it through every kind of moment the engine has (a drop, a build, a
DJ loop, no sections at all), and look at what leaves the frame.
"""
from __future__ import annotations

import pytest

from tools.gigbar_lights import settings_contract as contract
from tools.gigbar_lights import moments, show_settings, shows, tonight
from tools.gigbar_lights.looks import SOFT_WASH, Frame, LooksEngine, soft_settings, soften
from tools.gigbar_lights.rig import default_rig
from tools.gigbar_lights.show_script import Section
from tools.gigbar_lights.song_match import candidates


@pytest.fixture(autouse=True)
def fresh():
    show_settings.set_current(contract.defaults())
    show_settings.set_show_looks(None)
    show_settings.set_soft_songs("night", None)
    show_settings.set_soft_now(False)
    yield
    show_settings.set_current(contract.defaults())
    show_settings.set_show_looks(None)
    show_settings.set_soft_songs("night", None)
    show_settings.set_soft_now(False)


def loud(rig) -> list[str]:
    """Everything in this frame that is not a steady soft wash."""
    bad = []
    for b, bar in enumerate(rig.bars):
        bad += [f"bar {b} moving head lit" for m in bar.movers if m.dim > 0 or m.strobe > 0]
        bad += [f"bar {b} derby on" for d in bar.derbies if d.color != "off" or d.strobe > 0]
        if bar.laser != "off" or bar.laser_strobe > 0:
            bad.append(f"bar {b} laser on")
        if bar.strobe_white > 0 or bar.strobe_uv > 0 or bar.strobe_program:
            bad.append(f"bar {b} strobe on")
        bad += [f"bar {b} par strobing or too bright" for p in bar.pars if p.strobe > 0 or p.dim > SOFT_WASH + 1e-9]
    bad += [f"wash strobing or too bright ({type(fx).__name__})" for fx in (*rig.tetras, *rig.sticks)
            if fx.strobe > 0 or fx.dim > SOFT_WASH + 1e-9]
    return bad


def play(eng, song: shows.ShowSong, kinds=("intro", "verse", "build", "drop", "main", "breakdown", "outro", None)):
    """The song through every kind of section (None = a file Mixxx never analyzed), with a DJ loop
    held and the meters high: every way the engine has of getting loud. Yields each frame's rig."""
    keys = candidates(song.artist, song.title)
    for n, kind in enumerate(kinds):
        for i in range(0, 64, 3):
            beat = n * 64 + i / 2
            sec = Section(kind, n * 64, n * 64 + 32, 1.0) if kind else None
            f = Frame(beat, 128.0, True, level=0.95, loop_beats=0.5 if i % 2 else 0.0, section=sec,
                      track_key=7, song=keys[0], song_keys=keys)
            yield kind, eng.render(f, default_rig())


SIP = shows.ShowSong("The Band", "Sip", look="peak", part="cocktail", bpm=128)
EAT = shows.ShowSong("The Band", "Eat", look="peak", part="dinner", bpm=128)
JUMP = shows.ShowSong("The Band", "Jump", look="peak", part="dancing", bpm=128)
FIRST = shows.ShowSong("The Band", "Ours", look="slow-dance", part="dinner", moment="first-dance", bpm=80)


def follow(songs):
    show_settings.set_show_looks(shows.looks_for(songs), None, shows.soft_keys(songs), gentle=shows.gentle_keys(songs))


@pytest.mark.parametrize("song", [SIP, EAT], ids=["cocktail hour", "dinner"])
def test_a_cocktail_or_dinner_song_given_the_wildest_look_still_leaves_only_a_soft_wash(song):
    follow([SIP, EAT, JUMP, FIRST])
    eng = LooksEngine(settings=contract.normalize({**contract.defaults(), "crowd_safe": False}))
    lit = 0.0
    for kind, rig in play(eng, song):
        assert eng.limit == "soft" and loud(rig) == [], (kind, loud(rig))
        lit = max(lit, max(fx.dim for fx in (*rig.tetras, *rig.sticks)))
    assert 0.05 < lit <= SOFT_WASH, "the room is lit, softly: the limit is a wash, not a blackout"
    assert eng.showing == "show:peak"   # the look he (or a design) picked still names its colors


def test_dancing_keeps_the_full_show_and_a_dance_moment_keeps_its_own_look():
    follow([SIP, EAT, JUMP, FIRST])
    eng = LooksEngine(settings=contract.normalize({**contract.defaults(), "crowd_safe": False}))
    seen = set()
    for _kind, rig in play(eng, JUMP):
        assert eng.limit == ""
        seen.update(x.split(" ", 2)[2] if x.startswith("bar") else x for x in loud(rig))
    assert "moving head lit" in seen and any("strobe" in x for x in seen), seen   # the full show, as before
    heads = wash = 0.0
    for _kind, rig in play(eng, FIRST):   # the first dance sits in dinner's folder: it is the moment's, not dinner's
        # never the soft wash; since BL #12339 (his rule 2026-11-14) its moving heads move by
        # themselves, gently (test_heads_only_dancing)
        assert eng.limit == "gentle"
        heads = max(heads, max(m.dim for bar in rig.bars for m in bar.movers))
        wash = max(wash, max(fx.dim for fx in (*rig.tetras, *rig.sticks)))
    assert 0 < heads <= 0.6 and wash > 0.3, "the couple's dance keeps its own look, the heads gentle"


def test_no_design_can_lift_the_limit_and_his_own_hand_can():
    follow([SIP])
    keys = candidates(SIP.artist, SIP.title)
    base = contract.normalize({**contract.defaults(), "crowd_safe": False})
    eng = LooksEngine(settings=base)
    # every built-in look, a saved style of his, a look Llano designed for the night, and no look at all
    wild = contract.normalize_style({**contract.style_of(base), "sections": {
        s: {"wash": 1, "movers": 1, "pulse": 1, "strobe": 1, "derby": True, "laser": True} for s in contract.SECTIONS}})
    for look, own in [(n, None) for n in contract.BUILTIN_LOOKS] + [("llano-wild", {"llano-wild": wild}), ("", None)]:
        show_settings.set_show_looks({keys[0]: look}, own, shows.soft_keys([SIP]))
        cfg, _what = eng.show_for(base, keys[0], keys)
        assert eng.limit == "soft", look
        assert all(sec["movers"] == 0 and sec["strobe"] == 0 and not sec["laser"] and not sec["derby"]
                   and sec["move"]["shape"] == "hold" for sec in cfg["sections"].values()), look
        assert cfg["strobe"]["intensity"] == 0 and not cfg["strobe"]["loop_auto"] and not cfg["drop"]["burst"], look
        f = Frame(4.0, 128.0, True, level=0.95, loop_beats=0.5, section=Section("drop", 0, 32, 1.0),
                  track_key=7, song=keys[0], song_keys=keys)
        assert loud(eng.render(f, default_rig())) == [], look
    # a song filed under a style in the saved settings (how the night files its looks) is held too
    show_settings.set_show_looks(None)
    show_settings.set_soft_songs("night", keys)
    filed = contract.normalize({**base, "styles": {"wild": wild}, "songs": {keys[0]: "wild"}})
    eng2 = LooksEngine(settings=filed)
    f = Frame(4.0, 128.0, True, level=0.95, section=Section("drop", 0, 32, 1.0), track_key=7, song=keys[0], song_keys=keys)
    assert loud(eng2.render(f, default_rig())) == [] and eng2.showing == "style:wild" and eng2.limit == "soft"
    # a look he holds by hand is his own press: the limit stands aside for it
    eng2.overrides.simple = {"name": "house", "rgb": None}
    assert "moving head lit" in " ".join(loud(eng2.render(f, default_rig())))
    eng2.overrides.simple = None
    assert loud(eng2.render(f, default_rig())) == []


def test_the_night_built_on_this_laptop_names_the_soft_songs_with_no_box_ticked():
    report = {"title": "C & M", "steps": [
        {"kind": "music", "key": "cocktail", "name": "Cocktail hour", "songs": [{"artist": "The Band", "title": "Sip"}]},
        {"kind": "hold", "key": "entrance", "name": "Grand entrance", "look": "grand-entrance"},
        {"kind": "music", "key": "dinner", "name": "Dinner", "songs": [{"artist": "The Band", "title": "Eat"},
                                                                       {"artist": "The Band", "title": "Ours"}]},
        {"kind": "song", "key": "first-dance", "name": "First dance: Ours", "look": "first-dance",
         "songs": [{"artist": "The Band", "title": "Ours"}]},
        {"kind": "music", "key": "dancing", "name": "Dancing", "songs": [{"artist": "The Band", "title": "Jump"}]}]}
    night = tonight.Tonight.from_report(report)
    soft = night.soft_keys()
    assert set(candidates("The Band", "Sip")) <= soft and set(candidates("The Band", "Eat")) <= soft
    assert not soft & set(candidates("The Band", "Jump"))
    assert not soft & set(candidates("The Band", "Ours")), "a moment's song is the moment's, wherever its file sits"
    assert tonight.Tonight.plain().soft_keys() == set()
    show_settings.set_soft_songs("night", soft)
    eng = LooksEngine(settings=contract.defaults())
    for song, want in ((SIP, "soft"), (EAT, "soft"), (JUMP, ""), (FIRST, "")):
        keys = candidates(song.artist, song.title)
        eng.show_for(contract.defaults(), keys[0], keys)
        assert eng.limit == want, song.title
    # a song nobody listed (he plays a request at dinner) is not known to be dinner's: nothing is claimed for it
    eng.show_for(contract.defaults(), "someone-else-request", ("someone-else-request",))
    assert eng.limit == ""


def test_the_design_gives_cocktail_and_dinner_the_warm_wash_and_never_picks_photo_mode():
    songs = [shows.ShowSong("A", f"S{i}", part=p, bpm=b) for i, (p, b) in enumerate(
        [("cocktail", 100), ("cocktail", 128), ("dinner", 90), ("dinner", 124), ("dancing", 124), ("dancing", 128),
         ("dancing", 85), ("dancing", 126)])]
    songs.append(shows.ShowSong("A", "Ours", part="dinner", moment="first-dance", bpm=80))
    shows.design(songs)
    assert [s.look for s in songs[:4]] == ["warm-up"] * 4
    assert all("soft warm wash" in s.why for s in songs[:4])
    assert songs[-1].look == "slow-dance" and "first dance" in songs[-1].why
    assert all("photo" not in s.look for s in songs), "Photo mode is only ever his own press"
    assert [shows.is_soft(s.part, s.moment) for s in songs] == [True] * 4 + [False] * 5


def test_the_limit_pieces_on_their_own():
    base = contract.defaults()
    soft = soft_settings(base)
    assert soft is not base and base["strobe"]["intensity"] > 0, "the saved settings themselves are never changed"
    assert all(s["wash"] <= SOFT_WASH and s["pulse"] <= 0.25 for s in soft["sections"].values())
    assert soft["palettes"] == base["palettes"] and soft["master"] == base["master"]   # his colors and brightness stand
    rig = default_rig()
    for bar in rig.bars:
        bar.laser, bar.strobe_white, bar.strobe_program = "red", 1.0, 3
        for m in bar.movers:
            m.dim = 1.0
        for d in bar.derbies:
            d.color = "auto"
        for p in bar.pars:
            p.dim, p.strobe = 1.0, 0.5
    for fx in (*rig.tetras, *rig.sticks):
        fx.dim, fx.strobe, fx.red = 1.0, 0.8, 1.0
    soften(rig)
    assert loud(rig) == [] and rig.tetras[0].dim == SOFT_WASH and rig.tetras[0].red == 1.0
    # an isolated engine (a pad's preview) never reads the show's limit
    show_settings.set_soft_songs("night", ("a-b",))
    peek = LooksEngine(settings=base, isolated=True)
    peek.show_for(base, "a-b", ("a-b",))
    assert peek.limit == ""


def test_while_the_night_stands_on_cocktail_hour_or_dinner_a_request_nobody_listed_is_held_soft():
    """A song nobody put in the show (a request he plays at dinner) is soft too, while the night list
    says Cocktail hour or Dinner: Mixxx got there, or he pressed Next to it. A moment's song, a hold
    and the dancing keep their own look; the dancing lifts it; a Live show that ended leaves nothing held."""
    import time as _time
    report = {"title": "C & M", "steps": [
        {"kind": "music", "key": "cocktail", "name": "Cocktail hour", "songs": [{"artist": "The Band", "title": "Sip"}]},
        {"kind": "hold", "key": "entrance", "name": "Grand entrance", "look": "grand-entrance"},
        {"kind": "music", "key": "dinner", "name": "Dinner", "songs": [{"artist": "The Band", "title": "Eat"},
                                                                       {"artist": "The Band", "title": "Ours"}]},
        {"kind": "song", "key": "first-dance", "name": "First dance: Ours", "look": "first-dance",
         "songs": [{"artist": "The Band", "title": "Ours"}]},
        {"kind": "music", "key": "dancing", "name": "Dancing", "songs": [{"artist": "The Band", "title": "Jump"}]}]}
    night = tonight.Tonight.from_report(report)
    eng = LooksEngine(settings=contract.normalize({**contract.defaults(), "crowd_safe": False}))
    request = shows.ShowSong("Somebody", "A Request", look="peak", bpm=128)
    req = candidates(request.artist, request.title)

    class Studio:   # the bits of the studio Tonight touches
        look = None
        blackout = frozen = False
        _frozen = None
        def _remember(self):
            pass
    studio = Studio()

    def tick():   # what Show._tell_night says each control tick
        show_settings.set_soft_now(night.soft_now(), night.spared_keys())

    def limit(keys):
        eng.show_for(contract.defaults(), keys[0], keys)
        return eng.limit

    tick()
    assert limit(req) == "", "nothing is seen yet: no part of the night is claimed"
    night.see(studio, candidates("The Band", "Sip"), 0.0)          # Mixxx is on cocktail hour
    tick()
    assert night.soft_now() and limit(req) == "soft"
    for _kind, rig in play(eng, request):                          # the wildest look, every way of getting loud
        assert eng.limit == "soft" and loud(rig) == [], loud(rig)
    assert limit(list(candidates("The Band", "Jump"))) == "", "a dancing song he plays early keeps its own look"
    night.see(studio, candidates("The Band", "Ours"), 0.0)          # the first dance's song, filed in dinner's folder
    tick()
    assert limit(list(candidates("The Band", "Ours"))) == "", "the couple's dance is never held soft"
    night.see(studio, candidates("The Band", "Jump"), 0.0)          # the dancing
    tick()
    assert not night.soft_now() and limit(req) == ""
    night.goto(studio, 2, 0.0)                                      # he pressed Next back to dinner by hand
    tick()
    assert limit(req) == "soft"
    # the Live show stopped saying it: the word lapses, so nothing stays held after the show ends
    show_settings.set_soft_now(True, night.spared_keys(), now=_time.monotonic() - show_settings.SOFT_NOW_TTL_S - 1)
    assert limit(req) == ""
    assert not tonight.Tonight.plain().soft_now(), "with no night built nothing is held"
    show_settings.set_soft_now(False)


def test_photo_mode_lights_no_moving_heads_and_never_turns_the_spotlights_on():
    """His rule, 2026-11-13: Photo mode is steady flattering light, only when he presses it, and it
    never turns spotlights on: he picks them himself. Pressed from the studio (the laptop, the phone,
    llano.app) over a playing song, the heads stay dark and the spots stay off; when he turns a spot on
    himself, Photo mode leaves it on."""
    from tests.gigbar_lights.test_studio_engine import make, run
    assert moments.style("photo")["sections"]["drop"]["movers"] == 0
    show = make()
    st = show.studio
    assert st.spots["on"] is False
    st.command({"op": "look", "key": "moment:photo"})
    heads = []
    run(show, 6, each=lambda now, i: heads.append(max(m.dim for bar in show.rig.bars for m in bar.movers)) if i * 0.05 > 1 else None)
    assert st.spots["on"] is False and max(heads) == 0, "no beam on a guest, and no spot it was not asked for"
    assert all(t.dim > 0.5 for t in show.rig.tetras), "the room is lit for the photos"
    # his own press: a spot he turns on stays on under Photo mode
    st.command({"op": "spots", "on": True})
    run(show, 4)
    assert st.spots["on"] is True and max(m.dim for bar in show.rig.bars for m in bar.movers) > 0
    st.command({"op": "look", "key": "moment:photo"})
    run(show, 2)
    assert st.spots["on"] is True, "pressing Photo mode again never takes his spot away"


def test_the_live_show_stopping_clears_the_soft_hold_at_once():
    """Review finding (2026-11-13): the hold must never outlive the Live show, and must never lapse
    toward loud while it runs (a Mixxx library read can hold a control tick for seconds)."""
    from tools.gigbar_lights import __main__ as gl
    from tools.gigbar_lights.enttec import NullOutput
    from tools.gigbar_lights.show import Show
    assert show_settings.SOFT_NOW_TTL_S >= 30
    show = Show(analyze=False)
    show.control_tick = lambda now=None: None      # nothing repeats the word: only the stop clears it
    show_settings.set_soft_now(True, frozenset())
    assert show_settings.soft_now() is not None
    gl._run_loop(show, NullOutput(), seconds=0.05, view=False, read_keys=False)
    assert show_settings.soft_now() is None
