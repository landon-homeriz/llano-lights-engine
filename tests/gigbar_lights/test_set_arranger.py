"""The set arranger (Llano PM #23177): a wedding's songs put in an order that flows, with a reason for
every spot, reviewed and moved by hand, saved as the show's order and exported to Mixxx."""
import json
import struct

import pytest

from test_shows import _call, fresh_settings, lib, window  # noqa: F401 -- shared fixtures

from tools.gigbar_lights import set_arranger as sa
from tools.gigbar_lights import settings_contract as contract
from tools.gigbar_lights import song_canon, song_folder, shows
from tools.gigbar_lights.shows import ShowSong

# His wedding folder (Avery & Jordan, 2026-11-12), as the files' tags read: part, artist, title, BPM, key
WEDDING = [
    ("cocktail", "George Strait", "Amarillo by Morning", 121, "11B"), ("cocktail", "George Strait", "Check Yes or No", 112, "7B"),
    ("cocktail", "Billy Currington", "Good Directions", 123, "7B"), ("cocktail", "Alabama", "The Closer You Get", 114, "9B"),
    ("cocktail", "Keith Whitley", "When You Say Nothing at All", 80, "5B"), ("cocktail", "Zac Brown Band", "Chicken Fried", 86, "2B"),
    ("dinner", "Lonestar", "Amazed", 71, "4B"), ("dinner", "John Michael Montgomery", "I Swear", 86, "3B"),
    ("dinner", "Cody Johnson", "Dance Her Home", 114, "9B"), ("dinner", "Randy Travis", "Forever and Ever, Amen", 90, "10B"),
    ("dinner", "Eric Church", "Springsteen", 104, "10B"), ("dinner", "Cody Johnson", "With You I Am", 75, "9B"),
    ("dancing", "DJ Casper", "Cha Cha Slide (Short Mix)", 122, "4A"), ("dancing", "Black Eyed Peas", "I Gotta Feeling", 128, "8B"),
    ("dancing", "ABBA", "Dancing Queen", 101, "11B"), ("dancing", "Kenny Loggins", "Footloose", 174, "7B"),
    ("dancing", "Justin Bieber ft. Ludacris", "Baby", 130, "5B"), ("dancing", "Justin Bieber", "Sorry", 100, "4A"),
    ("dancing", "Journey", "Don't Stop Believin'", 118, "12B"), ("dancing", "Bon Jovi", "Livin' on a Prayer", 123, "9B"),
    ("dancing", "Darius Rucker", "Wagon Wheel", 148, "11B"), ("dancing", "Brooks & Dunn", "Boot Scootin' Boogie", 130, "12B"),
    ("dancing", "Brooks & Dunn", "My Maria", 126, "5B"), ("dancing", "Cupid", "Cupid Shuffle", 144, "6A"),
    ("dancing", "Alan Jackson", "Good Time", 130, "12B"), ("dancing", "Bryan Adams", "Summer of '69", 139, "10B"),
]


def wedding():
    return [ShowSong(a, t, bpm=b, camelot=k, part=p, secs=200) for p, a, t, b, k in WEDDING]


def test_every_key_spelling_reads_as_camelot_and_steps_score_like_a_dj():
    assert [sa.camelot(k) for k in ("8A", "08a", "Am", "A minor", "Bbm", "F#", "C maj", "1m", "1d", "Dbm", "", "zz")] == \
        ["8A", "8A", "8A", "8A", "3A", "2B", "8B", "8A", "8B", "12A", "", ""]
    assert sa.key_step("8A", "9A") == 0 and sa.key_step("12B", "1B") == 0 and sa.key_step("8A", "8B") == 0
    assert sa.key_step("8A", "2B") == 1 and sa.key_step("", "8A") == 0.25
    assert sa.tempo_step(70, 140) == pytest.approx(0) and sa.tempo_step(120, 126) == pytest.approx(0.0488, abs=1e-3)


def test_the_canon_knows_every_song_in_his_wedding_folder_under_its_file_name():
    for _, a, t, _, _ in WEDDING:
        assert song_canon.lookup(a, t), (a, t)
    assert song_canon.lookup("Taylor Swift", "You Belong With Me (Taylor's Version)").year == 2008
    assert song_canon.lookup("Shenandoah ft. Luke Combs", "Two Dozen Roses")
    assert song_canon.lookup("Someone Else", "Baby") is None   # a one-word title alone is never trusted


