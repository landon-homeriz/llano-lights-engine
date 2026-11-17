"""Read Mixxx's library (mixxxdb.sqlite) for the playing track's name and beat grid.

Mixxx's scripting API only carries numbers, so a mapping can't say which track is
playing. Mixxx's own library can: the mapping sends each deck's duration, file BPM and
sample rate, and this module finds the matching library row, its title and artist, and
the stored beat grid (whose first beat anchors our bar lines). It opens the database
read-only and never writes to it.

Beat blobs (Mixxx src/track/beats.cpp, src/proto/beats.proto):
  BeatGrid-2.0  protobuf BeatGrid { Bpm bpm = 1 { double bpm = 1 }; Beat first_beat = 2 { int32 frame_position = 1 } }
  BeatGrid-1.0  raw struct { double bpm; double firstBeat }  (legacy, 16 bytes)
  BeatMap-1.0   protobuf BeatMap { repeated Beat beat = 1 }
"""
from __future__ import annotations

import os
import sqlite3
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .beat_clock import TrackGrid
from .settings_contract import track_key
from .song_match import norm


def default_db_path() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", "")) / "Mixxx" / "mixxxdb.sqlite"
    if sys.platform == "darwin":
        return (Path.home() / "Library/Containers/org.mixxx.mixxx/Data/Library"
                / "Application Support/Mixxx/mixxxdb.sqlite")
    return Path.home() / ".mixxx" / "mixxxdb.sqlite"


# --- minimal protobuf reader (only what the two beat messages use) -------------------

def _varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = value = 0
    while True:
        if i >= len(buf):
            raise ValueError("truncated varint")
        b = buf[i]
        i += 1
        value |= (b & 0x7F) << shift
        if not b & 0x80:
            return value, i
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")


def _fields(buf: bytes):
    """Yield (field_number, wire_type, value) for one message."""
    i = 0
    while i < len(buf):
        key, i = _varint(buf, i)
        num, wire = key >> 3, key & 7
        if wire == 0:
            value, i = _varint(buf, i)
        elif wire == 1:
            value, i = buf[i:i + 8], i + 8
        elif wire == 2:
            n, i = _varint(buf, i)
            value, i = buf[i:i + n], i + n
        elif wire == 5:
            value, i = buf[i:i + 4], i + 4
        else:
            raise ValueError(f"unsupported wire type {wire}")
        if i > len(buf):
            raise ValueError("truncated field")
        yield num, wire, value


def _int32(v: int) -> int:
    v &= 0xFFFFFFFFFFFFFFFF
    return v - (1 << 64) if v >= 1 << 63 else v


def _beat_frame(buf: bytes) -> Optional[int]:
    """A Beat's frame, or None when absent or disabled (enabled = 2, default true)."""
    frame, enabled = None, True
    for num, wire, value in _fields(buf):
        if num == 1 and wire == 0:
            frame = _int32(value)
        elif num == 2 and wire == 0:
            enabled = bool(value)
    return frame if enabled else None


def parse_beats(version: str, blob: bytes, samplerate: int) -> Optional[TrackGrid]:
    if not blob or not samplerate:
        return None
    try:
        if version == "BeatMap-1.0":
            frames = [f for num, wire, v in _fields(blob) if num == 1 and wire == 2
                      for f in [_beat_frame(v)] if f is not None]
            return TrackGrid(samplerate, beats=tuple(frames)) if len(frames) >= 2 else None
        if version.startswith("BeatGrid"):
            try:
                bpm = first = None
                for num, wire, v in _fields(blob):
                    if num == 1 and wire == 2:
                        for n2, w2, v2 in _fields(v):
                            if n2 == 1 and w2 == 1:
                                bpm = struct.unpack("<d", v2)[0]
                    elif num == 2 and wire == 2:
                        first = _beat_frame(v)
                if bpm and first is not None:
                    return TrackGrid(samplerate, first_beat=float(first), bpm=bpm)
            except ValueError:
                pass
            if len(blob) == 16:  # BeatGrid-1.0 legacy struct, as Mixxx falls back to
                bpm, first = struct.unpack("<dd", blob)
                if bpm > 0:
                    return TrackGrid(samplerate, first_beat=first, bpm=bpm)
    except (ValueError, struct.error):
        return None
    return None


