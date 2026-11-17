"""Song sections for a track, worked out ahead of time (our version of SoundSwitch's autoscript).

SoundSwitch's shows look designed because it knows a track's structure before it plays:
it labels phrases (intro, verse/chorus-like mains, bridge/breakdown, outro) and changes
looks on those boundaries, so a drop hits on beat one instead of a beat late. Mixxx gives
us the beat grid but no sections, so we work them out here from the audio file:

  1. measure each bar's loudness and bass (kick) energy along Mixxx's beat grid;
  2. group bars into 8-bar phrases from the grid's first beat (dance music phrases in 8s);
  3. label each phrase from its energy against the track's own range and its neighbors.

Labels: intro, verse, build, drop, main, breakdown, outro. "drop" is only the first phrase
of a high-energy run; the rest of the run is "main". The result is cached per track so a
set analyzes once, like SoundSwitch's batch autoscript, and a wrong label never stops the
show: with no script the looks engine runs autoloops instead.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Sequence

BEATS_PER_BAR = 4
PHRASE_BARS = 8
SECTION_KINDS = ("intro", "verse", "build", "drop", "main", "breakdown", "outro")
HIGH_ENERGY_KINDS = ("drop", "main")


@dataclass
class Section:
    kind: str
    start_beat: int  # absolute beat, 0 = the grid's first beat
    end_beat: int
    energy: float    # 0..1, relative to this track


# 2: a cut counts its phrases from its original's first beat (phrase_phase, Llano PM #23787); a cached
# version-1 script of a cut was counted from the cut's own first beat, so the cache works it out again
# (ScriptCache.get); a whole song's version-1 script is still right and is kept.
SCRIPT_VERSION = 2


@dataclass
class ShowScript:
    sections: list[Section]
    version: int = 1

    def at(self, beat: float) -> tuple[Optional[Section], Optional[Section]]:
        """The section playing at `beat`, and the one after it. The count-in before the first
        section belongs to it (1.2.2 flashed the no-script rainbow there on every seek to 0:00)."""
        if self.sections and beat < self.sections[0].start_beat:
            return self.sections[0], self.sections[1] if len(self.sections) > 1 else None
        for i, s in enumerate(self.sections):
            if s.start_beat <= beat < s.end_beat:
                return s, self.sections[i + 1] if i + 1 < len(self.sections) else None
        return None, None

    def to_json(self) -> str:
        return json.dumps({"version": self.version, "sections": [asdict(s) for s in self.sections]})

    @classmethod
    def from_json(cls, text: str) -> "ShowScript":
        data = json.loads(text)
        return cls([Section(**s) for s in data["sections"]], data.get("version", 1))


def _normalize(values: Sequence[float]) -> list[float]:
    """Scale to the track's own range (10th to 95th percentile), clipped to 0..1."""
    ranked = sorted(values)
    lo = ranked[int(0.10 * (len(ranked) - 1))]
    hi = ranked[int(0.95 * (len(ranked) - 1))]
    span = hi - lo or 1.0
    return [max(0.0, min(1.0, (v - lo) / span)) for v in values]


