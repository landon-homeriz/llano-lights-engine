"""A smooth beat clock locked to Mixxx's beat position.

Mixxx updates a deck's beat_distance once per audio buffer (about 5 to 23 ms depending
on the buffer size set in Preferences > Sound Hardware), and the message then crosses a
thread and a MIDI port. Rendering straight from the last message would make every light
step in buffer-sized jumps. Instead the clock runs its own timeline at the deck's exact
BPM and nudges itself toward each measurement, so jitter averages out while a seek, a
loop or a new track snaps it immediately.

Mixxx computes beat positions for the buffer it is about to play, so the speakers are
behind the engine by the output latency. `beat_at(now)` takes that latency off so the
lights hit with the sound, not ahead of it.
"""
from __future__ import annotations

import bisect
import math
import statistics
from dataclasses import dataclass, field
from typing import Optional, Sequence

SNAP_BEATS = 0.25  # a measurement this far off is a jump (seek, loop, cue), not jitter
GAIN = 0.15        # fraction of the error corrected per measurement


@dataclass
class BeatClock:
    bpm: float = 120.0
    running: bool = False
    _t0: Optional[float] = None
    _b0: float = 0.0

    def predict(self, now: float) -> float:
        if self._t0 is None:
            return 0.0
        if not self.running:
            return self._b0
        return self._b0 + (now - self._t0) * self.bpm / 60.0

    def update(self, measured_beat: float, bpm: float, playing: bool, now: float) -> None:
        """Feed one measurement: the deck's absolute beat position at receipt time."""
        if bpm > 0:
            self.bpm = bpm
        if not playing:
            self.running = False
            self._t0, self._b0 = now, measured_beat
            return
        predicted = self.predict(now)
        if self._t0 is None or not self.running or abs(measured_beat - predicted) > SNAP_BEATS:
            self._b0 = measured_beat
        else:
            self._b0 = predicted + GAIN * (measured_beat - predicted)
        self._t0 = now
        self.running = True

    def free_run(self, bpm: float, phase_beat: float, now: float) -> None:
        """Run without Mixxx (tap tempo): beat `phase_beat` happens at `now`."""
        self.bpm, self._t0, self._b0, self.running = bpm, now, phase_beat, True

    def beat_at(self, now: float, latency_s: float = 0.0) -> float:
        b = self.predict(now)
        if self.running:
            b -= latency_s * self.bpm / 60.0
        return b


@dataclass
class TrackGrid:
    """Where a track's beats are, from Mixxx's library (see mixxx_db.py)."""
    samplerate: int
    first_beat: float = 0.0           # frames
    bpm: float = 0.0                  # constant-tempo grid
    beats: Sequence[float] = field(default_factory=tuple)  # variable-tempo beat map, frames

    def beat_position(self, pos_frames: float) -> Optional[float]:
        """Absolute beat number at a play position; beat 0 is the grid's first beat."""
        if self.beats and len(self.beats) >= 2:
            i = bisect.bisect_right(self.beats, pos_frames) - 1
            i = max(0, min(i, len(self.beats) - 2))
            a, b = self.beats[i], self.beats[i + 1]
            return i + ((pos_frames - a) / (b - a) if b > a else 0.0)
        if self.bpm > 0 and self.samplerate > 0:
            frames_per_beat = self.samplerate * 60.0 / self.bpm
            return (pos_frames - self.first_beat) / frames_per_beat
        return None

    def seconds_at(self, beat: float) -> Optional[float]:
        """Seconds into the file at an absolute beat (the inverse of beat_position); past a beat
        map's end, on at its closing tempo. None when the grid can't say."""
        if self.samplerate <= 0:
            return None
        if self.beats and len(self.beats) >= 2:
            n = len(self.beats)
            i = max(0, min(int(math.floor(beat)), n - 2))
            a, b = self.beats[i], self.beats[i + 1]
            return (a + (b - a) * (beat - i)) / self.samplerate
        if self.bpm > 0:
            return self.first_beat / self.samplerate + beat * 60.0 / self.bpm
        return None

    def beat_at_seconds(self, secs: float) -> Optional[float]:
        return self.beat_position(secs * self.samplerate) if self.samplerate > 0 else None


def measured_beat(pos_frames: float, beat_distance: float, samplerate: int, bpm_hint: float,
                  grid: Optional[TrackGrid] = None, predicted: Optional[float] = None) -> float:
    """The deck's absolute beat position: whole beats from the grid, fraction from Mixxx.

    beat_distance is Mixxx's exact fraction of the way to the next beat. The whole-beat
    count comes from the library grid when we have it (so beat 0, and so bar lines, sit
    on the track's first beat); without it, from the play position at the track's BPM,
    which keeps beats in order across seeks but leaves bar lines unanchored.

    Without a grid the play-position estimate is offset from Mixxx's beats by the first
    beat's position and lags beat_distance (Mixxx updates playposition less often), so it
    can sit on a rounding edge and flip a whole beat. When the clock is already running on
    this track (`predicted`), the whole beat comes from the clock unless the position says
    we jumped (a seek or cue), so counting stays steady.
    """
    rough = grid.beat_position(pos_frames) if grid else None
    if rough is not None:
        return math.floor(rough - beat_distance + 0.5) + beat_distance
    if samplerate <= 0 or bpm_hint <= 0:
        return beat_distance
    rough = pos_frames / samplerate * bpm_hint / 60.0
    from_position = math.floor(rough - beat_distance + 0.5) + beat_distance
    if predicted is not None:
        from_clock = math.floor(predicted - beat_distance + 0.5) + beat_distance
        if abs(from_clock - from_position) < 2.0:
            return from_clock
    return from_position


class TapTempo:
    """Tap along to set tempo and phase when Mixxx isn't feeding the show."""

    def __init__(self, max_gap_s: float = 2.0, window: int = 8):
        self.max_gap_s, self.window = max_gap_s, window
        self.taps: list[float] = []

    def tap(self, now: float) -> Optional[float]:
        if self.taps and now - self.taps[-1] > self.max_gap_s:
            self.taps = []
        self.taps = (self.taps + [now])[-self.window:]
        if len(self.taps) < 3:
            return None
        gaps = [b - a for a, b in zip(self.taps, self.taps[1:])]
        return 60.0 / statistics.median(gaps)