# --- library lookups ----------------------------------------------------------------

@dataclass
class TrackInfo:
    track_id: int
    artist: str
    title: str
    grid: Optional[TrackGrid]
    location: Optional[Path] = None

    @property
    def label(self) -> str:
        return " - ".join(p for p in (self.artist, self.title) if p) or f"track {self.track_id}"


class MixxxLibrary:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else default_db_path()

    def available(self) -> bool:
        return self.path.is_file()

    def _connect(self) -> sqlite3.Connection:
        uri = f"{self.path.resolve().as_uri()}?mode=ro"
        return sqlite3.connect(uri, uri=True, timeout=0.5)

    def find_track(self, samplerate: int, duration: float, file_bpm: float) -> Optional[TrackInfo]:
        """The library row for a deck's track.

        Matched on duration; BPM only ranks, because Mixxx writes a track's row lazily and a
        freshly analyzed or re-gridded track can still hold its old BPM (often 0) on disk.
        Ties go to the most recently played match.
        """
        if not self.available() or duration <= 0:
            return None
        sql = """
            SELECT l.id, COALESCE(l.artist, ''), COALESCE(l.title, ''), l.beats_version, l.beats,
                   l.samplerate, tl.location,
                   (SELECT MAX(pt.pl_datetime_added) FROM PlaylistTracks pt
                     JOIN Playlists p ON p.id = pt.playlist_id
                    WHERE pt.track_id = l.id AND p.hidden = 2) AS last_played
              FROM library l
              LEFT JOIN track_locations tl ON tl.id = l.location
             WHERE l.mixxx_deleted = 0
               AND ABS(l.duration - ?) < 0.02
             ORDER BY (l.samplerate = ?) DESC, ABS(COALESCE(l.bpm, 0) - ?) < 0.05 DESC,
                      last_played DESC
             LIMIT 1
        """
        try:
            with self._connect() as conn:
                row = conn.execute(sql, (duration, samplerate, file_bpm)).fetchone()
        except sqlite3.Error:
            return None
        if not row:
            return None
        track_id, artist, title, version, blob, row_rate, location, _played = row
        grid = parse_beats(version or "", blob or b"", row_rate or samplerate)
        return TrackInfo(track_id, artist, title, grid, Path(location) if location else None)

    def bpm_index(self) -> dict:
        """{song_match.norm(track_key(artist, title)): BPM} for every tagged library song, so a song
        known only by name (Spotify, YouTube Music) can borrow its tempo to settle the beat's octave
        (a 76 BPM ballad, not 152). Built once per show, off the show thread. Rows with no artist
        are left out: a bare title would lend its tempo to another artist's song of that name."""
        if not self.available():
            return {}
        try:
            with self._connect() as conn:
                rows = conn.execute("SELECT COALESCE(artist, ''), COALESCE(title, ''), bpm FROM library "
                                    "WHERE mixxx_deleted = 0 AND bpm > 0").fetchall()
        except sqlite3.Error:
            return {}
        out: dict = {}
        for artist, title, bpm in rows:
            if artist.strip() and title.strip():
                out.setdefault(norm(track_key(artist, title)), float(bpm))
        return out

    def analyzable_tracks(self, limit: int = 0) -> list[TrackInfo]:
        """Library tracks with a beat grid and a file on disk, most recently added first."""
        if not self.available():
            return []
        sql = """
            SELECT l.id, COALESCE(l.artist, ''), COALESCE(l.title, ''), l.beats_version, l.beats,
                   l.samplerate, tl.location
              FROM library l JOIN track_locations tl ON tl.id = l.location
             WHERE l.mixxx_deleted = 0 AND l.beats IS NOT NULL
             ORDER BY l.datetime_added DESC
        """ + (" LIMIT ?" if limit else "")
        try:
            with self._connect() as conn:
                rows = conn.execute(sql, (limit,) if limit else ()).fetchall()
        except sqlite3.Error:
            return []
        out = []
        for track_id, artist, title, version, blob, rate, location in rows:
            grid = parse_beats(version or "", blob or b"", rate or 0)
            if grid and location:
                out.append(TrackInfo(track_id, artist, title, grid, Path(location)))
        return out
