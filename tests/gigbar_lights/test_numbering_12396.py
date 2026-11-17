"""Llano BL #12396: the Stage setup keeps his Tetra numbering (Tetra 1 on the right).

He cables his Tetras from the right, so Tetra 1 stands on the right and 2, 3 go left (BL #12378). The
Flip the Tetra numbers button reversed them in the room on screen, but nothing remembered it: the next
Stage setup (Draw my room) or ready-made room drew tetra1..6 left to right again and undid it (on
2026-11-15 a session saved his Stage room as stage-tetra-1-on-the-right, and the next Stage setup would
have renumbered it). Now which end light 1 starts at is a rig fact, `rig.numbering`, set by the Flip
buttons, and every room the laptop draws numbers from there. These pin the geometry, the presets, the
store, the contract, the window's two actions end to end, and the button in a real browser.
"""
from __future__ import annotations

import json
import sys
import types
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tools.gigbar_lights import settings_contract as contract
from tools.gigbar_lights import show_settings
from tools.gigbar_lights.venue import FT, NUMBER_KINDS, Layout, LayoutStore, numbered, presets, stage_layout

SRC = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"
RIGHT = {"tetra": "right", "stick": "right"}


def xs(lay, kind):
    return [lay.spots[f].x for f in lay.number_ids(kind)]


@pytest.fixture(autouse=True)
def keep_settings():
    """show_settings is process-global: put the old document back (it leaks into later tests otherwise)."""
    old = show_settings.current()
    yield
    show_settings.set_current(old)


# --- the geometry ----------------------------------------------------------------------------

def test_stage_setup_numbers_the_tetras_from_the_right_when_his_rig_says_so():
    plain = stage_layout(20 * FT, 22 * FT, 10 * FT)
    his = stage_layout(20 * FT, 22 * FT, 10 * FT, numbering={"tetra": "right"})
    assert xs(plain, "tetra") == sorted(xs(plain, "tetra"))                     # as drawn: 1 on the left
    assert xs(his, "tetra") == sorted(xs(plain, "tetra"), reverse=True)         # his: 1 on the right, 2, 3 going left
    assert his.number_side("tetra") == "right" and plain.number_side("tetra") == "left"
    assert xs(his, "stick") == xs(plain, "stick")                               # sticks keep theirs
    # same room, same spots; only which light is which number changed
    assert sorted((s.x, s.y, s.z) for s in his.spots.values()) == sorted((s.x, s.y, s.z) for s in plain.spots.values())
    assert his.spots["bar1"] == plain.spots["bar1"] and his.spots["bar2"] == plain.spots["bar2"]


def test_numbered_is_idempotent_and_flip_reverses_the_plan_too():
    lay = stage_layout(20 * FT, 22 * FT, 10 * FT)
    lay.keep_plan()
    want = list(reversed([lay.plan[f] for f in lay.number_ids("tetra")]))
    numbered(lay, RIGHT)
    once = lay.to_dict()
    numbered(lay, RIGHT)
    assert lay.to_dict() == once                                                # asking twice changes nothing more
    assert [lay.plan[f] for f in lay.number_ids("tetra")] == want
    assert lay.number_side("stick") == "right"
    numbered(lay, {"tetra": "left", "stick": "sideways"})                       # junk side = left as it is
    assert lay.number_side("tetra") == "left" and lay.number_side("stick") == "right"


def test_every_ready_made_room_numbers_from_his_end():
    for name, lay in presets(RIGHT).items():
        for kind in NUMBER_KINDS:
            assert lay.number_side(kind) in ("right", ""), (name, kind)
    assert presets()["stage"].number_side("tetra") == "left"                     # no rig fact = as drawn


def test_the_store_draws_presets_his_way_and_never_touches_a_saved_room(tmp_path):
    rig = {"tetra": "left"}
    store = LayoutStore(tmp_path / "profile", numbering=lambda: dict(rig))
    store.save(Layout.from_dict({**stage_layout(20 * FT, 22 * FT, 10 * FT).to_dict(), "name": "barn", "label": "Barn"}))
    rig["tetra"] = "right"
    assert store.get("stage").number_side("tetra") == "right"                   # read fresh each time
    assert store.get("barn").number_side("tetra") == "left"                     # saved as he left it


def test_the_store_reads_the_rig_from_the_settings_in_use(tmp_path):
    show_settings.set_current(contract.apply_ops(contract.normalize({}), [{"path": "rig.numbering.tetra", "value": "right"}])[0])
    assert LayoutStore(tmp_path / "p").get("stage").number_side("tetra") == "right"


# --- the contract (byte for byte the same in aios) -------------------------------------------