def label_phrases(bar_energy: Sequence[float], bar_bass: Sequence[float],
                  phrase_bars: int = PHRASE_BARS) -> list[Section]:
    """Label 8-bar phrases from per-bar loudness and bass energy (any consistent units)."""
    if not bar_energy:
        return []
    energy, bass = _normalize(bar_energy), _normalize(bar_bass)
    phrases = []
    for start in range(0, len(energy), phrase_bars):
        e = energy[start:start + phrase_bars]
        b = bass[start:start + phrase_bars]
        head, tail = e[: max(1, len(e) // 4)], e[-max(1, len(e) // 4):]
        phrases.append({
            "start": start, "end": start + len(e),
            "level": 0.6 * (sum(e) / len(e)) + 0.4 * (sum(b) / len(b)),
            "rise": sum(tail) / len(tail) - sum(head) / len(head),
        })
    high = [p["level"] >= 0.6 for p in phrases]
    first_high = high.index(True) if any(high) else len(phrases)
    last_high = len(high) - 1 - high[::-1].index(True) if any(high) else -1

    kinds = []
    for i, p in enumerate(phrases):
        if high[i]:
            kinds.append("drop" if i == 0 or not high[i - 1] else "main")
        elif i + 1 < len(phrases) and high[i + 1] and (p["rise"] > 0.1 or p["level"] >= 0.35):
            kinds.append("build")
        elif i < first_high:
            kinds.append("intro")
        elif i > last_high:
            kinds.append("outro")
        elif p["level"] < 0.35:
            kinds.append("breakdown")
        else:
            kinds.append("verse")

    sections: list[Section] = []
    for p, kind in zip(phrases, kinds):
        start_beat, end_beat = p["start"] * BEATS_PER_BAR, p["end"] * BEATS_PER_BAR
        if sections and sections[-1].kind == kind and kind != "drop":
            prev = sections[-1]
            n_prev = (prev.end_beat - prev.start_beat) / BEATS_PER_BAR
            n_new = p["end"] - p["start"]
            prev.energy = (prev.energy * n_prev + p["level"] * n_new) / (n_prev + n_new)
            prev.end_beat = end_beat
        else:
            sections.append(Section(kind, start_beat, end_beat, round(p["level"], 3)))
    return sections


# --- audio front end (numpy + soundfile, imported lazily) ---------------------------

def bar_energies(samples, samplerate: int, bar_starts: Sequence[float]) -> tuple[list[float], list[float]]:
    """RMS loudness and bass RMS for each bar. `samples` is mono float, bar_starts in frames."""
    import numpy as np  # noqa: PLC0415

    x = np.asarray(samples, dtype=np.float32)
    # One-pole low-pass at ~150 Hz isolates the kick and bass line.
    alpha = 1.0 - math.exp(-2 * math.pi * 150.0 / samplerate)
    try:
        from scipy.signal import lfilter  # noqa: PLC0415
        bass = lfilter([alpha], [1, alpha - 1], x)
    except ImportError:  # slower pure-numpy fallback over a decimated signal
        step = max(1, samplerate // 2000)
        xd = x[::step]
        a = 1.0 - math.exp(-2 * math.pi * 150.0 / (samplerate / step))
        bass_d = np.empty_like(xd)
        acc = 0.0
        for i, v in enumerate(xd):
            acc += a * (v - acc)
            bass_d[i] = acc
        bass = np.repeat(bass_d, step)[: len(x)]
    loud, low = [], []
    for a_, b_ in zip(bar_starts, bar_starts[1:]):
        seg = slice(max(0, int(a_)), max(0, int(b_)))
        if seg.stop - seg.start < 16:
            continue
        loud.append(float(np.sqrt(np.mean(x[seg] ** 2))))
        low.append(float(np.sqrt(np.mean(bass[seg] ** 2))))
    return loud, low


def load_mono(path: Path):
    """Decode an audio file to mono float32. soundfile reads WAV/FLAC/AIFF/OGG/MP3."""
    import numpy as np  # noqa: PLC0415
    import soundfile  # noqa: PLC0415

    data, rate = soundfile.read(str(path), dtype="float32", always_2d=True)
    return np.mean(data, axis=1), rate


PHRASE_BEATS = PHRASE_BARS * BEATS_PER_BAR
CUT_TAG = "Llano cut: the original's 0:00 is at "   # + seconds + " s" in a cut file's comment (set_cuts.write)


def source_zero_s(path: Path) -> Optional[float]:
    """Where a Build the night cut file says its original's 0:00 sits, in the cut's own seconds
    (negative when the cut skips an intro); None for any other file."""
    try:
        import soundfile  # noqa: PLC0415
        with soundfile.SoundFile(str(path)) as f:
            comment = f.comment or ""
    except Exception:  # noqa: BLE001 -- an unreadable tag is a file with no tag
        return None
    if not comment.startswith(CUT_TAG):
        return None
    try:
        v = float(comment[len(CUT_TAG):].split()[0])
    except (ValueError, IndexError):
        return None
    return v if math.isfinite(v) else None


def phrase_phase(grid, zero_s: Optional[float]) -> int:
    """Which of the grid's beats (0..31) the 8-bar phrases are counted from (Llano PM #23787).

    Mixxx's constant grid starts at the earliest beat in the file. On a song file that is its own
    first beat, and the phrases counted from it are the ones his rig played on time (his 11-15 video
    of I Gotta Feeling). On a cut that skips an intro (set_cuts, 1.34.0) the earliest beat is
    wherever the lead happens to fall: I Gotta Feeling's sat a bar before its phrases, so every
    section and drop came 1.875 s early. A cut says where its original's 0:00 is, so its phrases are
    counted from the beat the original's would be: a cut plays the sections of the song it came from."""
    if zero_s is None or not grid.samplerate:
        return 0
    if grid.beats:   # a beat map: the first of its beats at or after the original's 0:00
        beats = [b / grid.samplerate for b in grid.beats]
        if len(beats) < 2:
            return 0
        slack = 0.05 * (beats[1] - beats[0])
        return next((i for i, t in enumerate(beats) if t >= zero_s - slack), 0) % PHRASE_BEATS
    if not grid.bpm:
        return 0
    beat_s = 60.0 / grid.bpm
    first_s = grid.first_beat / grid.samplerate
    # the original's first beat: the first one at or after its 0:00 (a hair early still counts)
    k = math.ceil((zero_s - first_s) / beat_s - 0.05)
    return k % PHRASE_BEATS


def analyze_track(path: Path, grid) -> Optional[ShowScript]:
    """Sections for one file, using its Mixxx beat grid (beat_clock.TrackGrid). A beat before the
    first phrase (phrase_phase) belongs to the first section."""
    samples, rate = load_mono(path)
    total_frames = len(samples) * grid.samplerate / rate
    beat_starts, k = [], 0
    if grid.beats:
        beat_starts = list(grid.beats)
    elif grid.bpm > 0:
        frames_per_beat = grid.samplerate * 60.0 / grid.bpm
        while grid.first_beat + k * frames_per_beat < total_frames:
            beat_starts.append(grid.first_beat + k * frames_per_beat)
            k += 1
    phase = phrase_phase(grid, source_zero_s(path))
    scale = rate / grid.samplerate  # grid frames are at the library's sample rate
    bar_starts = beat_starts[phase::BEATS_PER_BAR]
    if len(bar_starts) < PHRASE_BARS + 1:
        return None
    loud, low = bar_energies(samples, rate, [f * scale for f in bar_starts])
    sections = label_phrases(loud, low)
    for s in sections:
        s.start_beat += phase
        s.end_beat += phase
    return ShowScript(sections, SCRIPT_VERSION) if sections else None


class ScriptCache:
    """One JSON file per Mixxx track id, refreshed when the audio file changes."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def _path(self, track_id: int) -> Path:
        return self.folder / f"track-{track_id}.json"

    def get(self, track_id: int, audio_path: Optional[Path] = None) -> Optional[ShowScript]:
        p = self._path(track_id)
        if not p.is_file():
            return None
        if audio_path and audio_path.is_file() and audio_path.stat().st_mtime > p.stat().st_mtime:
            return None
        try:
            script = ShowScript.from_json(p.read_text())
        except (ValueError, KeyError, TypeError):
            return None
        # An older analysis of a night's cut counted its phrases from the cut's own first beat: redone.
        # A whole song's was counted the same way then as now, so it stays (no re-analysis of a library).
        if script.version < SCRIPT_VERSION and audio_path is not None and source_zero_s(audio_path) is not None:
            return None
        return script

    def put(self, track_id: int, script: ShowScript) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self._path(track_id).write_text(script.to_json())
