"""Local mode (1.8.0): the phone drives the show over the room's Wi-Fi, with no internet.

Every call needs the local key; a phone can send only the show keys and scenes it needs
mid-gig; nothing works when no show is running; a new key (or unlinking from Llano) locks out
phones paired before; the key and addresses ride in the status Llano keeps, so the paired
phone can switch over by itself when the internet drops.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tools.gigbar_lights import hotspot, local_mode

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
import gigbar_app  # noqa: E402
from tools.gigbar_lights.venue import LayoutStore  # noqa: E402


def call(url, body=None, key=None):
    headers = {"Content-Type": "application/json"}
    if key is not None:
        headers["X-Llano-Key"] = key
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=headers,
                                 method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@pytest.fixture
def server(tmp_path):
    sent, running = [], {"on": True}
    srv = local_mode.LocalServer(local_mode.LocalKey(tmp_path), lambda: {"show": running["on"], "status": "ok"},
                                 lambda item: running["on"] and (sent.append(item) or True))
    assert srv.start()
    yield srv, f"http://127.0.0.1:{srv.port}/", sent, running
    srv.stop()


def test_the_page_loads_without_a_key_but_every_call_needs_it(server):
    srv, url, sent, _ = server
    code, page = call(url)
    assert code == 200 and b"studio_console.js" in page and srv.key.get().encode() not in page   # the one console (1.20.0)
    assert call(url + "api/state")[0] == 403
    assert call(url + "api/state", key="wrong-key-wrong-key")[0] == 403
    assert call(url + "api/key", {"k": "b"}, key="nope")[0] == 403
    assert sent == []
    code, body = call(url + "api/state", key=srv.key.get())
    assert code == 200 and json.loads(body)["status"] == "ok"


def test_a_phone_sends_only_the_keys_and_scenes_it_needs(server):
    srv, url, sent, _ = server
    k = srv.key.get()
    for good in ("b", "s", "t", "h", "+", "-"):
        assert call(url + "api/key", {"k": good}, key=k)[0] == 200
    for bad in ("q", "[", "a", "n", "lineup:1:down"):
        assert call(url + "api/key", {"k": bad}, key=k)[0] == 400   # never quit, retime or aim from a phone
    assert call(url + "api/scene", {"scene": "party"}, key=k)[0] == 200
    assert call(url + "api/scene", {"scene": ""}, key=k)[0] == 200
    assert call(url + "api/scene", {"scene": "rm -rf"}, key=k)[0] == 400
    assert sent == ["b", "s", "t", "h", "+", "-", "scene:party", "scene:"]


def test_nothing_works_when_no_show_runs_and_a_new_key_locks_out_old_phones(server):
    srv, url, sent, running = server
    old = srv.key.get()
    running["on"] = False
    code, body = call(url + "api/key", {"k": "b"}, key=old)
    assert code == 409 and b"start the show" in body
    new = srv.key.rotate()
    assert new != old and call(url + "api/state", key=old)[0] == 403 and call(url + "api/state", key=new)[0] == 200


def test_public_names_addresses_and_only_shares_the_key_when_asked(server):
    srv, *_ = server
    pub = srv.public()
    assert pub["on"] and pub["port"] == srv.port and "key" not in pub
    assert all(u.startswith("http://") and u.endswith(f":{srv.port}/") for u in pub["urls"])
    assert not any(a.startswith("127.") for a in pub["addresses"])
    assert srv.public(with_key=True)["key"] == srv.key.get()


def test_the_wifi_code_and_the_hotspot_refuse_plainly_off_windows(tmp_path):
    pw = hotspot.password(tmp_path)
    assert 8 <= len(pw) <= 63 and hotspot.password(tmp_path) == pw          # the same password next time
    assert hotspot.wifi_qr_text("Llano Lights", "a;b") == "WIFI:T:WPA;S:Llano Lights;P:a\\;b;;"
    if sys.platform != "win32":
        ok, why = hotspot.start(tmp_path)
        assert not ok and "Windows" in why


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(gigbar_app.updater, "check", lambda: (None, "no update in tests"))
    monkeypatch.setattr(gigbar_app, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(local_mode.LocalKey, "__init__", lambda self, root=None: setattr(self, "path", tmp_path / "local_key.json"))
    opts = argparse.Namespace(seconds=0.0, bpm=128.0, no_browser=True, no_window=True, updated=False, update_failed=False)
    a = gigbar_app.App(opts, gigbar_app.LogBuffer(tmp_path / "log.txt"))
    a.preview = gigbar_app.Preview("", LayoutStore(tmp_path / "layouts"), app=a)
    yield a
    a.local.stop()
    a.stop()
    if a.runner:
        a.runner.join(timeout=8)
    a.preview.close()


def test_the_app_serves_the_phone_page_hands_keys_to_the_show_and_tells_llano_where_it_is(app):
    app.set_local(True)
    lc = app.state()["local"]
    assert lc["on"] and lc["pref"] and lc["key"] and app.local.page.name == "remote.html"
    url = f"http://127.0.0.1:{lc['port']}/"
    assert call(url, None)[0] == 200
    assert call(url + "api/key", {"k": "b"}, key=lc["key"])[0] == 409          # nothing running yet
    assert app.run("demo")[0] == 200
    end = time.monotonic() + 6
    while app.state()["live"] is None and time.monotonic() < end:
        time.sleep(0.05)
    assert call(url + "api/key", {"k": "b"}, key=lc["key"])[0] == 200
    end = time.monotonic() + 3
    while not app.state()["live"]["blackout"] and time.monotonic() < end:
        time.sleep(0.05)
    assert app.state()["live"]["blackout"]
    st = json.loads(call(url + "api/state", key=lc["key"])[1])
    assert st["show"] and st["live"]["blackout"] and "log" not in st and "local" not in st
    assert app._sync_status(False)["local"]["key"] == lc["key"]
    app.post("llano-unlink", {})
    assert app.local.key.get() != lc["key"]                                     # unlinking locks out the old phone
    app.set_local(False)
    assert app.state()["local"]["on"] is False and "local" not in app._sync_status(False)
    assert app._prefs()["local"] is False


def test_qr_codes_are_svg_or_absent():
    svg = gigbar_app.qr_svg("http://192.168.137.1:8790/#k=abc")
    assert svg == "" or svg.lstrip().startswith(("<?xml", "<svg"))
    assert gigbar_app.qr_svg("") == ""


def _raw(url, method="GET", headers=None):
    req = urllib.request.Request(url, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers)


def test_the_phone_app_on_llano_app_may_call_it_straight_and_nobody_else_can_read_it(server, monkeypatch):
    """One phone app (Llano PM #22371): llano.app/lights calls this server straight once Chrome's
    local network permission is allowed. Only llano.app may read the answers, and the key is
    still needed for every call."""
    srv, url, sent, _ = server
    pre = {"Origin": "https://llano.app", "Access-Control-Request-Method": "POST",
           "Access-Control-Request-Headers": "x-llano-key,content-type", "Access-Control-Request-Private-Network": "true"}
    code, h = _raw(url + "api/scene", "OPTIONS", pre)
    assert code == 204 and h["Access-Control-Allow-Origin"] == "https://llano.app"
    assert "X-Llano-Key" in h["Access-Control-Allow-Headers"] and h["Access-Control-Allow-Private-Network"] == "true"
    code, h = _raw(url + "api/state", headers={"Origin": "https://llano.app", "X-Llano-Key": srv.key.get()})
    assert code == 200 and h["Access-Control-Allow-Origin"] == "https://llano.app"
    code, h = _raw(url + "api/state", headers={"Origin": "https://llano.app"})
    assert code == 403                                   # the origin alone opens nothing
    for stranger in ("https://evil.example", "http://llano.app", "https://llano.app.evil.example", "null"):
        code, h = _raw(url + "api/scene", "OPTIONS", {**pre, "Origin": stranger})
        assert "Access-Control-Allow-Origin" not in h, stranger
        code, h = _raw(url + "api/state", headers={"Origin": stranger, "X-Llano-Key": srv.key.get()})
        assert "Access-Control-Allow-Origin" not in h, stranger
    monkeypatch.setenv("LLANO_LIGHTS_APP_ORIGINS", "https://dev.example, javascript:x, http://localhost:5173")
    assert local_mode.app_origins() == {"https://llano.app", "https://dev.example", "http://localhost:5173"}
    assert sent == []



# --- Stop the show over Wi-Fi (1.15.0, Llano BL #11606) --------------------------------------------

def test_the_phone_can_stop_the_show_with_the_key_and_an_old_app_says_it_cannot(tmp_path):
    stops = []
    srv = local_mode.LocalServer(local_mode.LocalKey(tmp_path), lambda: {"show": True}, lambda item: True,
                                 stop=lambda: stops.append(1) or {"note": "nothing was running"})
    assert srv.start()
    try:
        url = f"http://127.0.0.1:{srv.port}/"
        assert call(url + "api/stop", {}, key="nope")[0] == 403 and stops == []
        code, body = call(url + "api/stop", {}, key=srv.key.get())
        assert code == 200 and json.loads(body) == {"ok": True, "note": "nothing was running"} and stops == [1]
    finally:
        srv.stop()
    old = local_mode.LocalServer(local_mode.LocalKey(tmp_path), lambda: {}, lambda item: True)
    assert old.start()
    try:
        assert call(f"http://127.0.0.1:{old.port}/api/stop", {}, key=old.key.get())[0] == 501
    finally:
        old.stop()


def test_the_phone_stops_a_running_show_over_wifi_and_the_page_has_the_button(app):
    app.set_local(True)
    lc = app.state()["local"]
    url = f"http://127.0.0.1:{lc['port']}/"
    assert b"/api/stop" in call(url)[1] and b'data-act="stop"' in call(url + "studio_console.js")[1]   # the console's STOP (1.20.0)
    assert app.run("demo")[0] == 200
    end = time.monotonic() + 6
    while app.state()["live"] is None and time.monotonic() < end:
        time.sleep(0.05)
    assert app.running == "demo"
    assert call(url + "api/stop", {}, key=lc["key"])[0] == 200
    end = time.monotonic() + 10
    while app.running and time.monotonic() < end:
        time.sleep(0.05)
    assert app.running is None


def test_a_stop_from_llano_older_than_this_show_is_ignored_and_a_new_one_stops_it(app):
    assert app.run("demo")[0] == 200
    end = time.monotonic() + 6
    while app.state()["live"] is None and time.monotonic() < end:
        time.sleep(0.05)
    app._llano_stop(age_s=app_age(app) + 30)                     # pressed before this show began
    time.sleep(0.3)
    assert app.running == "demo"
    app._llano_stop(age_s=0.0)
    end = time.monotonic() + 10
    while app.running and time.monotonic() < end:
        time.sleep(0.05)
    assert app.running is None
    app._llano_stop(age_s=0.0)                                   # nothing running: nothing happens


def app_age(app):
    return time.monotonic() - app.run_started


# --- The laptop's own Wi-Fi button always answers (Llano BL #12109) ---------------------------------

def test_a_windows_hotspot_request_with_no_answer_gives_up_plainly(tmp_path, monkeypatch):
    import asyncio

    async def never(pw):
        await asyncio.sleep(3600)
    monkeypatch.setattr(hotspot, "_on_windows", lambda: True)
    monkeypatch.setattr(hotspot, "_start", never)
    t0 = time.monotonic()
    ok, why = hotspot.start(tmp_path, timeout=0.3)
    assert not ok and "didn't answer" in why and "phone's hotspot" in why and time.monotonic() - t0 < 3


def test_the_hotspot_press_answers_at_once_starts_once_and_tells_llano_what_windows_said(app, monkeypatch):
    import threading
    gate, calls = threading.Event(), []

    def slow_start():
        calls.append(1)
        gate.wait(5)
        return False, "Windows refused (no Wi-Fi adapter). Use your phone's hotspot or a travel router instead"
    monkeypatch.setattr(gigbar_app.hotspot, "start", slow_start)
    code, body = app.post("hotspot", {})
    assert code == 200 and body["starting"] is True
    hs = app.state()["local"]["hotspot"]
    assert hs["starting"] and "Starting" in hs["note"] and not hs["on"]
    assert app._sync_status(False)["hotspot"]["starting"] is True
    assert app.post("hotspot", {})[1]["starting"] is True                     # a second press starts nothing more
    gate.set()
    end = time.monotonic() + 5
    while app.state()["local"]["hotspot"]["starting"] and time.monotonic() < end:
        time.sleep(0.02)
    hs = app.state()["local"]["hotspot"]
    assert calls == [1] and not hs["starting"] and not hs["on"] and "no Wi-Fi adapter" in hs["note"]
    assert "no Wi-Fi adapter" in app._sync_status(False)["hotspot"]["note"]   # Llano can read what Windows said


def test_the_hotspot_button_shows_the_press_and_windows_answer_on_screen(app, monkeypatch):
    pw = pytest.importorskip("playwright.sync_api")
    import threading
    gate = threading.Event()
    monkeypatch.setattr(gigbar_app.hotspot, "start", lambda: (gate.wait(5), (False, "Windows refused (test)"))[1])
    app.set_local(True)
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no headless chromium: {e}")
        try:
            page = browser.new_page()
            # the hotspot panel is in the classic window, which is Set up (/setup) since 1.20.0 made the
            # Live screen the front page; "/" has no #localbody any more
            page.goto(app.preview.url.rstrip("/") + "/setup")
            page.wait_for_selector("#hotspot")
            assert page.inner_text("#hotspot") == "Start hotspot" and page.query_selector("#hssettings") is None
            page.click("#hotspot")
            page.wait_for_function("document.querySelector('#hotspot').disabled", timeout=500)  # at once, no poll needed
            assert "Starting" in page.inner_text("#hotspot")
            gate.set()
            page.wait_for_selector("#hsnote.bad", timeout=8000)
            assert "didn't start" in page.inner_text("#hsnote") and "Windows refused (test)" in page.inner_text("#hsnote")
            assert not page.is_disabled("#hotspot") and "again" in page.inner_text("#hotspot")
            # the fallback is one press away, and a hotspot he turns on in Windows shows its name and password
            opened = []
            monkeypatch.setattr(gigbar_app.hotspot, "open_settings", lambda: (opened.append(1), True)[1])
            page.click("#hssettings")
            page.wait_for_function("true", timeout=500)
            end = time.monotonic() + 3
            while not opened and time.monotonic() < end:
                time.sleep(0.05)
            assert opened == [1]
            monkeypatch.setattr(gigbar_app.hotspot, "status", lambda: {"on": True, "ssid": "DJ-LAPTOP 4417", "password": "fern-88-lamp"})
            app.check_hotspot()
            page.wait_for_selector("#hsnet", timeout=8000)
            said = page.inner_text("#hsnet")
            assert "DJ-LAPTOP 4417" in said and "fern-88-lamp" in said and page.inner_text("#hotspot") == "Hotspot is on"
            assert page.query_selector("#hssettings") is None and page.query_selector("#hsnote") is None
            # two codes, never three (his ask on 1.19.4): 1 joins the Wi-Fi with the password inside the
            # code, so the camera joins with no typing, the password small under it; 2 opens Llano Lights
            figs = page.eval_on_selector_all("#localbody figure", """fs => fs.map(f => ({
                cap: f.querySelector('figcaption').innerText, sub: (f.querySelector('.sub') || {}).innerText || '',
                d: decodeURIComponent(new URL(f.querySelector('img').src).searchParams.get('d'))}))""")
            if app.state()["local"]["urls"]:
                assert len(figs) == 2, figs
                assert figs[0]["cap"].startswith('1. Join the Wi-Fi "DJ-LAPTOP 4417"') and figs[0]["sub"] == "Password, if it asks: fern-88-lamp"
                assert figs[0]["d"] == "WIFI:T:WPA;S:DJ-LAPTOP 4417;P:fern-88-lamp;;"
                assert figs[1]["cap"].startswith("2. Open Llano Lights") and figs[1]["d"].startswith("https://llano.app/lights#k=")
                assert "No app yet" not in page.inner_text("#localbody")
                assert app.state()["local"]["urls"][0].split("#")[0] in page.inner_text("#localbody code")   # the typed fallback stays
        finally:
            browser.close()


def test_a_refused_hotspot_says_why_and_opens_windows_own_hotspot_screen(app, monkeypatch):
    """His ask, 2026-11-13: if Windows refuses, say so plainly and open Windows hotspot settings."""
    opened = []
    monkeypatch.setattr(gigbar_app.hotspot, "start", lambda: (False, "The laptop has no internet connection, and Windows usually won't start a hotspot without one. Windows refused (NoWwan). Use your phone's hotspot or a travel router instead: join the laptop and the phone to it."))
    monkeypatch.setattr(gigbar_app.hotspot, "open_settings", lambda: (opened.append(1), True)[1])
    asked = []
    monkeypatch.setattr(gigbar_app.hotspot, "status", lambda: (asked.append(1), {"on": False, "ssid": "", "password": ""})[1])
    app.check_hotspot()
    assert asked == [], "Windows is only asked about a hotspot after a refused start"
    app.start_hotspot()
    hs = app.state()["local"]["hotspot"]
    assert opened == [1] and hs["settings"] is True and not hs["on"] and not hs["starting"]
    assert "no internet connection" in hs["note"] and "hotspot screen is open" in hs["note"]
    assert app._sync_status(False)["hotspot"]["settings"] is True   # Llano can read that the fallback was offered
    app.check_hotspot()
    assert asked == [1] and not app.state()["local"]["hotspot"]["on"]   # still off in Windows: nothing changes
    # he turns it on in Windows: the window shows that network's own name and password, and its join code
    monkeypatch.setattr(gigbar_app.hotspot, "status", lambda: {"on": True, "ssid": "DJ-LAPTOP 4417", "password": "fern;88"})
    app.check_hotspot()
    hs = app.state()["local"]["hotspot"]
    assert hs["on"] and hs["note"] == "" and hs["settings"] is False
    assert (hs["ssid"], hs["password"], hs["qr"]) == ("DJ-LAPTOP 4417", "fern;88", "WIFI:T:WPA;S:DJ-LAPTOP 4417;P:fern\\;88;;")
    assert app.post("hotspot", {})[1] == {"ok": True, "starting": False, "on": True}   # nothing more to start


def test_the_windows_hotspot_screen_button_says_so_when_it_cannot_open(app, monkeypatch):
    monkeypatch.setattr(gigbar_app.hotspot, "open_settings", lambda: False)
    code, body = app.post("hotspot-settings", {})
    assert code == 400 and "Mobile hotspot" in body["error"]
    monkeypatch.setattr(gigbar_app.hotspot, "open_settings", lambda: True)
    assert app.post("hotspot-settings", {}) == (200, {"ok": True})
    # a refusal Windows' screen could not be opened for still shows its reason, with no false promise
    monkeypatch.setattr(gigbar_app.hotspot, "start", lambda: (False, "Windows refused (test)."))
    monkeypatch.setattr(gigbar_app.hotspot, "open_settings", lambda: (_ for _ in ()).throw(OSError("no shell")))
    app.start_hotspot()
    hs = app.state()["local"]["hotspot"]
    assert hs["note"] == "Windows refused (test)." and hs["settings"] is False


def _fake_winrt(monkeypatch, internet, profiles, manager):
    import sys
    import types
    conn, ops = types.ModuleType("connectivity"), types.ModuleType("networkoperators")
    conn.NetworkInformation = types.SimpleNamespace(get_internet_connection_profile=lambda: internet,
                                                    get_connection_profiles=lambda: profiles)
    ops.NetworkOperatorTetheringManager = types.SimpleNamespace(create_from_connection_profile=manager)
    ops.TetheringOperationStatus = types.SimpleNamespace(SUCCESS="ok")
    ops.TetheringOperationalState = types.SimpleNamespace(ON="on", OFF="off")
    for name, mod in (("winrt", types.ModuleType("winrt")), ("winrt.windows", types.ModuleType("w")),
                      ("winrt.windows.networking", types.ModuleType("n")),
                      ("winrt.windows.networking.connectivity", conn), ("winrt.windows.networking.networkoperators", ops)):
        monkeypatch.setitem(sys.modules, name, mod)


def test_a_start_windows_refuses_with_no_internet_names_the_missing_internet(tmp_path, monkeypatch):
    import asyncio
    import types

    def refuses(profile):
        raise OSError("The device is not ready")
    _fake_winrt(monkeypatch, None, [object()], refuses)
    why = asyncio.run(hotspot._start("pw-12345"))
    assert why.startswith(hotspot.NO_INTERNET) and "Windows refused" in why
    _fake_winrt(monkeypatch, object(), [], refuses)
    assert not asyncio.run(hotspot._start("pw-12345")).startswith(hotspot.NO_INTERNET)   # online: only what Windows said
    # and Windows' own state is read from whichever connection can say: on, with its name and password
    cfg = types.SimpleNamespace(ssid="DJ-LAPTOP 4417", passphrase="fern-88-lamp")
    on = types.SimpleNamespace(tethering_operational_state="on", get_current_access_point_configuration=lambda: cfg)
    off = types.SimpleNamespace(tethering_operational_state="off", get_current_access_point_configuration=lambda: cfg)
    _fake_winrt(monkeypatch, None, ["a", "b"], lambda prof: refuses(prof) if prof == "a" else on)
    assert asyncio.run(hotspot._status()) == {"on": True, "ssid": "DJ-LAPTOP 4417", "password": "fern-88-lamp"}
    _fake_winrt(monkeypatch, None, ["a"], lambda prof: off)
    assert asyncio.run(hotspot._status()) == hotspot.OFF
    # off Windows nothing is asked and nothing opens
    assert hotspot.status() == hotspot.OFF and hotspot.open_settings() is False
    monkeypatch.setattr(hotspot, "_on_windows", lambda: True)
    monkeypatch.setattr(hotspot, "_status", lambda: (_ for _ in ()).throw(RuntimeError("no WinRT")))
    assert hotspot.status() == hotspot.OFF   # never raises into the app


# --- the Light studio over Wi-Fi (1.20.0, Llano PM #23195): the same buttons as every other path ------

@pytest.fixture
def studio_app(app, tmp_path, monkeypatch):
    from tools.gigbar_lights import studio
    monkeypatch.setattr(app.settings_file, "path", tmp_path / "settings.json", raising=False)
    app.studio = studio.Studio(path=tmp_path / "studio.json", live=True)
    app.local.studio = app.studio_post
    app.set_local(True)
    lc = app.state()["local"]
    return app, f"http://127.0.0.1:{lc['port']}/", lc["key"]


def test_the_phone_draws_the_same_console_from_the_same_state_over_wifi(studio_app):
    app, url, key = studio_app
    code, js = call(url + "studio_console.js")
    assert code == 200 and js == gigbar_app.STUDIO_JS.read_bytes(), "the same bytes the laptop's Live screen draws"
    assert call(url + "api/studio", {"op": "look", "key": "simple:house"}, key="wrong")[0] == 403
    assert app.running is None and app.studio.look is None
    code, body = call(url + "api/studio", {"op": "look", "key": "simple:house"}, key=key)
    assert code == 200 and json.loads(body)["studio"]["look"]["name"] == "House lights" and app.running == "scenes"
    end = time.monotonic() + 6
    while not any(app.preview.universe) and time.monotonic() < end:
        time.sleep(0.05)
    st = json.loads(call(url + "api/state", key=key)[1])
    assert st["studio"]["look"]["key"] == "simple:house" and st["catalog"]["pages"] and st["running"] == "scenes"
    assert st["studio"]["spots"]["plan"]["room"] and st["studio"]["spots"]["views"]["phone"] == {"from": "booth", "turn": 0}
    assert st["glow"]["lamps"] and st["glow"]["pools"], "the room's light, for the phone's picture"
    # a refused command says why, in the app's words
    code, body = call(url + "api/studio", {"op": "look", "key": "simple:nope"}, key=key)
    assert code == 400 and json.loads(body)["error"] == "no such look"
    # the phone's own view of the room
    assert call(url + "api/studio", {"op": "view", "screen": "phone", "from": "floor"}, key=key)[0] == 200
    assert json.loads(call(url + "api/state", key=key)[1])["studio"]["spots"]["views"]["phone"]["from"] == "floor"


def test_settings_read_and_change_over_wifi_with_no_internet(studio_app):
    app, url, key = studio_app
    assert call(url + "api/settings")[0] == 403
    code, body = call(url + "api/settings", key=key)
    doc = json.loads(body)["settings"]
    assert code == 200 and "palettes" in doc and "strobe" in doc
    was = doc["strobe"]["build_ramp"]
    code, body = call(url + "api/settings", {"ops": [{"path": "strobe.build_ramp", "value": not was}]}, key=key)
    assert code == 200, body
    assert json.loads(body)["settings"]["strobe"]["build_ramp"] is (not was)
    assert gigbar_app.show_settings.current()["strobe"]["build_ramp"] is (not was), "in force on the laptop at once"
    code, body = call(url + "api/settings", {"ops": [{"path": "no.such.setting", "value": 1}]}, key=key)
    assert code == 400 and json.loads(body)["error"]
    assert call(url + "api/settings", {"ops": []}, key=key)[0] == 400
    call(url + "api/settings", {"ops": [{"path": "strobe.build_ramp", "value": was}]}, key=key)


def test_the_live_show_starts_from_the_phone_over_wifi_or_says_why_not(studio_app, monkeypatch):
    app, url, key = studio_app
    monkeypatch.setattr(gigbar_app, "connections", lambda *a, **k: {
        "enttec": {"ok": False, "detail": ""}, "loopmidi": {"ok": True, "detail": ""}, "mixxx": {"ok": True, "detail": ""}})
    # no lights box never locks him out (2026-11-13): the show starts, with the calm note
    code, body = call(url + "api/go", {"mode": "live"}, key=key)
    assert code == 200, body
    end = time.monotonic() + 6
    while app.running != "live" and time.monotonic() < end:
        time.sleep(0.05)
    assert app.running == "live"
    w = json.loads(call(url + "api/state", key=key)[1])["warning"]
    assert w["lights"] is True and w["text"].startswith("Lights not connected")
    app.stop()
    end = time.monotonic() + 4
    while app.running is not None and time.monotonic() < end:
        time.sleep(0.05)
    assert app.running is None
    assert call(url + "api/go", {"mode": "analyze"}, key=key)[0] == 400
    assert call(url + "api/go", {"mode": "preview"}, key="wrong")[0] == 403


def test_a_laptop_from_before_the_studio_says_so_instead_of_failing(server):
    srv, url, sent, _ = server   # a LocalServer made with no studio door
    code, body = call(url + "api/studio", {"op": "blackout"}, key=srv.key.get())
    assert code == 501 and json.loads(body)["error"]
