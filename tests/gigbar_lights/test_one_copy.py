"""One copy at a time (1.8.0): he had two 1.7.0 windows open on one laptop (2026-11-08), both able to
drive the ENTTEC box on COM7 and the Mixxx MIDI port. A second launch must bring the open window
forward and exit, never open a second copy or a second window."""
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "tools" / "gigbar_lights" / "windows" / "src"


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(SRC))
    import gigbar_app
    monkeypatch.setattr(gigbar_app, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(gigbar_app, "_instance_handle", None)
    return gigbar_app


@pytest.mark.skipif(sys.platform == "win32", reason="the lock-file path; Windows uses the named mutex")
def test_a_second_process_cannot_take_the_lock(app, tmp_path):
    assert app.take_instance_lock() is True
    assert app.take_instance_lock() is True  # held already: still ours
    other = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(ROOT)!r}); sys.path.insert(0, {str(SRC)!r})
        import gigbar_app
        from pathlib import Path
        gigbar_app.app_data_dir = lambda: Path({str(tmp_path)!r})
        print(gigbar_app.take_instance_lock())
    """)
    out = subprocess.run([sys.executable, "-c", other], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip().splitlines()[-1] == "False", out.stderr


def test_only_the_app_window_title_counts(app):
    assert app.is_app_window_title("Llano Lights 1.8.0 (built Nov 8, 2026, 7:22 AM CT)")
    assert app.is_app_window_title("Llano Lights")  # before the page sets its title
    assert not app.is_app_window_title("Llano Lights and 3 more pages - Personal - Microsoft​ Edge")
    assert not app.is_app_window_title("Lights - Llano")
    # a test-channel build's window (VERSION.<build>) is the app's too (BL #12140): it was missed, so
    # opening the app again opened another window and an update never closed the old one
    assert app.is_app_window_title("Llano Lights 1.19.3.24 (built Nov 13, 2026, 4:10 AM CT)")
    assert app.is_app_window_title("Llano Lights 1.19.3.24 (built x)", "1.19.3.24")
    assert not app.is_app_window_title("Llano Lights 1.19.3.24 (built x)", "1.19.3.25")
    assert not app.is_app_window_title("Llano Lights 1.19.3.24.1 (built x)")


def _gui_opts():
    return SimpleNamespace(no_window=False, ready_file=None)


def test_second_launch_brings_the_open_window_forward_and_exits(app, monkeypatch):
    monkeypatch.setattr(app, "LogBuffer", lambda *a, **k: sys.__stdout__)
    monkeypatch.setattr(app, "take_instance_lock", lambda: False)
    monkeypatch.setattr(app, "running_instance", lambda: ("http://127.0.0.1:8765/", {"version": app.VERSION}))
    monkeypatch.setattr(app, "same_copy", lambda info: True)
    calls = []
    monkeypatch.setattr(app, "focus_window", lambda: calls.append("focus") or True)
    monkeypatch.setattr(app, "open_window", lambda url: calls.append(("open", url)))
    monkeypatch.setattr(app, "App", lambda *a: pytest.fail("a second copy started"))
    try:
        assert app.gui(_gui_opts()) == 0
    finally:
        sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
    assert calls == ["focus"]  # no second window


def test_second_launch_opens_a_window_only_when_none_is_open(app, monkeypatch):
    monkeypatch.setattr(app, "LogBuffer", lambda *a, **k: sys.__stdout__)
    monkeypatch.setattr(app, "take_instance_lock", lambda: False)
    monkeypatch.setattr(app, "running_instance", lambda: ("http://127.0.0.1:8766/", {"version": app.VERSION}))
    monkeypatch.setattr(app, "same_copy", lambda info: True)
    monkeypatch.setattr(app, "focus_window", lambda: False)
    opened = []
    monkeypatch.setattr(app, "open_window", lambda url: opened.append(url))
    monkeypatch.setattr(app, "App", lambda *a: pytest.fail("a second copy started"))
    try:
        assert app.gui(_gui_opts()) == 0
    finally:
        sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
    assert opened == ["http://127.0.0.1:8766/"]


def test_launch_during_the_first_copys_startup_waits_for_it(app, monkeypatch):
    """Double-click: the first copy holds the lock but its server isn't up yet."""
    monkeypatch.setattr(app, "LogBuffer", lambda *a, **k: sys.__stdout__)
    monkeypatch.setattr(app, "take_instance_lock", lambda: False)
    probes = iter([None, None, ("http://127.0.0.1:8765/", {"version": app.VERSION})])
    monkeypatch.setattr(app, "running_instance", lambda: next(probes))
    monkeypatch.setattr(app, "same_copy", lambda info: True)
    monkeypatch.setattr(app.time, "sleep", lambda s: None)
    focused = []
    monkeypatch.setattr(app, "focus_window", lambda: focused.append(1) or True)
    monkeypatch.setattr(app, "App", lambda *a: pytest.fail("a second copy started"))
    try:
        assert app.gui(_gui_opts()) == 0
    finally:
        sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
    assert focused == [1]
