"""The green "Test build N ready" banner has an X (Llano BL #12145): hidden for that build only,
kept across launches, a newer test build shows again, and the small Update stays by Check for
updates. A test build is never forced or nagged."""
from __future__ import annotations

import dataclasses
from pathlib import Path

from tools.gigbar_lights import updater

from test_update_relaunch_11612 import make_app

HTML = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src" / "app.html"


def offer(build: int) -> updater.Offer:
    return updater.Offer(version=f"1.19.3.{build}", notes="n", zip_url=f"https://x/t{build}.zip",
                         sha256="0" * 64, size=1, channel="test", build=build)


def close(a):
    a.quit.set()
    a.preview.close()


def test_the_x_hides_that_build_only_and_it_stays_hidden_after_a_relaunch(tmp_path, monkeypatch):
    a = make_app(tmp_path, monkeypatch)
    try:
        a.test_offer = offer(25)
        assert a.state()["test_offer"]["later"] is False
        assert a.post("test-hide", {}) == (200, {"ok": True})
        assert a.state()["test_offer"]["later"] is True
        assert a.test_offer is not None, "hiding never drops the offer: Update stays by Check for updates"
    finally:
        close(a)
    b = make_app(tmp_path, monkeypatch)   # the same laptop, launched again
    try:
        b.test_offer = offer(25)
        assert b.state()["test_offer"]["later"] is True, "closed stays closed for build 25"
        b.test_offer = dataclasses.replace(b.test_offer, version="1.19.3.26", build=26)
        assert b.state()["test_offer"]["later"] is False, "a newer test build shows its banner again"
    finally:
        close(b)


def test_the_x_with_no_offer_and_with_a_broken_prefs_file(tmp_path, monkeypatch):
    a = make_app(tmp_path, monkeypatch)
    try:
        assert a.post("test-hide", {}) == (200, {"ok": True})
        assert a.state()["test_offer"] is None
        a.prefs_file.write_text("not json", encoding="utf-8")
        a.test_offer = offer(25)
        assert a.post("test-hide", {}) == (200, {"ok": True})
        assert a.state()["test_offer"]["later"] is True
    finally:
        close(a)


def test_the_page_has_the_x_and_keeps_one_update_by_check_for_updates():
    html = HTML.read_text(encoding="utf-8")
    assert 'post("/api/test-hide")' in html and 'btn("\\u00d7", "close"' in html
    assert 'if (t && !t.later && !["downloading", "ready", "restarting"].includes(u.state))' in html   # ready: BL #12377
    assert "el.append(`Test build ${t.build} ready: `" in html
    assert "updateStatus(S.update, running, S.test_offer);" in html
    assert 'btn("Later", "", () => post("/api/test-' not in html
