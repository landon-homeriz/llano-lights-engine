"""Ready-to-play cuts of a set's songs, so Mixxx's Auto DJ hands one song to the next cleanly
(Llano PM #23179, the wedding DJ system).

Why files and not cue points written into Mixxx. Mixxx's Auto DJ (checked against the 2.5 source,
src/library/autodj/autodjprocessor.cpp and src/engine/enginexfader.cpp, 2026-11-12):

  - has four modes (Full Intro + Outro, Fade At Outro Start, Full Track, Skip Silence) and never
    matches beats: it only moves the crossfader, in a straight line, over the transition time;
  - with the stock crossfader curve the next song fades IN over the first half of the transition
    while the old one is still at full, and the old one fades OUT over the second half;
  - so a song that starts on its first note loses that note to the fade-in, and intro/outro cues
    cannot fix it: a cue cannot sit before 0:00.

A cut file can. Each cut is the song from its first sound to where it should leave, with:

  lead   LEAD_S of sound too quiet to hear (but above the -60 dBFS Mixxx counts as "sound", so no
         mode skips it), so the first note lands exactly as the fade-in finishes: at full volume
  tail   TAIL_S of fade baked into the end, so the song leaves smoothly even on a crossfader curve
         that would cut it
  level  every song brought to the same loudness, so a 1987 recording is not half as loud as a
         2019 one

With Auto DJ set to TRANSITION_S seconds that is: the old song at full, the new one's first note at
full, and the old one gone a second later. Nothing is written into Mixxx, the originals are never
touched, and the same files play in order from a phone if the laptop dies.

The cut is the whole song unless it is told to leave early: a song that fades out for a long time is
left before the fade dies, and `short` leaves at a section change late in the song (a suggestion he
can take or move; never applied on its own).

A dance song also starts where the dancing starts and leaves where it stops (dance_points, Llano PM
#23751): a DJ mixes in past a long intro, but Auto DJ plays every file from its first second, so the
cut skips it (I Gotta Feeling's first 30 seconds) with a short fade in that ends on the downbeat, and
leaves a long outro or ambient tail with a short fade, so Auto DJ hands over on time. A line dance
(its calls start in the intro), cocktail hour, dinner and the moments play whole. His own Starts at
and Ends at (Review) win over all of it. Mixxx's beat grid, and so the lights, follow the cut file.
The opening song of a set keeps its intro (keep_intro, Llano PM #23864): the first song of the dancing
plays from its first note, and Review still offers where the dancing starts.

A hold is an hour of silence with a name ("HOLD: Toasts"). In the Auto DJ queue it is where the
music stops for a live moment; Fade Now moves on. Mixxx reads an all-silent file as all sound
(AnalyzerSilence::storeResults), so no mode skips it.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

TRANSITION_S = 2.0            # what Auto DJ's seconds box must say
LEAD_S = TRANSITION_S / 2     # the fade-in half
TAIL_S = TRANSITION_S / 2     # the fade-out half
LEAD_DBFS = -58.0             # above Mixxx's -60 dBFS "first sound"; a steady offset, so nothing is heard
LEAD_EDGE_S = 0.010           # the lead eases in and out over this long, so it never clicks
TARGET_LUFS = -16.0
FLOOR_LUFS = -23.0            # one quiet recording never pulls the whole night under this
PEAK_CEILING = 10 ** (-1.0 / 20)
PEAK_OUTLIER = 10 ** (3.0 / 20)   # a song's peak counts at most 3 dB over its 99.99th percentile sample
SILENT_DBFS = -55.0           # a song whose own loud level is under this is dead air, not music
MAX_CUT_S = 12 * 60.0         # a longer file (a recorded mix) is played as it is, never held in memory
# Types Mixxx plays that the audio library here cannot decode (MPEG-4 audio: iTunes, Apple Music)
UNDECODED = {".m4a", ".aac", ".mp4", ".m4b", ".alac", ".wma"}
HOP_S = 0.1
HOLD_S = 3600                 # a hold outlasts any toast; each hold gets its own length (see hold())
MIN_KEEP = 0.6                # a short cut never drops more than 40% of a song
SOFT_TAIL_S = 4.0             # the baked fade for background parts (cocktail, dinner)
# Where the music is "there": this far under the song's own loud level. On a dance floor a quiet
# intro or a long ring-out is dead air between two songs, so the cut starts as the music arrives
# and leaves when it has gone; background parts keep more of both.
ARRIVE_DB = {"dancing": 14.0, "soft": 30.0}
GONE_DB = {"dancing": 16.0, "soft": 24.0}
PRE_S = {"dancing": 0.4, "soft": 1.5}     # kept before the music arrives (faded in when trimmed)
POST_S = {"dancing": 0.6, "soft": 1.5}    # kept after it has gone, under the baked fade
# Where the dancing starts and stops (Llano PM #23751: "I Gotta Feeling" has 30 seconds before the song
# really starts; a DJ mixes in past it). Measured on his own Avery & Jordan dance songs, 2026-11-15.
INTRO_MIN_S = 6.0         # an opening shorter than this is not worth cutting
INTRO_MAX_S = 45.0        # past this the first section change is a verse ending, not an intro
INTRO_STRENGTH = 0.45     # how clear the change out of the intro is, against the song's clearest change
INTRO_CONTRAST = 2.0      # ... and in its own right (section_changes min_contrast)
LONG_INTRO_S = 10.0       # an intro this long is named in Review
OUTRO_MIN_S = 8.0         # a tail this long after the dancing stops is cut
LONG_OUTRO_S = 15.0       # a tail this long is named in Review
START_FADE_S = 0.25       # a cut that starts past the intro fades in this long, ending on the downbeat
END_FADE_S = 1.5          # a cut that leaves where the dancing stops fades out this long
GROOVE_DB = 6.0           # "dancing energy": within this of the song's loud level ...
GROOVE_LOW_DB = 12.0      # ... with its bass within this of the song's usual bass


# --- reading and measuring -------------------------------------------------------------------------

class DamagedFile(Exception):
    """A song file that cannot be played through: `read_s` seconds were readable of about `total_s`."""

    def __init__(self, path, read_s: float, total_s: float, missing_s: float = 0.0):
        self.path, self.read_s, self.total_s, self.missing_s = str(path), read_s, total_s, missing_s
        name = Path(path).name
        if missing_s:
            super().__init__(f"{name} is damaged: about {missing_s:.0f} seconds of it are blank. Replace the file.")
        else:
            super().__init__(f"{name} is damaged: it stops reading at {mmss(read_s)} of {mmss(total_s)}. Replace the file.")


class CannotCut(Exception):
    """A file that is fine but cannot be cut here: `why` is "type" (a kind this laptop's audio
    library cannot decode, like an iTunes .m4a) or "long" (over MAX_CUT_S). Mixxx plays it as it
    is; `seconds` is its length when the file says (0.0 when it does not)."""

    def __init__(self, path, why: str, seconds: float = 0.0):
        self.path, self.why, self.seconds = str(path), why, float(seconds or 0.0)
        super().__init__(f"{Path(path).name} cannot be cut here ({why})")


def media_seconds(path) -> float:
    """A file's length in seconds from its own header, without decoding it: MPEG-4 audio (.m4a) from
    its movie header, anything else through the audio library. 0.0 when it cannot be told."""
    import struct  # noqa: PLC0415

    p = Path(path)
    try:
        with open(p, "rb") as f:
            head = f.read(12)
            if len(head) >= 8 and head[4:8] == b"ftyp":
                f.seek(0)
                end = p.stat().st_size

                def boxes(stop):
                    while f.tell() + 8 <= stop:
                        at = f.tell()
                        size, kind = struct.unpack(">I4s", f.read(8))
                        if size == 1:
                            size = struct.unpack(">Q", f.read(8))[0]
                        elif size == 0:
                            size = stop - at
                        if size < 8:
                            return
                        yield kind, at, size
                        f.seek(at + size)

                for kind, at, size in boxes(end):
                    if kind != b"moov":
                        continue
                    f.seek(at + 8)
                    for k2, at2, _size2 in boxes(at + size):
                        if k2 == b"mvhd":
                            f.seek(at2 + 8)
                            body = f.read(32)
                            if body[:1] == b"\x01":
                                scale, dur = struct.unpack(">IQ", body[20:32])
                            else:
                                scale, dur = struct.unpack(">II", body[12:20])
                            return round(dur / scale, 2) if scale else 0.0
                    return 0.0
                return 0.0
    except (OSError, struct.error):
        return 0.0
    try:
        import soundfile  # noqa: PLC0415
        info = soundfile.info(str(p))
        return round(info.frames / info.samplerate, 2)
    except Exception:  # noqa: BLE001 -- ok: an unreadable header just means the length is unknown
        return 0.0


def _is_mpeg4(path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(12)[4:8] == b"ftyp"
    except OSError:
        return False


def blank_seconds(path) -> float:
    """Seconds of an MP3 that are blanked out (long runs of zero bytes inside the audio, the mark of
    an unfinished download). 0.0 for a whole file or one that is not MP3."""
    import re  # noqa: PLC0415

    p = Path(path)
    if p.suffix.lower() != ".mp3":
        return 0.0
    try:
        b = p.read_bytes()
    except OSError:
        return 0.0
    skip = 0
    if b[:3] == b"ID3" and len(b) > 10:     # the tag's own padding is zeros too: start after it
        skip = 10 + ((b[6] & 127) << 21 | (b[7] & 127) << 14 | (b[8] & 127) << 7 | (b[9] & 127))
    blank = sum(len(m.group()) for m in re.finditer(rb"\x00{65536,}", b[skip:]))
    audio = max(1, len(b) - skip)
    try:
        import soundfile  # noqa: PLC0415
        info = soundfile.info(str(p))
        secs = info.frames / info.samplerate
    except Exception:  # noqa: BLE001 -- ok: a file soundfile cannot open is reported by read()
        secs = 0.0
    if not blank:
        return 0.0
    # by its share of the file when the length is known, else at 320 kbps (the least it can be)
    return round(secs * blank / audio, 1) if secs else round(blank / 40000, 1)


def read(path) -> tuple:
    """(stereo float32 array of shape (n, 2), sample rate). soundfile reads MP3/FLAC/WAV/OGG.

    A sound file of a kind it cannot decode (an iTunes .m4a), or one longer than MAX_CUT_S, raises
    CannotCut: nothing is wrong with it, it just plays as it is.

    Read in pieces, because one bad frame makes soundfile give up on the whole file: a stray tag at
    the very end costs under a second and is let through; a file that stops reading early, or has
    blanked-out stretches, raises DamagedFile so a broken song is caught at home, not on the night."""
    import numpy as np  # noqa: PLC0415
    import soundfile  # noqa: PLC0415

    missing = blank_seconds(path)
    parts, n = [], 0
    try:
        f = soundfile.SoundFile(str(path))
    except soundfile.LibsndfileError:
        kind = Path(path).suffix.lower()
        if kind in UNDECODED and (kind in (".aac", ".wma") or _is_mpeg4(path)):
            raise CannotCut(path, "type", media_seconds(path)) from None
        raise DamagedFile(path, 0.0, 0.0, missing) from None     # not even its start can be read
    with f:
        rate, total = int(f.samplerate), int(f.frames)
        if rate and total / rate > MAX_CUT_S:
            raise CannotCut(path, "long", total / rate)
        step = 1 << 18
        while True:
            try:
                b = f.read(step, dtype="float32", always_2d=True)
            except soundfile.LibsndfileError:
                # one bad frame fails the whole read: go back and take the piece in small steps, so
                # only the frames at the bad spot are lost
                if step > 2048:
                    try:
                        f.seek(n)
                    except soundfile.LibsndfileError:
                        break
                    step = 2048
                    continue
                break
            if not len(b):
                break
            parts.append(b)
            n += len(b)
    # MP3 lengths in the header are estimates and can run long; within 5% or 8 seconds of the end
    # is the tail of the file (a stray tag), anything earlier is damage
    if total - n > max(8 * rate, 0.05 * total):
        raise DamagedFile(path, n / rate, total / rate, missing)
    if missing >= 2.0 or not parts:
        raise DamagedFile(path, n / rate, max(total, n) / rate, missing)
    x = np.concatenate(parts)
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    elif x.shape[1] > 2:
        x = x[:, :2]
    return np.ascontiguousarray(x), rate


def envelope(x, rate: int, hop_s: float = HOP_S):
    """Level in dBFS per hop (RMS over both channels); -120 for digital silence."""
    import numpy as np  # noqa: PLC0415

    hop = max(1, int(round(rate * hop_s)))
    n = len(x) // hop
    if n == 0:
        return np.full(1, -120.0)
    p = np.empty(n)
    step = 256                            # hops (about 25 s) at a time: the squares of a whole song at once are four times its size
    for lo in range(0, n, step):
        hi = min(n, lo + step)
        seg = x[lo * hop: hi * hop].astype(np.float64)
        p[lo:hi] = (seg * seg).mean(axis=1).reshape(hi - lo, hop).mean(axis=1)
    return 10 * np.log10(np.maximum(p, 1e-12))


def _k_weight(freqs, rate: int):
    """|H(f)|^2 of the ITU-R BS.1770 K-weighting (shelf then high-pass), for any sample rate."""
    import numpy as np  # noqa: PLC0415

    def biquad(f0, q, kind, gain_db=0.0):
        k = math.tan(math.pi * f0 / rate)
        if kind == "shelf":
            vh = 10 ** (gain_db / 20)
            vb = vh ** 0.4996667741545416
            a0 = 1 + k / q + k * k
            b = [(vh + vb * k / q + k * k) / a0, 2 * (k * k - vh) / a0, (vh - vb * k / q + k * k) / a0]
            a = [1.0, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0]
        else:
            a0 = 1 + k / q + k * k
            b = [1 / a0, -2 / a0, 1 / a0]
            a = [1.0, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0]
        z = np.exp(-2j * np.pi * freqs / rate)
        return np.abs((b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)) ** 2

    return (biquad(1681.974450955533, 0.7071752369554196, "shelf", 3.999843853973347)
            * biquad(38.13547087602444, 0.5003270373238773, "hp"))


def loudness(x, rate: int) -> float:
    """Integrated loudness in LUFS (BS.1770 gating: 400 ms blocks, 75% overlap, -70 absolute and
    -10 LU relative). -70.0 for silence."""
    import numpy as np  # noqa: PLC0415

    block, step = int(0.4 * rate), int(0.1 * rate)
    if len(x) < block:
        return -70.0
    w = _k_weight(np.fft.rfftfreq(block, 1 / rate), rate)
    powers = []
    for ch in range(x.shape[1]):
        # frames of the channel, one FFT per block; Parseval gives the weighted mean square
        idx = np.arange(0, len(x) - block + 1, step)
        out = np.empty(len(idx))
        for lo in range(0, len(idx), 96):      # blocks at a time: each is 0.4 s as float64 and again as its spectrum
            sl = idx[lo:lo + 96]
            frames = np.stack([x[i:i + block, ch] for i in sl]).astype(np.float64)
            spec = np.abs(np.fft.rfft(frames, axis=1)) ** 2
            spec[:, 1:-1] *= 2
            out[lo:lo + len(sl)] = (spec * w).sum(axis=1) / (block * block)
        powers.append(out)
    z = np.sum(powers, axis=0)
    lk = -0.691 + 10 * np.log10(np.maximum(z, 1e-12))
    keep = z[lk > -70.0]
    if not len(keep):
        return -70.0
    rel = -0.691 + 10 * np.log10(keep.mean()) - 10.0
    keep = z[(lk > -70.0) & (lk > rel)]
    if not len(keep):
        return -70.0
    return float(-0.691 + 10 * np.log10(keep.mean()))


# --- where a song starts and where it leaves --------------------------------------------------------

@dataclass
class Cut:
    """One song's cut. Seconds are in the SOURCE file; `fade_s` is the baked fade ending at end_s."""
    start_s: float
    end_s: float
    fade_s: float
    gain_db: float
    lufs: float
    source_s: float
    kind: str            # "whole", "trimmed", "left the fade", "short", "yours"
    why: str
    short_at_s: float = 0.0     # where a short cut would leave (0 = no good place found)
    peak: float = 0.0           # the loudest sample in the cut, before gain (0..1)
    fade_in_s: float = 0.0      # a short fade in, when a quiet intro was trimmed
    under_db: float = 0.0       # how far under the night's level it plays (a recording too quiet to raise)
    silent: bool = False        # nothing in it a room would hear: it is left out
    # where the dancing starts and stops (dance_points), measured for every dance song, whether or not
    # the cut follows it (a line dance and a song he set himself keep their own points)
    suggest_start_s: float = 0.0    # Llano's Starts at (seconds into the source)
    suggest_end_s: float = 0.0      # Llano's Ends at (seconds into the source)
    intro_s: float = 0.0            # how long the intro runs before the dancing starts
    outro_s: float = 0.0            # how long the tail runs after the dancing stops
    bar_s: float = 0.0              # one bar of the song (0 = its tempo was not found)
    mine: str = ""                  # "start", "end", "both": the points he set himself

    @property
    def plays_s(self) -> float:
        return LEAD_S + self.end_s - self.start_s

    def public(self) -> dict:
        d = asdict(self)
        d["plays_s"] = round(self.plays_s, 2)
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items()}


