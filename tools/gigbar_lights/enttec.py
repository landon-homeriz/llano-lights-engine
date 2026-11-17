"""DMX out through an ENTTEC DMX USB Pro (or a stand-in for testing without one).

ENTTEC DMX USB Pro API (support.enttec.com, "DMX USB Pro API"): each message is
  0x7E, label, length LSB, length MSB, data..., 0xE7
Label 6 "Output Only Send DMX Packet" carries the DMX start code (0) and the slots.
The box keeps repeating the last frame on the wire, and its own chip holds the DMX
timing, so a Windows hiccup on our side delays an update but never glitches the line.

Staying usable by SoundSwitch: we only ever send label 6. We never send label 4 (widget
parameters) or touch firmware, so nothing on the box changes. The port is held only
while the show runs and released on exit; close this app before opening SoundSwitch,
since only one program can hold the box at a time.
"""
from __future__ import annotations

import threading
import time
import weakref
from typing import Callable, Optional

START, END = 0x7E, 0xE7
LABEL_SEND_DMX = 6
FTDI_VID, FT232R_PID = 0x0403, 0x6001
FRAME_HZ = 40  # the room's plan; a full 512-slot DMX frame takes ~23 ms on the wire
RIG_SLOTS = 192  # the rig ends at slot 188; a short frame takes ~9 ms on the wire, not ~23


def dmx_packet(universe: bytes) -> bytes:
    """Label-6 message for a universe (slot 1 first). Pads to the API's 24-slot minimum."""
    slots = bytes(universe[:512]).ljust(24, b"\x00")
    data = b"\x00" + slots  # DMX start code
    return bytes([START, LABEL_SEND_DMX, len(data) & 0xFF, len(data) >> 8]) + data + bytes([END])


def find_port() -> Optional[str]:
    """The first serial port that looks like an ENTTEC Pro (FTDI FT232R, serial 'EN...')."""
    from serial.tools import list_ports  # noqa: PLC0415 - optional hardware dependency

    candidates = [p for p in list_ports.comports() if p.vid == FTDI_VID and p.pid == FT232R_PID]
    # A Mac lists each FTDI box twice, /dev/cu.usbserial-EN... and /dev/tty.usbserial-EN...; opening
    # the tty one waits for a carrier the box never raises, so the cu one goes first (Llano BL #12517).
    candidates.sort(key=lambda p: (not (p.serial_number or "").upper().startswith("EN"),
                                   (p.device or "").startswith("/dev/tty.")))
    return candidates[0].device if candidates else None


class EnttecPro:
    def __init__(self, port: Optional[str] = None, slots: int = RIG_SLOTS):
        import serial  # noqa: PLC0415

        self.slots = slots
        port = port or find_port()
        if not port:
            raise RuntimeError(
                "No ENTTEC DMX USB Pro found. Plug it in; if Windows shows no COM port for it, "
                "enable 'Load VCP' for the FTDI device in Device Manager. On a Mac it shows as "
                "/dev/cu.usbserial-EN... with no driver to install.")
        self.port = port
        self._serial = serial.Serial(port, baudrate=57600, timeout=0.1, write_timeout=0.5)

    def send(self, universe: bytes) -> None:
        self._serial.write(dmx_packet(universe[:self.slots]))

    def close(self) -> None:
        self._serial.close()


class NullOutput:
    """Keeps the last frame instead of sending it (dry runs, the simulator, tests)."""
    port = "none"

    def __init__(self):
        self.last: bytes = bytes(512)
        self.frames = 0

    def send(self, universe: bytes) -> None:
        self.last = bytes(universe)
        self.frames += 1

    def close(self) -> None:
        pass


