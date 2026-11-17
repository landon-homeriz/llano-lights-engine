"""His toasts and speeches playlist (2026-11-14): eleven instrumentals he picked from his "Wedding
Instrumentals" folder play quietly under the toasts, in his order, from their own "5 - Toasts
Background" folder; Sugar, Sugar stays under the cake ("5 - Cake Background"). The Instrumentals
folder is the library he picks from: it is never played as it is."""
from __future__ import annotations

from tools.gigbar_lights import run_of_show as ros
from tools.gigbar_lights import settings_contract as contract
from tools.gigbar_lights import set_arranger, shows, song_folder, tonight
from tools.gigbar_lights.song_match import candidates

HIS_ELEVEN = ["Bless The Broken Road (Instrumental Guitar Cover)", "When You Say Nothing at All (Instrumental Guitar Cover)",
              "Amazed (Instrumental Guitar Cover)", "You’re Still the One (Instrumental Piano)", "I Swear (Piano Instrumental)",
              "A Thousand Years (Instrumental Guitar Cover)", "How Long Will I Love You (Instrumental Guitar Cover)",
              "Until I Found You (Instrumental Guitar Cover)", "All of Me (Instrumental Acoustic Guitar)",
              "Come Away with Me (Instrumental Cover)", "Something (Instrumental Piano)"]


def touch(root, rel):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")


def his_folder(tmp_path):
    root = tmp_path / "Avery & Jordan Wedding Songs"
    touch(root, "2 - Dinner/Lonestar - Amazed.mp3")
    touch(root, "3 - Dancing/Journey - Don't Stop Believin'.mp3")
    for i, t in enumerate(HIS_ELEVEN, 1):
        touch(root, f"5 - Toasts Background/{i:02d} - {t}.mp3")
    touch(root, "5 - Cake Background/The Archies - Sugar, Sugar.mp3")
    touch(root, "6 - Grand Exit/Neil Diamond - Sweet Caroline.mp3")
    for i, t in enumerate(["A Thousand Years (Instrumental Guitar Cover)", "Perfect (Instrumental Piano)",
                           "Marry You (Instrumental Guitar)"], 1):
        touch(root, f"Wedding Instrumentals/{i:02d} - {t}.mp3")
    return root


def test_the_toasts_folder_plays_his_eleven_in_his_order_and_the_library_is_skipped(tmp_path):
    _name, songs = song_folder.read_folder(str(his_folder(tmp_path)))
    toasts = [s for s in songs if s["moment"] == "toasts-background"]
    assert [s["title"] for s in toasts] == HIS_ELEVEN
    assert all(s["artist"] == "" and s["part"] == "dinner" for s in toasts), "the number is not an artist"
    assert [(s["title"], s["moment"]) for s in songs if s["moment"] == "background"] == [("Sugar, Sugar", "background")]
    assert not any("Wedding Instrumentals" in s["file"] for s in songs), "the library folder never plays as it is"
    assert {s["title"]: s["moment"] for s in songs}["Amazed"] == "", "his dinner Amazed is still a dinner song"


def test_a_part_named_instrumentals_folder_still_plays_in_its_part(tmp_path):
    root = tmp_path / "w"
    touch(root, "2 - Dinner Instrumentals/Piano Guys - Perfect.mp3")
    assert [(s["part"], s["moment"]) for s in song_folder.read_folder(str(root))[1]] == [("dinner", "")]


def test_the_old_toasts_and_cake_folder_still_plays_under_both(tmp_path):
    root = tmp_path / "w"
    touch(root, "5 - Toasts and Cake Background/The Archies - Sugar, Sugar.mp3")
    assert [s["moment"] for s in song_folder.read_folder(str(root))[1]] == ["background"]


def test_the_new_moment_is_in_the_contract_and_a_saved_show_keeps_it():
    assert "toasts-background" in contract.SHOW_MOMENTS
    assert shows.MOMENT_TITLES["toasts-background"] == "Under the toasts"
    doc = contract.normalize({**contract.defaults(), "shows": {"w": {"title": "W", "songs": [
        {"artist": "", "title": "I Swear (Piano Instrumental)", "look": "", "secs": 271, "part": "dinner",
         "moment": "toasts-background"}]}}})
    assert doc["shows"]["w"]["songs"][0]["moment"] == "toasts-background"


def _night(parts):
    return tonight.Tonight.from_report({"title": "C & M", "steps": [s.public() for s in ros.plan(parts, {})]})


EAT = {"artist": "B", "title": "Eat", "secs": 200}
SUGAR = {"artist": "The Archies", "title": "Sugar, Sugar", "secs": 170}
BED = [{"artist": "", "title": t, "secs": 200} for t in HIS_ELEVEN]


def test_the_toasts_play_his_eleven_and_the_cake_plays_sugar_sugar_with_the_heads_still():
    steps = ros.plan({"dinner": [EAT], "dancing": [{"artist": "C", "title": "Jump", "secs": 200}],
                      "background": [SUGAR], "toasts-background": BED}, {})
    beds = [(s.name, s.key, [x["title"] for x in s.songs]) for s in steps if s.kind == "music" and s.key in ros.BEDS]
    assert beds == [("Toasts and speeches: quiet background", "toasts-background", HIS_ELEVEN),
                    ("Cake cutting: quiet background", "background", ["Sugar, Sugar"])]
    night = _night({"dinner": [EAT], "dancing": [{"artist": "C", "title": "Jump", "secs": 200}],
                    "background": [SUGAR], "toasts-background": BED})
    still = night.still_keys()
    for t in (HIS_ELEVEN[0], HIS_ELEVEN[-1]):
        assert set(candidates("", t)) <= still, "no moving heads under the toasts"
    assert set(candidates("The Archies", "Sugar, Sugar")) <= still
    show = ros.show_songs(steps)
    assert [d["title"] for d in show if d.get("moment") == "toasts-background"] == HIS_ELEVEN


def test_with_no_toasts_folder_the_toasts_get_the_cake_bed_as_before():
    steps = ros.plan({"dinner": [EAT], "background": [SUGAR]}, {})
    assert [(s.name, s.key) for s in steps if s.kind == "music" and s.key in ros.BEDS] == [
        ("Toasts and speeches: quiet background", "background"), ("Cake cutting: quiet background", "background")]


def test_the_arranger_keeps_the_toasts_songs_in_his_order_out_of_the_dancing():
    songs = [shows.ShowSong("Journey", "Don't Stop Believin'", part="dancing", bpm=119),
             shows.ShowSong("Lonestar", "Amazed", part="dinner", bpm=70)]
    songs += [shows.ShowSong("", t, part="dinner", moment="toasts-background", bpm=60 + 7 * i) for i, t in enumerate(HIS_ELEVEN)]
    songs.append(shows.ShowSong("Neil Diamond", "Sweet Caroline", part="dancing", bpm=128))
    placed = set_arranger.arrange(songs)
    toasts = [p for p in placed if p.song.moment == "toasts-background"]
    assert [p.song.title for p in toasts] == HIS_ELEVEN
    assert all(p.song.part == "dinner" and p.slot.part == "dinner" for p in toasts)
    assert all("toasts" in p.song.reason for p in toasts)
    set_arranger.suggestions(placed)   # a song known for a moment with no name (Sweet Caroline: exit) does not fail
