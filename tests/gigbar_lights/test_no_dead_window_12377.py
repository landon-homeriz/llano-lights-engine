"""No dead window after Update (Llano BL #12377).

His 11-14 report from the Dell laptop (1.20.1): running the show, he pressed Update, the app stopped
answering his presses, and the window showed Edge's "Hmmm... can't reach this page, 127.0.0.1 refused
to connect". Three causes, each pinned here:
  1. the whole download refused every show press ("an update is being installed");
  2. a window on any page but the Live screen or Set up (Shows, the guide, Line up) didn't carry the
     app's title, so the update's close missed it and it sat on the dead engine;
  3. any page load with the engine down was Edge's own error page.
"""
import json
import threading
import types
import urllib.request
from pathlib import Path

import pytest

from test_studio_app import call, close, make, post, wait_stopped

import gigbar_app  # noqa: E402  (test_studio_app put the app folder on the path)
from tools.gigbar_lights import windows_apps  # noqa: E402

SRC = Path(gigbar_app.__file__).resolve().parent
PAGES = {"/": None, "/setup": None, "/shows": "Shows", "/guide": "Set up guide", "/preview": "preview"}


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    app = make(tmp_path_factory.mktemp("bl12377"), mp)
    yield app
    close(app)
    mp.undo()


@pytest.fixture
def app(served):
    yield served
    served.stop()
    wait_stopped(served)
    served.update_state, served.staged, served.offer = "current", None, None
    served.quit.clear()


def h(app):
    return {"X-Llano-Token": app.preview.token, "Content-Type": "application/json"}


def fake_update(monkeypatch, swaps):
    offer = types.SimpleNamespace(version="9.9.9", notes="", built="", channel="stable")
    monkeypatch.setattr(gigbar_app.updater, "prepare", lambda o, progress=None: ["swap", o.version])
    monkeypatch.setattr(gigbar_app.updater, "launch_swap", lambda cmd: swaps.append(cmd))
    return offer


# 1. the show keeps answering while an update downloads, and nothing restarts under it

def test_a_show_starts_while_an_update_downloads(app):
    app.update_state = "downloading"
    code, out = post(app.preview.url, h(app), {"op": "look", "key": "simple:house"})
    assert code == 200, out
    assert app.running == "scenes"


def test_an_update_that_lands_during_a_show_waits_for_install_now(app, monkeypatch):
    swaps = []
    offer = fake_update(monkeypatch, swaps)
    assert post(app.preview.url, h(app), {"op": "look", "key": "simple:house"})[0] == 200
    app.offer, app.update_state = offer, "downloading"   # as start_update leaves it
    app._update(offer)                      # the download finishes while the scenes run
    assert app.update_state == "ready" and not swaps and not app.quit.is_set()
    code, out = app.post("install-update", {})
    assert code == 409 and "Stop the show" in out["error"]
    assert not swaps and app.running == "scenes"
    st = json.loads(call(app.preview.url + "api/studio")[1])
    assert st["update"]["state"] == "ready" and st["update"]["version"] == "9.9.9"
    app.stop()
    wait_stopped(app)
    code, out = app.post("install-update", {})
    assert code == 200
    for _ in range(50):
        if app.quit.is_set():
            break
        threading.Event().wait(0.05)
    assert swaps == [["swap", "9.9.9"]] and app.quit.is_set()


def test_an_update_with_nothing_running_installs_as_before(app, monkeypatch):
    swaps = []
    offer = fake_update(monkeypatch, swaps)
    app.update_state = "downloading"
    app._update(offer)
    assert swaps == [["swap", "9.9.9"]] and app.update_state == "restarting" and app.quit.is_set()


def test_nothing_starts_once_the_restart_is_under_way(app):
    app.update_state = "restarting"
    code, out = app.run("scenes")
    assert code == 409 and "restarting into the update" in out["error"]
    assert app.running is None


def test_update_and_go_back_refuse_during_a_show(app):
    assert post(app.preview.url, h(app), {"op": "look", "key": "simple:house"})[0] == 200
    app.offer = types.SimpleNamespace(version="9.9.9", notes="", built="")
    app.update_state = "offered"
    assert app.post("update", {})[0] == 409
    code, out = app.post("go-back", {})
    assert code in (400, 409)          # 400 when no stable copy is kept; never a restart mid-show
    assert app.running == "scenes" and app.update_state == "offered" and not app.quit.is_set()


def test_a_failed_install_keeps_this_version_running(app, monkeypatch):
    offer = types.SimpleNamespace(version="9.9.9", notes="", built="", channel="stable")
    monkeypatch.setattr(gigbar_app.updater, "prepare", lambda o, progress=None: ["swap"])

    def refuse(cmd):
        raise gigbar_app.updater.UpdateError("the installer didn't start, so nothing was changed")
    monkeypatch.setattr(gigbar_app.updater, "launch_swap", refuse)
    app._update(offer)
    assert app.update_state == "failed" and not app.quit.is_set()
    assert app.run("scenes")[0] == 200


# 2. every window page carries the app's title, so the update's close finds it

@pytest.mark.parametrize("path,page", PAGES.items())
def test_every_window_page_has_the_apps_title(app, path, page):
    html = call(app.preview.url + path.lstrip("/"))[1].decode()
    title = html.split("<title>", 1)[1].split("</title>", 1)[0]
    assert title == gigbar_app.window_title() + (f" · {page}" if page else "")
    assert gigbar_app.is_app_window_title(title, gigbar_app.VERSION)
    assert 'navigator.serviceWorker.register("/sw.js")' in html


