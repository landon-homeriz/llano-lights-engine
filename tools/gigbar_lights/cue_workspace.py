"""The cue workspace: a song, its beats, its parts and the show it will play, on one big screen (Llano PM #23869).

His words 2026-11-17: the Cue timeline tab was "pointless, too small, not editable, I can't see it on the
screen. This really needs its own dedicated workspace to adjust cues." The page (windows/src/cues.html)
draws what this module works out for one song file, with no Mixxx and no music playing:

  - `analyze(path, grid)`: the waveform (peak and loudness a slice), the beat grid (Mixxx's when the song is
    in his library, else one worked out from the sound, `estimate_grid`), and Llano's sections
    (show_script.analyze_track, the same analysis the live show plays);
  - `lanes(song, cues, keys)`: what the show does, light by light, every LANE_STEP seconds, rendered by the
    same looks engine and cue code the live show runs (looks.LooksEngine, stick_fx, cues.place/dress), so
    what he sees on a lane is what the rig will do. Lanes: pars and Tetras (wash), strobe, moving heads,
    Freedom Sticks, laser, derby, each a list of runs [start s, end s, "#rrggbb", level 0..1];
  - `payload(...)`: all of it for the page, his cues and the sections in force (his, else Llano's).

Seconds are the file's own; a cue is stored in the original recording's seconds (cues.py), which for a
whole song file (the only kind the workspace opens) are the same.
LLANO_LIGHTS_CUES=0 still turns every cue off on the lights; the workspace then draws the show without them.
"""
from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import cues as cues_mod
from .beat_clock import TrackGrid
from .show_script import ShowScript, analyze_track, load_mono

PEAKS_PER_S = 50          # waveform resolution: one peak and one loudness value per 20 ms
LANE_STEP = 0.05          # the show is rendered 20 times a second for the lanes
LANES = ("wash", "strobe", "heads", "sticks", "laser", "derby")
LANE_NAMES = {"wash": "Pars and Tetras", "strobe": "Strobe", "heads": "Moving heads", "sticks": "Freedom Sticks",
              "laser": "Laser", "derby": "Derby"}
MIN_BPM, MAX_BPM, PRIOR_BPM = 60.0, 190.0, 110.0
LASER_HEX = {"red": "#ff3030", "green": "#30ff60", "both": "#ffd030", "red_flash": "#ff3030",
             "green_flash": "#30ff60", "alternate": "#ffd030"}
DERBY_HEX = {"red": "#ff3030", "green": "#30ff60", "blue": "#3060ff", "white": "#ffffff", "yellow": "#ffe030",
             "magenta": "#ff40ff", "cyan": "#40e0ff", "auto": "#c0a0ff", "auto2": "#c0a0ff"}


@dataclass
class Song:
    """One song file as the workspace reads it (made once per file; the lanes are made per change of cues)."""
    path: Path
    length: float                 # seconds
    peaks: list                   # 0..255 per 1/PEAKS_PER_S s: the loudest sample
    loud: list                    # 0..255 per 1/PEAKS_PER_S s: the loudness (RMS), what the lights hear
    grid: TrackGrid
    grid_source: str              # "mixxx" or "estimated"
    script: Optional[ShowScript]
    made: float = field(default_factory=time.time)

    @property
    def bpm(self) -> float:
        if self.grid.bpm:
            return self.grid.bpm
        b = self.grid.beats
        return 60.0 * self.grid.samplerate * (len(b) - 1) / (b[-1] - b[0]) if b and len(b) > 1 and b[-1] > b[0] else 120.0

    def beats(self) -> list:
        """Every beat's second in the file, in order."""
        out, k = [], 0
        while k < 4000:
            s = self.grid.seconds_at(k)
            if s is None or s > self.length:
                break
            if s >= 0:
                out.append(round(s, 3))
            k += 1
        return out

    def level_at(self, secs: float) -> float:
        i = int(secs * PEAKS_PER_S)
        return self.loud[i] / 255.0 if 0 <= i < len(self.loud) else 0.0


ONSET_HOP, ONSET_N = 512, 2048


