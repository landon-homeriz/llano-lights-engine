"""Find the beat in live sound: tempo and where the next beat lands, from audio as it plays.

Mixxx hands us an exact beat grid. Spotify and YouTube Music hand us nothing but the
sound, so this listens to it (system_audio.py feeds it what the speakers play) and works
the beat out the way a person tapping along does:

  1. onset strength: how much new energy each ~11 ms slice of sound brings (spectral flux
     on a log spectrum, so a kick or a snare stands out and a held pad does not);
  2. tempo: the repeat period of that strength over the last 8 seconds (autocorrelation),
     weighted toward 120 BPM so it picks 128 over 64 or 256;
  3. phase: which offset of that period lines up with the most onsets (a comb);
  4. a beat counter that runs at the tempo between updates and is nudged toward each new
     phase reading, so the lights stay steady and never step backward.

Pure numpy, no audio device: tests feed it decoded files and check it against the beat
grid we know.
"""
from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

MIN_BPM, MAX_BPM = 60.0, 190.0
PRIOR_BPM, PRIOR_OCTAVES = 110.0, 0.7   # tempo prior: log-normal around 110 BPM
HISTORY_S = 8.0                         # onset history the tempo is read from
MIN_HISTORY_S = 3.0                     # no beat claimed before this much music
SILENCE_RMS = 1e-3                      # below this (about -60 dBFS) is silence
QUIET_AFTER_S = 1.5                     # this long under SILENCE_RMS = nothing playing
SOUNDING_GAP_S = 0.2                    # a gap longer than this breaks "continuous sound"
PHASE_GAIN = 0.5                       # share of the phase error corrected per update
SNAP_BEATS = 0.3                        # the averaged evidence this far off re-locks at once
PHASE_BINS = 48
EVIDENCE_DECAY = 0.85                   # per update: about 1.5 s of memory
UPDATE_S = 0.25                         # tempo and phase are read this often (the count runs between)
TEMPO_HOLD_S = 2.0                      # a new tempo has to keep winning this long to replace the old
# A beat period also shows at half and twice its lag; scoring those too keeps a syncopated
# bass line (its pattern repeats every two beats) from reading as half tempo. Tuned on the
# demo songs, 8 s windows every 4 s: every window lands on the real beats, the right octave
# on most; an octave off still flashes on beats (half or double time).
HALF_W = DOUBLE_W = 0.5
BANDS_HZ = ((30, 200), (200, 2000), (2000, 8000))
ONSET_LAG_S = 0.025                     # spectral flux peaks this long after the beat (measured on the demo songs)


@dataclass
class BeatReading:
    """What the tracker hears right now."""
    playing: bool        # sound, not silence (stays true through gaps up to QUIET_AFTER_S)
    sounding: bool       # sound right now, continuous: under SOUNDING_GAP_S of silence
    locked: bool         # enough music heard to trust the beat
    bpm: float
    beat: float          # running beat count at the reading's time (fraction = phase)
    level: float         # 0..1 loudness against the recent peak
    at: float            # perf_counter time the reading is for