def test_a_wedding_runs_cocktail_dinner_dancing_with_a_hype_opener_and_a_sing_along_close():
    placed = sa.arrange(wedding())
    parts = [p.slot.part for p in placed]
    assert parts == sorted(parts, key=sa.PARTS.index)          # parts stay together, in night order
    dancing = [p for p in placed if p.slot.part == "dancing"]
    opener = dancing[0]
    assert opener.facts.known == 3 and "hype" in opener.facts.tags and "line" not in opener.facts.tags
    assert all(p.facts.sing == 3 for p in dancing[-3:])
    assert sum("closer" in p.facts.tags for p in dancing[-3:]) >= 2
    for a, b in zip(placed, placed[1:]):                         # never the same act twice in a row
        assert sa._artist(a.song) != sa._artist(b.song) or a.slot.part != b.slot.part
    cocktail = [p.facts.energy for p in placed if p.slot.part == "cocktail"]
    dinner = [p.facts.energy for p in placed if p.slot.part == "dinner"]
    assert max(dinner) < min(p.facts.energy for p in dancing[-3:]) and sum(dinner) / len(dinner) < sum(cocktail) / len(cocktail)
    assert all(p.song.reason and len(p.song.reason) <= sa.REASON_CHARS for p in placed)
    assert "Opens the dancing" in opener.song.reason and "sing-along close" in dancing[-1].song.reason
    # deterministic: the same songs always give the same order
    assert [p.song.title for p in sa.arrange(wedding())] == [p.song.title for p in placed]


def test_the_couples_dances_open_the_dancing_and_the_last_dance_comes_just_before_the_final_sing_along():
    songs = wedding()
    by = {s.title: s for s in songs}
    by["Amazed"].moment, by["Dance Her Home"].moment, by["Wagon Wheel"].moment = "first-dance", "father-daughter", "last-dance"
    placed = sa.arrange(songs)
    dancing = [p.song.title for p in placed if p.slot.part == "dancing"]
    # the last dance plays just before the final sing-along, which still ends the night (his wedding)
    assert dancing[:2] == ["Amazed", "Dance Her Home"] and dancing[-2] == "Wagon Wheel"
    assert placed[-1].slot.role == "close" and placed[-1].facts.sing == 3
    assert placed[-2].song.reason == "The last dance, then one sing-along to send everyone off"
    # his night as he named it (2026-11-12): his four moment songs, the last dance before Don't Stop Believin'
    for artist, title, mom in (("Randy Travis", "Forever and Ever, Amen", "first-dance"),
                               ("Steven Curtis Chapman", "Cinderella", "father-daughter"),
                               ("Rascal Flatts", "My Wish", "mother-son"), ("Josh Turner", "Why Don't We Just Dance", "last-dance")):
        assert mom in song_canon.lookup(artist, title).tags
    order = [p.song for p in sa.arrange(wedding())]
    r = sa.discuss("make Summer of '69 the last dance", order)
    t = [x.title for x in r.songs]
    assert r.changed and t.index("Summer of '69") == len(t) - 2
    ev = sa.evaluate([p.song for p in placed])   # a saved order reopens exactly as arranged
    assert [p.song.title for p in ev] == [p.song.title for p in placed]


def test_a_slow_window_holds_the_slow_songs_together_past_the_middle_of_the_dancing():
    songs = wedding() + [ShowSong("Ed Sheeran", "Perfect", bpm=63, camelot="2B", part="dancing"),
                         ShowSong("Chris Stapleton", "Tennessee Whiskey", bpm=48, camelot="7A", part="dancing")]
    dancing = [p for p in sa.arrange(songs) if p.slot.part == "dancing"]
    at = [i for i, p in enumerate(dancing) if p.slot.role == "slow"]
    assert len(at) == 2 and at[1] == at[0] + 1 and at[0] >= len(dancing) / 2
    assert {dancing[i].song.title for i in at} == {"Perfect", "Tennessee Whiskey"}



@pytest.mark.parametrize("n_slow,n_up", [(9, 3), (11, 1), (12, 0), (14, 2), (20, 3)])
def test_a_dancing_part_of_nearly_all_slow_songs_arranges_every_song_once(n_slow, n_up):
    """Whole-app audit (2026-11-12): 12+ dancing songs with at most 3 upbeat planned one spot too
    many and Arrange the set crashed (TypeError). An untagged playlist defaults to dancing."""
    songs = ([ShowSong(f"Ballad Artist {i}", f"Ballad {i}", bpm=72) for i in range(n_slow)]
             + [ShowSong(f"Up Artist {i}", f"Up {i}", bpm=128) for i in range(n_up)])
    assert len(sa.plan_part("dancing", len(songs), "wedding", n_slow)) == len(songs)
    placed = sa.arrange(songs, "wedding")
    assert sorted(p.song.title for p in placed) == sorted(s.title for s in songs)

