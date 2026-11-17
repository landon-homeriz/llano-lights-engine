"""The night says what happens at every stop and what he presses (Llano Lights night words, 2026-11-15).

His two reports: the night showed a "Pause" and he could not tell whether Mixxx stops by itself or
what to press; and the written steps never told him how his songs get into Mixxx. A hold is an
hour-long silent track: Mixxx only moves past one by itself after that hour, so every hold says it waits for Fade Now.
"""
import re

from tools.gigbar_lights import run_of_show as ros
from tools.gigbar_lights import setup_guide, tonight


def S(artist, title, secs=200, **kw):
    return {"artist": artist, "title": title, "secs": secs, **kw}


# A show like his: songs for the three parts and the three dances, plus the grand exit's two songs.
SHOW = {"title": "C & M", "songs": [
    S("A", "Sip 1", part="cocktail"), S("A", "Sip 2", part="cocktail"),
    S("B", "Eat 1", part="dinner"), S("B", "Eat 2", part="dinner"),
    S("C", "Jump 1", part="dancing"), S("C", "Jump 2", part="dancing"), S("C", "Jump 3", part="dancing"),
    S("Randy Travis", "Forever and Ever, Amen", 213, part="dancing", moment="first-dance"),
    S("Dad", "My Girl", 180, part="dancing", moment="father-daughter"),
    S("Mom", "A Song for Mama", 190, part="dancing", moment="mother-son"),
    S("Journey", "Don't Stop Believin'", 250, part="dancing", moment="exit-prep"),
    S("Neil Diamond", "Sweet Caroline", 201, part="dancing", moment="exit"),
]}


def _no_two_holds(kinds):
    return not any(a == b == "hold" for a, b in zip(kinds, kinds[1:]))


def test_a_the_default_night_has_no_quiet_moment_and_never_two_holds_in_a_row():
    night = tonight.Tonight.from_show("cm", SHOW)
    names = [s["name"] for s in night.steps]
    assert "Pause" not in names and "Quiet moment" not in names
    assert _no_two_holds([s["kind"] for s in night.steps]), names
    assert "Father-daughter dance" in names and "Mother-groom dance" in names
    assert "pause" not in ros.DEFAULT_ORDER and "pause" in ros.OPTIONAL


def test_a_without_exit_songs_only_the_two_exit_moments_sit_back_to_back():
    """Two real moments back to back stay: each is something he announces (the sing-along call, then
    the send-off). The quiet moment is the only hold the plan drops."""
    show = {**SHOW, "songs": [s for s in SHOW["songs"] if s.get("moment") not in ("exit-prep", "exit")]}
    steps = tonight.Tonight.from_show("cm", show).steps
    pairs = [(a["name"], b["name"]) for a, b in zip(steps, steps[1:]) if a["kind"] == b["kind"] == "hold"]
    assert pairs == [("Prepare for grand exit", "Bride and groom exit")]


def test_b_a_saved_order_that_names_pause_still_loads():
    parts = {"cocktail": [S("A", "Sip")], "dinner": [S("B", "Eat")]}
    asked = ("cocktail", "pause", "dinner")
    assert [s.key for s in ros.plan(parts, order=asked)] == ["cocktail", "dinner"], "optional: off unless ticked"
    steps = ros.plan(parts, order=asked, skip=set())
    assert [(s.kind, s.name) for s in steps] == [("music", "Cocktail hour"), ("hold", "Quiet moment"), ("music", "Dinner")]
    assert steps[1].say == "Nothing plays. Press Fade Now in Mixxx when you are ready to go on."
    # a night built before today still has a step called Pause in its night.json: it loads and says what to press
    old = tonight.Tonight.from_report({"title": "old", "built": "x", "steps": [
        {"kind": "music", "key": "cocktail", "name": "Cocktail hour", "songs": [S("A", "Sip")]},
        {"kind": "hold", "key": "pause", "name": "Pause", "say": "Hold here."},
        {"kind": "music", "key": "dinner", "name": "Dinner", "songs": [S("B", "Eat")]}]})
    assert [s["name"] for s in old.steps] == ["Cocktail hour", "Pause", "Dinner"]
    assert "Fade Now" in old.steps[1]["press"] and "waits" in old.steps[1]["wait"]


def test_b_a_quiet_moment_next_to_another_hold_is_dropped():
    parts = {"cocktail": [S("A", "Sip")], "dinner": [S("B", "Eat")]}
    for asked in (("cocktail", "pause", "toasts", "dinner"),        # right before a hold
                  ("cocktail", "toasts", "pause", "dinner"),        # right after one
                  ("cocktail", "first-dance", "pause", "father-daughter", "dinner")):
        steps = ros.plan(parts, order=asked, skip=set())
        assert "pause" not in [s.key for s in steps], asked
        assert _no_two_holds([s.kind for s in steps]) or asked[1] == "first-dance", asked
    # his old default: the first dance's song, then the pause, then the father-daughter hold
    steps = ros.plan(parts, {"first-dance": S("R", "Forever")}, order=("cocktail", "first-dance", "pause", "father-daughter", "dinner"), skip=set())
    assert [s.kind for s in steps] == ["music", "hold", "song", "hold", "music"]


