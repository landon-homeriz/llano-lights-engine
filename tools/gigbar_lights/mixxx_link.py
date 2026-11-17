"""Read Mixxx's per-deck beat state from the Llano Light Link mapping.

Mixxx has no OSC and no Ableton Link (checked against the 2.5.6 release branch and the
development branch, 2026-11-06). What it does have is controller scripting: a mapping's
JavaScript can read every deck's engine controls (beat_distance, bpm, play, volume, ...)
as the audio engine updates them, and send MIDI out. mixxx/Llano-Light-Link.js sends
those values as SysEx over a virtual MIDI port (loopMIDI on Windows); this module
decodes them.

Wire format (all payload bytes 7-bit; multi-byte numbers little-endian, 7 bits each):
  F0 7D 4C 01 deck flags bpm*100[3] beat_distance*16383[2] pos_frames[5] weight level loop_beats*64[2] F7   tick
  F0 7D 4C 02 deck samplerate[3] duration*100[4] file_bpm*100[3] F7                  track
  F0 7D 4C 03 latency_ms*10[2] F7                                                    audio
0x7D is the MIDI "non-commercial / educational" manufacturer id; 0x4C is "L".
flags: bit0 playing, bit1 track loaded. weight: 0..127 audibility (volume x crossfader). level: 0..127 deck VU meter.
loop_beats: length of the active DJ loop in beats, 0 when no loop is on.
"""
from __future__ import annotations

import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable, Optional

SYSEX_HEADER = (0xF0, 0x7D, 0x4C)
MSG_TICK = 0x01
MSG_TRACK = 0x02
MSG_AUDIO = 0x03
DEFAULT_PORT_HINT = "Llano Mixxx"
SYSTEM_DECK = 5  # not a Mixxx deck: what the speakers play (system_audio.py), fed in the same format


def _unpack7(data, start: int, count: int) -> int:
    value = 0
    for i in range(count):
        value |= (data[start + i] & 0x7F) << (7 * i)
    return value


def pack7(value: int, count: int) -> list[int]:
    """Inverse of _unpack7; mirrors pack7() in Llano-Light-Link.js (used by the simulator)."""
    return [(int(value) >> (7 * i)) & 0x7F for i in range(count)]


@dataclass
class DeckState:
    deck: int
    playing: bool = False
    loaded: bool = False
    bpm: float = 0.0
    beat_distance: float = 0.0
    pos_frames: int = 0
    weight: float = 0.0
    level: float = 0.0
    loop_beats: float = 0.0
    samplerate: int = 0
    duration: float = 0.0
    file_bpm: float = 0.0
    last_tick: float = 0.0  # perf_counter receipt time (monotonic, sub-ms on Windows)
    track_serial: int = 0   # bumps on every new track message with changed identity


def encode_tick(deck: int, playing: bool, loaded: bool, bpm: float, beat_distance: float,
                pos_frames: int, weight: float, level: float = 0.0,
                loop_beats: float = 0.0) -> list[int]:
    flags = (1 if playing else 0) | (2 if loaded else 0)
    return [*SYSEX_HEADER, MSG_TICK, deck, flags,
            *pack7(round(bpm * 100), 3),
            *pack7(round(max(0.0, min(1.0, beat_distance)) * 16383), 2),
            *pack7(max(0, pos_frames), 5),
            max(0, min(127, round(weight * 127))), max(0, min(127, round(level * 127))),
            *pack7(round(max(0.0, min(255.0, loop_beats)) * 64), 2), 0xF7]


def encode_track(deck: int, samplerate: int, duration: float, file_bpm: float) -> list[int]:
    return [*SYSEX_HEADER, MSG_TRACK, deck, *pack7(samplerate, 3),
            *pack7(round(duration * 100), 4), *pack7(round(file_bpm * 100), 3), 0xF7]


def encode_audio(latency_ms: float) -> list[int]:
    return [*SYSEX_HEADER, MSG_AUDIO, *pack7(round(latency_ms * 10), 2), 0xF7]