class PluggableOutput:
    """The lights box when it is there, nothing when it is not, and it picks the box up by itself
    (his ask, 2026-11-13: everything works with no adapter, and when it is plugged in the lights
    pick up on their own). A background thread looks for the box every retry_s while none is open;
    a box that refuses every frame for STALL_S (unplugged mid-show) is closed and looked for again.
    send never raises and never waits on the search, so the 40 Hz loop and the room picture never
    stall on the box. on_change(port) hears it come ("COM3") and go ("")."""

    RETRY_S = 2.0
    STALL_S = 1.0
    _open_ones: "weakref.WeakSet" = weakref.WeakSet()   # one run at a time holds the box

    def __init__(self, finder: Optional[Callable[[], Optional[str]]] = None,
                 opener: Optional[Callable[[str], object]] = None,
                 on_change: Optional[Callable[[str], None]] = None, retry_s: Optional[float] = None):
        self._find = finder or find_port
        self._open = opener or (lambda port: EnttecPro(port))
        self.on_change = on_change
        self.retry_s = self.RETRY_S if retry_s is None else retry_s
        self.note = ""                 # why the last open failed (the port busy: SoundSwitch open)
        self._box = None
        self._fail_since: Optional[float] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        # A run that failed before its output was closed must never keep the port from the next one.
        for older in list(PluggableOutput._open_ones):
            older.close()
        PluggableOutput._open_ones.add(self)
        self._try_open()               # at once: a box plugged in before Start lights the first frame
        self._thread = threading.Thread(target=self._watch, name="dmx-find", daemon=True)
        self._thread.start()

    @property
    def port(self) -> str:
        box = self._box
        return box.port if box is not None else "none"

    @property
    def connected(self) -> bool:
        return self._box is not None

    def _try_open(self) -> bool:
        try:
            port = self._find()
        except Exception:  # noqa: BLE001 -- ok: the port list failed this time; the next look retries
            return False
        if not port:
            self.note = ""
            return False
        try:
            box = self._open(port)
        except Exception as e:  # noqa: BLE001 -- ok: busy or refused; said in .note, the next look retries
            self.note = f"The lights box on {port} wouldn't open ({e}). If SoundSwitch is open, close it."
            return False
        with self._lock:
            if self._stop.is_set():    # closed while it was opening: never leave the port held
                box.close()
                return False
            self._box, self._fail_since, self.note = box, None, ""
        self._changed(box.port)
        return True

    def _watch(self) -> None:
        while not self._stop.wait(self.retry_s):
            if self._box is None:
                self._try_open()

    def send(self, universe: bytes) -> None:
        box = self._box
        if box is None:
            return
        try:
            box.send(universe)
            self._fail_since = None
        except Exception:  # noqa: BLE001 -- ok: one refused frame repeats next tick; a run of them drops the box
            now = time.monotonic()
            if self._fail_since is None:
                self._fail_since = now
            elif now - self._fail_since >= self.STALL_S:
                self._drop(box)

    def _drop(self, box) -> None:
        with self._lock:
            if self._box is not box:
                return
            self._box = None
        try:
            box.close()
        except Exception:  # noqa: BLE001 -- ok: an unplugged port can refuse its own close
            pass
        self._changed("")

    def _changed(self, port: str) -> None:
        if self.on_change:
            try:
                self.on_change(port)
            except Exception:  # noqa: BLE001 -- ok: a status line never stops the lights
                pass

    def close(self) -> None:
        self._stop.set()
        PluggableOutput._open_ones.discard(self)
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=2.0)
        with self._lock:
            box, self._box = self._box, None
        if box is not None:
            try:
                box.close()
            except Exception:  # noqa: BLE001 -- ok: closing at Stop, nothing left to send
                pass


class OutputLoop:
    """Renders and sends a frame FRAME_HZ times a second on its own thread.

    `render` returns the universe for a moment in time. Frames are scheduled against the
    clock, not slept back to back, so a slow frame doesn't drift the rate. Each frame is
    rendered for half a frame ahead: it stays on the lights for one period, so centering it
    halves the worst-case lag instead of always showing the past.
    """

    def __init__(self, output, render: Callable[[float], bytes], hz: int = FRAME_HZ):
        self.output, self.render, self.period = output, render, 1.0 / hz
        self.lookahead = self.period / 2
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="dmx-out", daemon=True)
        self.errors = 0

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        next_at = time.perf_counter()
        while not self._stop.is_set():
            now = time.perf_counter()
            try:
                self.output.send(self.render(now + self.lookahead))
            except Exception:  # keep the show alive; a dropped frame repeats next tick
                self.errors += 1
            next_at += self.period
            delay = next_at - time.perf_counter()
            if delay < -self.period:  # fell well behind (laptop stalled): resync
                next_at = time.perf_counter()
            elif delay > 0:
                time.sleep(delay)  # high-resolution on Windows from Python 3.11; Event.wait is not

    def stop(self, final_frame: Optional[bytes] = None) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        if final_frame is not None:
            try:
                self.output.send(final_frame)
            except Exception:
                pass
