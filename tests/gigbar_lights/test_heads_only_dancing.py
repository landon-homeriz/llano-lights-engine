"""Moving heads run by themselves only in the dances (Llano BL #12339).

His rule, 2026-11-14: only Dancing had the moving heads running or moving. Changed the same day:
"I'd like the heads to move on their own in the dances with the option to stop them or take over."
So the first dance and the parent dances move them too, gently: one slow glide on the dance floor, no
strobe, never brighter than looks.GENTLE_HEADS. The entrance, toasts, cake and dinner keep them dark
and still. Last dance and the closing song count as Dancing. Follow someone, the Spotlight pads and
any pad he presses stay his; Stop heads and Back to auto are test_heads_control.py.

The end state: with the night on a hold, no frame leaves with a moving head lit unless a spot or pad
he pressed is on; on the first dance the heads glide gently over the floor.
"""
from __future__ import annotations

import time

import pytest

from tools.gigbar_lights import settings_contract as contract
from tools.gigbar_lights import moments, show_settings, shows, tonight
from tools.gigbar_lights.looks import GENTLE_HEADS, Frame, LooksEngine, gentle_heads, gentle_settings, still_heads, still_settings
from tools.gigbar_lights.rig import default_rig
from tools.gigbar_lights.show_script import Section
from tools.gigbar_lights.song_match import candidates

WILD = {"wash": 1, "movers": 1, "pulse": 1, "strobe": 1, "derby": True, "laser": True}


@pytest.fixture(autouse=True)
def fresh():
    def clear():
        show_settings.set_current(contract.defaults())
        show_settings.set_show_looks(None)
        show_settings.clear_play()
        for src in ("night", "show"):
            show_settings.set_soft_songs(src, None)
            show_settings.set_still_songs(src, None)
            show_settings.set_gentle_songs(src, None)
        show_settings.set_soft_now(False)
        show_settings.set_still_now(False)
        show_settings.set_gentle_now(False)
    clear()
    yield
    clear()


def heads_lit(rig) -> float:
    return max(m.dim for bar in rig.bars for m in bar.movers)


def aims(rig) -> list:
    return [(round(m.pan, 4), round(m.tilt, 4)) for bar in rig.bars for m in bar.movers]


def play(eng, artist: str, title: str):
    """The song through every kind of section, a DJ loop held and the meters high. Yields each rig."""
    keys = candidates(artist, title)
    for n, kind in enumerate(("intro", "verse", "build", "drop", "main", "breakdown", "outro", None)):
        for i in range(0, 64, 3):
            sec = Section(kind, n * 64, n * 64 + 32, 1.0) if kind else None
            f = Frame(n * 64 + i / 2, 128.0, True, level=0.95, loop_beats=0.5 if i % 2 else 0.0, section=sec,
                      track_key=7, song=keys[0], song_keys=keys)
            yield kind, eng.render(f, default_rig())


NIGHT = {"title": "C & M", "steps": [
    {"kind": "music", "key": "cocktail", "name": "Cocktail hour", "songs": [{"artist": "The Band", "title": "Sip"}]},
    {"kind": "hold", "key": "entrance", "name": "Grand entrance", "look": "grand-entrance",
     "songs": [{"artist": "Llano hold", "title": "HOLD - Grand entrance"}]},
    {"kind": "song", "key": "first-dance", "name": "First dance: Ours", "look": "first-dance",
     "songs": [{"artist": "The Band", "title": "Ours"}]},
    {"kind": "music", "key": "dinner", "name": "Dinner", "songs": [{"artist": "The Band", "title": "Eat"}]},
    {"kind": "hold", "key": "cake", "name": "Cake cutting", "look": "cake-cutting"},
    {"kind": "song", "key": "father-daughter", "name": "Father-daughter dance", "look": "parent-dance",
     "songs": [{"artist": "The Band", "title": "Dad"}]},
    {"kind": "music", "key": "dancing", "name": "Dancing", "songs": [{"artist": "The Band", "title": "Jump"}]},
    {"kind": "song", "key": "last-dance", "name": "Last dance", "look": "last-dance",
     "songs": [{"artist": "The Band", "title": "Last"}]},
    {"kind": "song", "key": "close", "name": "Closing song", "songs": [{"artist": "The Band", "title": "Close"}]}]}


