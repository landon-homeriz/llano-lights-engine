"""Tonight lists the saved show's night before it is built (Llano BL #12387).

The report, 2026-11-15: the order of events and the newly added songs
were not showing up in the app. Llano had set AJ Wedding's parts of the night, its
dances and its play order, and added two songs (Old Dance Floor_Mix 1 in Cocktail hour, Right for You
in Dinner). The laptop had all of it, but the Live screen's Tonight list read only a night built on
the laptop, so it said "No night is built yet" and stepped the usual wedding order.
"""
import argparse
import json
import sys
from pathlib import Path

from tools.gigbar_lights import run_of_show as ros
from tools.gigbar_lights import settings_contract as contract
from tools.gigbar_lights import show_settings, song_match, studio, tonight, wedding_night


def song(artist, title, part, moment=""):
    return {"artist": artist, "title": title, "part": part, "look": "warm-up", "secs": 200.0, "bpm": 100.0,
            **({"moment": moment} if moment else {})}


AJ = [song("George Strait", "Here for a Good Time", "cocktail"),
      song("", "Old Dance Floor_Mix 1", "cocktail"),                  # added Friday (BL #12363)
      song("Eric Church", "Springsteen", "dinner"),
      song("", "Right for You", "dinner"),                            # added Friday (BL #12363)
      song("Randy Travis", "Forever and Ever, Amen", "dancing", "first-dance"),
      song("Steven Curtis Chapman", "Cinderella", "dancing", "father-daughter"),
      song("Rascal Flatts", "My Wish", "dancing", "mother-son"),
      song("Black Eyed Peas", "I Gotta Feeling", "dancing"),
      song("Journey", "Don't Stop Believin'", "dancing")]


def doc_with(songs, title="AJ Wedding", name="aj-wedding", extra=None):
    shows = {name: {"title": title, "note": "", "looks": {}, "songs": songs}, **(extra or {})}
    return contract.normalize({"shows": shows})


def step_of(night, artist, title):
    want = set(song_match.candidates(artist, title))
    return [s["name"] for s in night.steps if s["keys"] & want]


def test_with_no_night_built_the_list_is_the_shows_own_night_in_his_order(tmp_path):
    night = tonight.Tonight.load(tmp_path, doc=doc_with(AJ))
    pub = night.public()
    assert pub["source"] == "show" and pub["show"] == "aj-wedding" and pub["title"] == "AJ Wedding"
    assert night.follows, "the show's songs move the night along as Mixxx plays them"
    names = [s["name"] for s in night.steps]
    assert names[:3] == ["Cocktail hour", "Grand entrance", "Dinner"]
    assert names.index("First dance: Forever and Ever, Amen") < names.index("Father-daughter dance: Cinderella") \
        < names.index("Mother-groom dance: My Wish") < names.index("Dancing")
    assert step_of(night, "", "Old Dance Floor_Mix 1") == ["Cocktail hour"]
    assert step_of(night, "", "Right for You")[0] == "Dinner"
    assert "AJ Wedding" in pub["note"] and "Build the night" in pub["note"]
    assert "No night is built yet" not in pub["note"]


def test_the_shows_night_is_the_same_order_the_build_makes():
    """from_show and build place songs through the one wedding_night.arrange: same steps."""
    night = tonight.Tonight.from_show("aj-wedding", doc_with(AJ)["shows"]["aj-wedding"])
    a = wedding_night.arrange(doc_with(AJ)["shows"]["aj-wedding"]["songs"], skip=set(ros.OPTIONAL) | {"close"})
    planned = ros.plan(a["parts"], a["moment_songs"], skip=a["off"])
    assert [s["name"] for s in night.steps] == [s.name for s in planned]


def test_a_song_with_no_part_is_left_out_of_the_list_not_an_error(tmp_path):
    night = tonight.Tonight.load(tmp_path, doc=doc_with(AJ + [song("Nobody", "Unplaced", "")]))
    assert night.source == "show" and not step_of(night, "Nobody", "Unplaced")


def built_report(songs):
    a = wedding_night.arrange(songs, skip=set(ros.OPTIONAL) | {"close"})
    steps = ros.plan(a["parts"], a["moment_songs"], skip=a["off"])
    return {"title": "AJ Wedding", "built": "2026-11-14 18:00", "steps": [s.public() for s in steps],
            "missing": [], "damaged": [], "silent": []}


def write_night(root, report):
    folder = root / "aj-wedding-night"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "night.json").write_text(json.dumps(report), encoding="utf-8")


