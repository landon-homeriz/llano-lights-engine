"""No USB lights box never locks him out, and the box picks up by itself (his ask, 2026-11-13).

enttec.PluggableOutput is every run's output: nothing is sent while no box is there, a box
plugged in mid-run is found within a couple of seconds, a box pulled out mid-run is dropped
and looked for again, and send never raises or waits on the search.
"""
from __future__ import annotations

import threading
import time

import pytest

from tools.gigbar_lights import enttec
from tools.gigbar_lights.enttec import PluggableOutput


class FakeBox:
    def __init__(self, port: str):
        self.port, self.frames, self.closed, self.broken = port, [], False, False

    def send(self, universe: bytes) -> None:
        if self.broken:
            raise OSError("device unplugged")
        self.frames.append(bytes(universe))

    def close(self) -> None:
        self.closed = True


class Bench:
    """A USB socket the test plugs boxes into and out of."""

    def __init__(self):
        self.port = None
        self.boxes: list[FakeBox] = []
        self.refuse = False

    def find(self):
        return self.port

    def open(self, port):
        if self.refuse:
            raise PermissionError("Access is denied")
        box = FakeBox(port)
        self.boxes.append(box)
        return box


def wait(cond, s=3.0):
    end = time.monotonic() + s
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def bench():
    return Bench()


def make(bench, seen=None, retry=0.02):
    return PluggableOutput(finder=bench.find, opener=bench.open,
                           on_change=(seen.append if seen is not None else None), retry_s=retry)


def test_with_no_box_nothing_is_sent_and_nothing_raises(bench):
    out = make(bench)
    try:
        assert not out.connected and out.port == "none"
        for _ in range(50):
            out.send(bytes(512))          # never raises, never blocks
        assert bench.boxes == []
    finally:
        out.close()


def test_a_box_plugged_in_mid_run_is_picked_up_by_itself(bench):
    seen = []
    out = make(bench, seen)
    try:
        out.send(b"\x01" * 512)
        bench.port = "COM3"               # he plugs it in
        assert wait(lambda: out.connected)
        assert out.port == "COM3" and seen == ["COM3"]
        out.send(b"\x02" * 512)
        assert bench.boxes[0].frames == [b"\x02" * 512], "frames before the box came are not replayed"
    finally:
        out.close()


def test_a_box_pulled_out_mid_run_is_dropped_and_found_again(bench, monkeypatch):
    monkeypatch.setattr(PluggableOutput, "STALL_S", 0.05)
    seen = []
    bench.port = "COM3"
    out = make(bench, seen)
    try:
        assert out.connected and seen == ["COM3"]
        first = bench.boxes[0]
        first.broken = True               # pulled out: every write refuses
        bench.port = None
        out.send(bytes(512))              # one refused frame keeps the box (a hiccup, not an unplug)
        assert out.connected
        time.sleep(0.08)
        out.send(bytes(512))
        assert not out.connected and first.closed and seen == ["COM3", ""]
        bench.port = "COM4"               # plugged back in, Windows gave it another port
        assert wait(lambda: out.connected) and out.port == "COM4" and seen == ["COM3", "", "COM4"]
    finally:
        out.close()


def test_a_box_that_wont_open_says_why_and_keeps_trying(bench):
    bench.port, bench.refuse = "COM3", True     # SoundSwitch holds it
    out = make(bench)
    try:
        assert not out.connected and "SoundSwitch" in out.note and "COM3" in out.note
        out.send(bytes(512))
        bench.refuse = False                    # he closes SoundSwitch
        assert wait(lambda: out.connected) and out.note == ""
    finally:
        out.close()


def test_close_lets_the_box_go_and_stops_looking(bench):
    bench.port = "COM3"
    out = make(bench)
    out.close()
    assert bench.boxes[0].closed and not out.connected
    n = len(bench.boxes)
    time.sleep(0.1)
    assert len(bench.boxes) == n, "a closed output never opens the box again"
    out.send(bytes(512))                        # a frame after Stop is a no-op, not an error
    out.close()                                 # twice is fine


def test_a_new_run_takes_the_box_from_one_that_was_never_closed(bench):
    """A run that failed before its output closed must never keep the port from the next run."""
    bench.port = "COM3"
    first = make(bench)
    second = make(bench)
    try:
        assert bench.boxes[0].closed and not first.connected
        assert second.connected and second.port == "COM3" and len(bench.boxes) == 2
    finally:
        first.close()
        second.close()


def test_a_finder_that_raises_is_a_miss_not_a_crash(bench):
    calls = []

    def finder():
        calls.append(1)
        raise OSError("port list failed")
    out = PluggableOutput(finder=finder, opener=bench.open, retry_s=0.02)
    try:
        assert wait(lambda: len(calls) >= 3) and not out.connected
    finally:
        out.close()


def test_an_on_change_that_raises_never_stops_the_lights(bench):
    def boom(port):
        raise RuntimeError("status line broke")
    bench.port = "COM3"
    out = PluggableOutput(finder=bench.find, opener=bench.open, on_change=boom, retry_s=0.02)
    try:
        assert out.connected
        out.send(b"\x07" * 512)
        assert bench.boxes[0].frames
    finally:
        out.close()


def test_send_never_waits_on_a_slow_search(bench):
    """The 40 Hz loop keeps time while the port scan is slow (a busy Windows port list)."""
    gate = threading.Event()

    def slow_find():
        gate.wait(1.0)
        return None
    out = PluggableOutput(finder=lambda: None, opener=bench.open, retry_s=0.01)
    out._find = slow_find
    try:
        time.sleep(0.05)                          # the watcher is now inside the slow scan
        t0 = time.monotonic()
        for _ in range(40):
            out.send(bytes(512))
        assert time.monotonic() - t0 < 0.1
    finally:
        gate.set()
        out.close()


def test_the_app_never_refuses_a_run_for_a_missing_box():
    """The window's runs all take the pluggable output; only Llano's probe still needs the box open."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "tools/gigbar_lights/windows/src/gigbar_app.py").read_text(encoding="utf-8")
    import re
    assert "NEEDS_BOX" not in src and len(re.findall(r"(?<!def )_open_enttec\(\)", src)) == 1   # mode_probe
    assert enttec.PluggableOutput.RETRY_S <= 2.0