def onset_envelope(samples, rate: int):
    """How much new sound each ~12 ms slice brings (spectral flux on a log spectrum, its local mean taken off):
    frame i sits at (i + 1) * ONSET_HOP + ONSET_N / 2 samples."""
    import numpy as np  # noqa: PLC0415

    x = np.asarray(samples, dtype=np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(x, ONSET_N)[::ONSET_HOP] * np.hanning(ONSET_N).astype(np.float32)
    spec = np.log1p(10.0 * np.abs(np.fft.rfft(frames, axis=1)))
    flux = np.maximum(0.0, np.diff(spec, axis=0)).sum(axis=1)
    return np.maximum(0.0, flux - np.convolve(flux, np.ones(16) / 16, "same"))


def grid_fit(env, rate: int, grid: TrackGrid) -> float:
    """The mean onset a grid's beats land on (higher is a better fit to the sound)."""
    import numpy as np  # noqa: PLC0415

    fps = rate / ONSET_HOP
    k, got = 0, []
    while True:
        t = grid.seconds_at(k)
        if t is None:
            break
        i = int(round((t * rate - ONSET_N / 2) / ONSET_HOP - 1))
        if i >= len(env):
            break
        if i >= 1:
            got.append(float(env[i - 1:i + 2].max()))
        k += 1
    return float(np.mean(got)) if got else 0.0 if fps else 0.0


def estimate_grid(samples, rate: int) -> TrackGrid:
    """A constant beat grid from the sound alone, for a song not in his Mixxx library: the tempo whose beats
    land on the most onset (a comb, weighted toward 110 BPM so it picks 100 over 133 or 200), then the tempo
    to 0.01 BPM and the first beat to 5 ms that fit the whole song best. Mixxx's own grid is always used
    when the library has one."""
    import numpy as np  # noqa: PLC0415

    hop, n = ONSET_HOP, ONSET_N
    if len(samples) < n * 8:
        return TrackGrid(samplerate=rate, first_beat=0.0, bpm=120.0)
    flux = onset_envelope(samples, rate)
    fps = rate / hop
    m = len(flux)

    def comb(bpm: float) -> tuple[float, float]:
        """(how much onset the beats of this tempo land on, per beat; the phase in frames) at its best phase."""
        period = 60.0 / bpm * fps
        count = int(m / period) - 1
        if count < 4:
            return -1.0, 0.0
        idx = (np.arange(count)[:, None] * period + np.arange(0, period, 0.5)[None, :]).astype(int)
        sc = flux[idx].sum(axis=0)
        k = int(sc.argmax())
        return float(sc[k]) / count, k * 0.5

    def prior(bpm: float) -> float:
        return math.exp(-0.5 * (math.log2(bpm / PRIOR_BPM) / 0.7) ** 2)

    coarse = float(max(np.arange(MIN_BPM, MAX_BPM, 0.25), key=lambda b: comb(b)[0] * prior(b)))
    # Then the tempo and first beat whose beats land on the most onset across the whole song (grid_fit, done
    # for every candidate at once): a tempo a hair off drifts a third of a beat by a song's end, and a first
    # beat read from one comb can sit between beats.
    peak = np.maximum(np.maximum(flux, np.roll(flux, 1)), np.roll(flux, -1))
    best_score, best_bpm, first_s = -1.0, coarse, 0.0
    for bpm in np.arange(coarse - 0.4, coarse + 0.4, 0.01):
        beat_s = 60.0 / bpm
        ks = np.arange(int(len(samples) / rate / beat_s) + 1)
        starts = np.arange(0.0, beat_s, 0.005)
        t = starts[:, None] + ks[None, :] * beat_s                        # every beat, for every first beat
        i = np.rint((t * rate - n / 2) / hop - 1).astype(int)
        ok = (i >= 0) & (i < m)
        sc = np.where(ok, peak[np.clip(i, 0, m - 1)], 0.0).sum(axis=1) / np.maximum(1, ok.sum(axis=1))
        j = int(sc.argmax())
        if sc[j] > best_score:
            best_score, best_bpm, first_s = float(sc[j]), float(bpm), float(starts[j])
    # bars count from the first beat, so it is the first beat the song is sounding on, never one in the
    # silence before it (Sorry: 0.58 s, not 0.0 s a beat earlier, which put every bar a beat off)
    x = np.abs(np.asarray(samples, dtype=np.float32))
    block = max(1, rate // 50)
    k = len(x) // block
    loud = x[: k * block].reshape(k, block).max(axis=1)
    sounding = np.nonzero(loud > 0.05 * (float(np.percentile(loud, 99)) or 1.0))[0]
    start = sounding[0] * block / rate if len(sounding) else 0.0
    beat_s = 60.0 / best_bpm
    while first_s < start - 0.1 * beat_s:
        first_s += beat_s
    return TrackGrid(samplerate=rate, first_beat=first_s * rate, bpm=round(best_bpm, 2))


def analyze(path: Path, grid: Optional[TrackGrid] = None, script: Optional[ShowScript] = None) -> Song:
    """Read one song file for the workspace. `grid` is Mixxx's when it has one; `script` a cached analysis."""
    import numpy as np  # noqa: PLC0415

    samples, rate = load_mono(path)
    x = np.abs(np.asarray(samples, dtype=np.float32))
    step = max(1, int(rate / PEAKS_PER_S))
    k = len(x) // step
    blocks = x[: k * step].reshape(k, step)
    peak = blocks.max(axis=1)
    rms = np.sqrt((blocks ** 2).mean(axis=1))
    top = float(np.percentile(peak, 99.5)) or 1.0
    peaks = [int(v) for v in np.clip(peak / top * 255, 0, 255)]
    # loudness on the peaks' scale (x2: music's peaks sit 2-4x over its RMS), so quiet and loud read apart
    loud = [int(v) for v in np.clip(rms / top * 2 * 255, 0, 255)]
    source = "mixxx"
    if grid is None or not (grid.bpm or grid.beats):
        grid, source = estimate_grid(samples, rate), "estimated"
    if script is None:
        try:
            script = analyze_track(path, grid)
        except Exception:  # noqa: BLE001 -- a file the analysis can't read still draws, with no parts
            script = None
    return Song(Path(path), len(samples) / rate, peaks, loud, grid, source, script)


def sections(song: Song, cues: tuple) -> list:
    """The sections in force (his section cues, else Llano's analysis) as [{kind, start, end}] in seconds."""
    script = cues_mod.script_for(cues, song.grid, None, song.script) if cues else song.script
    return _secs(song, script)


def _secs(song: Song, script: Optional[ShowScript]) -> list:
    out = []
    for s in (script.sections if script else []):
        a, b = song.grid.seconds_at(s.start_beat), song.grid.seconds_at(s.end_beat)
        if a is None or b is None:
            continue
        a, b = max(0.0, a), min(b, song.length)
        if b > a:
            out.append({"kind": s.kind, "start": round(a, 2), "end": round(b, 2)})
    return out


def _hex(r: float, g: float, b: float) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v * 255)))) for v in (r, g, b))


