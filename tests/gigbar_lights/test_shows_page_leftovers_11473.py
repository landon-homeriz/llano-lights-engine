"""The Shows page leftovers from the lead's click-through (Llano BL #11473, PR 3).

1. Every save, by any button, shows the saved show in the left list at once, and a save that had to
   make up the name (a folder's, playlist's or Spotify list's) says so: "Saved as "music". Change the
   name at the top any time." Two quick saves make one show, not two.
2. Leaving the Shows page ends the rehearsal it started (pagehide, a keepalive request), and the header
   says Previewing only while the show runs.
3. Paste a list leaves out the lines that are not a song (nothing but punctuation, or no artist and title
   to split that his library does not know) and names them; typed as "Title by Artist", a song goes in.
4. The arranger's note wraps: nothing on the page runs past its right edge at 1024 or 1366 wide.
5. A line about one action clears when he moves to another step or after 10 seconds; a warning stays
   until he acts.
6. The printed run sheet says what the lights do for Prepare for grand exit (the party look), not
   "Each song's own look".

The tests that need the window (the paste door, a paste with no Mixxx library, the page in a browser at
1366 and 1024) are in test_shows_page_fixes_11473.py, on its one window server: CI has 20 preview ports.
"""
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))   # gigbar_app
from tools.gigbar_lights import shows  # noqa: E402

GOOD = ["Earth, Wind & Fire - September", "At Last by Etta James", "Dua Lipa - Levitating", "ABBA - Dancing Queen",
        "Journey - Faithfully", "Lonestar - Amazed", "Owl City - Fireflies", "Bruno Mars - Uptown Funk",
        "Beyonce - Crazy In Love", "Daft Punk - One More Time"]


# --- 3: Paste a list -------------------------------------------------------------------------------

def test_a_paste_leaves_out_and_names_lines_that_are_not_a_song():
    text = "\n".join(GOOD + ["not a song", "----", "", "   ", "* * *"])
    songs, left = shows.parse_pasted(text, known=lambda t: False)
    assert len(songs) == 10 and left == ["not a song", "----", "* * *"]
    assert not [s for s in songs if not s["artist"]]
    # the paste box's own example is all songs, with nothing left out
    page = (Path(__file__).resolve().parents[2] / "tools/gigbar_lights/windows/src/shows.html").read_text(encoding="utf-8")
    example = page.split('id="paste" placeholder="', 1)[1].split('"', 1)[0].split("&#10;")[1:]
    assert example and shows.parse_pasted("\n".join(x.replace("&amp;", "&") for x in example), known=lambda t: False)[1] == []


def test_a_bare_title_his_library_has_still_goes_in_and_title_by_artist_always_does():
    songs, left = shows.parse_pasted("September\nnot a song\nnot a song by Nobody", known=lambda t: t == "September")
    assert [(s["artist"], s["title"]) for s in songs] == [("", "September"), ("Nobody", "not a song")]
    assert left == ["not a song"]
    # with no library to ask, the old parse_list keeps a bare title; a divider is never a song
    assert shows.parse_list("Mr. Brightside\n----") == [{"artist": "", "title": "Mr. Brightside", "secs": 0.0}]


def test_a_paste_of_300_lines_stops_at_a_shows_most_and_only_junk_adds_nothing():
    many = "\n".join(f"Band {i} - Song {i}" for i in range(300))
    songs, left = shows.parse_pasted(many, known=lambda t: False)
    assert len(songs) == shows.contract.MAX_SHOW_SONGS and left == []
    songs, left = shows.parse_pasted("----\n...\nhello there\n", known=lambda t: False)
    assert songs == [] and left == ["----", "...", "hello there"]


# --- the run sheet's words for the grand exit sing-along -----------------------------------------------

def test_the_printed_run_sheet_says_what_the_lights_do_for_the_grand_exit_sing_along():
    from tools.gigbar_lights import run_of_show as ros
    parts = {"cocktail": [], "dinner": [], "dancing": [{"artist": "The Killers", "title": "Mr. Brightside"}]}
    steps = ros.plan(parts, {"exit-prep": {"artist": "Neil Diamond", "title": "Sweet Caroline"}})
    rows = {r["what"]: r for r in ros.sheet_rows(steps)}
    assert ros.MOMENTS["exit-prep"][1] == "party"
    assert rows["Prepare for grand exit"]["lights"] == "Full color and full energy, the derby and lasers in the big moments"
