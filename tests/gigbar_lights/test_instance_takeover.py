"""An older copy that is still open must not stand in for this one (1.2.2): he unzipped 1.2.1 and
ran Setup while 1.1.0 ran, and every 1.2.1 launch just brought up the 1.1.0 window."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "tools" / "gigbar_lights" / "windows" / "src"
APP = SRC


@pytest.fixture
def app(monkeypatch):
    monkeypatch.syspath_prepend(str(APP))
    import gigbar_app
    return gigbar_app


def test_same_copy_needs_same_version_and_folder(app, monkeypatch):
    monkeypatch.setattr(app.updater, "install_root", lambda: Path("C:/Llano-Lights"))
    assert app.same_copy({"version": app.VERSION, "root": "C:/Llano-Lights"})
    assert app.same_copy({"version": app.VERSION})  # can't tell the folder: the version decides
    assert not app.same_copy({"version": "1.1.0"})  # 1.1.0 and 1.2.1 send no folder
    assert not app.same_copy({"version": app.VERSION, "root": "C:/Users/x/Downloads/Llano-Lights"})


def test_close_other_quits_an_old_copy_with_its_page_token(app):
    got = {}

    class Old(BaseHTTPRequestHandler):  # what 1.1.0 to 1.2.1 serve
        def log_message(self, *a):
            pass

        def do_GET(self):
            if got.get("quit"):
                self.send_response(404)
                self.end_headers()
                return
            body = (b'<meta name="llano-token" content="tok123">' if self.path == "/"
                    else json.dumps({"product": "llano-lights", "version": "1.1.0"}).encode())
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            got["quit"] = self.path == "/api/quit" and self.headers.get("X-Llano-Token") == "tok123"
            self.send_response(200 if got["quit"] else 403)
            self.end_headers()
            self.wfile.write(b"{}")
            if got["quit"]:
                threading.Thread(target=srv.shutdown, daemon=True).start()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Old)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    try:
        assert app.close_other(url, wait_s=5) is True
        assert got["quit"] is True
    finally:
        srv.server_close()


def test_state_says_which_folder_runs(app):
    import inspect
    assert '"root": str(updater.install_root())' in inspect.getsource(app.App.state)