def mmss(s: float) -> str:
    s = max(0, int(round(s)))
    return f"{s // 60}:{s % 60:02d}"


def _body_level(env) -> float:
    """The song's own loud level: the 80th percentile of its level, so a quiet intro does not pull it down."""
    import numpy as np  # noqa: PLC0415

    loud = env[env > -60]
    return float(np.percentile(loud, 80)) if len(loud) else -120.0


def first_sound(x, rate: int) -> float:
    """Seconds to the first sample at or above -60 dBFS (what Mixxx calls the first sound)."""
    import numpy as np  # noqa: PLC0415

    step = 1 << 20                        # a piece at a time: it is nearly always in the first one
    for lo in range(0, len(x), step):
        hit = np.abs(x[lo:lo + step]).max(axis=1) >= 0.001
        if hit.any():
            return float(lo + int(np.argmax(hit))) / rate
    return 0.0


def natural_end(env, body: float, hop_s: float = HOP_S) -> tuple[float, float]:
    """(where the music has effectively ended, how long it took to die away).

    The end is the last moment within 30 dB of the song's own level. The die-away is how long before
    that the level last sat within 6 dB of it: about nothing for a hard stop, a few seconds for a
    ring-out, 10 to 30 seconds for a studio fade-out."""
    import numpy as np  # noqa: PLC0415

    alive = np.flatnonzero(env > body - 30)
    if not len(alive):
        return len(env) * hop_s, 0.0
    end = int(alive[-1]) + 1
    full = np.flatnonzero(env[:end] > body - 6)
    last_full = int(full[-1]) + 1 if len(full) else end
    return end * hop_s, (end - last_full) * hop_s