class BeatTracker:
    def __init__(self, samplerate: int = 44100, hop: int = 512, frame: int = 1024):
        self.sr, self.hop, self.frame = samplerate, hop, frame
        self.fps = samplerate / hop
        self.window = np.hanning(frame).astype(np.float32)
        hz = samplerate / frame
        # kick, snare/body, hats: each band's flux is scaled by its own running average, so
        # a kick (a few low bins) counts as much as a hi-hat (hundreds of high bins)
        self.bands = [(max(1, int(lo / hz)), max(2, int(hi / hz))) for lo, hi in BANDS_HZ]
        self.bins = self.bands[-1][1]
        self.band_avg = np.ones(len(self.bands))
        self.prev_spec: Optional[np.ndarray] = None
        self.buf = np.zeros(0, dtype=np.float32)
        self.onsets: deque = deque(maxlen=int(HISTORY_S * self.fps))
        self.frames_seen = 0
        self.t_last: Optional[float] = None   # perf_counter time of the newest onset frame
        self.lock = threading.Lock()
        # tempo + phase state
        self.bpm = 0.0
        self.hint_bpm = 0.0                   # the song's BPM when known (his Mixxx library)
        self._pending_bpm = 0.0
        self._pending_since: Optional[float] = None
        self._next_update = 0.0
        self.b0: Optional[float] = None       # beat count at time t0
        self.t0 = 0.0
        self.evidence = np.zeros(PHASE_BINS)
        # loudness
        self.rms = 0.0
        self.peak_rms = 0.05
        self.quiet_s = QUIET_AFTER_S

    # --- audio in ------------------------------------------------------------------------

    def feed(self, samples: np.ndarray, at: float) -> None:
        """Add mono samples whose last one was heard at perf_counter time `at`."""
        x = np.asarray(samples, dtype=np.float32).ravel()
        if not len(x):
            return
        with self.lock:
            self._loudness(x)
            self.buf = np.concatenate([self.buf, x])
            n = (len(self.buf) - self.frame) // self.hop + 1
            if n <= 0:
                return
            for i in range(n):
                seg = self.buf[i * self.hop:i * self.hop + self.frame]
                spec = np.log1p(100.0 * np.abs(np.fft.rfft(seg * self.window))[:self.bins])
                flux = 0.0
                if self.prev_spec is not None:
                    rise = np.maximum(spec - self.prev_spec, 0.0)
                    per = np.array([rise[a:b].sum() for a, b in self.bands])
                    self.band_avg += 0.01 * (per - self.band_avg)   # about 1 s to settle
                    flux = float((per / np.maximum(self.band_avg, 1e-6)).sum())
                self.prev_spec = spec
                self.onsets.append(flux)
            self.frames_seen += n
            self.buf = self.buf[n * self.hop:]
            # the newest onset frame ends `len(buf)` samples before the last sample heard
            self.t_last = at - len(self.buf) / self.sr
            if self.t_last >= self._next_update:
                self._next_update = self.t_last + UPDATE_S
                self._update(self.t_last)

    def _loudness(self, x: np.ndarray) -> None:
        rms = float(np.sqrt(np.mean(x * x)))
        dt = len(x) / self.sr
        self.rms = rms
        self.quiet_s = self.quiet_s + dt if rms < SILENCE_RMS else 0.0
        # the peak falls back slowly (about 20 s to halve) so a quiet song still fills 0..1
        self.peak_rms = max(rms, self.peak_rms * 0.5 ** (dt / 20.0), 0.02)

    # --- tempo and phase -----------------------------------------------------------------

    def _envelope(self) -> np.ndarray:
        env = np.asarray(self.onsets, dtype=np.float64)
        # take out the local average (about 0.3 s) so only the hits are left
        k = max(3, int(0.3 * self.fps) | 1)
        local = np.convolve(env, np.ones(k) / k, mode="same")
        return np.maximum(env - local, 0.0)

    def _tempo(self, env: np.ndarray) -> Optional[float]:
        e = env - env.mean()
        n = len(e)
        spec = np.fft.rfft(e, 2 * n)
        ac = np.fft.irfft(spec * np.conj(spec))[:n]
        if ac[0] <= 0:
            return None
        lo, hi = int(self.fps * 60 / MAX_BPM), min(n - 2, int(self.fps * 60 / MIN_BPM) + 1)
        if hi <= lo + 2:
            return None
        lags = np.arange(lo, hi + 1)
        bpms = 60.0 * self.fps / lags
        prior = np.exp(-0.5 * (np.log2(bpms / PRIOR_BPM) / PRIOR_OCTAVES) ** 2)

        def at(lag: np.ndarray) -> np.ndarray:  # autocorrelation at fractional lags, 0 past the end
            i0 = np.floor(lag).astype(int)
            f = lag - i0
            ok = i0 + 1 < n
            out = np.zeros(len(lag))
            out[ok] = ac[i0[ok]] * (1 - f[ok]) + ac[i0[ok] + 1] * f[ok]
            return out

        lf = lags.astype(float)
        score = (at(lf) + HALF_W * at(lf / 2) + DOUBLE_W * at(lf * 2)) * prior
        i = int(np.argmax(score))
        if score[i] <= 0:
            return None
        lag = float(lags[i])
        if 0 < i < len(lags) - 1:  # parabolic peak for a fractional lag
            a, b, c = score[i - 1], score[i], score[i + 1]
            d = a - 2 * b + c
            if d < 0:
                lag += 0.5 * (a - c) / d
        bpm = 60.0 * self.fps / lag
        if self.hint_bpm:  # the library knows the song's tempo: it only settles the octave
            bpm = min((bpm * m for m in (0.5, 1.0, 2.0)), key=lambda b: abs(math.log2(b / self.hint_bpm)))
        return bpm

    def _settle_tempo(self, bpm: float, t: float) -> None:
        if not self.bpm:
            self.bpm = bpm
            return
        if abs(bpm / self.bpm - 1) < 0.04:  # the same tempo, read again: drift toward it gently
            self.bpm += 0.25 * (bpm - self.bpm)
            self._pending_since = None
            return
        if self._pending_since is None or abs(self._pending_bpm - bpm) / bpm >= 0.04:
            self._pending_bpm, self._pending_since = bpm, t
        elif t - self._pending_since >= TEMPO_HOLD_S:  # a new song, or we were wrong: move to it
            self.bpm, self._pending_since = bpm, None

    def _phase_scores(self, env: np.ndarray) -> np.ndarray:
        """How well each phase lines up with the onsets: PHASE_BINS scores, bin k = a beat
        k/PHASE_BINS of a beat before the newest onset frame."""
        period = 60.0 * self.fps / self.bpm
        n = len(env)
        out = np.zeros(PHASE_BINS)
        for k in range(PHASE_BINS):
            off = k * period / PHASE_BINS     # frames back from the newest to the last beat
            idx = n - 1 - off - period * np.arange(int((n - 1 - off) // period) + 1)
            idx = idx[idx >= 0]
            if not len(idx):
                continue
            w = 0.85 ** np.arange(len(idx))   # recent beats count more
            i0 = np.floor(idx).astype(int)
            frac = idx - i0
            i1 = np.minimum(i0 + 1, n - 1)
            out[k] = float(((env[i0] * (1 - frac) + env[i1] * frac) * w).sum())
        return out

    def _update(self, t: float) -> None:
        if self.frames_seen < MIN_HISTORY_S * self.fps or self.quiet_s >= QUIET_AFTER_S:
            return
        env = self._envelope()
        bpm = self._tempo(env)
        if bpm is None:
            return
        self._settle_tempo(bpm, t)
        scores = self._phase_scores(env)
        if scores.max() <= 0:
            return
        scores = scores / scores.max()
        lag = ONSET_LAG_S * self.bpm / 60.0
        phases = (np.arange(PHASE_BINS) / PHASE_BINS + lag) % 1.0   # beats since the last beat, per bin
        if self.b0 is None:
            self.b0, self.t0 = float(phases[int(np.argmax(scores))]), t
            self.evidence[:] = 0.0
        predicted = self.b0 + (t - self.t0) * self.bpm / 60.0
        # Evidence for where the beat sits against our count, averaged over a few seconds: with a
        # syncopated bass the on-beat and the off-beat each win single reads, but the on-beat (kick,
        # snare and hats every beat) wins on average. Bin j = the count is (j/N - 0.5) beats late.
        err = (phases - predicted + 0.5) % 1.0 - 0.5
        bins = np.floor((err + 0.5) * PHASE_BINS).astype(int) % PHASE_BINS
        self.evidence *= EVIDENCE_DECAY
        np.add.at(self.evidence, bins, scores)
        j = int(np.argmax(self.evidence))
        a, b, c = self.evidence[j - 1], self.evidence[j], self.evidence[(j + 1) % PHASE_BINS]
        d = a - 2 * b + c
        shift = 0.5 * (a - c) / d if d < 0 else 0.0
        best = (j + 0.5 + shift) / PHASE_BINS - 0.5
        step = best if abs(best) > SNAP_BEATS else PHASE_GAIN * best  # far off: a new song, re-lock now
        self.b0, self.t0 = predicted + step, t
        # the count moved by `step`: move the evidence with it, so it stays against the count
        self.evidence = np.roll(self.evidence, -int(round(step * PHASE_BINS)))

    # --- reading -------------------------------------------------------------------------

    def reading(self, now: float) -> BeatReading:
        with self.lock:
            playing = self.quiet_s < QUIET_AFTER_S and self.t_last is not None and now - self.t_last < 1.0
            locked = playing and self.b0 is not None and self.bpm > 0
            beat = self.b0 + (now - self.t0) * self.bpm / 60.0 if locked else 0.0
            level = min(1.0, math.sqrt(self.rms / self.peak_rms)) if playing else 0.0
            sounding = playing and self.quiet_s < SOUNDING_GAP_S
            return BeatReading(playing, sounding, locked, self.bpm, beat, level, now)

    def reset(self) -> None:
        """Forget the beat (a new song): keep the loudness scale."""
        with self.lock:
            self.onsets.clear()
            self.prev_spec, self.frames_seen = None, 0
            self.bpm, self._pending_since, self.b0 = 0.0, None, None
            self.evidence[:] = 0.0
