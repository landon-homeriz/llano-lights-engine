"""Two pieces of wording a first-time DJ reads at the venue (Llano BL #12435), before the 2026-11-25 wedding.

1. Line up my lights on one spot whose heads disagree said "its heads don't agree on where it faces (off by
   3.8 m)", in red and in meters in a room he set up in feet. The reply now carries a code and the distances
   in meters as numbers, `why` keeps plain words with no unit, and the page says it in the room's unit as
   what to do, not a fault.
2. The run sheet said "3 songs, 1 minutes." Every count reads right for 1 and for more.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from tools.gigbar_lights import run_of_show as ros
from tools.gigbar_lights.venue import FT, LayoutStore, presets

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_one_spot_116 import MIRRORED, RealBar  # noqa: E402

SRC = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"
UNIT = re.compile(r"\d\s*(m|ft|meters?|feet)\b|\boff by\b")


def _one_spot_apart(lay, bar=1):
    """Poses of one spot from heads that can't both be on one bar: head 2 as if hung 1 m lower and turned."""
    spot, a = (lay.floor.cx, lay.floor.cy), lay.facing(f"bar{bar}")
    r0, r1 = RealBar(lay, bar, a, 2.75, MIRRORED), RealBar(lay, bar, a + 30.0, 1.75, MIRRORED)
    return [(bar, 0, *r0.pose(0, *spot), spot), (bar, 1, *r1.pose(1, *spot), spot)]


# --- the reply ------------------------------------------------------------------------------------

def test_one_spot_apart_carries_its_code_and_meters_and_why_has_no_unit():
    lay = presets()["small-room-front"]
    r = lay.converge(_one_spot_apart(lay))["bars"][1]
    assert not r["solved"] and r["why_code"] == "one_spot_apart"
    assert isinstance(r["off_m"], float) and r["off_m"] > 0.35 and r["off_m"] == r["rms_m"]
    assert not UNIT.search(r["why"]) and "second spot" in r["why"] and "normal" not in r["why"]


def _two_spot_heads(lay, b=1):
    real = RealBar(lay, b, lay.facing(f"bar{b}"), 2.6, MIRRORED)
    fl = lay.floor
    spots = [(fl.cx, fl.cy), (fl.x + 1.0, fl.y + 1.0)]
    return {m: [(*real.pose(m, *p), p) for p in spots] for m in (0, 1)}


def test_spots_differ_and_moved_carry_their_codes_and_meters_and_why_has_no_unit():
    lay = presets()["small-room-front"]
    s = lay.spots["bar1"]
    was = {"facing": round(lay.facing("bar1"), 1), "height": s.z}
    r = lay._converge_bar(1, _two_spot_heads(lay), {"facing": lay.facing("bar1"), "height": 2.6, "rms_m": 0.91}, was)
    assert r["why_code"] == "spots_differ" and r["off_m"] == 0.91 and r["spots"] == 2
    assert not UNIT.search(r["why"]) and "held exactly" in r["why"]

    lay = presets()["small-room-front"]
    s = lay.spots["bar1"]
    solved = {"x": s.x + 0.9, "y": s.y + 0.4, "facing": lay.facing("bar1"), "height": 2.6, "rms_m": 0.5,
              "fixed_rms_m": 1.4}
    r = lay._converge_bar(1, _two_spot_heads(lay), solved, was)
    assert r["why_code"] == "moved_spots_differ" and r["off_m"] == 0.5 and r["moved_m"] == r["moved"]["by_m"] > 0.9
    assert not UNIT.search(r["why"]) and "Back to plan" in r["why"] and "moved there" in r["why"]


# --- the run sheet --------------------------------------------------------------------------------

def _song(secs):
    return {"artist": "A", "title": "T", "secs": secs}


def _music_detail(songs):
    steps = [ros.Step("music", "dinner", "Dinner", songs=songs)]
    return ros.sheet_rows(steps)[0]["detail"]


def test_run_sheet_counts_read_right_for_one_and_for_more():
    assert _music_detail([_song(60)]) == "1 song, 1 minute."
    assert _music_detail([_song(200), _song(200), _song(200)]) == "3 songs, 10 minutes."   # handoffs overlap
    assert _music_detail([_song(60), _song(60) | {"title": "U"}]).startswith("2 songs, ")
    assert ros._count(1, "minute") == "1 minute" and ros._count(0.6, "minute") == "1 minute"
    assert ros._count(0, "minute") == "0 minutes" and ros._count(12, "minute") == "12 minutes"
    assert ros._count(1, "more song") == "1 more song" and ros._count(4, "more song") == "4 more songs"


def test_no_count_sentence_in_the_run_sheet_hard_codes_a_plural():
    src = (Path(ros.__file__)).read_text(encoding="utf-8")
    assert not re.search(r"\}\s+(songs|minutes)\b", src), "a number placed before a fixed plural"
    assert "1 minutes" not in src and "1 songs" not in src


def test_a_one_minute_new_playlist_and_a_short_dancing_check_say_minute():
    nxt = ros.Step("music", "dancing", "Dancing", songs=[_song(200)], opens=True)
    assert "start again after 1 minute." in ros._new_playlist(nxt, 2, 1.0)
    dancing = ros.Step("music", "dancing", "Dancing", songs=[_song(60)])
    text = " ".join(c["text"] for c in ros.checks([dancing]))
    assert "Dancing has 1 minute of music." in text and "1 minutes" not in text


