"""Llano BL #12380: a My venues list he can see, open, rename and delete.

His 11-15 question: is there a place to see, save and pull up venues he has created. The room picture
could save and pick layouts, but nothing was called a venue, his own sat mixed in with the presets, and
nothing could rename or delete one. These pin the store's rules, the window's two new actions, what goes
to Llano so llano.app/lights matches, and the page itself in a real browser.
"""
from __future__ import annotations

import copy
import json
import sys
import types
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tools.gigbar_lights import settings_contract as contract
from tools.gigbar_lights.venue import DEFAULT_LAYOUT, Layout, LayoutStore, presets

SRC = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"


def venue(label: str):
    """A venue as the page saves one: its name and label from what he typed (from_dict makes the name)."""
    return Layout.from_dict({**copy.deepcopy(presets()[DEFAULT_LAYOUT]).to_dict(), "name": label, "label": label, "preset": False})


@pytest.fixture
def store(tmp_path):
    s = LayoutStore(tmp_path / "profile")
    s.save(venue("Rio Grande ballroom"))
    s.save(venue("Barn"))
    return s


# --- the store -----------------------------------------------------------------------------------

def test_rename_changes_only_the_name_he_sees(store):
    key = next(n for n, l in store.saved().items() if l.label == "Barn")
    lay = store.rename(key, "  The   Red Barn ")
    assert lay.name == key and lay.label == "The Red Barn"
    assert store.saved()[key].label == "The Red Barn"           # the file and the sync key stay
    assert len(list(store.dir.glob("*.json"))) == 2 and not list(store.dir.glob("*.tmp"))


def test_rename_refuses_in_plain_words(store):
    key = next(n for n, l in store.saved().items() if l.label == "Barn")
    with pytest.raises(ValueError, match="type a name"):
        store.rename(key, "   ")
    with pytest.raises(ValueError, match="already have a venue called Rio Grande ballroom"):
        store.rename(key, "rio grande BALLROOM")
    with pytest.raises(ValueError, match="ready-made room"):
        store.rename(DEFAULT_LAYOUT, "Mine now")
    with pytest.raises(ValueError, match="no saved venue"):
        store.rename("gone", "x")
    with pytest.raises(ValueError, match="80"):
        store.rename(key, "x" * 81)


def test_delete_sets_the_file_aside_and_keeps_the_one_in_use(store):
    barn = next(n for n, l in store.saved().items() if l.label == "Barn")
    rio = next(n for n, l in store.saved().items() if l.label != "Barn")
    store.use(rio)
    store.delete(barn)
    assert barn not in store.saved() and (store.dir / f"{barn}.json.removed").is_file()   # never erased
    with pytest.raises(ValueError, match="use another one first"):
        store.delete(rio)
    with pytest.raises(ValueError, match="ready-made room"):
        store.delete(DEFAULT_LAYOUT)
    assert store.current_name() == rio and rio in store.saved()


# --- the window's actions -----------------------------------------------------------------------

class FakeApp:
    def __init__(self):
        self.sent = []
        self.doctor = None

    def touch(self):
        pass

    def layout_changed(self, lay, saved, use=True):
        self.sent.append(("changed", lay.name, lay.label, saved, use))

    def layout_removed(self, name):
        self.sent.append(("removed", name))


@pytest.fixture
def preview(store):
    sys.path.insert(0, str(SRC))
    import gigbar_app
    p = gigbar_app.Preview("", store, app=FakeApp())
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


