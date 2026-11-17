"""The laptop-only link (offline_link.py) the open-source engine runs on (Llano BL #12514).

The app reaches its settings sync through one object. An edition without llano_sync.py falls back to
offline_link.LlanoLink, so the stand-in must answer everything the app asks of the real link, keep every
laptop change in force and on disk, and never touch the network.
"""
import ast
import importlib
import socket
import sys
from pathlib import Path

import pytest

from tools.gigbar_lights import offline_link, settings_contract, show_settings

APP = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src" / "gigbar_app.py"


def _used_on_link() -> set:
    """Every attribute gigbar_app reads off self.link, and every llano_sync.<name> it uses."""
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    used, mod = set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute) and n.value.attr == "link" \
                and isinstance(n.value.value, ast.Name) and n.value.value.id == "self":
            used.add(n.attr)
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "llano_sync":
            mod.add(n.attr)
    return used, mod


def _link(tmp_path):
    return offline_link.LlanoLink(show_settings.SettingsFile(tmp_path / "settings.json"), version="9.9.9",
                                  on_doc=lambda new, old: None, status=lambda w: {}, studio=None)


def test_the_stand_in_answers_everything_the_app_asks_of_the_link(tmp_path):
    used, mod = _used_on_link()
    assert used, "the app no longer reads self.link: update this test"
    link = _link(tmp_path)
    assert [a for a in sorted(used) if not hasattr(link, a)] == []
    assert [a for a in sorted(mod) if not hasattr(offline_link, a)] == []


def test_the_app_falls_back_to_the_stand_in_when_the_link_module_is_missing():
    src = APP.read_text(encoding="utf-8")
    assert "from tools.gigbar_lights import offline_link as llano_sync" in src
    assert "except ImportError" in src


def test_a_laptop_change_lands_in_force_and_on_disk(tmp_path):
    link = _link(tmp_path)
    before = show_settings.current()
    try:
        show_settings.set_current(settings_contract.defaults())
        doc = link.local_change([{"path": "master", "value": 0.42}])
        assert doc["master"] == 0.42 and show_settings.current()["master"] == 0.42
        assert show_settings.SettingsFile(tmp_path / "settings.json").load()["master"] == 0.42
    finally:
        show_settings.set_current(before)


def test_the_window_hides_the_link_box_and_linking_says_why(tmp_path):
    link = _link(tmp_path)
    pub = link.public()
    assert pub["enabled"] is False and pub["linked"] is False and pub["online"] is False
    assert pub["line"] and pub["pending"] == 0
    with pytest.raises(offline_link.LinkError, match="this laptop"):
        link.link("ABCDE12345")
    with pytest.raises(offline_link.LinkError, match="song folder on this laptop"):
        link.drive_folders()
    assert link.unlink() == link.landed_ok() == link.public()


def test_the_stand_in_never_opens_a_socket(tmp_path, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("offline_link opened a socket")
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    link = _link(tmp_path)
    link.start()
    link.public()
    link.stop()


def test_the_fallback_import_picks_the_stand_in(monkeypatch):
    import tools.gigbar_lights as pkg
    monkeypatch.setitem(sys.modules, "tools.gigbar_lights.llano_sync", None)   # import now raises ImportError
    monkeypatch.delattr(pkg, "llano_sync", raising=False)
    ns: dict = {}
    exec("try:\n    from tools.gigbar_lights import llano_sync\nexcept ImportError:\n"
         "    from tools.gigbar_lights import offline_link as llano_sync\n", ns)
    assert ns["llano_sync"] is importlib.import_module("tools.gigbar_lights.offline_link")


def test_a_held_laptop_moment_never_breaks_the_window_line(tmp_path):
    """A moment picked on the laptop holds with no end (until = infinity): not a draft, and no crash."""
    link = _link(tmp_path)
    try:
        show_settings.set_play(settings_contract.normalize_style({}), float("inf"), label="First dance")
        assert link.public()["draft"] == {"playing": False, "left": 0}
    finally:
        show_settings.clear_play()