# --- in a real browser ----------------------------------------------------------------------------

class FakeApp:
    doctor = None

    def touch(self):
        pass

    def layout_changed(self, lay, saved, use=True):
        pass

    def layout_removed(self, name):
        pass


@pytest.fixture(scope="module")
def preview(tmp_path_factory):
    sys.path.insert(0, str(SRC))
    import gigbar_app
    store = LayoutStore(tmp_path_factory.mktemp("lu12435") / "profile")
    store.use("small-room-front")
    p = gigbar_app.Preview("", store, app=FakeApp())
    yield p
    p.close()


@pytest.fixture(scope="module")
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        yield b
        b.close()


def _lined_up(browser, preview, unit):
    """Line up one spot on the line-up page so GigBAR 1's heads disagree, through the real server."""
    pg = browser.new_page(viewport={"width": 1024, "height": 700})
    pg.add_init_script(f"try {{ localStorage.setItem('llano-units', '{unit}'); }} catch (e) {{}}")
    pg.goto(preview.url + "lineup.html")
    pg.wait_for_function("() => typeof L !== 'undefined' && L && L.fixtures")
    lay = presets()["small-room-front"]
    rows, fresh = _one_spot_apart(lay), presets()["small-room-front"]
    spot = list(rows[0][4])
    pg.evaluate("""([spot, rows, fresh]) => { L = fresh; lu.spot = spot; lu.order = rows.map(r => [r[0], r[1]]);
        rows.forEach(r => { lu.poses[luKey([r[0], r[1]])] = [r[2], r[3]]; }); return luSolve(); }""",
                [spot, [[b, m, p, t] for b, m, p, t, _ in rows], fresh.to_dict()])   # a fresh room each time
    pg.wait_for_function("() => document.querySelector('#lures [data-luwhy]')")
    return pg, lay.converge(rows)["bars"][1]["off_m"]


def _line(pg):
    return pg.text_content("#lures [data-luwhy='1']")


def test_one_spot_apart_reads_in_feet_in_a_feet_room_and_follows_a_switch_to_meters(browser, preview):
    pg, off = _lined_up(browser, preview, "ft")
    ft = round(off / FT)
    assert _line(pg) == (f"GigBAR 1: its heads land about {ft} ft apart on this spot, so one spot is not enough to tell where the bar faces. "
                         "Line up a second spot and Llano holds both.")
    assert not re.search(r"\d\s*m\b|off by", _line(pg))
    assert pg.get_attribute("#lures [data-luwhy='1']", "class") is None   # news, not a fault: not in red
    # switched with the message on screen (the picker sits in the room designer, hidden on this page)
    pg.evaluate("() => { const u = document.querySelector('#units'); u.value = 'm'; u.dispatchEvent(new Event('change')); }")
    assert f"about {off:.1f} m apart" in _line(pg) and " ft" not in _line(pg)
    pg.close()


def test_one_spot_apart_reads_in_meters_in_a_meters_room(browser, preview):
    pg, off = _lined_up(browser, preview, "m")
    assert _line(pg) == (f"GigBAR 1: its heads land about {off:.1f} m apart on this spot, so one spot is not enough to tell where the bar faces. "
                         "Line up a second spot and Llano holds both.")
    assert not re.search(r"off by|\bft\b|feet", _line(pg))
    pg.close()


@pytest.mark.parametrize("unit", ["ft", "m"])
def test_an_unknown_code_or_missing_number_prints_why_and_edge_numbers_read_right(browser, preview, unit):
    pg = browser.new_page()
    pg.add_init_script(f"try {{ localStorage.setItem('llano-units', '{unit}'); }} catch (e) {{}}")
    pg.goto(preview.url + "lineup.html")
    pg.wait_for_function("() => typeof luWhy === 'function'")
    why = "its heads are thinking it over"
    say = lambda r: pg.evaluate("(r) => luWhy(1, r)", r)
    assert say({"why_code": "brand_new_code", "off_m": 1.0, "why": why}) == f"GigBAR 1: {why}."
    assert say({"why": why}) == f"GigBAR 1: {why}."
    assert say({"why_code": "one_spot_apart", "why": why}) == f"GigBAR 1: {why}."            # code, no number
    assert say({"why_code": "one_spot_apart", "off_m": None, "why": why}) == f"GigBAR 1: {why}."
    assert say({"why_code": "one_spot_apart", "off_m": -1, "why": why}) == f"GigBAR 1: {why}."
    assert say({"why_code": "moved_spots_differ", "off_m": 0.5, "why": why}) == f"GigBAR 1: {why}."   # one of two
    small = "less than 1 ft" if unit == "ft" else "less than 0.1 m"
    assert f"land {small} apart" in say({"why_code": "one_spot_apart", "off_m": 0, "why": why})
    big = "about 3281 ft" if unit == "ft" else "about 1000.0 m"
    assert f"land {big} apart" in say({"why_code": "one_spot_apart", "off_m": 1000, "why": why})
    moved = say({"why_code": "moved_spots_differ", "off_m": 0.5, "moved_m": 0.9, "why": why})
    assert "Back to plan undoes the move." in moved and "from the plan" in moved
    two = say({"why_code": "spots_differ", "off_m": 0.9, "spots": 3, "why": why})
    assert "all 3 spots" in two and "held exactly" in two
    pg.close()