def test_rename_and_delete_never_move_the_show(preview, store):
    rio = next(n for n, l in store.saved().items() if l.label != "Barn")
    barn = next(n for n, l in store.saved().items() if l.label == "Barn")
    assert _post(preview, {"action": "use", "name": rio})[0] == 200
    preview.app.sent.clear()

    code, body = _post(preview, {"action": "rename", "name": barn, "label": "Red Barn"})
    assert code == 200 and body["label"] == "Red Barn" and body["in_use"] == rio
    assert preview.layout.name == rio and store.current_name() == rio
    assert preview.app.sent == [("changed", barn, "Red Barn", True, False)]   # to Llano, not picked

    code, body = _post(preview, {"action": "rename", "name": rio, "label": "Rio"})
    assert code == 200 and preview.layout.label == "Rio"                     # the one in use, renamed

    code, body = _post(preview, {"action": "delete", "name": rio})
    assert code == 400 and "use another one first" in body["error"]
    code, body = _post(preview, {"action": "delete", "name": barn})
    assert code == 200 and body["in_use"] == rio and barn not in store.saved()
    assert preview.app.sent[-1] == ("removed", barn)

    with urllib.request.urlopen(preview.url + "layout", timeout=10) as r:
        listed = json.loads(r.read())["layouts"]
    assert [l["label"] for l in listed if not l["preset"]] == ["Rio"]


def test_a_rename_or_delete_reaches_llano_as_one_op(tmp_path):
    """What the laptop queues for llano.app/lights, and that the contract takes it."""
    sys.path.insert(0, str(SRC))
    import gigbar_app

    class Link:
        def __init__(self):
            self.ops = []

        def local_change(self, ops):
            contract.apply_ops(doc, ops)          # raises if Llano's contract would refuse it
            self.ops.append(ops)

    lay = venue("barn")
    doc = contract.apply_ops(contract.normalize({}), [{"path": "layouts.saved.barn", "value": lay.to_dict()}])[0]
    app = types.SimpleNamespace(link=Link())
    app._send_layout_ops = types.MethodType(gigbar_app.App._send_layout_ops, app)
    lay.label = "Red Barn"
    gigbar_app.App.layout_changed(app, lay, saved=True, use=False)
    gigbar_app.App.layout_removed(app, "barn")
    assert app.link.ops == [[{"path": "layouts.saved.barn", "value": lay.to_dict()}],
                            [{"path": "layouts.saved.barn", "value": None}]]
    gone = contract.apply_ops(doc, app.link.ops[1])[0]
    assert "barn" not in gone["layouts"]["saved"]


# --- the page, in a real browser ---------------------------------------------------------------

def test_the_page_lists_his_venues_first_and_renames_and_deletes_them(preview, store):
    pw = pytest.importorskip("playwright.sync_api")
    rio = next(n for n, l in store.saved().items() if l.label != "Barn")
    store.use(rio)
    preview.layout = store.current()
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            page = browser.new_page()
            page.goto(preview.url + "preview")
            page.wait_for_selector("#venues li")
            groups = page.eval_on_selector_all("#lay optgroup", "gs => gs.map(g => [g.label, g.children.length])")
            assert groups[0] == ["My venues", 2] and groups[1][0] == "Ready-made rooms"
            assert not any(o.startswith("Mine: ") for o in page.eval_on_selector_all("#lay option", "os => os.map(o => o.textContent)"))
            rows = page.eval_on_selector_all("#venues li .vname", "xs => xs.map(x => x.textContent)")
            assert rows == ["Barn", "Rio Grande ballroom"]
            rio_row = page.locator(f'#venues li[data-venue="{rio}"]')
            assert rio_row.locator("button", has_text="Delete").is_disabled()   # the show aims from it

            barn_row = page.locator('#venues li', has_text="Barn").first
            barn_row.locator("button", has_text="Rename").click(force=True)
            page.fill("#venues li input", "Red Barn")
            page.locator("#venues button", has_text="Save name").click(force=True)
            page.wait_for_function("() => [...document.querySelectorAll('#venues .vname')].some(x => x.textContent === 'Red Barn')")
            assert "Red Barn" in [l.label for l in store.saved().values()]

            page.locator('#venues li', has_text="Red Barn").locator("button", has_text="Delete").click(force=True)
            page.locator("#venues button", has_text="Yes, delete it").click(force=True)
            page.wait_for_function("() => document.querySelectorAll('#venues li').length === 1")
            assert [l.label for l in store.saved().values()] == ["Rio Grande ballroom"]
            assert "Deleted Red Barn" in page.text_content("#dmsg")
        finally:
            browser.close()