def _wash(fxs) -> tuple[str, float]:
    lit = [fx for fx in fxs if fx.dim > 0.02 and (fx.red + fx.green + fx.blue) > 0.02]
    if not lit:
        return "#000000", 0.0
    w = sum(fx.dim for fx in lit)
    r = sum(fx.red * fx.dim for fx in lit) / w
    g = sum(fx.green * fx.dim for fx in lit) / w
    b = sum(fx.blue * fx.dim for fx in lit) / w
    top = max(r, g, b) or 1.0
    return _hex(r / top, g / top, b / top), max(fx.dim for fx in lit)


def read_rig(rig) -> dict:
    """One rendered frame as the lanes draw it: {lane: (color, level 0..1)}."""
    from .rig import HEAD_WHEEL  # noqa: PLC0415

    bars = rig.bars
    out = {"wash": _wash([*rig.tetras, *(p for bar in bars for p in bar.pars)])}
    sw = max((bar.strobe_white for bar in bars), default=0.0)
    uv = max((bar.strobe_uv for bar in bars), default=0.0)
    flick = max((fx.strobe for fx in (*rig.tetras, *(p for bar in bars for p in bar.pars))), default=0.0)
    if sw > 0.02:
        out["strobe"] = ("#ffffff", sw)
    elif uv > 0.02:
        out["strobe"] = ("#8a40ff", uv)
    elif flick > 0.02:
        out["strobe"] = ("#c8c8c8", 0.5)
    else:
        out["strobe"] = ("#000000", 0.0)
    heads = [m for bar in bars for m in bar.movers if m.dim > 0.02]
    if heads:
        slot = heads[0].color if 0 <= heads[0].color < len(HEAD_WHEEL) else 0
        out["heads"] = (HEAD_WHEEL[slot][1], max(m.dim for m in heads))
    else:
        out["heads"] = ("#000000", 0.0)
    sticks = list(rig.sticks)
    color, level = _wash(sticks)
    masks = [sum(s.mask) / len(s.mask) for s in sticks if getattr(s, "mask", None)]
    out["sticks"] = (color, level * (masks and sum(masks) / len(masks) or 1.0))
    lasers = [bar.laser for bar in bars if bar.laser and bar.laser != "off"]
    out["laser"] = (LASER_HEX.get(lasers[0], "#30ff60"), 1.0) if lasers else ("#000000", 0.0)
    derbies = [d.color for bar in bars for d in bar.derbies if d.color and d.color != "off"]
    out["derby"] = (DERBY_HEX.get(derbies[0], "#ffffff"), 1.0) if derbies else ("#000000", 0.0)
    return out