def _bands(x, rate: int, frame_s: float = 0.5):
    """Log energy in 12 bands per half second (mono), for finding where a song's sections change."""
    import numpy as np  # noqa: PLC0415

    n = int(rate * frame_s)
    frames = len(x) // n
    if frames < 8:
        return np.zeros((0, 12))
    freqs = np.fft.rfftfreq(n, 1 / rate)
    edges = np.geomspace(60, min(12000, rate / 2 - 1), 13)
    masks = [(freqs >= lo) & (freqs < hi) for lo, hi in zip(edges[:-1], edges[1:])]
    win = np.hanning(n)
    out = np.empty((frames, 12))
    for lo in range(0, frames, 64):               # half a minute at a time: the whole song's spectrum at once is three times its size
        hi = min(frames, lo + 64)
        mono = x[lo * n: hi * n].mean(axis=1).reshape(hi - lo, n)
        spec = np.abs(np.fft.rfft(mono * win, axis=1)) ** 2
        out[lo:hi] = np.stack([spec[:, m].sum(axis=1) for m in masks], axis=1)
    return np.log10(out + 1e-9)


def _novelty(b, k: int):
    """Per frame, how far the k frames after it differ from the k before (band by band, as one distance)."""
    import numpy as np  # noqa: PLC0415

    csum = np.vstack([np.zeros((1, b.shape[1])), np.cumsum(b, axis=0)])
    nov = np.zeros(len(b))
    for i in range(k, len(b) - k):
        before = (csum[i] - csum[i - k]) / k
        after = (csum[i + k] - csum[i]) / k
        nov[i] = float(np.linalg.norm(after - before))
    return nov


