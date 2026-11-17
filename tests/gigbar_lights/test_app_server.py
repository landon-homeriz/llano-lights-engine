"""The Windows app's local server: only its own page, on this machine, can drive the lights."""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
import gigbar_app  # noqa: E402
from tools.gigbar_lights.venue import LayoutStore  # noqa: E402


def call(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(gigbar_app.updater, "check", lambda: (None, "no update in tests"))
    opts = argparse.Namespace(seconds=0.0, bpm=128.0, no_browser=True, no_window=True,
                              updated=False, update_failed=False)
    app = gigbar_app.App(opts, gigbar_app.LogBuffer(tmp_path / "log.txt"))
    app.preview = gigbar_app.Preview("", LayoutStore(tmp_path / "layouts"), app=app)
    yield app, app.preview.url, app.preview.token
    app.stop()
    if app.runner:
        app.runner.join(timeout=8)
    app.preview.close()


def test_page_carries_the_token_and_posts_need_it(server):
    app, url, token = server
    code, page = call(url)
    assert code == 200 and token.encode() in page and b"__LLANO_TOKEN__" not in page
    assert call(url + "key?k=b", b"")[0] == 403
    assert call(url + "api/run", b'{"mode": "demo"}', {"X-Llano-Token": "wrong"})[0] == 403
    assert app.running is None


def test_other_hosts_are_refused(server):
    _, url, token = server
    assert call(url + "api/app", headers={"Host": "attacker.example"})[0] == 403
    assert call(url + "api/app", headers={"Host": "localhost:1234"})[0] == 200


def test_one_mode_at_a_time_and_stop(server):
    app, url, token = server
    h = {"X-Llano-Token": token, "Content-Type": "application/json"}
    assert call(url + "api/run", b'{"mode": "demo"}', h)[0] == 200
    deadline = time.time() + 10
    while app.preview.frames == 0 and time.time() < deadline:
        time.sleep(0.05)
    state = json.loads(call(url + "api/app")[1])
    assert state["running"] == "demo" and state["show"]
    assert call(url + "api/run", b'{"mode": "check"}', h)[0] == 409
    assert call(url + "api/update", b"{}", h)[0] == 409  # never mid-show
    assert call(url + "api/stop", b"{}", h)[0] == 200
    app.runner.join(timeout=8)
    state = json.loads(call(url + "api/app")[1])
    assert state["running"] is None and state["last_run"].endswith("stopped")
    assert json.loads(call(url + "state")[1])["u"] == [0] * 192  # lights left dark