def _all_rows():
    nights = [ros.plan({"cocktail": [S("A", "a"), S("A", "b")], "dinner": [S("B", "c")], "dancing": [S("C", "d"), S("C", "e")],
                        "background": [S("B", "c")]}, {"first-dance": S("R", "F")}),
              ros.plan({"cocktail": [S("A", "a")], "dancing": [S("C", "d"), S("C", "e"), S("C", "f")]}, {},
                       order=("cocktail", "entrance", "first-dance", "welcome", "dancing", "bouquet", "dancing", "send-off")),
              tonight.Tonight.from_show("cm", SHOW)]
    out = []
    for n in nights:
        steps = n if isinstance(n, list) else None
        if steps is None:   # the Live screen's own words, from the saved show
            out += [{"kind": s["kind"], "text": s["wait"] + " " + s["press"]} for s in n.steps]
            continue
        out += [{"kind": s.kind, "text": r["detail"] + " " + r["next"]} for s, r in zip(steps, ros.sheet_rows(steps))]
        page = ros.sheet_html("x", steps)
        assert "stops by itself for the pause" not in page and "stops by itself" not in page
    return out


def test_c_every_hold_says_it_waits_for_fade_now_and_nothing_says_it_stops_by_itself():
    rows = _all_rows()
    holds = [r for r in rows if r["kind"] == "hold"]
    assert len(holds) >= 8
    for r in holds:
        assert "Fade Now" in r["text"] and "waits" in r["text"], r
        assert "It does not move on until you press Fade Now." in r["text"] and "up to an hour" in r["text"]
    for r in rows:
        assert "stops by itself" not in r["text"], r


def test_c_a_song_before_a_hold_and_music_before_a_new_playlist_say_exactly_what_happens():
    parts = {"cocktail": [S("A", "a", 300), S("A", "b", 300)], "dinner": [S("B", "c")]}
    steps = ros.plan(parts, {"first-dance": S("R", "Forever")}, order=("cocktail", "first-dance", "toasts", "dinner"))
    by = {r["what"]: r for r in ros.sheet_rows(steps)}
    assert by["Cocktail hour"]["next"] == (
        "When it is time for the first dance: in Mixxx, right click playlist 2 in the list on the left, choose Add to "
        "Auto DJ Queue (replace), then press Fade Now. Until then the songs keep playing, and start again after 10 minutes.")
    assert by["First dance: Forever"]["next"] == "Nothing. When the song ends, Mixxx goes quiet by itself and waits for you. Next: Toasts and speeches."
    assert by["Toasts and speeches"]["next"] == "When you are ready, press Fade Now in Mixxx: dinner starts."


def test_d_the_sheet_header_counts_the_fade_now_presses_and_new_playlists():
    parts = {"cocktail": [S("A", "a"), S("A", "b")], "dinner": [S("B", "c"), S("B", "d")], "dancing": [S("C", "e"), S("C", "f")]}
    steps = ros.plan(parts, {"first-dance": S("R", "F")},
                     order=("cocktail", "entrance", "dinner", "first-dance", "dancing", "send-off"))
    # cocktail | entrance (playlist 2) | dinner | first dance hold (playlist 3) | its song | dancing | send-off (playlist 4)
    assert [s.name for s in steps if s.opens] == ["Cocktail hour", "Grand entrance", "First dance", "Send-off"]
    assert ros.presses(steps) == (5, 3)    # leave the entrance and the first-dance holds, plus 3 new playlists
    page = ros.sheet_html("C & M", steps)
    assert "Tonight you press Fade Now 5 times and start a new playlist 3 times." in page
    i = [page.index(t) for t in ("Mixxx plays the music. Llano Lights listens to Mixxx and runs the lights.",
                                 "To start the night:", "What a HOLD is:", "is the second button in that row",
                                 "Tonight you press Fade Now", "If anything goes wrong:")]
    assert i == sorted(i), "the header reads in the brief's order"
    assert "If you pressed Load Mixxx at home, playlist 1 is already waiting in the list." in re.sub(r"\s+", " ", page)
    one = ros.plan({"dancing": [S("C", "e")]}, {}, order=("dancing", "send-off"))
    assert "Tonight you press Fade Now 1 time and start a new playlist 1 time." in ros.sheet_html("x", one)


def test_e_the_guide_builds_and_loads_with_load_mixxx_and_never_imports_by_hand():
    steps = {s["key"]: s for s in setup_guide.steps({})}
    assert list(steps) == list(setup_guide.KEYS)
    built = steps["built"]
    assert built["title"] == "Build the night and load it into Mixxx"
    assert "press Load Mixxx" in built["do"] and "You do not import anything by hand." in built["do"]
    assert "the by-hand steps are on the Shows page under Build the night" in built["fix"]
    assert steps["music"]["title"] == "Put your songs in a show" and "Extract All" in steps["music"]["do"]
    assert "Load, Moments, Listen, Mood, Review" in steps["music"]["fix"] and "Rules" not in steps["music"]["fix"]
    assert steps["autodj"]["title"] == "Check Mixxx's Auto DJ"
    for s in steps.values():
        text = f'{s["do"]} {s["fix"]}'
        assert not re.search(r"\bimport (its|the|your)?\s*(numbered )?playlists", text, re.I), s["key"]
        assert "-night folder" not in text, s["key"]