def section_changes(x, rate: int, frame_s: float = 0.5, span_s: float = 12.0,
                    min_contrast: float = 0.0) -> list[tuple[float, float]]:
    """[(seconds, strength 0..1)] where the song changes character (verse to chorus, chorus to
    bridge): the contrast between the `span_s` before and after each moment, peaks only.

    The strength is against the song's own clearest change, so a song with no real change still has
    one at 1.0. `min_contrast` also asks for a real one: the bands' own levels (log10 units, so 1.0
    is 10 dB) must differ by at least this much. A real intro ending measures 2.3 to 7 on his dance
    songs; verse to chorus inside a song, 1 to 2; a steady tone, nothing."""
    import numpy as np  # noqa: PLC0415

    raw = _bands(x, rate, frame_s)
    if len(raw) < 8:
        return []
    b = (raw - raw.mean(axis=0)) / (raw.std(axis=0) + 1e-9)
    k = max(2, int(span_s / frame_s))
    nov = _novelty(b, k)
    contrast = _novelty(raw, k) if min_contrast > 0 else None
    top = nov.max()
    if top <= 0:
        return []
    nov /= top
    out = []
    for i in range(k, len(b) - k):
        lo, hi = max(0, i - k // 2), min(len(b), i + k // 2 + 1)
        if nov[i] >= 0.3 and nov[i] == nov[lo:hi].max() and (contrast is None or contrast[i] >= min_contrast):
            out.append((i * frame_s, float(nov[i])))
    return out


def _snap_to_hit(x, rate: int, at_s: float, within_s: float = 0.4) -> float:
    """The strongest drum hit near at_s, so a cut leaves on a beat and not between two."""
    import numpy as np  # noqa: PLC0415

    lo, hi = int(max(0, at_s - within_s) * rate), int(min(len(x) / rate, at_s + within_s) * rate)
    win = int(0.01 * rate)
    seg = np.abs(x[lo:hi]).mean(axis=1)
    n = len(seg) // win
    if n < 4:
        return at_s
    e = seg[: n * win].reshape(n, win).mean(axis=1)
    rise = np.diff(e, prepend=e[0])
    return (lo + int(np.argmax(rise)) * win) / rate


def short_point(x, rate: int, start_s: float, end_s: float) -> float:
    """Where a short cut would leave: the strongest section change in the last part of the song, at
    least MIN_KEEP of the way in and at least 20 seconds before the end. 0 when there is no clear one
    (the song is then better whole)."""
    length = end_s - start_s
    if length < 150:
        return 0.0
    lo, hi = start_s + max(MIN_KEEP * length, 120.0), end_s - 20.0
    cands = [(t, s) for t, s in section_changes(x, rate) if lo <= t <= hi and s >= 0.45]
    if not cands:
        return 0.0
    # the earliest strong change: later ones are usually the same chorus coming round again
    t = min(cands, key=lambda c: (round(-c[1], 1), c[0]))[0]
    return round(_snap_to_hit(x, rate, t), 3)


def music_span(env, body: float, kind: str, hop_s: float = HOP_S) -> tuple[float, float]:
    """(seconds where the music arrives, seconds where it has gone). It has arrived at the first
    half second whose level is within ARRIVE_DB of the song's own loud level (half a second, so one
    stray drum tap in a soft intro is not "the band is in"); it has gone after the last moment
    within GONE_DB of it."""
    import numpy as np  # noqa: PLC0415

    k = max(1, int(round(0.5 / hop_s)))
    n = len(env) // k
    half = 10 * np.log10(np.maximum((10 ** (env[: n * k] / 10)).reshape(n, k).mean(axis=1), 1e-12)) if n else env
    up = np.flatnonzero(half > body - ARRIVE_DB[kind])
    there = np.flatnonzero(env > body - GONE_DB[kind])
    if not len(up) or not len(there):
        return 0.0, len(env) * hop_s
    return int(up[0]) * k * hop_s, (int(there[-1]) + 1) * hop_s


def beat_seconds(x, rate: int) -> float:
    """One beat of the song in seconds, from how its onsets repeat (spectral flux, autocorrelated,
    leaning toward 115 BPM so a song is not read at half or double its tempo). 0.0 when the song is
    too short to tell. Good enough to nudge a point by a bar; never used to place a cut on its own."""
    import numpy as np  # noqa: PLC0415

    n, hop = 1024, 512
    frames = (len(x) - n) // hop
    if frames < 64:
        return 0.0
    win = np.hanning(n).astype(np.float32)
    flux = np.zeros(frames, dtype=np.float32)
    prev = None
    for lo in range(0, frames, 1024):        # a piece at a time: the whole song's spectrum is several times its size
        hi = min(frames, lo + 1024)
        mono = x[lo * hop: (hi - 1) * hop + n].mean(axis=1)
        idx = (np.arange(hi - lo) * hop)[:, None] + np.arange(n)[None, :]
        lg = np.log1p(100 * np.abs(np.fft.rfft(mono[idx] * win, axis=1)))
        d = np.diff(np.vstack([lg[:1] if prev is None else prev, lg]), axis=0)
        prev = lg[-1:]
        flux[lo:hi] = np.maximum(d, 0).sum(axis=1)
    f = flux - flux.mean()
    m = 1 << int(np.ceil(np.log2(2 * len(f))))
    spec = np.fft.rfft(f, m)
    ac = np.fft.irfft(spec * np.conj(spec))[:len(f)]
    dt = hop / rate
    lags = np.arange(max(1, int(60 / 190 / dt)), int(60 / 65 / dt) + 1)
    lags = lags[lags < len(ac)]
    if not len(lags):
        return 0.0
    bpm = 60 / (lags * dt)
    k = int(lags[int(np.argmax(ac[lags] * np.exp(-0.5 * (np.log2(bpm / 115) / 0.6) ** 2)))])
    return round(k * dt, 4) if ac[k] > 0 else 0.0


@dataclass
class Points:
    """Where a dance song's dancing starts and stops (seconds into the source). `starts_s` is the first
    sound when it has no intro worth cutting; `ends_s` is where the music has gone when it has no tail
    worth cutting."""
    first_s: float
    starts_s: float
    ends_s: float
    gone_s: float
    intro_s: float      # starts_s - where the music arrived (the quiet lead-in is not counted)
    outro_s: float      # gone_s - where the dancing stopped (also when it is too short to cut)
    bar_s: float

    def public(self) -> dict:
        return {k: round(v, 3) for k, v in asdict(self).items()}


def dance_points(x, rate: int, env=None, body: Optional[float] = None) -> Points:
    """Where the dancing starts and where it stops, as a DJ hears it.

    Starts: the end of the song's opening section. A DJ mixes in past the intro, and an intro is not
    always quiet (I Gotta Feeling's first 30 seconds are as loud as its verse; what ends there is the
    opening loop, the clearest change in the whole song). So it is the first section change between
    INTRO_MIN_S and INTRO_MAX_S after the music arrives that is at least INTRO_STRENGTH as clear as the
    song's clearest change, on the drum hit at it. A song with no such change starts at its first sound.

    Stops: the end of the last stretch with dancing energy (the song near its own loud level, with its
    bass): what comes after (a fade-out, an outro, a spoken or ambient tail) is the tail."""
    import numpy as np  # noqa: PLC0415

    env = envelope(x, rate) if env is None else env
    body = _body_level(env) if body is None else body
    first = max(0.0, first_sound(x, rate) - 0.02)
    arrive, gone = music_span(env, body, "dancing")
    a = max(first, arrive)
    starts = first
    lo = int(a * rate)
    if len(x) - lo > int(30 * rate):
        for t, strength in section_changes(x[lo:], rate, 0.5, 12.0, INTRO_CONTRAST):
            if t > INTRO_MAX_S:
                break
            if t >= INTRO_MIN_S and strength >= INTRO_STRENGTH:
                starts = round(_snap_to_hit(x, rate, a + t, 0.6), 3)
                break
    # the tail: half-second frames with dancing energy, smoothed over 4 seconds
    # half-second levels from the tenth-second ones (power averaged): a second envelope of the audio
    # would take the whole song at once in its working copy
    k5 = int(round(0.5 / HOP_S))
    n5 = len(env) // k5
    half = 10 * np.log10(np.maximum((10 ** (env[: n5 * k5] / 10)).reshape(n5, k5).mean(axis=1), 1e-12))
    bands = _bands(x, rate, 0.5)
    ends = gone
    if len(bands) >= 8:
        low = bands[:, :2].max(axis=1) * 10            # the two lowest bands (kick and bass), in dB
        n = min(len(half), len(low))
        groove = (half[:n] > body - GROOVE_DB) & (low[:n] > np.percentile(low[:n], 80) - GROOVE_LOW_DB)
        k = 8                                          # 4 seconds: the dancing is three quarters of them
        csum = np.concatenate([[0.0], np.cumsum(groove)])
        on = np.flatnonzero((csum[k:] - csum[:-k]) / k >= 0.75)
        if len(on):
            m = int(on[-1])
            last = m + int(np.flatnonzero(groove[m:m + k])[-1])     # its last frame with the dancing in it
            ends = min(gone, (last + 1) * 0.5)
            if gone - ends >= OUTRO_MIN_S:
                ends = round(_snap_to_hit(x, rate, ends, 0.6), 3)
    return Points(round(first, 3), round(starts, 3), round(ends, 3), round(gone, 3),
                  round(max(0.0, starts - a), 3), round(max(0.0, gone - ends), 3), beat_seconds(x, rate) * 4)


def plan(x, rate: int, part: str = "dancing", leave_at_s: float = 0.0, short: bool = False,
         whole: bool = False, start_at_s: Optional[float] = None, end_at_s: Optional[float] = None,
         keep_intro: bool = False) -> Cut:
    """The cut for one song. `leave_at_s` is his own leave point (seconds into the source), `short`
    takes the suggested one, `whole` keeps the song's music whole (a line dance with calls to the
    end, a first dance): its quiet intro stays and it never leaves early; only the ring-out after
    the last note is not played out.

    A dance song also starts where the dancing starts and leaves where it stops (dance_points), unless it
    is kept whole (a line dance: the points are measured and suggested, not used). `start_at_s` and
    `end_at_s` are his own Starts at and Ends at (seconds into the source; None = Llano's): his win over
    everything else, for any part of the night. Ends at a point past the music plays it to its end.

    `keep_intro` is a set's opening song (Llano PM #23864: "it is the first song, so it needs to start at
    the beginning"): no intro is cut, quiet or loud, so it plays from its first sound; where the dancing
    starts is still measured and offered as the suggestion, and its ending is cut as any other's."""
    import numpy as np  # noqa: PLC0415

    env = envelope(x, rate)
    body = _body_level(env)
    source_s = len(x) / rate
    soft = part in ("cocktail", "dinner")
    kind_db = "soft" if soft else "dancing"
    first = max(0.0, first_sound(x, rate) - 0.02)
    end, die = natural_end(env, body)
    end = min(end, source_s)
    arrive, gone = music_span(env, body, kind_db)
    pts = dance_points(x, rate, env, body) if not soft else None
    follow = not whole and pts is not None
    start, fade_in = first, 0.0
    if not whole and not keep_intro and arrive - PRE_S[kind_db] > first + 0.3:
        start, fade_in = arrive - PRE_S[kind_db], min(0.3, PRE_S[kind_db])     # the quiet intro is trimmed
    intro_cut = follow and not keep_intro and pts.starts_s - START_FADE_S > start + 0.3
    if intro_cut:
        start, fade_in = pts.starts_s - START_FADE_S, START_FADE_S       # the downbeat lands at full
    fade = SOFT_TAIL_S if soft else TAIL_S
    kind, why = "whole", "The whole song"
    suggest = 0.0 if whole else short_point(x, rate, start, end)
    end = min(end, gone + POST_S[kind_db])           # the ring-out past the music is not played out
    if follow and pts.outro_s >= OUTRO_MIN_S and pts.ends_s + END_FADE_S < end:
        end, fade = pts.ends_s + END_FADE_S, END_FADE_S
        kind, why = "left the outro", f"Leaves at {mmss(end)}, where the dancing stops, {mmss(source_s - end)} before its end"
    elif die >= 8.0 and not whole:
        # a studio fade-out: leave once it is clearly going, not 20 seconds later at a whisper
        full = np.flatnonzero(env[: int(end / HOP_S)] > body - 6)
        last_full = (int(full[-1]) + 1) * HOP_S if len(full) else end
        leave = min(end, last_full + (6.0 if soft else 3.0))
        if end - leave > 2.0 or kind_db == "dancing":
            fade = max(fade, 3.0)
            end = min(end, leave)
            kind, why = "left the fade", f"Leaves as the song starts fading out, {mmss(source_s - end)} before its end"
    if start - first > 1.0:
        lead = (f"starts {mmss(start + fade_in)} in, where the dancing starts" if intro_cut
                else f"starts {mmss(start)} in, where the music arrives")
        why = lead[0].upper() + lead[1:] if kind == "whole" else f"{why}; {lead}"
        if kind == "whole":
            kind = "trimmed"
    # Llano's Starts at and Ends at, as Review shows them: where the music is at full volume, and where
    # it has gone. For a dance song it is the dancing's own (a line dance's too, where it is not used).
    s_start, s_end = start + fade_in, end
    if pts is not None:
        if pts.starts_s - START_FADE_S > start + 0.3:
            s_start = pts.starts_s
        if pts.outro_s >= OUTRO_MIN_S and pts.ends_s + END_FADE_S < end:
            s_end = pts.ends_s + END_FADE_S
    mine = []
    if start_at_s is not None and 0.0 <= start_at_s < end - 10:
        mine.append("start")
        if start_at_s <= first + 0.3:            # from the top: every note of it
            start, fade_in = first, 0.0
        else:                                    # his point lands at full volume, faded in just before it
            start, fade_in = max(first, start_at_s - START_FADE_S), min(START_FADE_S, start_at_s - first)
        why = f"Starts at {mmss(start + fade_in)}, where you set it" if start - first > 1.0 else "Starts at its first note, as you set it"
        kind = "yours"
    if end_at_s is not None and end_at_s > start + 10:
        mine.append("end")
        full = min(source_s, natural_end(env, body)[0], gone + POST_S[kind_db])
        if end_at_s >= full:                     # to the end: the whole song, only the silence after it left off
            end, fade = full, SOFT_TAIL_S if soft else TAIL_S
            said = "plays to its end, as you set it"
        else:
            end, fade = end_at_s, END_FADE_S
            said = f"ends at {mmss(end)}, where you set it"
        why = f"{why}; {said}" if "start" in mine else said[0].upper() + said[1:]
        kind = "yours"
    elif leave_at_s and start + 30 <= leave_at_s < end:
        end, kind = _snap_to_hit(x, rate, leave_at_s), "yours"
        why = f"Leaves at {mmss(end)}, where you set it"
    elif short and suggest and suggest < end - 5:
        end, kind = suggest, "short"
        why = f"Short cut: leaves at {mmss(end)}, at a section change, {mmss(source_s - end)} early"
    lufs = loudness(x[int(start * rate): int(end * rate)], rate)
    gain = 0.0 if lufs <= -69 else TARGET_LUFS - lufs
    peak = robust_peak(x[int(start * rate): int(end * rate)])
    if peak > 0 and peak * 10 ** (gain / 20) > PEAK_CEILING:
        gain = 20 * math.log10(PEAK_CEILING / peak)     # never clip to reach the target
    silent = peak < 0.001 or body < SILENT_DBFS         # nothing Mixxx or a room would call sound
    return Cut(round(start, 3), round(end, 3), round(min(fade, max(0.2, end - start - 1)), 3), round(gain, 2),
               round(lufs, 2), round(source_s, 2), kind, why, round(suggest, 3), round(peak, 5), round(fade_in, 3),
               silent=bool(silent), suggest_start_s=round(s_start, 3), suggest_end_s=round(s_end, 3),
               intro_s=pts.intro_s if pts else 0.0, outro_s=pts.outro_s if pts else 0.0,
               bar_s=pts.bar_s if pts else 0.0, mine="both" if len(mine) == 2 else "".join(mine))


def robust_peak(x) -> float:
    """The loudest sample that is music: the true peak, but never more than PEAK_OUTLIER over the
    99.99th percentile, so one bad sample (a glitch, a single click) does not decide a song's level.
    Whatever stands above it is clipped at the ceiling when the cut is rendered."""
    import numpy as np  # noqa: PLC0415

    if not len(x):
        return 0.0
    mag = np.empty(len(x), dtype=np.float32)
    step = 1 << 20
    for lo in range(0, len(x), step):
        mag[lo:lo + step] = np.abs(x[lo:lo + step]).max(axis=1)
    top = float(mag.max())
    if len(mag) < 20000:                  # too short for a percentile to mean anything
        return top
    k = len(mag) - max(1, len(mag) // 10000)
    mag.partition(k)                      # in place: no second copy of the song's samples
    return min(top, float(mag[k]) * PEAK_OUTLIER)


def set_level(cuts: list) -> float:
    """One loudness for a whole set, and every cut's gain set to reach it.

    An old recording has quiet verses and tall drum hits, so it cannot be turned up to a modern
    song's loudness without clipping. Rather than leave it quieter than its neighbours, the set's
    level is the loudest one EVERY song can reach cleanly (never above TARGET_LUFS). Returns it.

    It never goes under FLOOR_LUFS: a recording too quiet to reach the floor is turned up as far as
    it goes and plays that much under the others (its `under_db`), instead of pulling the whole
    night down with it."""
    real = [c for c in cuts if c.lufs > -69 and c.peak > 0 and not c.silent]
    if not real:
        return TARGET_LUFS
    reach = [c.lufs + 20 * math.log10(PEAK_CEILING / c.peak) for c in real]
    level = round(max(FLOOR_LUFS, min(TARGET_LUFS, min(reach))), 2)
    for c, r in zip(real, reach):
        got = min(level, r)
        c.gain_db = round(got - c.lufs, 2)
        c.under_db = round(level - got, 1) if level - got >= 0.05 else 0.0
    return level


# --- rendering ------------------------------------------------------------------------------------

def _lead(n: int, rate: int = 44100):
    """n frames of a steady offset at LEAD_DBFS. Mixxx's test for "sound" is each sample's size
    (0.001 and up), so a constant counts; a speaker cannot play a constant, so the room hears nothing
    (the first cut of this used noise, which is a second of hiss before a first dance). It eases in
    and out over LEAD_EDGE_S so there is no click at either end."""
    import numpy as np  # noqa: PLC0415

    amp = 10 ** (LEAD_DBFS / 20)                     # 0.00126
    y = np.full((n, 2), amp, dtype=np.float32)
    k = min(n // 2, max(1, int(LEAD_EDGE_S * rate)))
    if k > 1:
        ramp = (0.5 * (1 - np.cos(np.linspace(0, np.pi, k)))).astype(np.float32)[:, None]
        y[:k] *= ramp
        y[-k:] *= ramp[::-1]
    return y


def render(x, rate: int, cut: Cut):
    """The cut as audio: the lead, then the song from start_s to end_s at its gain, the last fade_s
    faded out along a raised cosine."""
    import numpy as np  # noqa: PLC0415

    a, b = int(cut.start_s * rate), min(len(x), int(cut.end_s * rate))
    body = x[a:b].astype(np.float32) * np.float32(10 ** (cut.gain_db / 20))
    n = min(len(body), int(cut.fade_s * rate))
    if n > 1:
        ramp = (0.5 * (1 + np.cos(np.linspace(0, np.pi, n)))).astype(np.float32)
        body[-n:] *= ramp[:, None]
    k = min(len(body), int(cut.fade_in_s * rate))
    if k > 1:
        body[:k] *= (0.5 * (1 - np.cos(np.linspace(0, np.pi, k)))).astype(np.float32)[:, None]
    top = PEAK_CEILING if cut.gain_db > 0 else 1.0   # a turned-up song never passes the ceiling
    np.clip(body, -top, top, out=body)
    return np.concatenate([_lead(int(LEAD_S * rate), rate), body])


def source_zero_s(cut: Cut) -> float:
    """Where the original's 0:00 sits in the cut file, in the cut's seconds (render: the lead, then the
    song from start_s): negative when the cut skips an intro."""
    return round(LEAD_S - cut.start_s, 3)


def write(path, y, rate: int, artist: str = "", title: str = "", album: str = "",
          zero_s: Optional[float] = None) -> Path:
    """Write a cut as FLAC (16-bit) with its artist and title, so Mixxx and the lights name it the
    same as the original. `zero_s` (source_zero_s) goes in its comment, so the lights count the
    cut's phrases from where its original's are (show_script.phrase_phase, Llano PM #23787)."""
    from .show_script import CUT_TAG  # noqa: PLC0415
    import soundfile  # noqa: PLC0415

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    with soundfile.SoundFile(str(tmp), "w", samplerate=rate, channels=2, format="FLAC", subtype="PCM_16") as f:
        if title:
            f.title = title
        if artist:
            f.artist = artist
        if album:
            f.album = album
        if zero_s is not None:
            f.comment = f"{CUT_TAG}{zero_s:.3f} s"
        f.write(y)
    _into_place(tmp, path)
    return path


def _into_place(tmp: Path, path: Path) -> None:
    """Rename a finished temp file over its target. When that is refused (on Windows: Mixxx has the
    old file open) the temp file is removed and the old file is left as it was."""
    try:
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def hold_seconds(n: int) -> int:
    """Hold number n's length. Each hold is a different whole number of seconds, because the lights
    tell Mixxx tracks apart by their length."""
    return HOLD_S + 7 * max(0, int(n))


def hold(path, n: int, title: str, rate: int = 22050) -> Path:
    """An hour of silence named for a live moment. Written a few seconds at a time (an hour held in
    memory at once is over a gigabyte), at half the usual sample rate: silence needs no more, and
    Mixxx plays any rate."""
    import numpy as np  # noqa: PLC0415
    import soundfile  # noqa: PLC0415

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    block = np.zeros((rate * 30, 2), dtype=np.int16)
    left = hold_seconds(n) * rate
    with soundfile.SoundFile(str(tmp), "w", samplerate=rate, channels=2, format="FLAC", subtype="PCM_16") as f:
        f.title, f.artist, f.album = title, "Llano hold", "Holds"
        while left > 0:
            k = min(left, len(block))
            f.write(block[:k])
            left -= k
    _into_place(tmp, path)
    return path


# --- what Mixxx does with two cuts (for the tests, the handoff preview and the one-file backup) -----

def xfade_gains(pos: float, curve: str = "additive") -> tuple[float, float]:
    """(left gain, right gain) for a crossfader at pos -1..1, as Mixxx's EngineXfader::getXfadeGains
    with its stock settings: "additive" (slow fade, transform 1) or "cut" (fast cut, transform 1000)."""
    t = 1.0 if curve == "additive" else 1000.0
    right = 1.0 - (-pos) ** t if pos < 0 else 1.0
    left = 1.0 - pos ** t if pos > 0 else 1.0
    return max(0.0, left), max(0.0, right)


def resample(x, rate: int, to: int):
    """x at another sample rate (straight-line interpolation: plenty for a preview or a phone backup,
    never used for the cuts themselves)."""
    import numpy as np  # noqa: PLC0415

    if rate == to or not len(x):
        return x
    n = int(round(len(x) * to / rate))
    at = np.linspace(0, len(x) - 1, n)
    return np.stack([np.interp(at, np.arange(len(x)), x[:, c]) for c in range(x.shape[1])], axis=1).astype(np.float32)


def _fade_gains(n: int, curve: str):
    """(gain of the song coming in, gain of the song going out) across a transition of n frames."""
    import numpy as np  # noqa: PLC0415

    pos = np.linspace(-1.0, 1.0, n, dtype=np.float64)
    t = 1.0 if curve == "additive" else 1000.0
    g_in = np.where(pos < 0, 1.0 - np.abs(pos) ** t, 1.0).astype(np.float32)[:, None]
    g_out = np.where(pos > 0, 1.0 - np.abs(pos) ** t, 1.0).astype(np.float32)[:, None]
    return g_in, g_out


def handoff(a, b, rate: int, transition_s: float = TRANSITION_S, curve: str = "additive",
            before_s: float = 8.0, after_s: float = 8.0):
    """The handoff from cut `a` to cut `b` as Auto DJ plays it in Full Track mode: b starts
    transition_s before a's end, the crossfader moves in a straight line across it. Returns
    (mixed audio from before_s ahead of the fade to after_s past it, seconds into that where b's
    first note lands). A cut shorter than the transition overlaps for as long as it lasts."""
    import numpy as np  # noqa: PLC0415

    n = min(int(transition_s * rate), len(a), len(b))
    pre, post = min(int(before_s * rate), max(0, len(a) - n)), min(int(after_s * rate), max(0, len(b) - n))
    out = np.zeros((pre + n + post, 2), dtype=np.float32)
    out[:pre] = a[len(a) - n - pre: len(a) - n]
    if n:
        g_b, g_a = _fade_gains(n, curve)
        out[pre:pre + n] = a[len(a) - n:] * g_a + b[:n] * g_b
    out[pre + n:] = b[n:n + post]
    np.clip(out, -1.0, 1.0, out=out)
    return out, (pre + min(int(LEAD_S * rate), len(b))) / rate


def mixdown_pieces(loaders: list, rate: int, transition_s: float = TRANSITION_S, curve: str = "additive"):
    """Every cut in order as one continuous piece, joined exactly as Auto DJ joins them, handed out a
    piece at a time. `loaders` are functions that each return one cut's audio; a cut is loaded only
    when its turn comes and dropped before the next, so a two-hour set never sits in memory at once.
    A cut shorter than the transition is not crossfaded: it plays whole between its neighbours."""
    import numpy as np  # noqa: PLC0415

    n = int(transition_s * rate)
    g_in, g_out = _fade_gains(n, curve) if n else (None, None)
    carry = None                                  # the faded-out end of the song before, still to be played
    for k, load in enumerate(loaders):
        c = np.array(load(), dtype=np.float32)    # a copy: the gains below must not touch the caller's audio
        fades = n > 0 and len(c) >= n
        if fades and k:
            c[:n] *= g_in
        if fades and k + 1 < len(loaders):
            c[-n:] *= g_out
        if carry is not None:
            if fades:
                c[:n] += carry
            else:
                yield np.clip(carry, -1.0, 1.0)
            carry = None
        if fades and k + 1 < len(loaders):
            carry, c = c[len(c) - n:].copy(), c[:len(c) - n]
        if len(c):
            yield np.clip(c, -1.0, 1.0)
    if carry is not None:
        yield np.clip(carry, -1.0, 1.0)


def mixdown(cuts: list, rate: int, transition_s: float = TRANSITION_S, curve: str = "additive"):
    """Every cut in order as one array (see mixdown_pieces): for the tests and short sets."""
    import numpy as np  # noqa: PLC0415

    pieces = list(mixdown_pieces([(lambda c=c: c) for c in cuts], rate, transition_s, curve))
    return np.concatenate(pieces) if pieces else np.zeros((0, 2), dtype=np.float32)
