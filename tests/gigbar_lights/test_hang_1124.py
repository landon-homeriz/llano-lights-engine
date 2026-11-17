"""1.12.4, the 11-08 report (BL #11606): the page showed the laptop offline and Stop stopped responding.

The laptop's log: a live show with the Mixxx MIDI link open stopped at 19:37:07 ("Frames rendered")
and the app never answered again; the next launch found "Another copy holds the lock but doesn't
answer". The run had reached LiveSources.close(), where only the MIDI close can block: on Windows
closing an rtmidi input waits for the driver's thread, which waits to run our Python callback.
Earlier, at 18:40:59, one ENTTEC write timeout ended Control a light.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
import gigbar_app  # noqa: E402
from tools.gigbar_lights import mixxx_link, show_settings  # noqa: E402
from tools.gigbar_lights.venue import LayoutStore  # noqa: E402


def test_the_midi_link_is_polled_never_a_callback(monkeypatch):
    """1.20.1, his 11-13 freeze (the 11-08 one again): with a callback, rtmidi's close_port held the
    GIL while waiting on the driver thread that was waiting for the GIL to run our callback.
    Polled, no callback is ever set, and the reader has stopped before the port closes."""
    calls, got = [], []
    queue = [([0x90, 1, 127], 0.0), ([0x80, 1, 0], 0.01)]

    class FakeMidiIn:
        def ignore_types(self, **kw): pass
        def get_ports(self): return ["Llano Mixxx 0"]
        def open_port(self, i): calls.append("open")
        def set_callback(self, cb): calls.append("set_callback")
        def cancel_callback(self): calls.append("cancel_callback")
        def get_message(self): return queue.pop(0) if queue else None
        def close_port(self): calls.append(("close_port", m._thread.is_alive()))

    monkeypatch.setitem(sys.modules, "rtmidi", types.SimpleNamespace(MidiIn=FakeMidiIn))
    m = mixxx_link.MidiInput(got.append)
    deadline = time.monotonic() + 2
    while len(got) < 2 and time.monotonic() < deadline:
        time.sleep(0.005)
    assert got == [[0x90, 1, 127], [0x80, 1, 0]]
    m.close()
    assert calls == ["open", ("close_port", False)]   # no callback, and the reader was gone first


def test_a_bad_message_never_stops_the_listening(monkeypatch, capsys):
    got = []
    queue = [([1], 0.0), ([2], 0.0)]

    class FakeMidiIn:
        def ignore_types(self, **kw): pass
        def get_ports(self): return ["Llano Mixxx 0"]
        def open_port(self, i): pass
        def get_message(self): return queue.pop(0) if queue else None
        def close_port(self): pass

    def on(msg):
        if msg == [1]:
            raise ValueError("bad")
        got.append(msg)

    monkeypatch.setitem(sys.modules, "rtmidi", types.SimpleNamespace(MidiIn=FakeMidiIn))
    m = mixxx_link.MidiInput(on)
    deadline = time.monotonic() + 2
    while not got and time.monotonic() < deadline:
        time.sleep(0.005)
    m.close()
    assert got == [[2]] and "ValueError" in capsys.readouterr().err


def test_a_run_stuck_after_stop_leaves_every_stack_in_crash_log(monkeypatch, tmp_path):
    f = open(tmp_path / "crash.log", "w", encoding="utf-8")
    monkeypatch.setattr(gigbar_app, "_crash_file", f)
    monkeypatch.setattr(gigbar_app, "STOP_DUMP_S", 0.2)
    gigbar_app.arm_stop_dump()
    time.sleep(0.6)
    f.flush()
    assert "Thread" in (tmp_path / "crash.log").read_text()   # faulthandler's all-threads dump
    f2 = open(tmp_path / "crash2.log", "w", encoding="utf-8")
    monkeypatch.setattr(gigbar_app, "_crash_file", f2)
    gigbar_app.arm_stop_dump()
    gigbar_app.disarm_stop_dump()   # the run ended in time: nothing written
    time.sleep(0.4)
    f2.flush()
    assert (tmp_path / "crash2.log").read_text() == ""


def test_the_frozen_copy_is_the_one_the_run_marker_names(tmp_path):
    import json
    import os
    marker = tmp_path / gigbar_app.RUN_MARKER
    assert gigbar_app.frozen_pid(tmp_path) == 0   # no marker
    marker.write_text(json.dumps({"pid": os.getpid()}))
    assert gigbar_app.frozen_pid(tmp_path) == 0   # this copy: never itself
    marker.write_text(json.dumps({"pid": 4242}))
    assert gigbar_app.frozen_pid(tmp_path) == 4242
    marker.write_text("not json")
    assert gigbar_app.frozen_pid(tmp_path) == 0
    if sys.platform != "win32":
        assert gigbar_app.end_frozen_copy(tmp_path) is False


def test_a_close_that_hangs_is_left_behind(capsys):
    release = threading.Event()
    t0 = time.monotonic()
    assert gigbar_app.bounded("a stuck driver", release.wait, seconds=0.3) is False
    assert time.monotonic() - t0 < 1.0
    assert "left it behind" in capsys.readouterr().out
    release.set()
    assert gigbar_app.bounded("a quick close", lambda: None, seconds=1.0) is True


class Stalls:
    port = "COM7"

    def __init__(self):
        self.fail = True
        self.sent = 0

    def send(self, universe):
        if self.fail:
            raise TimeoutError("Write timeout")   # serial.SerialTimeoutException's shape
        self.sent += 1

    def close(self): pass


def test_a_refused_frame_is_dropped_and_a_stall_is_said_once(capsys):
    preview = types.SimpleNamespace(universe=b"", frames=0, status="", trail=[])
    box = Stalls()
    tee = gigbar_app.TeeOutput(box, preview)
    for _ in range(gigbar_app.STALL_FRAMES * 2):
        tee.send(bytes(512))   # never raises
    out = capsys.readouterr().out
    assert out.count("stopped taking data") == 1 and "COM7" in preview.status
    assert preview.frames == gigbar_app.STALL_FRAMES * 2   # the room picture kept going
    box.fail = False
    tee.send(bytes(512))
    assert box.sent == 1 and "taking data again" in capsys.readouterr().out and tee.failing == 0


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(gigbar_app.updater, "check", lambda: (None, "no update in tests"))
    monkeypatch.setattr(gigbar_app, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(gigbar_app, "_enttec_port", lambda: None)
    monkeypatch.setattr(gigbar_app, "midi_port", lambda: "")
    opts = argparse.Namespace(seconds=0.0, bpm=128.0, no_browser=True, no_window=True,
                              updated=False, update_failed=False)
    a = gigbar_app.App(opts, gigbar_app.LogBuffer(tmp_path / "log.txt"))
    a.mixxx.running = False
    a.preview = gigbar_app.Preview("", LayoutStore(tmp_path / "profile"), app=a)
    yield a
    a.quit.set()
    a.stop()
    a.preview.close()
    show_settings.clear_play()


def wait(cond, s=6.0):
    end = time.monotonic() + s
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def test_stop_frees_the_window_when_a_run_will_not_finish(app, monkeypatch):
    stuck = threading.Event()

    def hangs_on_close(opts):
        opts.preview.begin("hangs", None)
        while opts.preview.keys.empty():
            time.sleep(0.02)
        stuck.wait(30)   # Stop arrived; the close never comes back (his 19:37 hang)
        return 0

    monkeypatch.setattr(gigbar_app, "STOP_WAIT_S", 0.5)
    monkeypatch.setitem(gigbar_app.MODES, "manual", ("Control a light by hand", hangs_on_close))
    assert app.run("manual")[0] == 200
    assert wait(lambda: app.running == "manual")
    assert app.stop()[0] == 200
    assert wait(lambda: app.running is None, 3.0)   # the window is free again
    assert "didn't finish closing" in app.last_run
    assert app.run("lineup")[0] == 200              # and the next thing starts
    assert wait(lambda: app.running == "lineup")
    stuck.set()   # the old run ends late: it must not clear the new one
    time.sleep(0.3)
    assert app.running == "lineup"
    app.stop()
    assert wait(lambda: app.running is None, 4.0)


class _Fake:
    made = []

    def __init__(self, *a, **kw):
        _Fake.made.append(type(self).__name__)
        self.want, self.stopped = threading.Event(), False

    def start(self):
        return self

    def stop(self):
        self.stopped = True


class _Watch(_Fake): pass
class _Capture(_Fake): pass
class _Media(_Fake): pass


class _Feed:
    def __init__(self, show, capture, media, library, watch=None):
        self.use_audio, self.mixxx_link, self.seen = True, True, 0

    def saw_mixxx(self):
        self.seen += 1


class _Midi:
    opened = 0

    def __init__(self, deliver):
        _Midi.opened += 1
        self.deliver, self.port_name, self.there, self.closed = deliver, "Llano Mixxx 0", True, False

    def still_there(self):
        return self.there

    def close(self):
        self.closed = True


def test_live_shows_share_one_set_of_native_inputs(monkeypatch):
    """1.20.1, his 11-13 10:04 crash: his second live show of a run died while it opened the MIDI
    port, the speaker capture and Windows' now playing again. Now they open once per app run;
    Stop gives them back without closing anything native, and the next show borrows the same ones."""
    _Fake.made, _Midi.opened = [], 0
    monkeypatch.setattr(gigbar_app, "MixxxWatch", _Watch)
    monkeypatch.setattr(gigbar_app, "LoopbackCapture", _Capture)
    monkeypatch.setattr(gigbar_app, "MediaSessions", _Media)
    monkeypatch.setattr(gigbar_app, "SystemFeed", _Feed)
    monkeypatch.setattr(gigbar_app, "_open_midi", lambda deliver: _Midi(deliver))
    inputs = gigbar_app.SharedInputs()
    heard = []
    show = types.SimpleNamespace(library=None, on_midi=heard.append)
    opts = argparse.Namespace()

    first = gigbar_app.LiveSources(show, opts, inputs)
    first.capture.want.set()
    first.midi.deliver([0x90, 1, 127])
    first.close()
    assert not first.capture.want.is_set() and not first.capture.stopped and not first.midi.closed
    first.midi.deliver([0x90, 2, 127])   # between shows: dropped, never sent to a stopped show
    assert heard == [[0x90, 1, 127]]

    second = gigbar_app.LiveSources(show, opts, inputs)
    assert (second.capture, second.media, second.watch, second.midi) == \
        (first.capture, first.media, first.watch, first.midi)
    assert _Fake.made == ["_Watch", "_Capture", "_Media"] and _Midi.opened == 1
    second.midi.deliver([0x80, 1, 0])
    assert heard[-1] == [0x80, 1, 0] and second.feed.seen == 1
    second.close()

    first.midi.there = False   # loopMIDI was restarted: the next show opens the port again
    third = gigbar_app.LiveSources(show, opts, inputs)
    assert _Midi.opened == 2 and first.midi.closed and third.midi is not first.midi
    third.close()


def test_the_crash_report_keeps_the_head_of_crash_log():
    """The 11-13 10:04 report kept only the last 4000 characters, which cut the fault and the
    crashing thread (faulthandler writes them first) and kept only idle threads."""
    head = "Windows fatal exception: access violation\n\nCurrent thread 0x1 (most recent call first):\n"
    text = head + "".join(f"\nThread 0x{i:x} (most recent call first):\n  File \"threading.py\", line 359 in wait\n"
                          for i in range(400))
    out = gigbar_app.fault_excerpt(text)
    assert out.startswith(head) and len(out) <= gigbar_app.FAULT_CHARS and "cut" in out
    assert gigbar_app.fault_excerpt("short") == "short"
