"""The built Mac app on a real Mac (Llano BL #12517): mac/build.py's Llano-Lights-<version>-mac.zip,
named by LLANO_LIGHTS_MAC_APP_ZIP (the engine CI's macos job builds it first). It goes in the way an
update puts it in (updater.unpack_mac: ditto, then Apple's codesign checks every signature), its
Python and every native library load on Apple Silicon and, under Rosetta, on Intel, and the app's
own launcher starts it and serves the window with its token and Host check.
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

ZIP = os.environ.get("LLANO_LIGHTS_MAC_APP_ZIP", "")
DMG = os.environ.get("LLANO_LIGHTS_MAC_DMG", "")
pytestmark = pytest.mark.skipif(sys.platform != "darwin" or not ZIP, reason="needs a real Mac and a built app zip")

IMPORTS = "import numpy, rtmidi, serial, soundfile, segno, ssl, sqlite3, ctypes; print(numpy.__version__)"


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    from tools.gigbar_lights import updater
    where = tmp_path_factory.mktemp("Applications")
    return updater.unpack_mac(Path(ZIP), where / updater.MAC_APP)   # raises if codesign says no


def test_the_app_is_universal_and_its_signature_holds(app):
    from tools.gigbar_lights import updater
    for rel in (updater.MAC_LAUNCHER, f"{updater.MAC_INNER}/runtime/bin/python3"):
        archs = subprocess.run(["/usr/bin/lipo", "-archs", str(app / rel)], capture_output=True, text=True).stdout.split()
        assert sorted(archs) == ["arm64", "x86_64"], rel
    r = subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("arch", ["arm64", "x86_64"])
def test_its_python_and_native_libraries_load(app, arch):
    from tools.gigbar_lights import updater
    py = app / updater.MAC_INNER / "runtime" / "bin" / "python3"
    if arch == "x86_64" and subprocess.run(["/usr/bin/arch", "-x86_64", "/usr/bin/true"]).returncode != 0:
        pytest.skip("no Rosetta on this Mac")
    r = subprocess.run(["/usr/bin/arch", f"-{arch}", str(py), "-B", "-E", "-s", "-c", IMPORTS],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr


def test_the_launcher_starts_the_app_and_it_serves_its_window(app, tmp_path):
    from tools.gigbar_lights import updater
    base = random.randrange(20000, 60000, 50)
    ready = tmp_path / "ready"
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env.update(HOME=str(tmp_path), LLANO_LIGHTS_PORT_BASE=str(base))
    proc = subprocess.Popen([str(app / updater.MAC_LAUNCHER), "gui", "--no-window", "--ready-file", str(ready)],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 120
        while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.2)
        log_file = tmp_path / "Library" / "Application Support" / "Llano Lights" / "llano-lights.log"
        assert ready.exists(), (proc.poll(), log_file.read_text()[-3000:] if log_file.exists() else "no log")
        log = log_file.read_text()
        assert "Contents/Resources/Llano-Lights" in log   # it says where it runs from: inside the bundle
        url = re.search(r"Window server at (http://127\.0\.0\.1:\d+/)", log).group(1)
        with urllib.request.urlopen(url, timeout=5) as r:
            page = r.read()
        assert b"Llano Lights" in page and b"__LLANO_TOKEN__" not in page
        req = urllib.request.Request(url + "api/app", headers={"Host": "attacker.example"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        assert e.value.code == 403
        with urllib.request.urlopen(url + "api/app", timeout=5) as r:
            assert r.status == 200 and updater.is_installed(app / updater.MAC_INNER)
    finally:
        proc.kill()
        proc.wait(timeout=10)
    # Having run, the app is still exactly as signed: Python wrote its caches to ~/Library/Caches,
    # never into the bundle (a file added there breaks the seal).
    assert not list(app.rglob("__pycache__"))
    assert (tmp_path / "Library" / "Caches" / "Llano Lights" / "pycache").is_dir()
    r = subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(not DMG, reason="no disk image built")
def test_the_disk_image_mounts_with_the_app_and_an_applications_shortcut(tmp_path):
    """The Linux-made image (mac/dmg.py) is what a new user opens: it must mount on a real Mac and hold
    the same signed app beside a shortcut to Applications."""
    mnt = tmp_path / "mnt"
    mnt.mkdir()
    r = subprocess.run(["/usr/bin/hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mnt), DMG],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    try:
        assert (mnt / "Applications").is_symlink() and os.readlink(mnt / "Applications") == "/Applications"
        app = mnt / "Llano Lights.app"
        r = subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert os.access(app / "Contents" / "MacOS" / "Llano Lights", os.X_OK)
    finally:
        subprocess.run(["/usr/bin/hdiutil", "detach", str(mnt)], capture_output=True, timeout=60)
