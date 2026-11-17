"""His reception order for 2026-11-25 (Llano BL #12360).

His printed timeline: Cocktail hour and family photos 4:50, Grand entrance 5:30, Dinner 5:40, First
dance 6:20, a Pause, Father-daughter dance 6:25, Mother-groom dance 6:30, Toasts and speeches 6:40 and
Cake cutting 6:55 (both with low background music), Open dancing 7:05, Prepare for grand exit 8:15 (one
big sing-along, heads on), Bride and groom exit 8:30 (Sweet Caroline, heads on slow). Every part is
its own step he advances by hand. The songs he adds in Drive: a Background folder (the quiet songs
under the toasts and the cake; Sugar, Sugar for the cake) and a Grand Exit folder (Sweet Caroline).
"""
from __future__ import annotations

import pytest

from tools.gigbar_lights import run_of_show as ros
from tools.gigbar_lights import settings_contract as contract
from tools.gigbar_lights import shows, song_folder, tonight


def touch(root, rel):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")
    return p


def test_the_two_new_folders_place_their_songs(tmp_path):
    root = tmp_path / "Avery & Jordan Wedding Songs"
    touch(root, "2 - Dinner/Lonestar - Amazed.mp3")
    touch(root, "3 - Dancing/Journey - Don't Stop Believin'.mp3")
    touch(root, "5 - Toasts and Cake Background/The Archies - Sugar, Sugar.mp3")
    touch(root, "6 - Grand Exit/Neil Diamond - Sweet Caroline.mp3")
    _name, songs = song_folder.read_folder(str(root))
    by = {s["title"]: s for s in songs}
    assert (by["Sugar, Sugar"]["part"], by["Sugar, Sugar"]["moment"]) == ("dinner", "background")
    assert (by["Sweet Caroline"]["part"], by["Sweet Caroline"]["moment"]) == ("dancing", "exit")
    assert (by["Amazed"]["part"], by["Amazed"]["moment"]) == ("dinner", "")
    assert (by["Don't Stop Believin'"]["part"], by["Don't Stop Believin'"]["moment"]) == ("dancing", "")
    assert all(s["moment"] in ("", *contract.SHOW_MOMENTS) for s in songs)


def test_a_grand_exit_folder_with_two_songs_gives_each_its_moment(tmp_path):
    root = tmp_path / "w"
    touch(root, "6 - Grand Exit/01 - The Killers - Mr. Brightside.mp3")
    touch(root, "6 - Grand Exit/02 - Neil Diamond - Sweet Caroline.mp3")
    by = {s["title"]: s["moment"] for s in song_folder.read_folder(str(root))[1]}
    assert by == {"Mr. Brightside": "exit-prep", "Sweet Caroline": "exit"}
    root2 = tmp_path / "w2"   # songs nobody knows: the last file is the exit, the one before the sing-along
    touch(root2, "6 - Grand Exit/01 - A - First.mp3")
    touch(root2, "6 - Grand Exit/02 - B - Second.mp3")
    assert {s["title"]: s["moment"] for s in song_folder.read_folder(str(root2))[1]} == {"First": "exit-prep", "Second": "exit"}


def test_the_new_moments_are_part_of_the_contract_and_the_shows_page():
    for m in ("exit-prep", "exit", "background"):
        assert m in contract.SHOW_MOMENTS
    assert shows.MOMENT_TITLES["mother-son"] == "Mother-groom dance"
    assert ros.MOMENTS["mother-son"][0] == "Mother-groom dance"
    doc = contract.normalize({**contract.defaults(), "shows": {"w": {"title": "W", "songs": [
        {"artist": "Neil Diamond", "title": "Sweet Caroline", "look": "", "secs": 201, "part": "dancing", "moment": "exit"},
        {"artist": "The Archies", "title": "Sugar, Sugar", "look": "", "secs": 170, "part": "dinner", "moment": "background"}]}}})
    assert [s["moment"] for s in doc["shows"]["w"]["songs"]] == ["exit", "background"], "a saved show keeps them"


def test_the_exit_songs_get_sing_along_looks():
    songs = [shows.ShowSong("Neil Diamond", "Sweet Caroline", part="dancing", moment="exit", bpm=128),
             shows.ShowSong("The Killers", "Mr. Brightside", part="dancing", moment="exit-prep", bpm=148),
             shows.ShowSong("The Archies", "Sugar, Sugar", part="dinner", moment="background", bpm=120)]
    shows.design(songs)
    assert [s.look for s in songs] == ["sing-along", "sing-along", "warm-up"]


NIGHT = {"title": "C & M", "steps": [s.public() for s in ros.plan(
    {"cocktail": [{"artist": "A", "title": "Sip", "secs": 200}], "dinner": [{"artist": "B", "title": "Eat", "secs": 200}],
     "dancing": [{"artist": "C", "title": "Jump", "secs": 200}],
     "background": [{"artist": "The Archies", "title": "Sugar, Sugar", "secs": 170}]},
    {"exit-prep": {"artist": "Journey", "title": "Don't Stop Believin'", "secs": 250},
     "exit": {"artist": "Neil Diamond", "title": "Sweet Caroline", "secs": 201}})]}


def test_his_night_steps_and_where_the_heads_run():
    night = tonight.Tonight.from_report(NIGHT)
    names = [s["name"] for s in night.steps]
    assert names[:3] == ["Cocktail hour", "Grand entrance", "Dinner"]
    assert "Pause" not in names and "Quiet moment" not in names and "Mother-groom dance" in names
    assert names[-4:] == ["Prepare for grand exit", "Prepare for grand exit: Don't Stop Believin'",
                          "Bride and groom exit", "Bride and groom exit: Sweet Caroline"]
    bed = [s for s in night.steps if s["part"] == ros.BACKGROUND]
    assert [s["name"] for s in bed] == ["Toasts and speeches: quiet background", "Cake cutting: quiet background"]
    assert all(s["pad"] in ("moment:toast", "moment:cake") for s in bed), "the bed plays in the moment's light"
    from tools.gigbar_lights.song_match import candidates
    still, dancing = night.still_keys(), night.dancing_keys()
    assert set(candidates("The Archies", "Sugar, Sugar")) <= still, "no moving heads under the toasts or the cake"
    for a, t in (("Journey", "Don't Stop Believin'"), ("Neil Diamond", "Sweet Caroline")):
        assert set(candidates(a, t)) <= dancing and not still & set(candidates(a, t)), "the grand exit runs the heads"
    # every part is its own step, advanced by hand: Next walks them one by one
    class Studio:
        look = None
        blackout = frozen = False
        _frozen = None

        def _remember(self):
            pass
    st = Studio()
    seen = []
    for _ in names:
        night.next(st, 0.0)
        seen.append(night.current())
    assert seen == list(range(len(names))) or seen[:-1] == list(range(len(names) - 1))


@pytest.mark.parametrize("key", ["exit-prep", "exit"])
def test_an_exit_with_no_song_yet_keeps_its_hold_and_says_so(key):
    steps = ros.plan({"dancing": [{"artist": "C", "title": "Jump", "secs": 200}]}, {})
    assert ("hold", key) in [(s.kind, s.key) for s in steps]
    assert any(f"{ros.MOMENTS[key][0]} has no song yet" in c["text"] for c in ros.checks(steps))
