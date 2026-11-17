"""A loaded compilation is always fully filled (Llano BL #11473).

He loaded every song of his latest wedding compilation and the show had blank spots: all 70 songs had
length 0 (lengths only ever came from Mixxx, and his songs were not in Mixxx yet), a Moments-folder song
the app did not know was left out with only its name said, a second song for one dance was lost the same
way, a song whose folder named no part went in with none, and Save pressed while the songs were still
being read stored blank looks. Opening the show never filled them, and adding the folder again said
"No new songs" and repaired nothing.

Now: every song the folder holds is in the show; every song has a look; every song has a part of the
night or a moment, or is on the needs-you list; every song whose file is here has its real length; and
nothing is ever dropped without a line telling him. These tests drive the same server door the Shows
page uses (/api/shows-folder, -fill, -save, -open, -needs), and the page itself in a headless browser.
"""
import json
import struct
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.gigbar_lights.test_shows import _call, lib, window  # noqa: E402,F401
from tools.gigbar_lights import settings_contract as contract  # noqa: E402
from tools.gigbar_lights import shows, song_folder  # noqa: E402

FRAME = b"\xff\xfb\x90\x00" + b"\0" * 413      # one MPEG-1 Layer III frame, 128 kbps, 44.1 kHz: 1152 samples


def _id3(bpm: float = 0.0) -> bytes:
    frames = b""
    if bpm:
        body = b"\x00" + str(int(bpm)).encode()
        frames += b"TBPM" + struct.pack(">I", len(body)) + b"\x00\x00" + body
    size = len(frames)
    syncsafe = bytes([(size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F])
    return b"ID3\x03\x00\x00" + syncsafe + frames


def _mp3(path: Path, secs: float, bpm: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_id3(bpm) + FRAME * round(secs * 44100 / 1152))


def _compilation(tmp: Path) -> Path:
    """His folder's shape: numbered parts, a Moments folder with a known dance, an unknown song and two
    songs for one dance, a folder that names no part, a file with no tempo tag and one that is broken."""
    root = tmp / "C and M Wedding"
    _mp3(root / "1 - Cocktail Hour" / "George Strait - Check Yes or No.mp3", 30, 121)
    _mp3(root / "2 - Dinner" / "Norah Jones - Come Away With Me.mp3", 40, 85)
    _mp3(root / "3 - Dancing" / "Journey - Faithfully.mp3", 50, 130)
    _mp3(root / "3 - Dancing" / "Quiet Band - No Tempo Here.mp3", 20)          # no TBPM tag: tempo 0
    (root / "3 - Dancing" / "Bad Rip - Broken.mp3").write_bytes(b"not audio")  # opens, no length in it
    _mp3(root / "4 - Moments" / "Steven Curtis Chapman - Cinderella.mp3", 25, 70)   # father-daughter
    _mp3(root / "4 - Moments" / "Lonestar - Amazed.mp3", 26, 70)                    # first dance
    _mp3(root / "4 - Moments" / "Luke Combs - Beautiful Crazy.mp3", 27, 70)         # a second first dance
    _mp3(root / "4 - Moments" / "Zz Nobody - Our Own Song.mp3", 28, 90)             # no moment known
    _mp3(root / "Extra Songs" / "Owl City - Fireflies.mp3", 22, 90)                 # its folder names no part
    return root


FILES = 10
EXPECTED_NEEDS = [
    ("part", "Fireflies by Owl City has no part of the night: pick its part in its row."),
    ("hold", "Grand entrance has no song: pick one in step 2, or untick it."),
    ("hold", "Mother-groom dance has no song: pick one in step 2, or untick it."),
    ("hold", "Prepare for grand exit has no song: pick one in step 2, or untick it."),
    ("hold", "Bride and groom exit has no song: pick one in step 2, or untick it."),
    ("unplaced", "Beautiful Crazy by Luke Combs is in the Moments folder but no moment is known for it: pick its moment in step 2. Until you do, it plays with the dancing songs."),
    ("unplaced", "Our Own Song by Zz Nobody is in the Moments folder but no moment is known for it: pick its moment in step 2. "
                 "Until you do, it plays with the dancing songs."),
    ("length", "Broken by Bad Rip: its length could not be read, so the night's minutes do not count it. It still plays."),
]


def _blank(s: dict) -> bool:
    return not s.get("look") and s.get("why") != "your pick"


def _add(url, token, root, have=None):
    """What the page does on Add these songs: read the folder, put its songs in, fill the whole show."""
    code, r = _call(url + "api/shows-folder", {"path": str(root), "have": have or []}, token)
    assert code == 200, r
    return r


def _fill(url, token, songs, root=None, moments=None, unplaced=None):
    code, r = _call(url + "api/shows-fill", {"songs": songs, "folder": str(root) if root else "",
                                              "moments": moments, "unplaced": unplaced or []}, token)
    assert code == 200, r
    return r


# --- lengths from the file ---------------------------------------------------------------------------

def test_a_songs_length_is_read_from_its_own_file(tmp_path):
    _mp3(tmp_path / "a.mp3", 60, 120)
    assert song_folder.audio_length(tmp_path / "a.mp3") == (pytest.approx(60, abs=0.2), "")
    (tmp_path / "empty.mp3").write_bytes(b"")
    assert song_folder.audio_length(tmp_path / "empty.mp3") == (0.0, "unreadable")
    assert song_folder.audio_length(tmp_path / "gone.mp3") == (0.0, "unreadable")
    (tmp_path / "junk.mp3").write_bytes(b"junk")
    assert song_folder.audio_length(tmp_path / "junk.mp3") == (0.0, "no-length")
    import wave
    with wave.open(str(tmp_path / "w.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * 8000 * 3)
    assert song_folder.audio_length(tmp_path / "w.wav") == (3.0, "")
    # a real song: the demo mp3s know their own length
    from tools.gigbar_lights import demo_songs
    d = demo_songs.load()[0]
    assert song_folder.audio_length(d.path)[0] == pytest.approx(d.duration_s, abs=0.5)


def test_every_song_of_the_folder_has_its_real_length(tmp_path):
    _name, found = song_folder.read_folder(str(_compilation(tmp_path)))
    by = {s["title"]: s for s in found}
    assert len(found) == FILES
    assert by["Faithfully"]["secs"] == pytest.approx(50, abs=0.2) and by["Faithfully"]["trouble"] == ""
    assert by["No Tempo Here"]["secs"] == pytest.approx(20, abs=0.2) and by["No Tempo Here"]["bpm"] == 0
    assert by["Broken"]["secs"] == 0 and by["Broken"]["trouble"] == "no-length"


# --- the whole flow, through the page's own server door ----------------------------------------------

def test_a_loaded_compilation_is_always_fully_filled(window):  # noqa: F811
    app, url, token, tmp = window
    root = _compilation(tmp)
    r = _add(url, token, root)
    # every file is in the show: the unknown Moments song and the second first dance too
    assert len(r["songs"]) == FILES and r["left_out"] == 0
    assert sorted(r["unplaced"]) == ["Luke Combs - Beautiful Crazy", "Zz Nobody - Our Own Song"]
    by = {s["title"]: s for s in r["songs"]}
    assert by["Our Own Song"]["part"] == "dancing" and by["Our Own Song"]["moment"] == ""
    assert by["Beautiful Crazy"]["part"] == "dancing" and by["Beautiful Crazy"]["moment"] == ""
    assert by["Amazed"]["moment"] == "first-dance" and by["Cinderella"]["moment"] == "father-daughter"
    assert by["Fireflies"]["part"] == "" and by["Broken"]["trouble"] == "no-length"
    assert all(s["secs"] > 0 for s in r["songs"] if s["title"] != "Broken")

    # a Save pressed before a single song was read or designed stores no blank look
    fresh = r["songs"]
    assert all(_blank(s) for s in fresh)
    code, saved = _call(url + "api/shows-save", {"title": "C and M Wedding", "songs": fresh}, token)
    assert code == 200 and saved["fixed"] == FILES
    kept = shows.saved_shows()[saved["name"]]["songs"]
    assert len(kept) == FILES and not [s["title"] for s in kept if _blank(s)]
    assert {s["title"]: s["secs"] for s in kept}["Faithfully"] == pytest.approx(50, abs=0.2)
    # the song with no tempo tag still has its look and its Dancing tag
    nt = next(s for s in kept if s["title"] == "No Tempo Here")
    assert nt["look"] in contract.BUILTIN_LOOKS and nt["tag"] in shows.ENERGY_TAGS

    # the page fills right after adding: no blank look, and the needs-you list holds exactly these lines
    f = _fill(url, token, fresh, root, moments={}, unplaced=r["unplaced"])
    assert not [s["title"] for s in f["songs"] if _blank(s)]
    assert [(n["kind"], n["text"]) for n in f["needs"]] == EXPECTED_NEEDS
    # picking the unplaced songs' moments in step 2, and the missing dances' songs, empties those lines
    picked = {"entrance": {"on": True, "song": "Zz Nobody - Our Own Song"},
              "mother-son": {"on": True, "song": "Luke Combs - Beautiful Crazy"},
              "exit-prep": {"on": False, "song": ""}, "exit": {"on": False, "song": ""}}
    code, n = _call(url + "api/shows-needs", {"songs": f["songs"], "moments": picked, "unplaced": r["unplaced"]}, token)
    assert code == 200 and [x["kind"] for x in n["needs"]] == ["part", "length"]

    # his old show: saved before songs kept a part, a look or a length
    old = [{**s, "part": "", "moment": "", "look": "", "why": "", "secs": 0.0, "tag": ""} for s in kept]
    app.link.local_change([{"path": "shows.old-show", "value": {"title": "Old show", "note": "", "looks": {}, "songs": old}}])
    # opening it returns it filled, with every length its folder holds
    code, opened = _call(url + "api/shows-open", {"name": "old-show", "folder": str(root)}, token)
    assert code == 200
    assert not [s["title"] for s in opened["songs"] if _blank(s)]
    assert opened["lengths"] == FILES - 1 and opened["fixed"] == FILES
    ob = {s["title"]: s for s in opened["songs"]}
    assert ob["Check Yes or No"]["part"] == "cocktail" and ob["Cinderella"]["moment"] == "father-daughter"
    assert ob["Our Own Song"]["part"] == "dancing" and ob["Fireflies"]["part"] == ""
    assert ob["Faithfully"]["secs"] == pytest.approx(50, abs=0.2)
    assert [x["kind"] for x in opened["needs"]] == ["part", "length"]

    # adding the folder again repairs a show and says how many songs were fixed
    have = [{"artist": s["artist"], "title": s["title"], "part": "", "moment": ""} for s in old]
    again = _add(url, token, root, have)
    placed = {p["i"] for p in again["placed"]}
    assert len(placed) == FILES - 1      # every song but Fireflies takes its folder's part
    repaired = _fill(url, token, old, root)
    assert repaired["fixed"] == FILES and repaired["lengths"] == FILES - 1


def test_the_same_song_in_two_folders_is_in_the_show_once_and_said(window):  # noqa: F811
    _app, url, token, tmp = window
    root = tmp / "Two"
    _mp3(root / "1 - Cocktail Hour" / "Journey - Faithfully.mp3", 30, 120)
    _mp3(root / "3 - Dancing" / "Journey - Faithfully.mp3", 30, 120)
    r = _add(url, token, root)
    assert [s["part"] for s in r["songs"]] == ["cocktail"]
    assert r["twins"] == ["Faithfully by Journey is in two folders, so it is in the show once, in Cocktail hour. "
                          "If it belongs elsewhere, pick its part in its row."]


# --- try to break it ---------------------------------------------------------------------------------

def test_an_empty_folder_says_so(window):  # noqa: F811
    _app, url, token, tmp = window
    (tmp / "Empty").mkdir()
    code, r = _call(url + "api/shows-folder", {"path": str(tmp / "Empty")}, token)
    assert code == 400 and "no songs in that folder" in r["error"]


def test_a_folder_of_only_unknown_songs_is_all_in_and_all_listed(window):  # noqa: F811
    _app, url, token, tmp = window
    root = tmp / "Party Mix"
    for i in range(3):
        _mp3(root / f"Nobody {i} - Unknown {i}.mp3", 20)
    for i in range(2):
        _mp3(root / "Moments" / f"Stranger {i} - Mystery {i}.mp3", 20)
    r = _add(url, token, root)
    assert len(r["songs"]) == 5 and len(r["unplaced"]) == 2
    f = _fill(url, token, r["songs"], root, unplaced=r["unplaced"])
    assert not [s for s in f["songs"] if _blank(s)]
    assert [n["kind"] for n in f["needs"]] == ["part"] * 3 + ["unplaced"] * 2


def test_121_songs_keep_120_and_say_one_was_left_out(window):  # noqa: F811
    _app, url, token, tmp = window
    root = tmp / "Big"
    for i in range(121):
        _mp3(root / "3 - Dancing" / f"Band {i:03d} - Song {i:03d}.mp3", 2)
    r = _add(url, token, root)
    assert len(r["songs"]) == contract.MAX_SHOW_SONGS and r["left_out"] == 1
    f = _fill(url, token, r["songs"], root)
    assert not [s for s in f["songs"] if _blank(s)] and f["needs"] == []
    code, saved = _call(url + "api/shows-save", {"title": "Big", "songs": f["songs"]}, token)
    assert code == 200


def test_a_file_deleted_between_add_and_save(window):  # noqa: F811
    _app, url, token, tmp = window
    root = _compilation(tmp)
    r = _add(url, token, root)
    (root / "3 - Dancing" / "Journey - Faithfully.mp3").unlink()
    code, saved = _call(url + "api/shows-save", {"title": "Gone", "songs": r["songs"]}, token)
    assert code == 200
    # its length was read when it came in, so it stays; a song with no length and no file is said
    songs = [{**s, "secs": 0.0} if s["title"] == "Faithfully" else s for s in r["songs"]]
    f = _fill(url, token, songs, root)
    assert ("nofile", "Faithfully by Journey: its length is not known yet. Add its folder in step 1 and it is read "
                      "from the file.") in [(n["kind"], n["text"]) for n in f["needs"]]


def test_two_saves_at_once_store_one_whole_show(window):  # noqa: F811
    _app, url, token, tmp = window
    r = _add(url, token, _compilation(tmp))
    out = []
    ts = [threading.Thread(target=lambda: out.append(_call(url + "api/shows-save", {"title": "Twice", "songs": r["songs"]}, token)))
          for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert [c for c, _ in out] == [200, 200]
    assert list(shows.saved_shows()) == ["twice"]
    assert not [s for s in shows.saved_shows()["twice"]["songs"] if _blank(s)]


def test_a_house_show_pick_is_his_and_kept():
    s = [shows.ShowSong("A", "B", look="", why="your pick", part="dancing"), shows.ShowSong("C", "D", part="dinner")]
    done = shows.fill(s)
    assert s[0].look == "" and s[0].why == "your pick" and s[1].look == "warm-up" and done["fixed"] == 1


# --- the page ------------------------------------------------------------------------------------------

def test_the_review_panel_lists_what_he_must_settle_and_repairs_on_adding_again(window):  # noqa: F811
    pw = pytest.importorskip("playwright.sync_api")
    _app, url, _token, tmp = window
    root = _compilation(tmp)
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            page = browser.new_page()
            page.goto(url + "shows")
            page.wait_for_selector("#save")
            page.fill("#title", "C and M Wedding")
            page.fill("#folder", str(root))
            page.click("#addfolder")
            page.wait_for_function(f"document.querySelectorAll('#songs select[data-part]').length === {FILES}", timeout=10000)
            # no song ever waits with a blank look, even while the songs are being read
            assert page.evaluate("() => show.songs.filter(s => !s.look && s.why !== 'your pick').length") == 0
            page.wait_for_function("!document.querySelector('#design').disabled", timeout=30000)
            page.wait_for_function("document.querySelector('#nopart li[data-kind=unplaced]')", timeout=5000)
            lines = page.eval_on_selector_all("#nopart li", "els => els.map(e => [e.dataset.kind, e.innerText])")
            assert [k for k, _ in lines] == [k for k, _ in EXPECTED_NEEDS]
            assert page.is_visible("#sortparts")
            # the panel is the first thing in Review
            first = page.evaluate("() => document.querySelector('#h-step-5').nextElementSibling.id")
            assert first == "nopart"
            # blank the show the way his old one was saved, then add the same folder again
            page.evaluate("() => { for (const s of show.songs) { s.part = ''; s.moment = ''; s.look = ''; s.why = ''; s.secs = 0; } renderAll(); }")
            page.click("#addfolder")
            page.wait_for_function("document.querySelector('#msg').innerText.includes('No new songs. Fixed')", timeout=10000)
            msg = page.inner_text("#msg")
            assert f"Fixed {FILES} songs that were missing a part of the night or a look." in msg, msg
            assert f"Read the length of {FILES - 1} songs from their files." in msg, msg
            assert page.evaluate("() => show.songs.filter(s => !s.look && s.why !== 'your pick').length") == 0
            # settle everything: the green line
            page.evaluate("""() => { for (const s of show.songs) { if (!s.part && !s.moment) s.part = 'dancing';
                                       if (!s.secs) s.secs = 200; s.trouble = ''; } N.unplaced = []; renderAll(); }""")
            for key in ("entrance", "mother-son", "exit-prep", "exit"):
                page.uncheck(f"#nm-on-{key}")
            page.wait_for_function("document.querySelector('#nopart').innerText.includes('Every song has its part, its lights and its length.')", timeout=5000)
            assert page.locator("#nopart li").count() == 0
        finally:
            browser.close()


def test_the_page_copy_uses_no_dash_as_punctuation():
    page = (Path(__file__).resolve().parents[2] / "tools/gigbar_lights/windows/src/shows.html").read_text(encoding="utf-8")
    for line in ("Every song has its part, its lights and its length.", "missing a part of the night or a look."):
        assert line in page
    texts = [n["text"] for n in shows.needs([shows.ShowSong("A", "B", trouble="unreadable")], {}, ["X - Y"])]
    assert texts and not [t for t in texts if " - " in t or "–" in t or "—" in t]
    assert json.dumps(texts)   # plain strings, ready for the page


# --- the lead's review (PR 142) ----------------------------------------------------------------------

def _his_shape() -> list:
    """The shape of his saved show that the first fill broke: Dancing songs with a sing-along look and no tag."""
    return [shows.ShowSong("Neil Diamond", "Sweet Caroline", look="sing-along", why="the last song of the night",
                           part="dancing", bpm=128),
            shows.ShowSong("Journey", "Don't Stop Believin'", look="sing-along", why="a big sing-along",
                           part="dancing", bpm=119),
            shows.ShowSong("Clint Black", "Killin_ Time", look="warm-up", why="", part="cocktail"),
            shows.ShowSong("Owl City", "Fireflies", part="dancing", bpm=90)]          # filed under his style


def test_fill_never_changes_a_look_a_song_already_has():
    songs = _his_shape()
    before = [(s.look, s.why) for s in songs[:3]]
    done = shows.fill(songs, filed={contract.track_key("Owl City", "Fireflies"): "my-style"}, styles={"my-style": {}})
    assert [(s.look, s.why) for s in songs[:3]] == before        # looks and whys untouched, an empty why too
    assert songs[0].tag in shows.ENERGY_TAGS and songs[1].tag in shows.ENERGY_TAGS   # a tag where there was none
    assert songs[3].look == "my-style" and songs[3].tag in shows.ENERGY_TAGS       # his style stays its look
    assert done["fixed"] == 1


def test_fill_twice_changes_nothing():
    songs = _his_shape()
    shows.fill(songs)
    once = [s.public() for s in songs]
    done = shows.fill(songs)
    assert [s.public() for s in songs] == once and done["fixed"] == 0 and done["lengths"] == 0


def test_songs_named_with_no_latin_letters_stay_three_songs(window):  # noqa: F811
    _app, url, token, tmp = window
    root = tmp / "Mix"
    for name, secs in (("가수 - 노래", 21), ("Певец - Песня", 32), ("Исполнитель - Другая", 43)):
        _mp3(root / "3 - Dancing" / f"{name}.mp3", secs, 120)
    r = _add(url, token, root)
    assert r["twins"] == [] and len(r["songs"]) == 3
    assert sorted(round(s["secs"]) for s in r["songs"]) == [21, 32, 43]
    f = _fill(url, token, [{**s, "secs": 0} for s in r["songs"]], root)
    assert sorted(round(s["secs"]) for s in f["songs"]) == [21, 32, 43]   # each its own file's length
    assert shows.song_key("", "노래") != shows.song_key("", "Песня") and shows.song_key("", "") == ""
    # a library song with such a name is never the match for another one
    assert shows.LibraryIndex(None).find("가수", "노래") is None


def test_opening_never_fails_on_its_folder(window, monkeypatch):  # noqa: F811
    app, url, token, tmp = window
    root = _compilation(tmp)
    r = _add(url, token, root)
    code, saved = _call(url + "api/shows-save", {"title": "Opens", "songs": r["songs"]}, token)
    assert code == 200

    def boom(*a, **k):
        raise ValueError("one file no reader expected")
    monkeypatch.setattr(song_folder, "read_folder_all", boom)
    code, opened = _call(url + "api/shows-open", {"name": saved["name"], "folder": str(root)}, token)
    assert code == 200 and len(opened["songs"]) == FILES


def test_the_page_opens_a_show_only_with_its_own_folder():
    page = (Path(__file__).resolve().parents[2] / "tools/gigbar_lights/windows/src/shows.html").read_text(encoding="utf-8")
    assert 'api("open", {name, folder: kept.folder || "",' in page and '$("#folder").value), moments' not in page


def test_an_unplaced_line_goes_when_its_song_leaves_the_show():
    songs = [shows.ShowSong("Zz Nobody", "Our Own Song", part="dancing", secs=200)]
    assert [n["kind"] for n in shows.needs(songs, None, ["Zz Nobody - Our Own Song"])] == ["unplaced"]
    assert shows.needs([], None, ["Zz Nobody - Our Own Song"]) == []
    assert shows.needs([shows.ShowSong("A", "B", part="dinner", secs=10)], None, ["Zz Nobody - Our Own Song"]) == []


def test_adding_the_folder_again_never_undoes_a_part_he_chose(window):  # noqa: F811
    _app, url, token, tmp = window
    root = _compilation(tmp)
    have = [{"artist": "Norah Jones", "title": "Come Away With Me", "part": "dancing", "moment": "", "secs": 40},   # he moved it
            {"artist": "George Strait", "title": "Check Yes or No", "part": "", "moment": "", "secs": 0}]
    r = _add(url, token, root, have)
    assert r["placed"] == [{"i": 1, "part": "cocktail", "moment": ""}]
    assert r["lengths"] == [{"i": 1, "secs": pytest.approx(30, abs=0.2), "trouble": ""}]   # read in this same pass


def test_the_length_lines_say_what_is_true():
    long = shows.ShowSong("A", "Long Mix", part="dancing", trouble="too-long")
    raw = shows.ShowSong("B", "Raw", part="dancing", trouble="no-length")
    assert [n["text"] for n in shows.needs([long, raw])] == [
        "Long Mix by A is longer than an hour, which a show cannot hold: use a shorter file.",
        "Raw by B: its length could not be read, so the night's minutes do not count it. It still plays."]
    few = [shows.ShowSong("A", f"S{i}", part="dinner") for i in range(3)]
    assert len(shows.needs(few)) == 3
    many = [shows.ShowSong("A", f"S{i}", part="dinner") for i in range(9)]
    assert [n["text"] for n in shows.needs(many)] == ["9 songs have no length yet: add their folder in step 1 and each is read from its file."]


# --- every reader, with built headers ------------------------------------------------------------------

def _syncsafe(n: int) -> bytes:
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


def test_an_mp3_with_a_xing_frame_count(tmp_path):
    side = 32
    xing = b"\xff\xfb\x90\x00" + b"\0" * side + b"Xing" + struct.pack(">I", 1) + struct.pack(">I", 7000)
    first = xing + b"\0" * (417 - len(xing))
    (tmp_path / "v.mp3").write_bytes(first + FRAME * 20)            # 20 frames on disk, 7000 said: VBR
    assert song_folder.audio_length(tmp_path / "v.mp3") == (pytest.approx(7000 * 1152 / 44100, abs=0.01), "")


def test_an_mp3_with_a_vbri_frame_count(tmp_path):
    vbri = b"\xff\xfb\x90\x00" + b"\0" * 32 + b"VBRI" + b"\0" * 10 + struct.pack(">I", 5000)
    first = vbri + b"\0" * (417 - len(vbri))
    (tmp_path / "v.mp3").write_bytes(first + FRAME * 20)
    assert song_folder.audio_length(tmp_path / "v.mp3")[0] == pytest.approx(5000 * 1152 / 44100, abs=0.01)


def test_an_mpeg2_mp3(tmp_path, monkeypatch):
    # MPEG-2 Layer III, 64 kbps, 22.05 kHz: 72 * 64000 / 22050 = 208 bytes a frame, 576 samples. The header
    # reader alone (soundfile, where it is installed, decodes the real 26.12 s instead)
    monkeypatch.setattr(song_folder, "_soundfile_secs", lambda p: 0.0)
    frame = b"\xff\xf3\x80\x00" + b"\0" * 204
    (tmp_path / "m2.mp3").write_bytes(frame * 1000)
    assert song_folder.audio_length(tmp_path / "m2.mp3")[0] == pytest.approx(1000 * 208 * 8 / 64000, abs=0.05)


def test_an_id3_tag_with_a_footer_is_skipped_whole(tmp_path, monkeypatch):
    monkeypatch.setattr(song_folder, "_soundfile_secs", lambda p: 0.0)   # the header reader alone
    body = b"\0" * 20
    tag = b"ID3\x04\x00\x10" + _syncsafe(len(body)) + body + b"3DI\x04\x00\x10" + _syncsafe(len(body))
    (tmp_path / "f.mp3").write_bytes(tag + FRAME * 500)
    assert song_folder.audio_length(tmp_path / "f.mp3")[0] == pytest.approx(500 * 1152 / 44100, abs=0.1)


def test_a_false_sync_in_cover_art_is_not_a_frame(tmp_path, monkeypatch):
    monkeypatch.setattr(song_folder, "_soundfile_secs", lambda p: 0.0)   # the header reader alone
    junk = b"\xff\xfb\x90\x00" + b"\x01" * 100           # looks like a header, no second frame where it ends
    (tmp_path / "c.mp3").write_bytes(junk + FRAME * 300)
    assert song_folder.audio_length(tmp_path / "c.mp3")[0] == pytest.approx(300 * 1152 / 44100, abs=0.15)


def test_with_no_frame_count_soundfile_is_asked_before_the_size_estimate(tmp_path, monkeypatch):
    (tmp_path / "cbr.mp3").write_bytes(FRAME * 1000)
    monkeypatch.setattr(song_folder, "_soundfile_secs", lambda p: 99.5)
    assert song_folder.audio_length(tmp_path / "cbr.mp3") == (99.5, "")
    monkeypatch.setattr(song_folder, "_soundfile_secs", lambda p: 0.0)   # not here, or it failed
    assert song_folder.audio_length(tmp_path / "cbr.mp3")[0] == pytest.approx(1000 * 1152 / 44100, abs=0.1)


def test_a_flac_stream_info(tmp_path):
    rate, total = 44100, 44100 * 75
    info = bytearray(34)
    info[10], info[11], info[12] = rate >> 12 & 0xFF, rate >> 4 & 0xFF, (rate & 0xF) << 4 | 0x02
    info[13] = 0x70 | (total >> 32 & 0x0F)
    info[14:18] = struct.pack(">I", total & 0xFFFFFFFF)
    (tmp_path / "a.flac").write_bytes(b"fLaC" + b"\x80\x00\x00\x22" + bytes(info) + b"\0" * 64)
    assert song_folder.audio_length(tmp_path / "a.flac") == (75.0, "")


def _box(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", 8 + len(body)) + kind + body


def test_an_m4a_movie_header_version_0_and_1(tmp_path):
    v0 = _box(b"mvhd", b"\x00\x00\x00\x00" + b"\0" * 8 + struct.pack(">II", 1000, 183_500) + b"\0" * 80)
    (tmp_path / "a.m4a").write_bytes(_box(b"ftyp", b"M4A \0\0\0\0") + _box(b"moov", v0))
    assert song_folder.audio_length(tmp_path / "a.m4a") == (183.5, "")
    v1 = _box(b"mvhd", b"\x01\x00\x00\x00" + b"\0" * 16 + struct.pack(">IQ", 48000, 48000 * 200) + b"\0" * 80)
    (tmp_path / "b.m4a").write_bytes(_box(b"ftyp", b"M4A \0\0\0\0") + _box(b"free", b"\0" * 30) + _box(b"moov", v1))
    assert song_folder.audio_length(tmp_path / "b.m4a") == (200.0, "")


def test_a_file_over_an_hour_is_too_long_not_broken(tmp_path, monkeypatch):
    monkeypatch.setattr(song_folder, "_soundfile_secs", lambda p: 0.0)   # the header reader alone
    (tmp_path / "long.mp3").write_bytes(FRAME * round(3700 * 44100 / 1152))
    assert song_folder.audio_length(tmp_path / "long.mp3") == (0.0, "too-long")


# --- the page's races ------------------------------------------------------------------------------------

def test_one_add_at_a_time_and_a_failed_check_is_never_the_green_line(window):  # noqa: F811
    pw = pytest.importorskip("playwright.sync_api")
    _app, url, _token, tmp = window
    root = _compilation(tmp)
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            page = browser.new_page()
            reads = []
            page.on("request", lambda r: reads.append(r.url) if r.url.endswith("/api/shows-folder") else None)
            page.goto(url + "shows")
            page.wait_for_selector("#save")
            page.fill("#folder", str(root))
            page.evaluate("() => { document.querySelector('#addfolder').click(); document.querySelector('#addfolder').click(); }")
            page.wait_for_function(f"document.querySelectorAll('#songs select[data-part]').length === {FILES}", timeout=10000)
            assert len(reads) == 1
            # the notices are said as the songs come in, before they are read
            assert "in the show with no moment yet" in page.inner_text("#msg")
            page.wait_for_function("!document.querySelector('#design').disabled", timeout=30000)
            # the needs check fails: the panel says so, never the green line
            page.route("**/api/shows-needs", lambda route: route.fulfill(status=500, body="{}"))
            page.evaluate("() => { show.songs[0].part = 'dinner'; renderAll(); }")
            page.wait_for_function("document.querySelector('#nopart li[data-kind=error]')", timeout=5000)
            assert page.inner_text("#nopart") == "Could not check the show: press Save show to check again."
            page.unroute("**/api/shows-needs")
            # a re-add that fixes nothing leaves the show as saved as it was
            page.evaluate("() => { dirty = false; }")
            page.click("#addfolder")
            page.wait_for_function("document.querySelector('#msg').innerText.includes('No new songs')", timeout=10000)
            assert page.evaluate("() => dirty") is False
        finally:
            browser.close()