class Studio:   # the bits of the studio Tonight touches
    look = None
    blackout = frozen = False
    _frozen = None

    def _remember(self):
        pass


def filed_wild(*titles) -> dict:
    """Saved settings where each song is filed under a style with the heads fully on (the way his
    night filed the moments' looks before this change)."""
    base = contract.normalize({**contract.defaults(), "crowd_safe": False})
    wild = contract.normalize_style({**contract.style_of(base), "sections": {s: dict(WILD) for s in contract.SECTIONS}})
    songs = {candidates("The Band", t)[0]: "wild" for t in titles}
    return contract.normalize({**base, "styles": {"wild": wild}, "songs": songs})


def test_the_night_names_its_still_steps_its_gentle_dances_and_its_dancing():
    night = tonight.Tonight.from_report(NIGHT)
    still, gentle = night.still_keys(), night.gentle_keys()
    for t in ("Ours", "Dad"):
        assert set(candidates("The Band", t)) <= gentle, t
        assert not still & set(candidates("The Band", t)), t
    assert set(candidates("Llano hold", "HOLD - Grand entrance")) <= still
    for t in ("Jump", "Last", "Close", "Sip", "Eat"):
        assert not (still | gentle) & set(candidates("The Band", t)), t
    dancing = night.dancing_keys()
    for t in ("Jump", "Last", "Close"):
        assert set(candidates("The Band", t)) <= dancing, t
    assert tonight.Tonight.plain().still_keys() == set() and tonight.Tonight.plain().gentle_keys() == set()


def test_a_dance_filed_under_a_wild_look_moves_the_heads_gently():
    night = tonight.Tonight.from_report(NIGHT)
    show_settings.set_gentle_songs("night", night.gentle_keys())
    eng = LooksEngine(settings=filed_wild("Ours", "Dad", "Jump", "Last"))
    for title in ("Ours", "Dad"):
        wash, lit, poses = 0.0, 0.0, set()
        for kind, rig in play(eng, "The Band", title):
            assert eng.limit == "gentle" and heads_lit(rig) <= GENTLE_HEADS, (title, kind)
            assert all(m.strobe == 0 for bar in rig.bars for m in bar.movers)
            lit = max(lit, heads_lit(rig))
            poses.add(tuple(aims(rig)))
            wash = max(wash, max(fx.dim for fx in (*rig.tetras, *rig.sticks)))
        assert lit > 0, "the heads move on their own in the dances"
        assert len(poses) > 1, "and they move"
        assert wash > 0.5, "the moment keeps its own look: only the heads are calmed"
        assert eng.showing == "style:wild"
    for title in ("Jump", "Last"):   # Dancing, and the last dance, which counts as Dancing
        lit = max(heads_lit(rig) for _k, rig in play(eng, "The Band", title))
        assert eng.limit == "" and lit > 0, title


def test_the_gentle_move_stays_on_the_dance_floor_and_slow():
    """Nothing that swings beams at the couple's eyes or out over the tables: the heads stay between
    the front of the booth and the middle of the floor, never tilted up past where "crowd" points."""
    show_settings.set_gentle_songs("night", tonight.Tonight.from_report(NIGHT).gentle_keys())
    eng = LooksEngine(settings=filed_wild("Ours"))
    from tools.gigbar_lights.looks import DEFAULT_POSITIONS
    top = max(t for _p, t in DEFAULT_POSITIONS["crowd"]) + 0.02
    tilts, pans = [], []
    for _k, rig in play(eng, "The Band", "Ours"):
        for bar in rig.bars:
            for m in bar.movers:
                tilts.append(m.tilt)
                pans.append(m.pan)
    assert max(tilts) <= top, ("a beam tipped up toward eyes", max(tilts))
    assert max(pans) - min(pans) < 0.3, "no wide swing out over the tables"


def test_a_hold_keeps_the_heads_dark_and_still():
    show_settings.set_still_songs("night", tonight.Tonight.from_report(NIGHT).still_keys())
    eng = LooksEngine(settings=filed_wild("HOLD - Grand entrance"))
    poses = []
    for _k, rig in play(eng, "Llano hold", "HOLD - Grand entrance"):
        assert eng.limit == "still" and heads_lit(rig) == 0
        poses.append(tuple(aims(rig)))
    assert len(set(poses)) == 1, "no head moves by itself during the entrance"


