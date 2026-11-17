"""The demo's real songs: free-to-ship tracks the lights follow, beat for beat and section by section.

demo_songs/songs.json (written by windows/make_demo_songs.py) holds each song's tempo, first beat,
its sections from Find song sections, and each bar's loudness, so the demo needs no math library.
The window plays the song and tells the app where it is every quarter second (SongClock); SongFeed
turns that into the same messages Mixxx sends, with the song's real beat grid and sections. With no
window reporting (a test, or audio blocked) the song runs on its own clock so the lights still play.
"""
from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .beat_clock import TrackGrid
from .mixxx_db import TrackInfo
from .mixxx_link import encode_audio, encode_tick, encode_track
from .show import DeckTrack, Show
from .show_script import Section, ShowScript

DIR = Path(__file__).resolve().parent / "demo_songs"
RATE = 44100
STALE_S = 2.0  # a report older than this means the window stopped telling us


@dataclass
class DemoSong:
    id: str
    file: str
    title: str
    artist: str
    feel: str
    license: str
    license_url: str
    source: str
    credit: str
    bpm: float
    first_beat_s: float
    duration_s: float
    bars: list = field(default_factory=list)
    sections: list = field(default_factory=list)

    @property
    def path(self) -> Path:
        return DIR / self.file

    def script(self) -> ShowScript:
        return ShowScript([Section(**s) for s in self.sections])

    def grid(self) -> TrackGrid:
        return TrackGrid(samplerate=RATE, first_beat=self.first_beat_s * RATE, bpm=self.bpm)

    def public(self) -> dict:
        """What the window shows: the picker line and the credit under it."""
        return {k: getattr(self, k) for k in ("id", "title", "artist", "feel", "license", "license_url",
                                               "source", "credit", "duration_s", "bpm")} | {"url": f"/demo-songs/{self.file}"}


def load(folder: Path = DIR) -> list[DemoSong]:
    try:
        data = json.loads((folder / "songs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [DemoSong(**s) for s in data.get("songs", []) if (folder / s.get("file", "")).is_file()]


def find(song_id: str, folder: Path = DIR) -> Optional[DemoSong]:
    return next((s for s in load(folder) if s.id == song_id), None)


class SongClock:
    """Where the window's player is: the last reported time, run forward while it plays."""

    def __init__(self):
        self.lock = threading.Lock()
        self.song = ""
        self.t = 0.0
        self.at = -1e9
        self.playing = False

    def report(self, song: str, t: float, playing: bool, now: Optional[float] = None) -> None:
        with self.lock:
            self.song, self.t, self.playing = song, max(0.0, float(t)), bool(playing)
            self.at = time.perf_counter() if now is None else now

    def position(self, song: str, now: float) -> Optional[tuple[float, bool]]:
        """(seconds into the song, playing) from a fresh report for this song, else None."""
        with self.lock:
            if self.song != song or now - self.at > STALE_S:
                return None
            return (self.t + (now - self.at) if self.playing else self.t), self.playing


class SongFeed:
    """Sends what the Mixxx mapping would for a deck playing this song, one tick per ~11.6 ms."""

    def __init__(self, show: Show, song: DemoSong, clock: Optional[SongClock] = None):
        self.show, self.song, self.clock = show, song, clock
        self.script = song.script()
        self.t0: Optional[float] = None
        self.last_tick = -1.0
        self.anchor: Optional[tuple[float, float, bool]] = None  # (song time, when, playing) last reported

    def song_time(self, now: float) -> tuple[float, bool]:
        pos = self.clock.position(self.song.id, now) if self.clock else None
        if pos is not None:  # a seek in the window lands here on its next report
            t, playing = pos
            self.anchor = (t, now, playing)
        elif self.anchor:  # the window went quiet (hidden, throttled): carry on from where it was, not from the top
            t, at, playing = self.anchor
            t = t + (now - at) if playing else t
        else:  # no window reporting at all (a test, or audio blocked): run on our own clock
            t, playing = now - self.t0, True
        return (t % self.song.duration_s if self.song.duration_s else t), playing

    def level(self, t: float, beats: float) -> float:
        bar = int(max(0.0, beats) // 4)
        loud = self.song.bars[bar] if 0 <= bar < len(self.song.bars) else 0.3
        return 0.15 + 0.7 * loud + 0.1 * math.exp(-4 * (beats % 1))

    def __call__(self, now: float) -> None:
        if self.t0 is None:
            self.t0 = now
            s = self.song
            self.show.on_midi(encode_track(1, RATE, s.duration_s, s.bpm), now)
            self.show.on_midi(encode_audio(0.0), now)  # the window reports what it is playing now
            info = TrackInfo(track_id=0, artist=s.artist, title=s.title, grid=s.grid())
            self.show.tracks[1] = DeckTrack(serial=1, info=info, script=self.script, looked_up=now)
        if now - self.last_tick < 512 / RATE:
            return
        self.last_tick = now
        t, playing = self.song_time(now)
        beats = (t - self.song.first_beat_s) * self.song.bpm / 60
        self.show.on_midi(encode_tick(1, playing, True, self.song.bpm, beats % 1, int(t * RATE), 0.9,
                                      self.level(t, beats)), now)