def test_the_load_refusal_points_at_the_shows_page():
    from pathlib import Path
    src = (Path(ros.__file__).parent / "mixxx_load.py").read_text(encoding="utf-8")
    assert "the steps below" not in src and "The by-hand steps are on the Shows page under Build the night." in src


def test_the_live_screen_gets_what_to_press_at_every_step():
    night = tonight.Tonight.from_show("cm", SHOW)
    pub = night.public()
    assert all(s["press"] for s in pub["steps"]), [s["name"] for s in pub["steps"] if not s["press"]]
    for s in pub["steps"]:
        assert ("waits" in s["wait"]) == (s["kind"] == "hold")
    assert pub["press"] == ""    # Mixxx not seen yet
    night.at = 1                  # the grand entrance hold
    assert night.public()["press"].startswith("When you are ready, press Fade Now in Mixxx:")
    plain = tonight.Tonight.plain().public()
    assert all(s["press"] for s in plain["steps"])
    assert "start again after 0 minutes" not in " ".join(s["press"] for s in plain["steps"])


# --- try to break it --------------------------------------------------------------------------------

def test_a_night_of_only_holds():
    steps = ros.plan({}, {}, order=("entrance", "toasts", "cake", "send-off"))
    assert [s.kind for s in steps] == ["hold"] * 4 and steps[0].opens and not any(s.opens for s in steps[1:])
    rows = ros.sheet_rows(steps)
    assert all("Fade Now" in r["next"] for r in rows)
    assert ros.presses(steps) == (3, 0)
    assert "Tonight you press Fade Now 3 times and start a new playlist 0 times." in ros.sheet_html("x", steps)


def test_an_empty_show():
    # no songs at all: the live moments still stand as holds (no quiet moment among them), each saying Fade Now
    steps = ros.plan({}, {})
    assert steps and all(s.kind == "hold" for s in steps) and "pause" not in [s.key for s in steps]
    assert all("Fade Now" in r["next"] for r in ros.sheet_rows(steps))
    live = tonight.Tonight.from_show("e", {"songs": []})
    assert [s["name"] for s in live.steps] == [s.name for s in steps] and all(s["press"] for s in live.steps)
    # nothing at all
    assert ros.sheet_rows([]) == [] and ros.presses([]) == (0, 0)
    assert "Nothing is planned for tonight yet." in ros.sheet_html("x", [])
    assert tonight.Tonight.from_report({"steps": []}).public()["press"] == ""


def test_a_night_whose_last_step_is_a_hold():
    steps = ros.plan({"dancing": [S("C", "e"), S("C", "f")]}, {}, order=("dancing", "send-off"))
    last = ros.sheet_rows(steps)[-1]
    assert last["next"].startswith("Nothing more: this is the end of the night") and "Fade Now" in last["next"]
    assert "waits" in last["detail"]


def test_a_quiet_moment_first_or_last():
    parts = {"cocktail": [S("A", "a"), S("A", "b")]}
    first = ros.plan(parts, order=("pause", "cocktail"), skip=set())
    assert [(s.kind, s.key, s.opens) for s in first] == [("hold", "pause", True), ("music", "cocktail", False)]
    assert ros.sheet_rows(first)[0]["next"] == "When you are ready, press Fade Now in Mixxx: cocktail hour starts."
    assert ros.presses(first) == (1, 0)
    last = ros.plan(parts, order=("cocktail", "pause"), skip=set())
    assert [(s.kind, s.key) for s in last] == [("music", "cocktail"), ("hold", "pause")]
    rows = ros.sheet_rows(last)
    assert rows[0]["next"] == ("When it is time for the quiet moment: in Mixxx, right click playlist 2 in the list on the left, "
                               "choose Add to Auto DJ Queue (replace), then press Fade Now. Until then the songs keep "
                               "playing, and start again after 7 minutes.")
    alone = ros.plan({}, order=("pause",), skip=set())
    assert [s.name for s in alone] == ["Quiet moment"]
    twice = ros.plan(parts, order=("cocktail", "pause", "pause"), skip=set())
    assert [s.key for s in twice] == ["cocktail", "pause"]


def test_a_saved_song_step_with_no_song_does_not_break_the_words():
    night = tonight.Tonight.from_report({"steps": [
        {"kind": "hold", "key": "first-dance", "name": "First dance"},
        {"kind": "song", "key": "first-dance", "name": "First dance: ?", "songs": []},
        {"kind": "hold", "key": "send-off", "name": "Send-off"}]})
    assert night.steps[0]["press"] == "When you are ready, press Fade Now in Mixxx: the song starts."
    assert night.steps[1]["press"].startswith("Nothing. When the song ends, Mixxx goes quiet")