def test_titles_the_close_finds_and_the_ones_it_leaves():
    t = gigbar_app.is_app_window_title
    assert t("Llano Lights 1.25.0 (built Nov 14, 2026, 7:51 PM CT) · Shows", "1.25.0")
    assert not t("Llano Lights 1.25.0 (built x) · Shows", "1.26.0")
    assert t("Llano Lights · not running", "1.25.0")       # the sw.js screen: any copy closes it
    assert t("Llano Lights 1.20.1 (built x)", "")                # a starting copy closes every version's
    assert not t("Llano Lights · Shows - Microsoft​ Edge")
    assert not t("Llano Lights 1.25.0 · Shows and 2 more pages - Personal - Microsoft Edge")


def test_the_sw_screen_title_is_one_the_close_finds():
    sw = (SRC / "sw.js").read_text(encoding="utf-8")
    title = sw.split("<title>", 1)[1].split("</title>", 1)[0]
    assert gigbar_app.is_app_window_title(title)


def test_a_starting_copy_closes_old_windows_before_opening_its_own():
    src = (SRC / "gigbar_app.py").read_text(encoding="utf-8")
    body = src.split("def gui(opts)", 1)[1]
    assert body.index("close_stale_windows()") < body.index("open_window(url)")


# 3. a page load with the engine down gets Llano Lights' own screen, offline

def test_the_service_worker_is_served_at_the_root(app):
    with urllib.request.urlopen(app.preview.url + "sw.js", timeout=5) as r:
        assert r.status == 200 and "javascript" in r.headers["Content-Type"]
        js = r.read().decode()
    assert 'e.request.mode !== "navigate"' in js           # only page loads; the API goes straight through
    assert "caches." not in js                             # nothing cached: each page has its run's token
    assert "Start Llano Lights" in js and "Try again" in js and "llano-lights:start" in js
    assert "—" not in js and "–" not in js


def test_alive_is_readable_from_another_window_port_only(app):
    def alive(origin):
        req = urllib.request.Request(app.preview.url + "api/alive", headers={"Origin": origin} if origin else {})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.load(r), r.headers.get("Access-Control-Allow-Origin")
    body, allow = alive("http://127.0.0.1:8770")
    assert body == {"product": "llano-lights", "version": gigbar_app.VERSION} and allow == "http://127.0.0.1:8770"
    assert alive("https://evil.example")[1] is None
    assert alive("http://192.168.1.5:8770")[1] is None
    assert alive("")[1] is None


class FakeReg:
    HKEY_CURRENT_USER, KEY_ALL_ACCESS, REG_SZ, REG_DWORD = "HKCU", 0, 1, 4

    def __init__(self):
        self.keys = {}

    def CreateKeyEx(self, root, key, res, access):
        reg = self

        class K:
            def __enter__(self):
                reg.keys.setdefault(key, {})
                return key

            def __exit__(self, *a):
                return False
        return K()

    def SetValueEx(self, k, name, res, kind, value):
        self.keys[k][name] = value


def test_the_start_button_link_runs_this_install(tmp_path):
    root = tmp_path / "Llano-Lights"
    assert not windows_apps.register_start_link(root, FakeReg())   # not an install: nothing written
    (root / "runtime").mkdir(parents=True)
    (root / "runtime" / "pythonw.exe").write_text("")
    (root / "app").mkdir()
    (root / "app" / "gigbar_app.py").write_text("")
    reg = FakeReg()
    assert windows_apps.register_start_link(root, reg)
    k = reg.keys[windows_apps.LINK_KEY]
    assert k[""] == "URL:Llano Lights" and k["URL Protocol"] == ""
    cmd = reg.keys[windows_apps.LINK_KEY + r"\shell\open\command"][""]
    assert cmd == f'"{root / "runtime" / "pythonw.exe"}" "{root / "app" / "gigbar_app.py"}"'


def test_uninstall_removes_the_start_link():
    ps = (SRC / "win" / "uninstall.ps1").read_text()
    assert 'Remove-Item -LiteralPath "HKCU:\\Software\\Classes\\llano-lights"' in ps


def test_the_windows_say_what_the_update_is_doing():
    studio = (SRC / "studio.html").read_text(encoding="utf-8")
    app_html = (SRC / "app.html").read_text(encoding="utf-8")
    assert 'call("/api/install-update")' in studio and 'post("/api/install-update")' in app_html
    assert "nothing restarts during a show" in studio and "nothing restarts during a show" in app_html
    assert "Installing the update. The new version opens in its own window" in studio


def test_an_update_never_restarts_over_a_room_he_has_not_saved(app, monkeypatch):
    # the 11-14 video: after an update the lights moved back to where they were before (PM #23745)
    swaps = []
    offer = fake_update(monkeypatch, swaps)
    monkeypatch.setattr(app.preview, "tried", True)   # lights moved in the Show Designer, not saved
    app.offer, app.update_state = offer, "downloading"
    app._update(offer)
    assert app.update_state == "ready" and not swaps and not app.quit.is_set()
    assert "haven't saved" in app.update_note
    code, out = app.post("install-update", {})
    assert code == 409 and "Save my layout" in out["error"] and not swaps
    monkeypatch.setattr(app.preview, "tried", False)  # saved (or Reset)
    code, out = app.post("install-update", {})
    assert code == 200
    for _ in range(50):
        if app.quit.is_set():
            break
        threading.Event().wait(0.05)
    assert swaps == [["swap", "9.9.9"]]