@dataclass
class MixxxState:
    """Latest state per deck, plus which deck the lights should follow."""
    decks: dict[int, DeckState] = field(default_factory=dict)
    followed: Optional[int] = None
    stale_after: float = 1.0
    output_latency_ms: Optional[float] = None  # Mixxx's [Master],latency, when reported
    last_message: float = 0.0

    def feed(self, msg, now: Optional[float] = None) -> Optional[DeckState]:
        """Apply one raw SysEx message (list/bytes incl. F0..F7). Returns the deck touched."""
        now = time.perf_counter() if now is None else now
        if len(msg) < 6 or tuple(msg[:3]) != SYSEX_HEADER or msg[-1] != 0xF7:
            return None
        kind = msg[3]
        if kind == MSG_AUDIO and len(msg) == 7:
            self.output_latency_ms = _unpack7(msg, 4, 2) / 10.0
            self.last_message = now
            return None
        deck = msg[4]
        if not 1 <= deck <= SYSTEM_DECK:
            return None
        if kind == MSG_TICK and len(msg) == 21:
            st = self.decks.setdefault(deck, DeckState(deck))
            st.playing = bool(msg[5] & 1)
            st.loaded = bool(msg[5] & 2)
            st.bpm = _unpack7(msg, 6, 3) / 100.0
            st.beat_distance = _unpack7(msg, 9, 2) / 16383.0
            st.pos_frames = _unpack7(msg, 11, 5)
            st.weight = msg[16] / 127.0
            st.level = msg[17] / 127.0
            st.loop_beats = _unpack7(msg, 18, 2) / 64.0
            st.last_tick = now
        elif kind == MSG_TRACK and len(msg) == 16:
            st = self.decks.setdefault(deck, DeckState(deck))
            ident = (_unpack7(msg, 5, 3), _unpack7(msg, 8, 4) / 100.0, _unpack7(msg, 12, 3) / 100.0)
            if ident != (st.samplerate, st.duration, st.file_bpm):
                st.samplerate, st.duration, st.file_bpm = ident
                st.track_serial += 1
        else:
            return None
        self.last_message = now
        return st

    def pick_followed(self, now: Optional[float] = None, margin: float = 0.15) -> Optional[DeckState]:
        """Follow the loudest playing deck; only switch when another is clearly louder.

        Same idea as Mixxx's own "current playing deck" (PlayerInfo): playing, volume up,
        weighted by the crossfader. The margin stops the lights flapping mid-blend.
        """
        now = time.perf_counter() if now is None else now
        live = [d for d in self.decks.values()
                if d.playing and d.weight > 0 and now - d.last_tick < self.stale_after]
        if not live:
            self.followed = None
            return None
        best = max(live, key=lambda d: d.weight)
        current = self.decks.get(self.followed) if self.followed is not None else None
        if any(d is current for d in live) and best.weight < current.weight + margin:
            return current
        self.followed = best.deck
        return best


MIDI_POLL_S = 0.001   # how often the reader looks for Mixxx's messages (time.sleep is fine-grained on Windows)


class MidiInput:
    """The virtual MIDI port's receive side (python-rtmidi, imported lazily).

    Polled on our own thread, never a callback (1.20.1, his 11-13 freeze; 1.12.4 was the same one).
    With a callback, the Windows MIDI driver's thread runs our Python, so it needs the GIL; rtmidi's
    close_port holds the GIL while it waits for that thread to finish. A message from Mixxx landing
    as Stop closed the port froze the whole app (window, Stop, the Llano link) for good, and
    cancelling the callback first can't stop one already on its way in. Polled, the driver only
    fills rtmidi's own queue and never waits on Python, so closing can't deadlock."""

    def __init__(self, on_message: Callable[[list[int]], None], port_hint: str = DEFAULT_PORT_HINT,
                 poll_s: float = MIDI_POLL_S):
        import rtmidi  # noqa: PLC0415 - optional hardware dependency

        self._midi = rtmidi.MidiIn()
        self._midi.ignore_types(sysex=False, timing=True, active_sense=True)
        names = self._midi.get_ports()
        matches = [i for i, n in enumerate(names) if port_hint.lower() in n.lower()]
        if not matches:
            raise RuntimeError(
                f"No MIDI input matching {port_hint!r}. Ports seen: {names or 'none'}. "
                "Create it in loopMIDI and enable the Llano Light Link mapping in Mixxx.")
        self.port_name = names[matches[0]]
        self._midi.open_port(matches[0])
        self._on_message, self.poll_s = on_message, poll_s
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._poll, name="mixxx-midi", daemon=True)
        self._thread.start()

    def _poll(self) -> None:
        get = self._midi.get_message
        while not self._stop.is_set():
            got = False
            while not self._stop.is_set():
                try:
                    m = get()
                except Exception:  # noqa: BLE001 -- the port went away: closing, or the driver is gone
                    m = None
                if not m:
                    break
                got = True
                try:
                    self._on_message(m[0])
                except Exception:  # noqa: BLE001 -- one bad message never stops the listening
                    traceback.print_exc()
            if not got:
                time.sleep(self.poll_s)

    def still_there(self) -> bool:
        """The port is still listed (loopMIDI not closed or restarted since it was opened)."""
        try:
            return self.port_name in self._midi.get_ports()
        except Exception:  # noqa: BLE001
            return False

    def close(self) -> None:
        self._stop.set()
        if self._thread is not threading.current_thread():
            self._thread.join(1.0)
        self._midi.close_port()
