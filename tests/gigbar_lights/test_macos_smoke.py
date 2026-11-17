"""The Mac smoke test (Llano BL #12517): on a real macOS (a GitHub macOS runner), the app starts,
serves its window with the per-launch token and the Host check, keeps its files in the Mac's own
place, and the Mac calls it makes (osascript, CoreMIDI, serial ports) answer. Skipped elsewhere;
test_macos_12517.py covers the same code with the Mac faked.
"""
from __future__ import annotations

import os
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="needs a real Mac")

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "tools" / "gigbar_lights" / "windows" / "src" / "gigbar_app.py"


def get(url: str, host: str = ""):
    req = urllib.request.Request(url, headers={"Host": host} if host else {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_the_app_starts_on_a_mac_and_serves_its_window(tmp_path):
    base = random.randrange(20000, 60000, 50)
    ready = tmp_path / "ready"
    env = {**os.environ, "HOME": str(tmp_path), "LLANO_LIGHTS_PORT_BASE": str(base),
           "LLANO_LIGHTS_UPDATE_URL": "http://127.0.0.1:9/latest-mac.json", "PYTHONPATH": str(REPO)}
    proc = subprocess.Popen([sys.executable, str(APP), "gui", "--no-window", "--ready-file", str(ready)],
                            cwd=str(APP.parent), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 90
        while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.2)
        assert ready.exists(), "the app never came up"
        log = (tmp_path / "Library" / "Application Support" / "Llano Lights" / "llano-lights.log").read_text()
        url = re.search(r"Window server at (http://127\.0\.0\.1:\d+/)", log).group(1)
        code, page = get(url)
        assert code == 200 and b"Llano Lights" in page and b"__LLANO_TOKEN__" not in page
        assert get(url + "api/app", host="attacker.example")[0] == 403      # the Host check holds on a Mac
        assert get(url + "api/app")[0] == 200
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_osascript_now_playing_compiles_and_answers():
    """No player is open on a runner (and Spotify isn't installed): asking must be quick and quiet,
    never osascript's "Where is Spotify?" wait. The script itself must compile on this macOS."""
    from tools.gigbar_lights import macos
    t = time.monotonic()
    assert macos.read_now_playing() == [] and time.monotonic() - t < 3
    code, _out, err = macos.osascript(macos.NOW_PLAYING, "com.apple.finder")   # compiles; Finder has no track
    assert "syntax error" not in err.lower(), err


def test_the_mac_folders_are_the_mac_ones():
    from tools.gigbar_lights import macos
    assert str(macos.app_data_dir()).endswith("Library/Application Support/Llano Lights")
    assert "Library" in str(macos.mixxx_settings_dir())


def test_coremidi_and_serial_ports_answer():
    rtmidi = pytest.importorskip("rtmidi")
    rtmidi.MidiIn().get_ports()           # CoreMIDI: the Mixxx beat link's transport
    from serial.tools import list_ports
    from tools.gigbar_lights import enttec
    list_ports.comports()
    assert enttec.find_port() is None     # no ENTTEC on a runner, and asking doesn't fail
