"""Llano BL #12427: the test channel published nothing all night because its fast tests found no
free port in 8765-8784. On the shared host uvicorn services hold four of them and peer sessions'
app copies and suites hold the rest. Runs off the laptop now count every port from
LLANO_LIGHTS_PORT_BASE (conftest picks a free one), and the laptop, with it unset, keeps
8765-8784 and 8790-8799 exactly."""
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "gigbar_lights" / "windows" / "src"))
import gigbar_app  # noqa: E402
from tools.gigbar_lights import local_mode  # noqa: E402
from tools.gigbar_lights.venue import LayoutStore  # noqa: E402

LAPTOP_WINDOW = range(8765, 8785)
LAPTOP_LOCAL = range(8790, 8800)


def _ranges(base: "str | None") -> str:
    env = {k: v for k, v in os.environ.items() if k != "LLANO_LIGHTS_PORT_BASE"}
    if base is not None:
        env["LLANO_LIGHTS_PORT_BASE"] = base
    code = ("from tools.gigbar_lights import ports as p;"
            "print(p.WINDOW_PORTS[0], p.WINDOW_PORTS[-1], p.LOCAL_PORTS[0], p.LOCAL_PORTS[-1])")
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env={**env, "PYTHONPATH": str(ROOT)},
                          capture_output=True, text=True, check=True).stdout.split()


@pytest.mark.parametrize("base", [None, "", "abc", "80", "70000"])
def test_the_laptop_keeps_its_ports(base):
    """Unset (his laptop) or not a usable port number: the ranges every release has used."""
    assert _ranges(base) == ["8765", "8784", "8790", "8799"]


def test_a_base_moves_every_port():
    assert _ranges("21000") == ["21000", "21019", "21025", "21034"]


def test_the_suite_runs_off_the_laptop_ports():
    assert not set(gigbar_app.PORTS) & set(LAPTOP_WINDOW)
    assert not set(local_mode.LOCAL_PORTS) & set(LAPTOP_LOCAL)


def test_the_window_opens_while_other_copies_hold_every_laptop_port(tmp_path):
    """The end state: every one of 8765-8784 held (more than the ten copies the item names),
    and the app under test still gets a window server."""
    held = []
    try:
        for port in LAPTOP_WINDOW:
            s = socket.socket()
            try:
                s.bind(("127.0.0.1", port))
                s.listen()
                held.append(s)
            except OSError:
                s.close()   # already held by something else on this host: just as busy
        preview = gigbar_app.Preview("", LayoutStore(tmp_path / "layouts"))
        try:
            port = preview.server.server_port
            assert port in gigbar_app.PORTS and port not in LAPTOP_WINDOW
        finally:
            preview.server.shutdown()
            preview.server.server_close()
    finally:
        for s in held:
            s.close()