def test_the_contract_keeps_the_rig_numbering():
    doc = contract.normalize({})
    assert doc["rig"]["numbering"] == {"tetra": "left", "stick": "left"}        # an old document plays as before
    new, applied = contract.apply_ops(doc, [{"path": "rig.numbering.tetra", "value": "right"}])
    assert new["rig"]["numbering"] == {"tetra": "right", "stick": "left"}
    assert applied == [{"path": "rig.numbering.tetra", "value": "right", "before": "left"}]
    assert contract.apply_ops(new, contract.undo_ops(applied))[0]["rig"]["numbering"]["tetra"] == "left"
    assert contract.normalize({"rig": {"numbering": {"tetra": "up", "stick": 3}}})["rig"]["numbering"] == \
        {"tetra": "left", "stick": "left"}
    assert "rig.numbering" in contract.FIELDS


# --- the window: Flip the Tetra numbers, then Draw my room -----------------------------------

class Link:
    """The laptop's settings link, as local_change behaves: in force at once."""
    def __init__(self):
        self.ops = []

    def local_change(self, ops):
        new, _ = contract.apply_ops(show_settings.current(), ops)
        show_settings.set_current(new)
        self.ops.append(ops)
        return new


class FakeApp:
    def __init__(self):
        self.link = Link()
        self.doctor = None

    def touch(self):
        pass

    def layout_changed(self, lay, saved, use=True):
        pass


@pytest.fixture
def preview(tmp_path):
    show_settings.set_current(contract.normalize({}))
    sys.path.insert(0, str(SRC))
    import gigbar_app
    store = LayoutStore(tmp_path / "profile")
    store.use("stage")
    p = gigbar_app.Preview("", store, app=FakeApp())
    p.layout = store.current()
    yield p
    p.close()


def _post(p, msg):
    req = urllib.request.Request(p.url + "layout", json.dumps(msg).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Llano-Token": p.token})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_flip_then_stage_setup_keeps_tetra_1_on_the_right(preview):
    code, body = _post(preview, {"action": "numbers", "kind": "tetra", "layout": preview.layout.to_dict()})
    assert code == 200
    flipped = Layout.from_dict(body["layout"])
    assert flipped.number_side("tetra") == "right" and preview.tried                 # aimed now, not saved
    assert preview.app.link.ops == [[{"path": "rig.numbering.tetra", "value": "right"}]]
    assert show_settings.current()["rig"]["numbering"]["tetra"] == "right"

    # the bug: the next Stage setup drew tetra1..6 left to right again
    code, body = _post(preview, {"action": "stage", "stage_w": 18 * FT, "floor_d": 20 * FT, "bar_h": 9 * FT})
    assert code == 200
    drawn = Layout.from_dict(body["layout"])
    assert drawn.number_side("tetra") == "right" and drawn.number_side("stick") == "left"
    assert xs(drawn, "tetra") == sorted(xs(drawn, "tetra"), reverse=True)

    # a ready-made room he opens is numbered his way too, and flipping back is remembered the same way
    with urllib.request.urlopen(preview.url + "layout?name=small-room-front", timeout=10) as r:
        assert Layout.from_dict(json.loads(r.read())["layout"]).number_side("tetra") == "right"
    code, body = _post(preview, {"action": "numbers", "kind": "tetra", "layout": drawn.to_dict()})
    assert code == 200 and show_settings.current()["rig"]["numbering"]["tetra"] == "left"
    assert _post(preview, {"action": "numbers", "kind": "lamp", "layout": drawn.to_dict()})[0] == 400


def test_the_catalog_llano_shows_numbers_the_presets_his_way(preview):
    import gigbar_app
    show_settings.set_current(contract.apply_ops(contract.normalize({}), [{"path": "rig.numbering.tetra", "value": "right"}])[0])
    cat = gigbar_app.App._sync_catalog(types.SimpleNamespace())
    assert Layout.from_dict(cat["layouts"]["stage"]).number_side("tetra") == "right"


def test_the_button_on_the_page_keeps_it_for_the_next_stage_setup(preview):
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            page = browser.new_page()
            page.goto(preview.url + "preview")
            page.wait_for_function("() => document.querySelector('#numsay').textContent.includes('Tetra 1 is on the left')")
            page.locator("button[data-renumber='tetra']").click(force=True)
            page.wait_for_function("() => document.querySelector('#numsay').textContent.includes('Tetra 1 is on the right')")
            assert show_settings.current()["rig"]["numbering"]["tetra"] == "right"
            assert "next Stage setup" in page.text_content("#dmsg")
            page.locator("#qsgo").click(force=True)                                   # Draw my room
            page.wait_for_function("() => document.querySelector('#dmsg').textContent && !document.querySelector('#dmsg').textContent.includes('next Stage setup')")
            page.wait_for_function("() => document.querySelector('#numsay').textContent.includes('Tetra 1 is on the right')")
            assert preview.layout.number_side("tetra") == "right"
        finally:
            browser.close()
