"""Write demo_songs/songs.json: each demo song's tempo, first beat, song sections and bar loudness.

  python make_demo_songs.py      # needs numpy + soundfile (a dev machine, not the shipped app)

The sections come from the same Find song sections the app runs on Mixxx songs (show_script.
analyze_track); Mixxx normally supplies the beat grid, so here the tempo and first beat are found
from the audio first. The shipped app only reads songs.json, so the demo needs no math library.
Every song must be CC0, or CC-BY with its credit shown in the app; the credit and license
travel in SONGS below and the window shows them under the song picker.
"""
import json
import sys
from pathlib import Path

import numpy as np

W = Path(__file__).resolve().parent
REPO = next(p for p in W.parents if (p / "tools" / "gigbar_lights").is_dir())
sys.path.insert(0, str(REPO))
from tools.gigbar_lights import show_script  # noqa: E402
from tools.gigbar_lights.beat_clock import TrackGrid  # noqa: E402

DIR = REPO / "tools" / "gigbar_lights" / "demo_songs"
CC0 = ("CC0 1.0 (public domain)", "https://creativecommons.org/publicdomain/zero/1.0/")
SONGS = [
    {"id": "groove", "file": "cute-bass.mp3", "title": "Cute Bass", "artist": "Alex McCulloch (Pro Sensory)",
     "feel": "Steady groove", "license": CC0, "source": "https://opengameart.org/content/cute-bass",
     "credit": "Music: \"Cute Bass\" by Alex McCulloch (Pro Sensory), CC0, via OpenGameArt"},
    {"id": "drop", "file": "neon-hyperdrive.mp3", "title": "Neon Hyperdrive", "artist": "adiutorium",
     "feel": "Big build and drop", "license": CC0, "source": "https://opengameart.org/content/neon-hyperdrive",
     "credit": "Music: \"Neon Hyperdrive\" by adiutorium, CC0, via OpenGameArt"},
    {"id": "slow", "file": "basi-beta.mp3", "title": "Basi Beta", "artist": "lushogames",
     "feel": "Slower", "license": CC0, "source": "https://opengameart.org/content/basi-beta",
     "credit": "Music: \"Basi Beta\" by lushogames, CC0, via OpenGameArt"},
]


def onset_strength(x, rate, hop=512, n=2048):
    """Spectral flux: how much new sound starts in each ~12 ms step."""
    frames = 1 + (len(x) - n) // hop
    win = np.hanning(n).astype(np.float32)
    out = np.zeros(frames, dtype=np.float32)
    prev = None
    for i in range(frames):
        s = np.log1p(np.abs(np.fft.rfft(x[i * hop:i * hop + n] * win)))
        if prev is not None:
            out[i] = np.maximum(0, s - prev).sum()
        prev = s
    out -= np.convolve(out, np.ones(16) / 16, mode="same")
    return np.maximum(out, 0), rate / hop


def tempo_and_first_beat(x, rate, lo=60.0, hi=180.0) -> tuple[float, float]:
    env, fps = onset_strength(x, rate)
    ac = np.correlate(env, env, mode="full")[len(env) - 1:]
    lags = np.arange(len(ac))
    best = None
    for bpm in np.arange(lo, hi, 0.05):
        lag = fps * 60 / bpm
        score = sum(w * np.interp(k * lag, lags, ac) for k, w in ((1, 1.0), (2, 0.5), (4, 0.25)))
        score *= np.exp(-0.5 * (np.log2(bpm / 115) / 0.7) ** 2)  # a dancer's beat over half/double time
        if best is None or score > best[0]:
            best = (score, float(bpm))
    bpm = best[1]
    period, t = fps * 60 / bpm, np.arange(len(env))
    phases = np.arange(0, period, 0.25)
    scores = [np.interp(np.arange(p, len(env) - 1, period), t, env).sum() for p in phases]
    return bpm, float(phases[int(np.argmax(scores))] / fps)


def describe(song: dict) -> dict:
    path = DIR / song["file"]
    x, rate = show_script.load_mono(path)
    bpm, first = tempo_and_first_beat(x, rate)
    grid = TrackGrid(samplerate=rate, first_beat=first * rate, bpm=bpm)
    script = show_script.analyze_track(path, grid)  # Find song sections, as for a Mixxx song
    if script is None:
        raise SystemExit(f"{song['file']}: too short for song sections")
    frames_per_bar = rate * 60 / bpm * show_script.BEATS_PER_BAR
    starts = list(np.arange(first * rate, len(x), frames_per_bar))
    loud, _ = show_script.bar_energies(x, rate, starts)
    lo_, hi_ = min(loud), max(loud)
    out = {k: v for k, v in song.items() if k != "license"}
    out.update(license=song["license"][0], license_url=song["license"][1], bpm=round(bpm, 2),
               first_beat_s=round(first, 3), duration_s=round(len(x) / rate, 2),
               bars=[round((v - lo_) / (hi_ - lo_ or 1), 3) for v in loud],
               sections=json.loads(script.to_json())["sections"])
    return out


if __name__ == "__main__":
    songs = [describe(s) for s in SONGS]
    (DIR / "songs.json").write_text(json.dumps({"version": 1, "songs": songs}, indent=1) + "\n")
    for s in songs:
        kinds = " ".join(f"{x['kind']}@{round(x['start_beat'] * 60 / s['bpm'] + s['first_beat_s'])}s" for x in s["sections"])
        print(f"{s['title']}: {s['bpm']} BPM, first beat {s['first_beat_s']} s, {s['duration_s']} s; {kinds}")