def lanes(song: Song, cues: tuple, keys: tuple = (), settings: Optional[dict] = None,
          step: float = LANE_STEP) -> dict:
    """What the show plays on each lane across the whole song: {lane: [[start, end, color, level], ...]}.
    Rendered through the live show's own code path (Show.frame/render: looks, stick_fx, cues.place/dress)
    by a looks engine of its own (isolated), so nothing the live show shares is touched."""
    from . import stick_fx  # noqa: PLC0415
    from .looks import Frame, LooksEngine  # noqa: PLC0415
    from .rig import default_rig  # noqa: PLC0415

    eng = LooksEngine()
    eng.isolated = True
    if settings is not None:
        eng.settings = settings
    rig = default_rig()
    script = cues_mod.script_for(cues, song.grid, None, song.script) if cues else song.script
    bpm = song.bpm
    runs: dict = {k: [] for k in LANES}
    n = int(song.length / step) + 1
    seed = abs(hash(keys[0] if keys else str(song.path))) % 100000
    for i in range(n):
        t = i * step
        beat = song.grid.beat_at_seconds(t)
        if beat is None:
            continue
        look_beat, section, nxt, feel = cues_mod.place(cues, song.grid, None, script, beat, t)
        f = Frame(look_beat, bpm, True, level=song.level_at(t), section=section, next_section=nxt,
                  track_key=seed, song=keys[0] if keys else "", song_keys=tuple(keys), now=t, secs=t,
                  cues=cues, feel=feel)
        if feel[1]:
            from . import studio as studio_mod  # noqa: PLC0415
            rgb_ = studio_mod.parse_color(feel[1])
            eng.overrides.color = studio_mod.hue_sat(rgb_) if rgb_ else None
        else:
            eng.overrides.color = None
        out = eng.render(f, rig)
        moving = not eng.limit and not eng.is_still(eng._cfg or {})
        stick_fx.apply(out, section if moving else None, look_beat)
        if cues:
            cues_mod.dress(out, f)
        for lane, (color, level) in read_rig(out).items():
            level = round(min(1.0, level), 2)
            rs = runs[lane]
            if rs and rs[-1][2] == color and abs(rs[-1][3] - level) < 0.08 and abs(rs[-1][1] - t) < step * 1.5:
                rs[-1][1] = round(t + step, 3)
            else:
                rs.append([round(t, 3), round(t + step, 3), color, level])
    return runs


class Workspace:
    """Songs read for the workspace, kept while their file is unchanged (the analysis takes seconds; the
    lanes are made again on each change of his cues, a second or so). Thread-safe; at most KEEP songs."""
    KEEP = 12

    def __init__(self):
        self._songs: dict = {}
        self._lanes: dict = {}
        self.lock = threading.Lock()

    def song(self, path: Path, grid: Optional[TrackGrid] = None, script: Optional[ShowScript] = None) -> Song:
        path = Path(path)
        mtime = path.stat().st_mtime
        with self.lock:
            got = self._songs.get(str(path))
        if got is not None and got[0] == mtime:
            return got[1]
        s = analyze(path, grid, script)
        with self.lock:
            self._songs[str(path)] = (mtime, s)
            while len(self._songs) > self.KEEP:
                self._songs.pop(min(self._songs, key=lambda k: self._songs[k][1].made))
        return s

    def lanes(self, song: Song, cues: tuple, keys: tuple, settings: Optional[dict] = None) -> dict:
        key = (str(song.path), song.made, json.dumps(list(cues), sort_keys=True), tuple(keys))   # a cue is a dict
        with self.lock:
            got = self._lanes.get(key)
        if got is not None:
            return got
        made = lanes(song, cues, keys, settings)
        with self.lock:
            self._lanes = {k: v for k, v in self._lanes.items() if k[0] != key[0]}
            self._lanes[key] = made
        return made


def payload(song: Song, cues: tuple, keys: tuple, title: str, lanes_: dict) -> dict:
    """Everything the page draws for one song."""
    return {"key": keys[0] if keys else "", "title": title, "length": round(song.length, 2),
            "bpm": round(song.bpm, 2), "grid": song.grid_source, "beats": song.beats(),
            "peaks_per_s": PEAKS_PER_S, "peaks": song.peaks, "loud": song.loud,
            "sections": sections(song, cues), "auto": _secs(song, song.script),
            "mine": any(c.get("do") == "section" for c in cues), "cues": list(cues),
            "lanes": lanes_, "lane_names": LANE_NAMES, "lane_step": LANE_STEP}