def test_while_the_night_stands_on_a_hold_every_unlisted_song_is_held_and_dancing_lifts_it():
    night = tonight.Tonight.from_report(NIGHT)
    studio = Studio()
    eng = LooksEngine(settings=contract.normalize({**contract.defaults(), "crowd_safe": False}))
    req = list(candidates("Somebody", "A Request"))

    def tick():   # what Show._tell_night says each control tick
        show_settings.set_soft_now(night.soft_now(), night.spared_keys())
        show_settings.set_still_now(night.still_now(), night.dancing_keys())
        show_settings.set_gentle_now(night.gentle_now(), night.dancing_keys())

    def limit(keys):
        eng.show_for(contract.defaults(), keys[0], keys)
        return eng.limit

    tick()
    assert limit(req) == "", "nothing seen yet: nothing claimed"
    night.see(studio, candidates("Llano hold", "HOLD - Grand entrance"), 0.0)   # Mixxx is on the entrance hold
    tick()
    assert night.still_now() and limit(req) == "still"
    for _kind, rig in play(eng, "Somebody", "A Request"):
        assert heads_lit(rig) == 0
    assert limit(list(candidates("The Band", "Jump"))) == "", "a Dancing song keeps its heads"
    night.see(studio, candidates("The Band", "Ours"), 0.0)                      # the first dance
    tick()
    assert night.gentle_now() and not night.still_now() and limit(req) == "gentle"
    night.see(studio, candidates("The Band", "Eat"), 0.0)                       # dinner: the soft limit, as before
    tick()
    assert not night.still_now() and not night.gentle_now() and limit(req) == "soft"
    night.see(studio, candidates("The Band", "Jump"), 0.0)                      # Dancing
    tick()
    assert limit(req) == ""
    night.see(studio, candidates("The Band", "Last"), 0.0)                      # the last dance is Dancing
    tick()
    assert not night.still_now() and limit(req) == ""
    night.goto(studio, 4, 0.0)                                                  # he pressed Next back to the cake
    tick()
    assert night.still_now() and limit(req) == "still"
    # the word lapses when the Live show stops saying it
    show_settings.set_still_now(True, night.dancing_keys(), now=time.monotonic() - show_settings.SOFT_NOW_TTL_S - 1)
    assert limit(req) == ""
    show_settings.set_gentle_now(True, night.dancing_keys(), now=time.monotonic() - show_settings.SOFT_NOW_TTL_S - 1)
    assert limit(req) == ""
    assert not tonight.Tonight.plain().still_now(), "with no night built nothing is held"


def test_a_show_moves_its_first_and_parent_dances_gently_and_the_last_dance_fully():
    songs = [shows.ShowSong("The Band", "Ours", look="peak", part="dinner", moment="first-dance"),
             shows.ShowSong("The Band", "Dad", look="peak", part="dancing", moment="father-daughter"),
             shows.ShowSong("The Band", "Mom", look="peak", part="dancing", moment="mother-son"),
             shows.ShowSong("The Band", "Last", look="peak", part="dancing", moment="last-dance"),
             shows.ShowSong("The Band", "Jump", look="peak", part="dancing")]
    gentle = shows.gentle_keys(songs)
    for t in ("Ours", "Dad", "Mom"):
        assert set(candidates("The Band", t)) <= gentle, t
    for t in ("Last", "Jump"):
        assert not gentle & set(candidates("The Band", t)), t
    show_settings.set_show_looks(shows.looks_for(songs), None, shows.soft_keys(songs), gentle=gentle)
    eng = LooksEngine(settings=contract.normalize({**contract.defaults(), "crowd_safe": False}))
    lit = 0.0
    for _kind, rig in play(eng, "The Band", "Ours"):
        assert eng.limit == "gentle" and heads_lit(rig) <= GENTLE_HEADS
        lit = max(lit, heads_lit(rig))
    assert lit > 0
    assert max(heads_lit(rig) for _k, rig in play(eng, "The Band", "Jump")) > GENTLE_HEADS
    show_settings.set_show_looks(None)
    assert show_settings.gentle_songs() == frozenset() and show_settings.still_songs() == frozenset()


