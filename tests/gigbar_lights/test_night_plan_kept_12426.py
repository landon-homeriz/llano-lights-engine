"""A saved show keeps its wedding-night plan across a restart on another port (Llano BL #12426).

Found in the Nov 15 click-through of 1.28.0: the app came back on another port of 8765-8784, the saved
show was reopened, and step 2's folder box was empty and the "no moment yet" needs line was gone. The plan
lived only in the window's localStorage, which is per origin (per port). The app keeps it now.
"""
import json
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from tests.gigbar_lights.test_shows import _call, lib, window  # noqa: E402,F401
from tools.gigbar_lights import night_plans  # noqa: E402

PAGE = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src" / "shows.html"

SONGS = [
    {"artist": "Ed Sheeran", "title": "Perfect", "secs": 263, "part": "dancing"},
    {"artist": "Etta James", "title": "At Last", "secs": 180, "part": "dancing"},
]
PLAN = {"folder": r"C:\Users\dj\Music\AJ Wedding",
        "moments": {"entrance": {"on": True, "at": "6:30", "song": ""},
                    "cake": {"on": False, "at": "", "song": ""}},
        "keep": ["etta-james-at-last"],
        "times": {"cocktail": "5:00", "dinner": "6:00", "dancing": "8:00"},
        "unplaced": ["Etta James - At Last"]}


def test_a_plan_is_cleaned_kept_and_dropped(tmp_path):
    store = night_plans.NightPlans(tmp_path / "night_plans.json")
    assert store.get("wedding") is None
    store.put("wedding", {**PLAN, "times": {"dinner": "6:00", "junk": "x"}, "moments": {"cake": "not a box"}, "keep": "no"})
    got = store.get("wedding")
    assert got["folder"] == PLAN["folder"] and got["times"] == {"cocktail": "", "dinner": "6:00", "dancing": ""}
    assert got["moments"] == {} and got["keep"] == [] and got["unplaced"] == ["Etta James - At Last"]
    assert night_plans.NightPlans(tmp_path / "night_plans.json").get("wedding") == got   # on disk, not in memory
    assert store.put("", PLAN) is None and store.put("x", "not a plan") is None
    store.drop("wedding")
    assert store.get("wedding") is None
    (tmp_path / "night_plans.json").write_text("{broken", encoding="utf-8")
    assert store.get("wedding") is None   # a broken file is no plans, never a failed open
    assert night_plans.empty(night_plans.clean({})) and not night_plans.empty(night_plans.clean(PLAN))


def test_another_ports_window_opens_the_show_with_its_plan(window):  # noqa: F811
    app, url, token, tmp = window
    code, saved = _call(url + "api/shows-save", {"title": "AJ Wedding", "songs": SONGS}, token)
    assert code == 200 and saved["name"] == "aj-wedding"
    assert _call(url + "api/shows-night-remember", {"name": "nope", "plan": PLAN}, token)[0] == 404
    assert _call(url + "api/shows-night-remember", {"name": "aj-wedding", "plan": "x"}, token)[0] == 400
    assert _call(url + "api/shows-night-remember", {"name": "aj-wedding", "plan": PLAN}, token)[0] == 200
    assert json.loads((tmp / "night_plans.json").read_text())["aj-wedding"]["folder"] == PLAN["folder"]

    # a window on another port has an empty localStorage: it sends nothing of the plan
    code, opened = _call(url + "api/shows-open", {"name": "aj-wedding"}, token)
    assert code == 200
    assert opened["night"]["folder"] == PLAN["folder"]
    assert opened["night"]["times"] == PLAN["times"] and opened["night"]["keep"] == ["etta-james-at-last"]
    assert opened["night"]["moments"]["entrance"]["at"] == "6:30" and opened["night"]["moments"]["cake"]["on"] is False
    assert any(n["kind"] == "unplaced" and "At Last" in n["text"] for n in opened["needs"])   # the needs line is back

    # an old window's stale copy never overrides what the app kept
    stale = {"name": "aj-wedding", "folder": r"D:\old", "times": {"dinner": "9:00"}, "unplaced": []}
    assert _call(url + "api/shows-open", stale, token)[1]["night"]["folder"] == PLAN["folder"]

    # a cleared plan stays cleared: another port's old copy does not bring it back
    assert _call(url + "api/shows-night-remember", {"name": "aj-wedding", "plan": {"unplaced": []}}, token)[0] == 200
    assert _call(url + "api/shows-open", stale, token)[1]["night"]["folder"] == ""

    # deleting the show forgets its plan
    assert _call(url + "api/shows-delete", {"name": "aj-wedding"}, token)[0] == 200
    assert "aj-wedding" not in json.loads((tmp / "night_plans.json").read_text())


def test_a_plan_kept_only_in_this_window_moves_into_the_app(window):  # noqa: F811
    app, url, token, tmp = window
    assert _call(url + "api/shows-save", {"title": "AJ Wedding", "songs": SONGS}, token)[0] == 200
    page_copy = {"name": "aj-wedding", **{k: PLAN[k] for k in ("folder", "moments", "keep", "times", "unplaced")}}
    code, opened = _call(url + "api/shows-open", page_copy, token)
    assert code == 200 and opened["night"]["folder"] == PLAN["folder"]
    # the next window, on any port, gets it from the app
    assert _call(url + "api/shows-open", {"name": "aj-wedding"}, token)[1]["night"]["times"] == PLAN["times"]


def test_the_page_adopts_the_apps_plan_and_keeps_each_change_there():
    page = PAGE.read_text(encoding="utf-8")
    assert '"/api/shows-night-remember"' in page                                   # each step 2 change
    assert 'localStorage.setItem("llano-night:" + s.name, JSON.stringify(s.night))' in page   # the app's plan on open
    assert "keep: kept.keep || [], times: kept.times || {}" in page               # an old window's whole copy moves over
    save = page[page.index("async function saveOnce"):page.index('$("#save").addEventListener')]
    assert "nightKeep();" in save                                                  # a new show's plan, under its new name


def test_a_plan_file_that_cannot_be_written_never_stops_a_show_opening(window, monkeypatch):  # noqa: F811
    app, url, token, tmp = window
    assert _call(url + "api/shows-save", {"title": "A&J Wedding", "songs": SONGS}, token)[0] == 200

    def refuse(*a, **k):
        raise PermissionError("the disk said no")
    monkeypatch.setattr(night_plans.NightPlans, "_write", refuse)
    code, opened = _call(url + "api/shows-open", {"name": "a-j-wedding", "folder": PLAN["folder"]}, token)
    assert code == 200 and opened["night"]["folder"] == PLAN["folder"]           # the window's plan, used as it opens
    assert any(n["kind"] == "folder" for n in opened["needs"])                    # and a folder not here is said
    assert _call(url + "api/shows-night-remember", {"name": "a-j-wedding", "plan": PLAN}, token)[0] == 500
    assert _call(url + "api/shows-delete", {"name": "a-j-wedding"}, token)[0] == 200


def test_a_half_written_or_odd_file_is_no_plans(tmp_path):
    f = tmp_path / "night_plans.json"
    store = night_plans.NightPlans(f)
    for junk in ('{"a-j-wedding": {"folder": "C:\\\\x"', "[1, 2]", '{"a-j-wedding": "folder"}', ""):
        f.write_text(junk, encoding="utf-8")
        assert store.get("a-j-wedding") is None
    store.put("a-j-wedding", PLAN)                     # and the next keep writes a whole file again
    assert store.get("a-j-wedding")["folder"] == PLAN["folder"]
    assert not (tmp_path / "night_plans.json.tmp").exists()