def test_a_built_night_that_has_every_song_where_the_show_puts_it_wins(tmp_path):
    write_night(tmp_path, built_report(AJ))
    night = tonight.Tonight.load(tmp_path, doc=doc_with(AJ))
    assert night.source == "built" and night.built and night.note == ""


def test_songs_added_after_the_build_bring_the_shows_order_back(tmp_path):
    write_night(tmp_path, built_report(AJ[:1] + AJ[2:3] + AJ[4:]))    # built before the two songs came
    night = tonight.Tonight.load(tmp_path, doc=doc_with(AJ))
    assert night.source == "show" and step_of(night, "", "Right for You")[0] == "Dinner"
    assert "changed after the night was built" in night.note and "Build the night again" in night.note


def test_a_song_moved_to_another_part_after_the_build_brings_the_shows_order_back(tmp_path):
    write_night(tmp_path, built_report(AJ))
    moved = [dict(s, part="dinner") if s["title"] == "Here for a Good Time" else s for s in AJ]
    night = tonight.Tonight.load(tmp_path, doc=doc_with(moved))
    assert night.source == "show" and step_of(night, "George Strait", "Here for a Good Time")[0] == "Dinner"


def test_a_song_the_build_could_not_use_never_counts_against_the_built_night(tmp_path):
    report = built_report([s for s in AJ if s["title"] != "Springsteen"])
    report["missing"] = ["Eric Church - Springsteen"]
    write_night(tmp_path, report)
    assert tonight.Tonight.load(tmp_path, doc=doc_with(AJ)).source == "built"


def test_no_show_arranged_into_a_night_keeps_the_plain_order(tmp_path):
    night = tonight.Tonight.load(tmp_path, doc=doc_with([dict(s, part="") for s in AJ]))
    assert night.source == "plain" and not night.follows and night.note == ""
    assert tonight.Tonight.load(tmp_path, doc=contract.normalize({})).source == "plain"


def test_the_show_the_live_show_follows_is_tonights_show(tmp_path):
    other = {"party": {"title": "A Party", "note": "", "looks": {}, "songs": [song("Cupid", "Cupid Shuffle", "dancing")]}}
    doc = doc_with(AJ, extra=other)
    assert tonight.Tonight.load(tmp_path, doc=doc, prefer="party").show == "party"
    assert tonight.Tonight.load(tmp_path, doc=doc, prefer="gone").show == "party"   # a stale pref falls back
    assert tonight.Tonight.pick_show(doc, "") == "party"          # "A Party" sorts before "AJ Wedding"
    assert tonight.Tonight.pick_show(doc, "", title="cm wedding") == "aj-wedding"


def test_a_broken_show_never_costs_the_built_night(tmp_path, monkeypatch):
    write_night(tmp_path, built_report(AJ[:3]))
    monkeypatch.setattr(tonight.Tonight, "from_show", classmethod(lambda cls, n, sh: 1 / 0))
    assert tonight.Tonight.load(tmp_path, doc=doc_with(AJ)).source == "built"


# --- the laptop app: a show Llano changes reaches the Live screen --------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))


def test_the_app_lists_a_show_llano_changed_and_keeps_where_mixxx_is(tmp_path, monkeypatch):
    import gigbar_app
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(gigbar_app.updater, "check", lambda: (None, "no update in tests"))
    monkeypatch.setattr(studio, "default_path", lambda: tmp_path / "studio.json")
    monkeypatch.setattr(gigbar_app, "app_data_dir", lambda: tmp_path)
    show_settings.set_current(contract.normalize({}))
    opts = argparse.Namespace(seconds=0.0, bpm=128.0, no_browser=True, no_window=True, updated=False, update_failed=False)
    app = gigbar_app.App(opts, gigbar_app.LogBuffer(tmp_path / "log.txt"))
    try:
        assert app.studio.night.source == "plain"
        show_settings.set_current(doc_with(AJ[:1] + AJ[2:3] + AJ[4:]))     # Llano sets the order
        assert app.reload_night() and app.studio.night.source == "show"
        app.studio.night.see(app.studio, song_match.candidates("Eric Church", "Springsteen"), 0.0)
        at = app.studio.night.at
        assert at == 2 and not app.reload_night(), "nothing changed: the list is left alone"
        show_settings.set_current(doc_with(AJ))                            # then adds the two songs
        rev = app.studio.rev
        assert app.reload_night() and app.studio.rev > rev
        assert app.studio.night.at == at, "same steps: where Mixxx is carries over"
        assert step_of(app.studio.night, "", "Right for You")[0] == "Dinner"
        assert app.studio.public()["night"]["source"] == "show"
    finally:
        app.stop()
        show_settings.set_current(contract.normalize({}))