def test_his_own_controls_stay_his():
    show_settings.set_still_songs("night", tonight.Tonight.from_report(NIGHT).still_keys())
    eng = LooksEngine(settings=filed_wild("HOLD - Grand entrance"))
    keys = candidates("Llano hold", "HOLD - Grand entrance")
    f = Frame(200.0, 128.0, True, level=0.95, section=Section("drop", 192, 224, 1.0), track_key=7,
              song=keys[0], song_keys=keys)
    assert heads_lit(eng.render(f, default_rig())) == 0
    # a pad he presses plays as the draft: the Spotlight pad lights its heads during the entrance
    show_settings.set_play(moments.style("spotlight"), float("inf"), label="Spotlight")
    assert heads_lit(eng.render(f, default_rig())) > 0 and eng.limit == ""
    show_settings.clear_play()
    assert heads_lit(eng.render(f, default_rig())) == 0
    # a held simple look, a scene pad and the line-up screens are his too
    for field, value in (("simple", {"name": "house", "rgb": None}), ("scene", contract.SCENES[0]),
                         ("lineup", (0, "center"))):
        setattr(eng.overrides, field, value)
        lit = heads_lit(eng.render(f, default_rig()))
        setattr(eng.overrides, field, None)
        if field != "scene":   # a scene may itself keep the heads dark; it is only never cut by the limit
            assert lit > 0, field
        assert eng.limit == "still"   # the limit is still named: only its backstop stands aside


def test_the_moments_themselves_keep_the_heads_off_outside_the_dances():
    for key in ("dinner", "entrance", "cake", "toast", "photo"):
        st = moments.style(key)
        assert all(sec["movers"] == 0 and sec["move"]["shape"] == "hold" for sec in st["sections"].values()), key
    for key in ("first-dance", "father-daughter"):   # the dances glide the heads slowly over the floor
        for sec in moments.style(key)["sections"].values():
            mv = sec["move"]
            assert 0 < sec["movers"] <= GENTLE_HEADS and sec["strobe"] == 0, key
            assert mv["shape"] == "glide" and {mv["from"], mv["to"]} <= {"booth", "crowd"} and mv["beats"] >= 32, key
    for key in ("party", "last-dance", "spotlight", "two-spotlights"):
        assert any(sec["movers"] > 0 for sec in moments.style(key)["sections"].values()), key


def test_the_limit_pieces_on_their_own():
    base = contract.normalize({**contract.defaults(), "crowd_safe": False})
    cfg = still_settings(base)
    assert all(s["movers"] == 0 and s["move"]["shape"] == "hold" for s in cfg["sections"].values())
    assert cfg["strobe"] == base["strobe"] and cfg["drop"] == base["drop"], "only the heads change"
    assert base["sections"] != cfg["sections"], "the settings it was given are not changed"
    rig = default_rig()
    for bar in rig.bars:
        for m in bar.movers:
            m.dim, m.strobe = 1.0, 0.5
    still_heads(rig)
    assert heads_lit(rig) == 0 and all(m.strobe == 0 for bar in rig.bars for m in bar.movers)


def test_the_gentle_pieces_on_their_own():
    base = contract.normalize({**contract.defaults(), "crowd_safe": False})
    cfg = gentle_settings(base)
    for sec in cfg["sections"].values():
        assert 0.45 <= sec["movers"] <= GENTLE_HEADS and sec["move"]["shape"] == "glide"
        assert sec["move"]["from"] == "booth" and sec["move"]["to"] == "crowd" and sec["move"]["beats"] == 32
    assert base["sections"] != cfg["sections"], "the settings it was given are not changed"
    dark = contract.normalize({**base, "sections": {s: {**v, "movers": 0.0} for s, v in base["sections"].items()}})
    assert all(sec["movers"] >= 0.45 for sec in gentle_settings(dark)["sections"].values()), \
        "a look that keeps its heads off still moves them in a dance: they move on their own"
    rig = default_rig()
    for bar in rig.bars:
        for m in bar.movers:
            m.dim, m.strobe = 1.0, 0.5
    gentle_heads(rig)
    assert heads_lit(rig) == GENTLE_HEADS and all(m.strobe == 0 for bar in rig.bars for m in bar.movers)
