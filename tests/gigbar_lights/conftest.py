"""The fast subset (Llano PM #22425): `pytest -m "not slow"` is what the test channel runs before it
publishes a test build on every merge, so a fix reaches the laptop in minutes. The full suite still
runs on every pull request and on main (.github/workflows/tests.yml), and a release still needs it.
Slow = measured over about a second each (pytest --durations): the per-move aim sweep and the swap
rollbacks that wait out their timeouts."""
import os
import random
import socket

import pytest


def _free_port_base() -> int:
    """A port base whose whole span is free right now, well away from the laptop's 8765-8799 and
    below Linux's ephemeral range (Llano BL #12427). On a shared host other services and other
    sessions' app copies hold 8765-8784, so a suite that used them found no free port and the test
    channel published nothing. Random, so two suites at once rarely meet."""
    from tools.gigbar_lights import ports
    rng = random.Random()
    for _ in range(200):
        b = rng.randrange(20000, 32000 - ports.SPAN, ports.SPAN)
        held = []
        try:
            for port in range(b, b + ports.SPAN):
                s = socket.socket()
                held.append(s)
                s.bind(("0.0.0.0", port))
            return b
        except OSError:
            continue
        finally:
            for s in held:
                s.close()
    return ports.DEFAULT_BASE


# Before any test imports the app (its port ranges are fixed at import). A base set by the caller
# (the test channel's publish) wins; apps a test starts as a child inherit it.
if not os.environ.get("LLANO_LIGHTS_PORT_BASE"):
    os.environ["LLANO_LIGHTS_PORT_BASE"] = str(_free_port_base())
    import importlib

    from tools.gigbar_lights import ports as _ports
    importlib.reload(_ports)   # the pick imported it at the default base

SLOW_FILES = {"test_spots_face_forward.py"}
SLOW_TESTS = {
    "test_swap_rolls_back_when_the_new_copy_cannot_move",
    "test_swap_puts_the_old_copy_back_when_the_new_one_never_comes_up",
}


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: left out of the test channel's fast subset")


def pytest_collection_modifyitems(config, items):
    for item in items:
        if item.path.name in SLOW_FILES or item.originalname in SLOW_TESTS:
            item.add_marker(pytest.mark.slow)


@pytest.fixture(autouse=True)
def _no_first_run_guide(monkeypatch):
    """The setup guide (1.21) opens on a fresh laptop's first page load. Tests written for the Live
    screen and the classic window load "/" on a fresh profile, so the guide is off unless a test
    turns it on (test_setup_guide.py does)."""
    monkeypatch.setenv("LLANO_LIGHTS_GUIDE", "0")