def test_suggestions_name_moments_and_a_missing_slow_window():
    says = [s["say"] for s in sa.suggestions(sa.arrange(wedding()))]
    assert "make Dance Her Home the father-daughter dance" in says
    assert any(s.startswith("put ") and s.endswith(" in dancing") for s in says)


def test_a_song_moved_by_hand_stays_put_and_is_explained():
    placed = sa.arrange(wedding())
    order = [p.song for p in placed]
    s = next(x for x in order if x.title == "Footloose")
    order.remove(s)
    s.pinned = True
    order.insert(len(order) - 1, s)                              # dragged to second from last
    again = [p.song.title for p in sa.arrange(order)]
    assert again.index("Footloose") == len(again) - 2
    ev = sa.evaluate(order)
    k = next(i for i, p in enumerate(ev) if p.song is s)
    assert ev[k].song.reason.startswith("You put it here")
    assert "song 25 of the show" in sa.explain(ev, k) and "You placed it" in sa.explain(ev, k)


def test_plain_words_explain_and_move():
    order = [p.song for p in sa.arrange(wedding())]
    r = sa.discuss("why is Wagon Wheel here?", order)
    assert r.answer.startswith("Wagon Wheel is song") and not r.changed
    r = sa.discuss("move Write This Down after Bye Bye", order)   # neither is in this show
    assert not r.changed
    r = sa.discuss("make Dance Her Home the father-daughter dance", order)
    assert r.changed and any(x.moment == "father-daughter" and x.title == "Dance Her Home" for x in r.songs)
    r = sa.discuss("move Footloose after Sorry", r.songs)
    t = [x.title for x in r.songs]
    assert t.index("Footloose") == t.index("Sorry") + 1


def test_part_moment_and_reason_save_with_the_show_and_older_shows_keep_their_bytes():
    songs = sa.arrange(wedding())
    saved = [p.song.saved() for p in songs]
    name, ops = shows.save_ops("Avery & Jordan", saved)
    doc = contract.normalize({"shows": {name: ops[0]["value"]}})
    got = doc["shows"][name]["songs"]
    assert [(s["part"], s["reason"]) for s in got] == [(s["part"], s["reason"]) for s in saved]
    old = {"artist": "A", "title": "B", "look": "", "why": "", "secs": 1.0, "bpm": 2.0}
    assert contract.normalize({"shows": {"x": {"title": "x", "songs": [old]}}})["shows"]["x"]["songs"] == [old]
    bad = {**old, "part": "brunch", "moment": "conga", "reason": 7}
    assert contract.normalize({"shows": {"x": {"title": "x", "songs": [bad]}}})["shows"]["x"]["songs"] == [{**old, "reason": "7"}]
    assert contract.normalize(doc) == doc   # idempotent


def test_a_full_show_with_long_reasons_still_saves_whole_by_dropping_reasons_first():
    songs = [{"artist": f"Artist number {i:02d} with a long name", "title": f"A fairly long song title number {i:02d}",
              "look": "", "why": "w" * 60, "secs": 200.0, "bpm": 120.0, "part": "dancing",
              "reason": "r" * 90} for i in range(contract.MAX_SHOW_SONGS)]
    name, ops = shows.save_ops("Big night", songs)
    assert len(ops[0]["value"]["songs"]) == contract.MAX_SHOW_SONGS


def test_pasted_headings_set_parts_and_the_mixxx_playlist_reads_by_part(lib):
    got = shows.parse_list("Cocktail Hour\nGeorge Strait - Check Yes or No\n2 - Dinner:\nLonestar - Amazed\nDancing\nABBA - Dancing Queen")
    assert [(s["title"], s.get("part")) for s in got] == [("Check Yes or No", "cocktail"), ("Amazed", "dinner"),
                                                          ("Dancing Queen", "dancing")]
    assert shows.part_from_name("1 - Cocktail Hour - Set Order") == "cocktail" and shows.part_from_name("Megan party") == ""
    songs = [ShowSong("Etta James", "At Last", track_id=2, part="dinner", secs=182),
             ShowSong("Earth, Wind & Fire", "September", track_id=1, part="dancing", moment="first-dance", secs=215)]
    text = shows.m3u(songs, lib)
    assert text.index("# --- Dinner ---") < text.index("song2.mp3") < text.index("# --- Dancing ---") \
        < text.index("# First dance") < text.index("song1.mp3")
    assert shows.tags(lib, [1, 2]) == {}    # a library without key/year columns reads as no tags, never an error


