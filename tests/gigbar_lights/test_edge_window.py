"""The app window's Edge launch: no extensions, no sync, its own profile (1.2.1)."""
import json
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(APP))
    import gigbar_app
    monkeypatch.setattr(gigbar_app, "app_data_dir", lambda: tmp_path)
    return gigbar_app


def test_edge_runs_without_extensions_or_sync(app, tmp_path):
    cmd = app.edge_command(Path("msedge.exe"), "http://127.0.0.1:8765/", app.window_profile())
    assert "--app=http://127.0.0.1:8765/" in cmd
    assert "--disable-extensions" in cmd and "--disable-sync" in cmd and "--no-first-run" in cmd
    assert f"--user-data-dir={tmp_path / 'edge-window'}" in cmd


def test_profile_says_no_to_sign_in_and_old_profile_goes(app, tmp_path):
    (tmp_path / "window" / "Default" / "Extensions").mkdir(parents=True)
    profile = app.window_profile()
    assert not (tmp_path / "window").exists()
    prefs = json.loads((profile / "Default" / "Preferences").read_text())
    assert prefs["signin"]["allowed"] is False and prefs["sync"]["requested"] is False


def test_profile_prefs_written_once(app):
    prefs = app.window_profile() / "Default" / "Preferences"
    prefs.write_text('{"edge": "own"}')  # Edge's own later writes are kept
    app.window_profile()
    import json
    d = json.loads(prefs.read_text())
    assert d["edge"] == "own"
    # 1.10.0: a hard-closed window never comes back as a second one (his recording, 9:11)
    assert d["profile"] == {"exit_type": "Normal", "exited_cleanly": True}
    before = prefs.stat().st_mtime_ns
    app.window_profile()
    assert prefs.stat().st_mtime_ns == before     # already clean: not rewritten


def test_open_window_uses_one_edge_process(app, monkeypatch):
    calls = []
    monkeypatch.setattr(app.sys, "platform", "win32")
    monkeypatch.setattr(app, "find_edge", lambda: Path("msedge.exe"))
    monkeypatch.setattr(app.subprocess, "Popen", lambda cmd, **kw: calls.append(cmd) or "proc")
    monkeypatch.setattr(app.webbrowser, "open", lambda *a, **k: pytest.fail("no default browser"))
    assert app.open_window("http://127.0.0.1:8765/") == "proc"
    assert len(calls) == 1 and "--disable-extensions" in calls[0]


def test_check_for_updates_states(app, monkeypatch):
    """The window's button: Up to date, Update available, or Can't reach the update server."""
    a = app.App.__new__(app.App)
    a.offer, a.update_state, a.update_note = None, "current", ""
    import threading
    a.lock = threading.Lock()
    for answer, state in (((None, "Llano Lights 1.2.1 is the newest version"), "current"),
                          ((None, app.updater.UNREACHABLE), "unreachable"),
                          (("offer", "Llano Lights 1.2.2 is ready"), "offered")):
        monkeypatch.setattr(app.updater, "check", lambda answer=answer: answer)
        a.check_update()
        assert a.update_state == state


def test_sign_in_page_reads_as_unreachable(app, monkeypatch):
    import io
    page = io.BytesIO(b"<!DOCTYPE html><html>Sign in</html>")
    monkeypatch.setattr(app.updater, "_get", lambda url, t: page)
    offer, note = app.updater.check("https://example.invalid/latest.json")
    assert offer is None and note.startswith("Can't reach the update server yet")


def test_window_page_has_an_icon(app):
    for name, _ in app.ICONS.values():
        assert (app.ICON_DIR / name).stat().st_size > 0
    html = app.APP_HTML.read_text()
    assert 'rel="icon"' in html and "Check for updates" in html


def test_check_for_updates_button_posts_its_action(app):
    html = app.APP_HTML.read_text()
    assert '$("#checkupd").addEventListener("click", () => post("/api/check-update"))' in html
