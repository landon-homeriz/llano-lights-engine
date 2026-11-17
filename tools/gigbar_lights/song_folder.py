"""Songs from a folder on this laptop, for the Shows page (set arranger, Llano PM #23177).

His wedding playlists live as folders ("1 - Cocktail Hour", "2 - Dinner", "3 - Dancing"), each file
named "Artist - Title.mp3", synced from Drive. This reads such a folder: every audio file one level
or two down, its part of the night from the folder it sits in, its artist and title from the file
name (or its tags), and its tempo, key and year from its ID3 tags when it has them (TBPM, TKEY,
TDRC/TYER). It never decodes audio and never writes to the files.

Each song's length comes from its file (Llano BL #11473): his 70 wedding songs all had length 0, because
lengths only ever came from Mixxx's library and his songs were not in Mixxx yet, so the night showed
"0 minutes" runs. audio_length reads it from the file's own header (an MP3's frame header, a WAV, a
FLAC's stream info, an M4A's movie header), else from soundfile (which the Windows app ships), else
from the MP3's TLEN tag. A file it cannot open, or whose length it cannot read, is said so.

A folder named Moments ("4 - Moments") holds the songs for the night's dances. Each is given its
moment from what the song is known for (Cinderella is a father-daughter dance), so it plays at that
moment and stays out of the dance floor's songs; one nobody knows is left for him to place.

Two more folders follow his reception order (Llano BL #12360): a Background folder ("5 - Toasts and
Cake Background") holds the quiet songs under the toasts and the cake cutting (moment "background"),
and a Grand Exit folder ("6 - Grand Exit") the couple's exit song and the sing-along before it
(moments "exit" and "exit-prep"; one song alone is the exit song).

The toasts and the cake each have their own quiet music (his toasts playlist, 2026-11-14): a
Background folder that names the toasts or speeches and not the cake ("5 - Toasts Background") holds
the songs under the toasts, in its numbered order (moment "toasts-background"); any other Background
folder ("5 - Cake Background") plays under the cake (moment "background"), and under the toasts too
while there is no toasts folder. An Instrumentals folder that names no part ("Wedding Instrumentals")
is a library he picks those songs from: it is skipped, never played as it is.
"""
from __future__ import annotations

import re
import struct
import wave
from pathlib import Path
from . import settings_contract as contract
from .shows import part_from_name

AUDIO = {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".aiff", ".aif"}
_WANT = {"TBPM": "bpm", "TKEY": "key", "TDRC": "year", "TYER": "year", "TPE1": "artist", "TIT2": "title",
         "TLEN": "tlen"}
LONGEST_S = 3600.0      # settings_contract keeps a song's length up to an hour


def _syncsafe(b: bytes) -> int:
    return (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]


def _text(frame: bytes) -> str:
    if not frame:
        return ""
    enc, body = frame[0], frame[1:]
    codec = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}.get(enc, "latin-1")
    try:
        txt = body.decode(codec, "replace")
    except LookupError:
        return ""
    return txt.replace("\x00", " ").strip()


def id3_tags(path: Path) -> dict:
    """{bpm, key, year, artist, title} from an MP3's ID3v2.3/2.4 tag; {} when there is none."""
    try:
        with open(path, "rb") as f:
            head = f.read(10)
            if len(head) < 10 or head[:3] != b"ID3" or head[3] not in (3, 4):
                return {}
            size = _syncsafe(head[6:10])
            data = f.read(min(size, 512 * 1024))
    except OSError:
        return {}
    ver, out, i = head[3], {}, 0
    if head[5] & 0x40 and len(data) >= 4:   # extended header
        ext = _syncsafe(data[:4]) if ver == 4 else struct.unpack(">I", data[:4])[0] + 4
        i = ext
    while i + 10 <= len(data):
        fid = data[i:i + 4]
        if not re.fullmatch(rb"[A-Z0-9]{4}", fid):
            break
        n = _syncsafe(data[i + 4:i + 8]) if ver == 4 else struct.unpack(">I", data[i + 4:i + 8])[0]
        body = data[i + 10:i + 10 + n]
        name = _WANT.get(fid.decode())
        if name and name not in out:
            out[name] = _text(body)
        i += 10 + n
    clean: dict = {}
    try:
        bpm = float(re.match(r"\s*(\d+(?:\.\d+)?)", out.get("bpm", "")).group(1))
        if 40 <= bpm <= 250:
            clean["bpm"] = bpm
    except (AttributeError, ValueError):
        pass
    if out.get("key"):
        clean["key"] = out["key"][:8]
    m = re.match(r"\s*(\d{4})", out.get("year", ""))
    if m:
        clean["year"] = int(m.group(1))
    for k in ("artist", "title"):
        if out.get(k):
            clean[k] = out[k][:120]
    try:
        ms = float(re.match(r"\s*(\d+)", out.get("tlen", "")).group(1))
        if 1000 <= ms <= LONGEST_S * 1000:
            clean["secs"] = ms / 1000
    except (AttributeError, ValueError):
        pass
    return clean


