"""Which light is which (Llano BL #12378). The report, 2026-11-15: the light's number showed
but not its DMX address. Every light's DMX start address and channel mode, from the rig block in
force, beside its name on the Set up screen, the room picture, Line up my lights, a printable patch sheet
and the printed run sheet."""
from __future__ import annotations

import copy
import json
import urllib.request
from pathlib import Path

from tools.gigbar_lights import patch_sheet, run_of_show as ros, settings_contract, show_settings
from tools.gigbar_lights.venue import presets

from test_update_relaunch_11612 import make_app

SRC = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"


def rig_block() -> dict:
    return copy.deepcopy(settings_contract.defaults()["rig"])


def test_every_light_has_its_address_and_mode_from_the_rig_block():
    rs = {r["id"]: r for r in patch_sheet.rows(rig_block())}
    assert len(rs) == 12
    assert (rs["bar1"]["address"], rs["bar1"]["mode"], rs["bar1"]["last"]) == (1, "35-channel", 35)
    assert (rs["bar2"]["address"], rs["bar2"]["last"]) == (41, 75)
    assert (rs["tetra1"]["address"], rs["tetra1"]["mode"]) == (81, "6-channel")
    assert (rs["tetra6"]["address"], rs["stick1"]["address"], rs["stick1"]["mode"]) == (131, 151, "8-channel")
    assert [r["n"] for r in patch_sheet.rows(rig_block())] == list(range(1, 13))
    assert patch_sheet.label(rs["tetra3"]) == "Tetra 3: address 101, 6-channel mode"
    assert patch_sheet.overlaps(list(rs.values())) == []


def test_an_address_changed_on_llano_app_is_the_one_shown():
    rig = rig_block()
    rig["addresses"]["tetra2"] = 300
    rig["channels"]["tetra"] = rig["channels"]["tetra"][:4]   # a 4-channel mode
    rs = {r["id"]: r for r in patch_sheet.rows(rig)}
    assert (rs["tetra2"]["address"], rs["tetra2"]["mode"], rs["tetra2"]["last"]) == (300, "4-channel", 303)


def test_lights_not_set_up_tonight_and_overlaps_are_named():
    rig = rig_block()
    rig["counts"] = {"bars": 2, "tetras": 3, "sticks": 0}
    rs = {r["id"]: r for r in patch_sheet.rows(rig)}
    assert rs["tetra3"]["present"] and not rs["tetra4"]["present"] and not rs["stick1"]["present"]
    rig["addresses"]["bar2"] = 30            # inside GigBAR 1's 35 channels
    clash = patch_sheet.overlaps(patch_sheet.rows(rig))
    assert clash and "GigBAR 1" in clash[0] and "GigBAR 2" in clash[0]
    assert "GigBAR 2" in patch_sheet.sheet_html(patch_sheet.rows(rig)).split("<ul>")[1].split("</ul>")[0]


def test_where_each_light_stands_comes_from_the_layout_in_use():
    lay = presets()["small-room-front"]
    rs = {r["id"]: r for r in patch_sheet.rows(rig_block(), lay)}
    # booth center (4.0, 0.8) m; GigBAR 1 at (2.3, 0.8) is 1.7 m (5 ft 7 in) left, level with it, 2.4 m up
    assert rs["bar1"]["where"] == "5 ft 7 in left of the DJ booth's center, level with the booth's center, 7 ft 10 in up"
    assert rs["stick3"]["where"] == "8 ft 2 in left of the DJ booth's center, 22 ft in front of the booth's center"
    assert rs["bar2"]["where"].startswith("5 ft 7 in right of the DJ booth's center")
    assert " up" not in rs["tetra1"]["where"]


def test_the_patch_sheet_prints_every_address_mode_and_spot():
    page = patch_sheet.sheet_html(patch_sheet.rows(rig_block(), presets()["small-room-front"]), "Small room")
    for a in ("001", "041", "081", "091", "101", "111", "121", "131", "151", "161", "171", "181"):
        assert f"<td class=a>{a}</td>" in page
    assert "35-channel" in page and "6-channel" in page and "8-channel" in page
    assert "left of the DJ booth" in page and "window.print()" in page and "Room layout: Small room" in page


def test_the_run_sheet_carries_the_patch_on_its_own_page():
    steps = ros.plan({"dancing": [{"artist": "A", "title": "B", "secs": 200}]})
    page = ros.sheet_html("Avery & Jordan", steps, patch=patch_sheet.rows(rig_block()))
    assert "Which light is which" in page and "<td class=a>081</td>" in page and ".pb{break-before:page}" in page
    assert "Which light is which" not in ros.sheet_html("x", steps)


def test_the_room_picture_and_setup_screen_read_the_patch_not_a_typed_address():
    preview = (SRC / "preview.html").read_text(encoding="utf-8")
    assert "n==1?1:41" not in preview, "GigBAR addresses were typed into the room picture"
    assert 'fetch("/api/patch"' in preview and "loadPatch();" in preview
    assert 'data-fid="tetra${i+1}"' in preview and 'data-fid="stick${i+1}"' in preview and 'data-fid="bar${n}"' in preview
    app = (SRC / "app.html").read_text(encoding="utf-8")
    assert 'id="patchlist"' in app and 'fetch("/api/patch"' in app and '"/patch.html"' in app


def test_the_window_serves_the_patch_from_the_settings_in_force(tmp_path, monkeypatch):
    a = make_app(tmp_path, monkeypatch)
    before = show_settings.current()
    try:
        doc = before
        doc = {**doc, "rig": {**doc["rig"], "addresses": {**doc["rig"]["addresses"], "stick4": 201}}}
        show_settings.set_current(doc)
        with urllib.request.urlopen(a.preview.url + "api/patch", timeout=10) as r:
            j = json.loads(r.read())
        rs = {x["id"]: x for x in j["rows"]}
        assert rs["stick4"]["address"] == 201 and rs["bar1"]["mode"] == "35-channel"
        assert j["layout"] and rs["bar1"]["where"]
        with urllib.request.urlopen(a.preview.url + "patch.html", timeout=10) as r:
            page = r.read().decode()
        assert "<td class=a>201</td>" in page and "Which light is which" in page
    finally:
        show_settings.set_current(before)   # the next test renders from the settings in force
        a.quit.set()
        a.preview.close()


def test_the_layout_screen_can_flip_which_tetra_is_number_one():
    """His 11-15 ask: Tetra 1 on the right, then 2, 3 going left, the way his cords run. The spots stay; the
    numbers (and so the addresses) reverse; the screen says which way they run now."""
    preview = (SRC / "preview.html").read_text(encoding="utf-8")
    assert 'data-renumber="tetra"' in preview and 'data-renumber="stick"' in preview
    # the app flips them now and keeps the side as rig.numbering (BL #12396, test_numbering_12396.py)
    assert 'postLayout({action: "numbers", kind, layout: L})' in preview and "showNumbers();" in preview