def _id3(frames: dict, version=3) -> bytes:
    body = b""
    for fid, txt in frames.items():
        data = b"\x03" + txt.encode()
        size = struct.pack(">I", len(data)) if version == 3 else bytes([(len(data) >> s) & 0x7F for s in (21, 14, 7, 0)])
        body += fid.encode() + size + b"\x00\x00" + data
    n = len(body)
    return b"ID3" + bytes([version, 0, 0]) + bytes([(n >> s) & 0x7F for s in (21, 14, 7, 0)]) + body + b"\xff\xfb" + b"\x00" * 64


def test_a_wedding_folder_reads_parts_from_subfolders_and_tempo_key_year_from_tags(tmp_path):
    for sub, name, tags in [("1 - Cocktail Hour", "George Strait - Check Yes or No.mp3", {"TBPM": "112", "TKEY": "7B", "TYER": "1995"}),
                            ("2 - Dinner", "Lonestar - Amazed.mp3", {"TBPM": "71.0", "TKEY": "Am", "TDRC": "1999-06-01"}),
                            ("3 - Dancing", "07 - ABBA - Dancing Queen.mp3", {}), ("Extra", "notes.txt", {})]:
        (tmp_path / sub).mkdir(exist_ok=True)
        (tmp_path / sub / name).write_bytes(_id3(tags, 4 if "Dinner" in sub else 3) if tags else b"not an id3 file")
    name, songs = song_folder.read_folder(str(tmp_path))
    assert [(s["artist"], s["title"], s["part"], s["bpm"], s["camelot"], s["year"]) for s in songs] == [
        ("George Strait", "Check Yes or No", "cocktail", 112.0, "7B", 1995),
        ("Lonestar", "Amazed", "dinner", 71.0, "Am", 1999),
        ("ABBA", "Dancing Queen", "dancing", 0.0, "", 0)]
    with pytest.raises(FileNotFoundError):
        song_folder.read_folder(str(tmp_path / "nope"))


def test_the_shows_page_arranges_reviews_moves_and_saves_the_order(window):
    app, url, token, tmp = window
    code, page = _call(url + "shows")
    assert code == 200 and b"Put the songs in a good order" in page and b"Save as the show's order" in page
    songs = [ShowSong(a, t, bpm=b, camelot=k, part=p, secs=200).public() for p, a, t, b, k in WEDDING]
    code, r = _call(url + "api/shows-arrange", {"songs": songs, "event": "wedding"}, token)
    assert code == 200 and set(r["curves"]) == {"cocktail", "dinner", "dancing"}
    assert all(s["reason"] for s in r["songs"]) and len(r["roles"]) == len(songs) and r["suggestions"]
    moved = r["songs"]
    s = moved.pop(next(i for i, x in enumerate(moved) if x["title"] == "Footloose"))
    moved.insert(len(moved) - 1, {**s, "pinned": True})          # what a drag sends
    code, ev = _call(url + "api/shows-evaluate", {"songs": moved, "event": "wedding"}, token)
    assert code == 200 and ev["songs"][-2]["title"] == "Footloose" and ev["songs"][-2]["reason"].startswith("You put it here")
    code, ask = _call(url + "api/shows-ask", {"songs": ev["songs"], "text": "why is song 1 here"}, token)
    assert code == 200 and ask["answer"].startswith(ev["songs"][0]["title"]) and not ask["changed"]
    assert _call(url + "api/shows-arrange", {"songs": []}, token)[0] == 400
    code, saved = _call(url + "api/shows-save", {"title": "Avery & Jordan", "songs": ev["songs"]}, token)
    assert code == 200
    kept = json.loads((tmp / "settings.json").read_text())["shows"][saved["name"]]["songs"]
    assert [x["title"] for x in kept] == [x["title"] for x in ev["songs"]] and kept[0]["part"] == "cocktail"
    _, opened = _call(url + "api/shows-open", {"name": saved["name"]}, token)
    assert opened["songs"][-2]["reason"].startswith("You put it here") and opened["songs"][0]["part"] == "cocktail"
    code, m = _call(url + "api/shows-mixxx-playlist", {"songs": ev["songs"], "title": "Avery & Jordan"}, token)
    assert code == 200
    from pathlib import Path
    text = Path(m["path"]).read_text(encoding="utf-8")
    assert text.index("# --- Cocktail hour ---") < text.index("# --- Dinner ---") < text.index("# --- Dancing ---")