# --- a song's length, from its file -----------------------------------------------------------------

_MP3_KBPS = {  # (MPEG-1?, layer) -> bitrate table, index 1..14
    (True, 1): (32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448),
    (True, 2): (32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384),
    (True, 3): (32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    (False, 1): (32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256),
    (False, 2): (8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
}
_MP3_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


def _mp3_frame(buf: bytes, i: int) -> "tuple | None":
    """(frame length in bytes, samples per frame, sample rate, side-info bytes, kbps) for an MPEG audio
    frame header at buf[i], or None when those four bytes are not one."""
    if i + 4 > len(buf) or buf[i] != 0xFF or buf[i + 1] & 0xE0 != 0xE0:
        return None
    b1, b2, b3 = buf[i + 1], buf[i + 2], buf[i + 3]
    ver, layer_bits, br_i, sr_i, pad = (b1 >> 3) & 3, (b1 >> 1) & 3, b2 >> 4, (b2 >> 2) & 3, (b2 >> 1) & 1
    if ver == 1 or layer_bits == 0 or br_i in (0, 15) or sr_i == 3:
        return None
    layer, mpeg1 = 4 - layer_bits, ver == 3
    kbps = (_MP3_KBPS[(mpeg1, layer)] if (mpeg1 or layer == 1) else _MP3_KBPS[(False, 2)])[br_i - 1]
    rate = _MP3_RATES[ver][sr_i]
    per_frame = 384 if layer == 1 else 1152 if (layer == 2 or mpeg1) else 576
    length = (12 * kbps * 1000 // rate + pad) * 4 if layer == 1 else per_frame // 8 * kbps * 1000 // rate + pad
    mono = (b3 >> 6) == 3
    side = (17 if mono else 32) if mpeg1 else (9 if mono else 17)
    return length, per_frame, rate, side, kbps


def _mp3_secs(path: Path) -> "tuple[float, bool]":
    """(seconds, exact) for an MP3 from its first frame. Exact: the Xing/Info or VBRI frame count the
    encoder wrote (every VBR file has one). Else the file size over the first frame's bitrate, which is
    right only for a constant-bitrate file, so audio_length asks soundfile first. A sync is trusted
    only when a second frame header sits where the first frame's length says (cover-art bytes can look
    like a header). (0.0, False) when no frame is found."""
    size = path.stat().st_size
    with open(path, "rb") as f:
        head = f.read(10)
        start = 0
        if len(head) == 10 and head[:3] == b"ID3":
            start = 10 + _syncsafe(head[6:10]) + (10 if head[5] & 0x10 else 0)   # 0x10: a footer follows the tag
        f.seek(start)
        buf = f.read(64 * 1024)
        f.seek(max(0, size - 128))
        tail = f.read(3)
    for i in range(max(0, len(buf) - 4)):
        fr = _mp3_frame(buf, i)
        if fr is None:
            continue
        length, per_frame, rate, side, kbps = fr
        nxt = i + length
        if nxt + 4 <= len(buf) and _mp3_frame(buf, nxt) is None:
            continue                       # no second frame where this one ends: a false sync
        if nxt + 4 > len(buf) and start + i + length < size - 4:
            continue                       # can't check the next frame inside what was read: keep looking
        frame = buf[i:i + 200]
        frames, x = 0, 4 + side
        if frame[x:x + 4] in (b"Xing", b"Info") and len(frame) >= x + 12 and frame[x + 7] & 1:
            frames = struct.unpack(">I", frame[x + 8:x + 12])[0]
        elif frame[36:40] == b"VBRI" and len(frame) >= 36 + 18:
            frames = struct.unpack(">I", frame[36 + 14:36 + 18])[0]
        if frames:
            return frames * per_frame / rate, True
        audio = size - start - i - (128 if tail == b"TAG" else 0)
        return max(0.0, audio * 8 / (kbps * 1000)), False
    return 0.0, False


def _flac_secs(path: Path) -> float:
    with open(path, "rb") as f:
        head = f.read(4 + 4 + 34)
    if len(head) < 42 or head[:4] != b"fLaC" or head[4] & 0x7F != 0:
        return 0.0
    info = head[8:]
    rate = (info[10] << 12) | (info[11] << 4) | (info[12] >> 4)
    total = ((info[13] & 0x0F) << 32) | struct.unpack(">I", info[14:18])[0]
    return total / rate if rate and total else 0.0


def _m4a_secs(path: Path) -> float:
    """An MP4/M4A's length from moov/mvhd (its timescale and duration), walking the boxes."""
    with open(path, "rb") as f:
        def boxes(end: int):
            while f.tell() + 8 <= end:
                at = f.tell()
                n, kind = struct.unpack(">I4s", f.read(8))
                if n == 1:
                    n = struct.unpack(">Q", f.read(8))[0]
                elif n == 0:
                    n = end - at
                if n < 8:
                    return
                yield kind, at, at + n
                f.seek(at + n)
        end = path.stat().st_size
        for kind, at, stop in boxes(end):
            if kind != b"moov":
                continue
            f.seek(at + 8)
            for k2, at2, _stop2 in boxes(stop):
                if k2 == b"mvhd":
                    f.seek(at2 + 8)
                    ver = f.read(4)[0]
                    if ver == 1:
                        f.read(16)
                        scale, dur = struct.unpack(">IQ", f.read(12))
                    else:
                        f.read(8)
                        scale, dur = struct.unpack(">II", f.read(8))
                    return dur / scale if scale else 0.0
    return 0.0


def _wav_secs(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / w.getframerate() if w.getframerate() else 0.0
    except (wave.Error, EOFError):
        return 0.0


def _soundfile_secs(path: Path) -> float:
    try:
        import soundfile  # noqa: PLC0415 -- the Windows app ships it; a test machine may not
    except (ImportError, OSError):
        return 0.0
    try:
        return float(soundfile.info(str(path)).duration or 0.0)
    except Exception:  # noqa: BLE001 -- ok: a file soundfile cannot read falls back to its tags
        return 0.0


_READERS = {".flac": _flac_secs, ".m4a": _m4a_secs, ".aac": _m4a_secs, ".wav": _wav_secs}


def audio_length(path, tags: "dict | None" = None) -> tuple[float, str]:
    """(seconds, problem) for an audio file. problem is "" when its length was read; "unreadable" when
    the file cannot be opened (or is empty); "too-long" when it is longer than a show can hold (an hour);
    "no-length" when it opens and no length can be read (a raw .aac, an .ogg with no soundfile here).
    `tags` is its id3_tags when the caller has them (an MP3's TLEN is the last resort)."""
    p = Path(path)
    try:
        if not p.is_file() or p.stat().st_size == 0:
            return 0.0, "unreadable"
        with open(p, "rb") as f:
            f.read(1)
    except OSError:
        return 0.0, "unreadable"
    ext = p.suffix.lower()
    secs = 0.0
    try:
        if ext == ".mp3":
            est, exact = _mp3_secs(p)
            # no frame count in the file: soundfile reads the real length; the size estimate is only
            # right for a constant bitrate, so it is used when soundfile is not here or fails
            secs = est if exact else (_soundfile_secs(p) or est)
        elif ext in _READERS:
            secs = _READERS[ext](p)
    except (OSError, struct.error, IndexError, ValueError):
        secs = 0.0
    if secs < 1.0:
        secs = _soundfile_secs(p)
    if secs < 1.0:
        secs = float((tags if tags is not None else (id3_tags(p) if ext == ".mp3" else {})).get("secs") or 0)
    if secs > LONGEST_S:
        return 0.0, "too-long"
    if secs < 1.0:
        return 0.0, "no-length"
    return round(secs, 2), ""


def _name(path: Path) -> tuple[str, str]:
    stem = re.sub(r"^\s*\d{1,3}\s*[-.)]\s*", "", path.stem)   # "07 - Artist - Title" or "07. Title"
    for sep in (" - ", " – ", " — "):
        if sep in stem:
            a, t = stem.split(sep, 1)
            return a.strip(), t.strip()
    return "", stem.strip()


def read_folder(folder: str) -> tuple[str, list[dict]]:
    """(folder name, songs) for a folder of audio files, at most contract.MAX_SHOW_SONGS. Parts come
    from the subfolder names (or the folder's own name); a numbered prefix sets the order of parts.
    A song from a Moments folder that no moment is known for keeps the mark "?" as its moment: the
    caller keeps it out of the night's parts and asks him where it goes."""
    name, songs, _left = read_folder_all(folder)
    return name, songs


def read_folder_all(folder: str) -> tuple[str, list[dict], int]:
    """read_folder, and how many songs did not fit in a show (0 when all did). When a folder holds
    more than a show can, the Moments folder's songs are kept first: the dances are the last thing
    that may go missing."""
    root = Path(str(folder or "").strip().strip('"')).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"no folder at {root}")
    files = []
    for p in sorted(root.rglob("*"), key=lambda x: [s.lower() for s in x.relative_to(root).parts]):
        if p.suffix.lower() in AUDIO and p.is_file() and len(p.relative_to(root).parts) <= 3:
            files.append(p)
    songs = []
    for p in files:
        rel = p.relative_to(root)
        part = next((part_from_name(x) for x in reversed(rel.parts[:-1]) if part_from_name(x)), "") \
            or part_from_name(root.name)
        artist, title = _name(p)
        tags = id3_tags(p) if p.suffix.lower() == ".mp3" else {}
        if not title:
            continue
        dirs = [x.lower() for x in rel.parts[:-1]]
        if any(_LIBRARY_DIR.search(x) and not part_from_name(x) for x in dirs):   # "Dinner Instrumentals" stays dinner
            continue
        if any(_BACKGROUND_DIR.search(x) and _TOASTS_DIR.search(x) and not _CAKE_DIR.search(x) for x in dirs):
            part, special = "dinner", "toasts-background"
        elif any(_BACKGROUND_DIR.search(x) for x in dirs):
            part, special = "dinner", "background"
        elif any(_EXIT_DIR.search(x) for x in dirs):
            part, special = "dancing", "?exit"
        else:
            special = ""
        songs.append({"artist": artist or tags.get("artist", ""), "title": title or tags.get("title", ""),
                      "secs": 0.0, "trouble": "", "_tags": tags, "bpm": tags.get("bpm", 0.0), "camelot": tags.get("key", ""),
                      "year": tags.get("year", 0), "part": part, "file": str(p),
                      "moment": special or ("?" if not part and any(_MOMENTS_DIR.search(x) for x in dirs) else "")})
    left = max(0, len(songs) - contract.MAX_SHOW_SONGS)
    if left:
        room = contract.MAX_SHOW_SONGS - sum(1 for s in songs if s["moment"])
        kept = []
        for s in songs:
            if s["moment"] or room > 0:
                kept.append(s)
                room -= 0 if s["moment"] else 1
        songs = kept[:contract.MAX_SHOW_SONGS]
    for s in songs:   # only the songs the show keeps have their file read for its length
        tags = s.pop("_tags")
        s["secs"], s["trouble"] = audio_length(s["file"], tags if s["file"].lower().endswith(".mp3") else None)
    _place_moments(songs)
    _place_exit(songs)
    return root.name, songs, left


_MOMENTS_DIR = re.compile(r"\bmoments?\b")
_BACKGROUND_DIR = re.compile(r"\bbackground\b")
_TOASTS_DIR = re.compile(r"\btoasts?\b|\bspeech(es)?\b")
_CAKE_DIR = re.compile(r"\bcake\b")
_LIBRARY_DIR = re.compile(r"\binstrumentals\b")
_EXIT_DIR = re.compile(r"\bgrand exit\b|\bexit\b")


def _place_exit(songs: list[dict]) -> None:
    """The Grand Exit folder's songs (marked "?exit"): the song known as an exit song is the exit, one
    known as a sing-along the one before it; else the last file is the exit and the one before it the
    sing-along. One song alone is the exit song. More than two: the rest play in Dancing."""
    from . import song_canon  # noqa: PLC0415
    marked = [s for s in songs if s.get("moment") == "?exit"]
    if not marked:
        return

    def tags(s: dict) -> frozenset:
        k = song_canon.lookup(s.get("artist", ""), s.get("title", ""))
        return k.tags if k else frozenset()

    left = list(marked)
    for moment in ("exit", "exit-prep"):
        if not left:
            break
        known = [s for s in left if moment in tags(s)]
        pick = known[0] if known else left[-1]
        pick["moment"] = moment
        left.remove(pick)
    for s in left:
        s["moment"] = ""


def place_from_folder(have: list, found: list) -> list:
    """Songs already in a show take their part of the night, and their dance, from the folder they sit
    in (Llano BL #12338). His AJ Wedding show held 54 songs and none had a part: it was saved before a
    song kept one, and adding the folder again answered "No new songs" and changed nothing, so dinner
    songs were given dance lights and the night would have built as one Dancing playlist.

    `have` is the show's songs, `found` what read_folder gave. Returns [{"i", "part", "moment"}], one
    per song of `have` the folder places differently. Songs are matched by track key, so "Killin_ Time"
    (a Drive zip turns an apostrophe into an underscore) is "Killin' Time". A song that already has a
    dance is left alone: he, or the app, tied it to that moment. A folder that names no part moves
    nothing."""
    by: dict = {}
    for f in found or []:
        if isinstance(f, dict) and f.get("moment") != "?":
            k = contract.track_key(f.get("artist", ""), f.get("title", ""))
            if k:
                by.setdefault(k, f)
    out = []
    for i, s in enumerate(have or []):
        if not isinstance(s, dict) or s.get("moment") in contract.SHOW_MOMENTS:
            continue
        f = by.get(contract.track_key(s.get("artist", ""), s.get("title", "")))
        part = (f or {}).get("part") or ""
        if part not in contract.SHOW_PARTS:
            continue
        moment = f.get("moment") if f.get("moment") in contract.SHOW_MOMENTS else ""
        if part != (s.get("part") or "") or moment != (s.get("moment") or ""):
            out.append({"i": i, "part": part, "moment": moment})
    return out


def _place_moments(songs: list[dict]) -> None:
    """Give each song from a Moments folder (marked "?") the moment it is known for, one song per
    moment, the surest first: a song that suits one moment takes it before a song that suits two
    chooses. A song with no known moment, or whose moments are taken, keeps its "?"."""
    from . import song_canon  # noqa: PLC0415

    def suits(s: dict) -> list:
        k = song_canon.lookup(s.get("artist", ""), s.get("title", ""))
        return [m for m in contract.SHOW_MOMENTS if k and m in k.tags]

    marked = [s for s in songs if s.get("moment") == "?"]
    taken: set = set()
    for s in sorted(marked, key=lambda s: len(suits(s)) or 99):
        s["moment"] = next((m for m in suits(s) if m not in taken), "?")
        if s["moment"] != "?":
            taken.add(s["moment"])
            s["part"] = "dancing"      # the dances happen on the dance floor's side of the night

