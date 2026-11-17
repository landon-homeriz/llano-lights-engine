"""Shows: a party's playlist designed into one light show, saved by name (his recording, 2026-11-08).

"Here's the playlist, here's every song, analyze it, design the show, see the whole show play out
right here... save it as Megan's birthday party." A show is the songs in play order, each with the
look it plays (settings_contract BUILTIN_LOOKS or one of his saved styles). It lives in the settings
document under `shows`, so it is saved with everything else in settings.json and, when the laptop is
linked, kept by Llano per tenant like the rest of the settings.

Where the songs come from:
  - Mixxx: a playlist or crate, or a library search. These songs have a file and a beat grid, so
    their sections are worked out from the audio (show_script, cached per track) and the show can
    play right in the window.
  - A pasted list ("Artist - Title" per line, numbered or not, tab or comma separated) or a public
    Spotify playlist link. Each song is matched to the Mixxx library by name; one with no match keeps
    estimated sections from its tempo and length, and plays wherever it really plays (Spotify, a
    phone) with the lights finding the beat by ear.

Spotify: its Web API stopped giving song analysis to new apps in Nov 2024, and its developer policy
forbids syncing its recordings to visuals, so nothing here touches Spotify audio. A playlist link is
read from Spotify's public embed page (titles, artists and lengths only, up to the 50 to 100 songs it
lists); when that page changes or refuses, the window says so and a pasted list still works.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
import sqlite3
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import demo_songs, show_settings
from . import settings_contract as contract
from .beat_clock import TrackGrid
from .mixxx_db import MixxxLibrary, parse_beats
from .song_match import norm
from .show_script import BEATS_PER_BAR, PHRASE_BARS, ScriptCache, Section, ShowScript, analyze_track

DEFAULT_SECS = 210.0
DEFAULT_BPM = 120.0
SPOTIFY_EMBED = "https://open.spotify.com/embed/playlist/{id}"
SPOTIFY_RE = re.compile(r"open\.spotify\.com/(?:intl-[a-z-]+/)?(?:embed/)?playlist/([A-Za-z0-9]{10,40})")
PART_TITLES = {"cocktail": "Cocktail hour", "dinner": "Dinner", "dancing": "Dancing"}
MOMENT_TITLES = {"first-dance": "First dance", "father-daughter": "Father-daughter dance",
                 "mother-son": "Mother-groom dance", "last-dance": "Last dance",
                 "exit-prep": "Prepare for grand exit", "exit": "Bride and groom exit", "background": "Quiet background",
                 "toasts-background": "Under the toasts"}
# A show's look by where the song falls in the night and how fast it is (design()).
SLOW_BPM = 96
# A Dancing song's energy (Llano BL #12341): Hype plays the peak look, Dance the groove, Slow the slow
# dance. Read from the song itself (the known-song list, else its tempo and how loud and full its audio
# is), never from where it sits in the list, so moving a song never changes its tag.
ENERGY_TAGS = contract.SONG_TAGS
TAG_LOOKS = {"hype": "peak", "dance": "groove", "slow": "slow-dance"}
TAG_TITLES = {"hype": "Hype", "dance": "Dance", "slow": "Slow"}
TROUBLES = ("unreadable", "no-length", "too-long")
HYPE_ENERGY = 0.72   # a song the known-song list doesn't know is Hype at this energy (0..1) or above


@dataclass
class ShowSong:
    """One song of a show as the window draws it: the saved fields plus what the library knows."""
    artist: str
    title: str
    look: str = ""
    secs: float = 0.0
    bpm: float = 0.0
    track_id: int = 0          # Mixxx library id, 0 when the song is not in the library
    first_beat_s: float = 0.0
    sections: list = field(default_factory=list)   # [{kind, start, end, energy}] in seconds
    source: str = "estimated"  # "mixxx" (worked out from the file) or "estimated"
    playable: bool = False     # the window can play its file
    why: str = ""              # why design() picked its look
    # the set arranger (1.18.0): where in the night it plays, a wedding moment, why it sits there
    part: str = ""             # contract.SHOW_PARTS or ""
    moment: str = ""           # contract.SHOW_MOMENTS or ""
    reason: str = ""
    pinned: bool = False       # he placed it by hand: arranging again leaves it (not saved)
    camelot: str = ""          # its key, from the library ("8A"); read again on open, not saved
    year: int = 0
    energy: float = 0.0        # 0..1 as the arranger reads it (for the curve)
    tag: str = ""              # a Dancing song's energy: ENERGY_TAGS or "" (BL #12341)
    tag_mine: bool = False     # he chose the tag himself: designing again keeps it
    # why its length is unknown (BL #11473): "unreadable" (the file would not open), "no-length" (it
    # opened, no length in it), "too-long" (over an hour), or "" (read, or no file here). Not saved.
    trouble: str = ""
    # his own Starts at / Ends at for the night's cut (Llano PM #23751): seconds into the song file, or
    # None for Llano's suggestion (wedding_night.cut_args)
    start_at: Optional[float] = None
    end_at: Optional[float] = None

    def saved(self) -> dict:
        out = {"artist": self.artist, "title": self.title, "look": self.look, "why": self.why,
               "secs": round(self.secs, 2), "bpm": round(self.bpm, 2)}
        for k in ("part", "moment", "reason", "tag"):
            if getattr(self, k):
                out[k] = getattr(self, k)
        if self.tag and self.tag_mine:
            out["tag_mine"] = True
        for k in ("start_at", "end_at"):
            if getattr(self, k) is not None:
                out[k] = round(getattr(self, k), 2)
        return out

    def public(self) -> dict:
        return asdict(self)

    @property
    def key(self) -> str:
        return contract.track_key(self.artist, self.title)


# --- names --------------------------------------------------------------------------------------

def slug(title: str) -> str:
    """'Megan's birthday party' -> 'megans-birthday-party' (a contract.good_name)."""
    words = re.findall(r"[a-z0-9]+", str(title or "").lower().replace("'", "").replace("’", ""))
    out = ""
    for w in words:
        if len(out) + len(w) + (1 if out else 0) > 44:
            break
        out = f"{out}-{w}" if out else w
    if not out or out in contract.WINDOWS_RESERVED:
        out = f"show-{out}" if out else "show"
    return out


# --- the Mixxx library --------------------------------------------------------------------------

_TRACK_COLS = """l.id, COALESCE(l.artist, ''), COALESCE(l.title, ''), COALESCE(l.duration, 0),
                 COALESCE(l.bpm, 0), l.beats_version, l.beats, l.samplerate, tl.location"""


@dataclass
class LibTrack:
    track_id: int
    artist: str
    title: str
    secs: float
    bpm: float
    grid: Optional[TrackGrid]
    location: Optional[Path]

    def song(self) -> ShowSong:
        return ShowSong(self.artist, self.title, secs=self.secs, bpm=self.bpm, track_id=self.track_id,
                        playable=bool(self.location and self.location.is_file()))

    def public(self) -> dict:
        return {"track_id": self.track_id, "artist": self.artist, "title": self.title,
                "secs": round(self.secs, 1), "bpm": round(self.bpm, 1)}


def _rows(lib: MixxxLibrary, sql: str, args: tuple = ()) -> list:
    if not lib.available():
        return []
    try:
        with lib._connect() as conn:
            return conn.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def _track(row) -> LibTrack:
    track_id, artist, title, secs, bpm, version, blob, rate, location = row
    grid = parse_beats(version or "", blob or b"", rate or 44100) if blob else None
    return LibTrack(track_id, artist, title, float(secs or 0), float(bpm or 0), grid,
                    Path(location) if location else None)


def lists(lib: MixxxLibrary) -> list[dict]:
    """His Mixxx playlists and crates, for the "Start from" picker (history and Auto DJ left out)."""
    out = [{"kind": "playlist", "id": pid, "name": name, "count": n} for pid, name, n in _rows(lib, """
        SELECT p.id, p.name, (SELECT COUNT(*) FROM PlaylistTracks pt WHERE pt.playlist_id = p.id)
          FROM Playlists p WHERE p.hidden = 0 ORDER BY p.name COLLATE NOCASE""")]
    out += [{"kind": "crate", "id": cid, "name": name, "count": n} for cid, name, n in _rows(lib, """
        SELECT c.id, c.name, (SELECT COUNT(*) FROM crate_tracks ct WHERE ct.crate_id = c.id)
          FROM crates c ORDER BY c.name COLLATE NOCASE""")]
    return out


def list_tracks(lib: MixxxLibrary, kind: str, list_id: int) -> list[LibTrack]:
    if kind == "playlist":
        sql = f"""SELECT {_TRACK_COLS} FROM PlaylistTracks pt JOIN library l ON l.id = pt.track_id
                  LEFT JOIN track_locations tl ON tl.id = l.location
                  WHERE pt.playlist_id = ? AND l.mixxx_deleted = 0 ORDER BY pt.position"""
    elif kind == "crate":
        sql = f"""SELECT {_TRACK_COLS} FROM crate_tracks ct JOIN library l ON l.id = ct.track_id
                  LEFT JOIN track_locations tl ON tl.id = l.location
                  WHERE ct.crate_id = ? AND l.mixxx_deleted = 0 ORDER BY l.artist, l.title"""
    else:
        return []
    return [_track(r) for r in _rows(lib, sql, (int(list_id),))][:contract.MAX_SHOW_SONGS]


def search(lib: MixxxLibrary, q: str, limit: int = 30) -> list[LibTrack]:
    words = [w for w in re.findall(r"\w+", str(q or "").lower()) if w][:6]
    if not words:
        return []
    where = " AND ".join("(LOWER(COALESCE(l.artist,'')) || ' ' || LOWER(COALESCE(l.title,''))) LIKE ?" for _ in words)
    sql = f"""SELECT {_TRACK_COLS} FROM library l LEFT JOIN track_locations tl ON tl.id = l.location
              WHERE l.mixxx_deleted = 0 AND {where} ORDER BY l.artist, l.title LIMIT ?"""
    return [_track(r) for r in _rows(lib, sql, (*[f"%{w}%" for w in words], int(limit)))]


def tags(lib: MixxxLibrary, track_ids: list) -> dict:
    """{track id: (key, year)} from the library, for the set arranger. Mixxx writes the key in the
    notation picked in its settings; set_arranger.camelot reads them all. {} when unreadable."""
    ids = [int(t) for t in track_ids if t][:500]
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    out = {}
    for tid, key, year in _rows(lib, f"SELECT id, COALESCE(key, ''), COALESCE(year, '') FROM library "
                                     f"WHERE id IN ({marks})", tuple(ids)):
        m = re.match(r"\s*(\d{4})", str(year))
        out[tid] = (str(key), int(m.group(1)) if m else 0)
    return out


def track(lib: MixxxLibrary, track_id: int) -> Optional[LibTrack]:
    rows = _rows(lib, f"""SELECT {_TRACK_COLS} FROM library l LEFT JOIN track_locations tl ON tl.id = l.location
                          WHERE l.id = ? AND l.mixxx_deleted = 0""", (int(track_id),))
    return _track(rows[0]) if rows else None


class LibraryIndex:
    """Find a song known only by name (a pasted list, Spotify) in the Mixxx library, forgiving
    case, punctuation, "feat." and "Remastered" the way song_match does for live playback."""

    def __init__(self, lib: MixxxLibrary):
        self.lib = lib
        self._by_key: Optional[dict] = None

    def find(self, artist: str, title: str) -> Optional[LibTrack]:
        if not norm(contract.track_key(artist, title)):   # a name with no a-z or 0-9: never another song's match
            return None
        if self._by_key is None:
            self._by_key, self._by_title = {}, {}
            for tid, a, t in _rows(self.lib, "SELECT id, COALESCE(artist,''), COALESCE(title,'') FROM library "
                                             "WHERE mixxx_deleted = 0"):
                if t.strip():   # a name with no a-z or 0-9 keys as "": it never matches (BL #11473)
                    for index, k in ((self._by_key, norm(contract.track_key(a, t))), (self._by_title, norm(contract.track_key(t)))):
                        if k:
                            index.setdefault(k, tid)
        tid = self._by_key.get(norm(contract.track_key(artist, title))) if artist else None
        if tid is None:   # "Title - Artist" typed the other way round, or no artist given
            tid = self._by_key.get(norm(contract.track_key(title, artist))) if artist else \
                self._by_title.get(norm(contract.track_key(title)))
        return track(self.lib, tid) if tid is not None else None


# --- song lists from outside Mixxx --------------------------------------------------------------

_NUMBERED = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+")
_TIME = re.compile(r"\s*[\(\[]?\b(\d{1,2}):([0-5]\d)\b[\)\]]?\s*$")


def parse_list(text: str) -> list[dict]:
    """Songs from pasted text: one per line as "Artist - Title", "Title by Artist", or a CSV/TSV
    export with artist and title columns (Exportify, a spreadsheet). A trailing 3:45 is the length.
    A line of nothing but punctuation ("----") is never a song."""
    return parse_pasted(text)[0]


def _words(t: str) -> bool:
    """Whether `t` holds a letter or a digit in any script: "----" and "..." do not."""
    return any(ch.isalnum() for ch in str(t or ""))


def parse_pasted(text: str, known=None) -> tuple[list[dict], list[str]]:
    """(songs, left_out) from pasted text, for the Shows page's Paste a list (Llano BL #11473).
    left_out names, in paste order, the lines that do not look like a song: nothing but punctuation,
    or no artist and title to split ("not a song"). With `known` (a title -> bool from his Mixxx
    library), a bare title his library has is a song all the same; with no `known`, every bare title
    is kept (the old parse_list). Typed as "Title by Artist", any song goes in."""
    text = str(text or "")[:60_000]
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return [], []
    head = lines[0].lower()
    if ("\t" in lines[0] or "," in lines[0]) and "title" in head or "track name" in head:
        return _parse_table(text), []
    out, left = [], []
    part = ""
    for ln in lines:
        raw = " ".join(ln.split())
        ln = _NUMBERED.sub("", ln).strip()
        if not ln or SPOTIFY_RE.search(ln) or ln.startswith("http"):
            continue
        if not _words(ln):   # "----", "* * *", "...": a divider, never a song
            left.append(raw[:60])
            continue
        bare = re.sub(r"^\d{1,2}\s*[-–—.)]\s*", "", ln).rstrip(" :")
        head = part_from_name(bare) if len(bare) <= 40 and not any(sep in bare for sep in (" - ", " – ", " — ", "\t", " by ")) else ""
        if head:   # a heading line like "Cocktail hour" or "3 - Dancing:" starts that part
            part = head
            continue
        secs = 0.0
        m = _TIME.search(ln)
        if m:
            secs, ln = int(m.group(1)) * 60 + int(m.group(2)), ln[:m.start()].strip()
        artist, title = "", ln
        for sep in (" – ", " — ", " - ", "\t", " | "):
            if sep in ln:
                artist, title = (p.strip() for p in ln.split(sep, 1))
                break
        else:
            low = ln.lower()
            if " by " in low:
                i = low.rindex(" by ")
                title, artist = ln[:i].strip(), ln[i + 4:].strip()
        if not _words(title) or (artist and not _words(artist)) or \
                (not artist and known is not None and not known(title)):
            left.append(raw[:60])   # nothing to split into an artist and a title, and not a song he has
            continue
        out.append({"artist": artist, "title": title, "secs": secs, **({"part": part} if part else {})})
        if len(out) >= contract.MAX_SHOW_SONGS:
            break
    return out, left


def _parse_table(text: str) -> list[dict]:
    dialect = "excel-tab" if "\t" in text.splitlines()[0] else "excel"
    rows = list(csv.reader(io.StringIO(text), dialect=dialect))
    head = [h.strip().lower() for h in rows[0]]

    def col(*names):
        return next((i for i, h in enumerate(head) for n in names if n in h), None)

    ti, ai, di = col("track name", "title", "song"), col("artist"), col("duration", "length", "time")
    out = []
    for r in rows[1:]:
        if ti is None or ti >= len(r) or not r[ti].strip():
            continue
        secs = 0.0
        if di is not None and di < len(r):
            v = r[di].strip()
            m = re.fullmatch(r"(\d{1,2}):([0-5]\d)", v)
            secs = int(m.group(1)) * 60 + int(m.group(2)) if m else (float(v) / 1000 if v.isdigit() and int(v) > 10_000 else 0.0)
        artist = r[ai].split(",")[0].strip() if ai is not None and ai < len(r) else ""
        out.append({"artist": artist, "title": r[ti].strip(), "secs": secs})
        if len(out) >= contract.MAX_SHOW_SONGS:
            break
    return out


_PART_NAMES = (("cocktail", "cocktail"), ("dinner", "dinner"), ("supper", "dinner"), ("dancing", "dancing"),
               ("dance floor", "dancing"), ("dance party", "dancing"), ("reception", "dancing"))


def part_from_name(name: str) -> str:
    """The part of the night a playlist, crate, folder or heading names ("1 - Cocktail Hour - Set
    Order" is cocktail), else ""."""
    low = " ".join(re.findall(r"[a-z]+", str(name or "").lower()))
    for word, part in _PART_NAMES:
        if re.search(rf"\b{word}\b", low):
            return part
    return ""


class SpotifyError(Exception):
    """A playlist link that couldn't be read: a plain reason for the window."""


def spotify_id(url: str) -> str:
    m = SPOTIFY_RE.search(str(url or ""))
    return m.group(1) if m else ""


def spotify_playlist(url: str, fetch: Optional[Callable[[str], str]] = None) -> tuple[str, list[dict]]:
    """(playlist name, songs) from a PUBLIC Spotify playlist's embed page. Titles, artists and
    lengths only: no audio, and nothing that needs a Spotify account or developer app."""
    pid = spotify_id(url)
    if not pid:
        raise SpotifyError("that isn't a Spotify playlist link (Share, then Copy link to playlist)")

    def _get(u: str) -> str:
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read(4_000_000).decode("utf-8", "replace")

    try:
        page = (fetch or _get)(SPOTIFY_EMBED.format(id=pid))
    except Exception as e:  # noqa: BLE001 -- offline, refused, timed out: one plain line
        raise SpotifyError(f"couldn't reach Spotify ({type(e).__name__}); paste the song names instead") from e
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', page, re.S)
    try:
        entity = json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
        tracks = entity["trackList"]
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        raise SpotifyError("Spotify didn't list that playlist's songs (is it public?); paste the song "
                           "names instead") from e
    songs = []
    for t in tracks[:contract.MAX_SHOW_SONGS]:
        if isinstance(t, dict) and t.get("title"):
            songs.append({"artist": str(t.get("subtitle") or "").split(",")[0].strip(),
                          "title": str(t["title"]).strip(),
                          "secs": round((t.get("duration") or 0) / 1000, 1)})
    if not songs:
        raise SpotifyError("that playlist has no songs Spotify will list; paste the song names instead")
    return str(entity.get("name") or entity.get("title") or ""), songs


# --- sections -----------------------------------------------------------------------------------

def _beat_secs(grid: TrackGrid, beat: float) -> float:
    if grid.beats:
        i = int(beat)
        if 0 <= i < len(grid.beats) - 1:
            a, b = grid.beats[i], grid.beats[i + 1]
            return (a + (b - a) * (beat - i)) / grid.samplerate
        if grid.beats and i >= len(grid.beats) - 1 and grid.bpm > 0:
            return grid.beats[-1] / grid.samplerate + (beat - len(grid.beats) + 1) * 60 / grid.bpm
    return grid.first_beat / grid.samplerate + beat * 60 / (grid.bpm or DEFAULT_BPM)


def estimated_sections(secs: float, bpm: float, first_beat_s: float = 0.0) -> list[dict]:
    """A typical dance-song shape on 8-bar phrases, for a song we can't read: intro, verse, build,
    drop, main, breakdown, build, drop, main, outro, stretched or cut to the song's length."""
    secs, bpm = secs or DEFAULT_SECS, bpm or DEFAULT_BPM
    phrase = PHRASE_BARS * BEATS_PER_BAR * 60 / bpm
    plan = ["intro", "verse", "build", "drop", "main", "breakdown", "build", "drop", "main", "outro"]
    n = max(4, round((secs - first_beat_s) / phrase))
    if n < len(plan):
        plan = ["intro", "build", "drop", "main", "breakdown", "build", "drop", "outro"][:n - 1] + ["outro"]
    else:   # longer songs repeat the middle
        mid = ["verse", "build", "drop", "main", "breakdown"]
        while len(plan) < n:
            plan[-1:-1] = [mid[(len(plan) - 10) % len(mid)]]
    energy = {"intro": 0.3, "verse": 0.5, "build": 0.6, "drop": 1.0, "main": 0.9, "breakdown": 0.35, "outro": 0.25}
    out, t = [], first_beat_s
    for i, kind in enumerate(plan):
        end = secs if i == len(plan) - 1 else min(secs, t + phrase)
        if out and out[-1]["kind"] == kind:
            out[-1]["end"] = round(end, 2)
        else:
            out.append({"kind": kind, "start": round(t, 2), "end": round(end, 2), "energy": energy[kind]})
        t = end
    return out


def analyze(song: ShowSong, lib: MixxxLibrary, cache: ScriptCache, read_audio: bool = True) -> ShowSong:
    """Fill a song's sections: from its Mixxx file and beat grid when it has them (cached per track,
    so a show analyzes once), else estimated from its tempo and length."""
    lt = track(lib, song.track_id) if song.track_id else None
    if lt:
        song.secs, song.bpm = lt.secs or song.secs, lt.bpm or song.bpm
        song.playable = bool(lt.location and lt.location.is_file())
    if lt and lt.grid:
        song.first_beat_s = round(_beat_secs(lt.grid, 0), 3)
        song.bpm = lt.grid.bpm or song.bpm
        script = cache.get(lt.track_id, lt.location)
        if script is None and read_audio and song.playable:
            try:
                script = analyze_track(lt.location, lt.grid)
            except Exception as e:  # noqa: BLE001 -- an unreadable file falls back to an estimate
                print(f"Couldn't read sections from {lt.location.name}: {type(e).__name__}: {e}")
                script = None
            if script:
                cache.put(lt.track_id, script)
        if script and script.sections:
            song.sections = [{"kind": s.kind, "start": round(_beat_secs(lt.grid, s.start_beat), 2),
                              "end": round(min(song.secs or 1e9, _beat_secs(lt.grid, s.end_beat)), 2),
                              "energy": s.energy} for s in script.sections]
            song.sections[-1]["end"] = round(max(song.sections[-1]["end"], song.secs), 2)
            song.source = "mixxx"
            return song
    song.sections = estimated_sections(song.secs, song.bpm, song.first_beat_s)
    song.source = "estimated"
    return song


# --- designing ------------------------------------------------------------------------------------

def design(songs: list[ShowSong], filed: Optional[dict] = None, styles: Optional[dict] = None,
           keep: bool = False) -> list[ShowSong]:
    """Give every song a look for its place in the night. A song he already filed under a saved style
    keeps it; with keep=True a song that already has a look keeps that too (redesign the rest).

    A Dancing song plays its energy tag's look (tag_song), wherever it sits. A show with no parts of
    the night follows the arc: the first fifth warms up; slow songs (under 96 BPM) are slow dances wherever they fall;
    the middle grooves, with the faster songs from just past halfway to near the end as the peak; the
    last song is the sing-along send-off."""
    from .song_match import candidates, pick  # noqa: PLC0415

    filed, styles = filed or {}, styles or {}
    n = len(songs)
    # An arranged wedding (1.18.0) says which part each song plays in: the arc runs over the dancing
    # alone, cocktail hour and dinner get their own looks, and the couple's dances are slow dances.
    dancing = [k for k, s in enumerate(songs) if s.part == "dancing"] if any(s.part for s in songs) else []
    for i, s in enumerate(songs):
        if keep and (s.look or s.why == "your pick"):   # "" with "your pick" is his House show pick
            s.why = s.why or "kept"
            continue
        hit = pick(filed, candidates(s.artist, s.title)) if filed else None
        if hit and filed[hit] in styles:
            s.look, s.why = filed[hit], f"you filed it under {filed[hit]}"
            continue
        if s.moment in ("first-dance", "father-daughter", "mother-son"):
            s.look, s.why = "slow-dance", "a wedding moment: " + s.moment.replace("-", " ")
            continue
        if s.moment in ("exit-prep", "exit"):   # his grand exit (BL #12360): the whole room sings
            s.look, s.why = "sing-along", "the grand exit: " + ("the last big sing-along" if s.moment == "exit-prep" else "the couple's exit song")
            continue
        if s.moment in ("background", "toasts-background"):
            s.look, s.why = "warm-up", ("quiet background under the toasts and speeches" if s.moment == "toasts-background"
                                        else "quiet background under the toasts and the cake")
            continue
        if s.moment == "last-dance":
            s.look, s.why = ("slow-dance" if s.bpm and s.bpm < SLOW_BPM else "sing-along"), "the last dance"
            continue
        if s.part == "cocktail":
            s.look, s.why = "warm-up", "cocktail hour: a soft warm wash, nothing moves or flashes"
            continue
        if s.part == "dinner":
            s.look, s.why = "warm-up", "dinner: a soft warm wash, so tables can talk"
            continue
        if s.part == "dancing":   # the song's own energy picks its look, wherever it sits (BL #12341)
            tag_song(s)
            s.look, s.why = TAG_LOOKS[s.tag], f"{TAG_TITLES[s.tag]}: {s.why}"
            continue
        pos = i / max(1, n - 1)
        if dancing and i in dancing:
            k, m = dancing.index(i), len(dancing)
            pos, last = k / max(1, m - 1), k == m - 1
        else:
            last = n > 2 and i == n - 1
        if s.bpm and s.bpm < SLOW_BPM:
            s.look, s.why = "slow-dance", f"slow ({s.bpm:.0f} BPM)"
        elif last:
            s.look, s.why = "sing-along", "the last song of the night"
        elif pos < 0.2:
            s.look, s.why = "warm-up", "early in the night"
        elif 0.5 <= pos <= 0.9 and (s.bpm or DEFAULT_BPM) >= 118:
            s.look, s.why = "peak", "the peak of the night" + (f", {s.bpm:.0f} BPM" if s.bpm else "")
        else:
            s.look, s.why = "groove", "steady dancing"
    return songs


def audio_level(song: ShowSong) -> Optional[float]:
    """How loud and full a song's audio is, 0..1: its sections' measured levels, weighted by length.
    None when the sections are estimated from tempo (there is nothing measured to read)."""
    if song.source != "mixxx" or not song.sections:
        return None
    total = sum(max(0.0, x["end"] - x["start"]) for x in song.sections)
    if total <= 0:
        return None
    return sum(max(0.0, x["end"] - x["start"]) * float(x.get("energy") or 0) for x in song.sections) / total


def energy_tag(song: ShowSong) -> tuple[str, str]:
    """(tag, why) for a Dancing song, from the song alone: the known-song list when it knows the song
    (its hype and closer songs are Hype, its slow ones Slow, the rest Dance), else its tempo and how
    loud and full its audio is (set_arranger.facts_for)."""
    from .set_arranger import facts_for  # noqa: PLC0415
    f = facts_for(song, audio_level(song))
    bpm = f" at {f.bpm:.0f} BPM" if f.bpm else ""
    if f.slow:
        return "slow", ("a known slow dance" if f.in_canon else f"slow and soft{bpm}")
    if f.in_canon:
        if f.tags & {"hype", "closer"}:
            return "hype", "a known floor-filler"
        return "dance", "a known dance song" if "line" not in f.tags else "a known line dance"
    if f.energy >= HYPE_ENERGY:
        return "hype", f"fast and full{bpm}"
    return "dance", f"steady{bpm}"


def tag_song(song: ShowSong) -> ShowSong:
    """Give a song its energy tag unless he chose one himself; song.why says where it came from."""
    if song.tag_mine and song.tag in ENERGY_TAGS:
        song.why = "you tagged it"
        return song
    song.tag, song.why = energy_tag(song)
    song.tag_mine = False
    return song


def prefill_tags(songs: list[ShowSong], own: Optional[dict] = None) -> list[ShowSong]:
    """A show saved before tags (or a Dancing song added since) opens with every Dancing song tagged,
    its look following the tag. His own look picks and the looks Llano designed for the show stay."""
    own = own or {}
    for s in songs:
        if s.part != "dancing" or s.moment or s.tag in ENERGY_TAGS:
            continue
        mine = s.why == "your pick" or (s.look and s.look in own)
        was = s.why
        tag_song(s)
        if mine:
            s.why = was
            continue
        s.look, s.why = TAG_LOOKS[s.tag], f"{TAG_TITLES[s.tag]}: {s.why}"
    return songs


def tag_index(songs: list[ShowSong]) -> dict:
    """{every key a song could play under: (index, part, tag)} for the Live screen's song line."""
    from .song_match import candidates  # noqa: PLC0415
    out = {}
    for i, s in enumerate(songs):
        for k in candidates(s.artist, s.title):
            out.setdefault(k, (i, s.part, s.tag))
    return out


def tag_of(index: dict, artist: str, title: str) -> Optional[tuple]:
    """(index, part, tag) of the playing song in the show the Live show follows, or None."""
    from .song_match import candidates, pick  # noqa: PLC0415
    hit = pick(index, candidates(artist, title)) if index and (artist or title) else None
    return index[hit] if hit else None


def retag_ops(name: str, sh: dict, i: int, tag: str) -> list:
    """The settings change that sets song i of saved show `name` to `tag`, his own choice, and plays
    that tag's look (the Live screen's tap)."""
    if tag not in ENERGY_TAGS:
        raise contract.ContractError("the tag is hype, dance or slow")
    songs = [dict(s) for s in sh["songs"]]
    if not 0 <= i < len(songs):
        raise contract.ContractError("that song is not in the show")
    songs[i].update(tag=tag, tag_mine=True, look=TAG_LOOKS[tag], why=f"{TAG_TITLES[tag]}: you tagged it")
    return [{"path": f"shows.{name}", "value": {**sh, "songs": songs}}]


def timeline(songs: list[ShowSong]) -> dict:
    """Where each song starts in the whole show, and the show's length, for the front-to-back view."""
    t, starts = 0.0, []
    for s in songs:
        starts.append(round(t, 2))
        t += s.secs or (s.sections[-1]["end"] if s.sections else DEFAULT_SECS)
    return {"starts": starts, "total": round(t, 2)}


# --- saving ----------------------------------------------------------------------------------------

def own_looks(looks) -> dict:
    """A show's own looks as the contract keeps them (clamped; at most MAX_SHOW_LOOKS)."""
    return contract.normalize({"shows": {"x": {"title": "x", "looks": looks if isinstance(looks, dict) else {},
                                                "songs": []}}})["shows"]["x"]["looks"]


def saved_shows(doc: Optional[dict] = None) -> dict:
    return (doc or show_settings.current()).get("shows", {})


def list_public(doc: Optional[dict] = None) -> list[dict]:
    out = []
    for name, sh in saved_shows(doc).items():
        total = sum(s.get("secs") or DEFAULT_SECS for s in sh["songs"])
        out.append({"name": name, "title": sh["title"] or name, "songs": len(sh["songs"]), "secs": round(total)})
    return sorted(out, key=lambda x: x["title"].lower())


def save_ops(title: str, songs: list[dict], note: str = "", name: str = "", looks: Optional[dict] = None,
             moods: Optional[dict] = None) -> tuple[str, list]:
    """(name, ops) that save a show: under `name` when re-saving, else a fresh name from the title
    that doesn't overwrite another show. `looks` are the show's own (Llano's design): saving from
    this page keeps them, so a re-save never wipes what Llano designed."""
    title = " ".join(str(title or "").split())[:80]
    if not title:
        raise contract.ContractError("give the show a name, like Megan's birthday party")
    if not songs:
        raise contract.ContractError("a show needs at least one song")
    value = {"title": title, "note": str(note or "")[:300], "looks": own_looks(looks), "songs": songs}
    if isinstance(moods, dict):   # cocktail hour and dinner's moods (BL #12340), saved with the show
        value["moods"] = contract.moods(moods)
    if len(songs) <= contract.MAX_SHOW_SONGS and not contract.show_fits(value):
        # the arranger's reasons are rebuilt whenever the show opens: drop them before any song
        trimmed = {**value, "songs": [{k: v for k, v in s.items() if k != "reason"} for s in songs]}
        if contract.show_fits(trimmed):
            value = trimmed
    if len(songs) > contract.MAX_SHOW_SONGS or not contract.show_fits(value):
        fit = len(contract.normalize({"shows": {"x": value}})["shows"].get("x", {"songs": []})["songs"])
        raise contract.ContractError(f"that show is too long to save: the first {fit} songs fit; "
                                     "split it into two shows")
    have = saved_shows()
    if not (name and contract.good_name(name)):
        base = slug(title)
        name, k = base, 2
        while name in have and (have[name]["title"] or name) != title:
            name, k = f"{base}-{k}", k + 1
    if name not in have and len(have) >= contract.MAX_SHOWS:
        raise contract.ContractError(f"at most {contract.MAX_SHOWS} saved shows; delete one first")
    return name, [{"path": f"shows.{name}", "value": value}]


def load(name: str, lib: MixxxLibrary, cache: ScriptCache, read_audio: bool = False, found: Optional[list] = None,
         filed: Optional[dict] = None, styles: Optional[dict] = None) -> Optional[dict]:
    """A saved show with each song found in the library again and its sections, for the window, filled
    (fill): a show saved with a blank look, a part its folder names or no length opens whole. `found` is
    song_folder.read_folder of the show's folder on this laptop, when the page knows it."""
    sh = saved_shows().get(name)
    if sh is None:
        return None
    index = LibraryIndex(lib)
    songs = []
    for s in sh["songs"]:
        song = ShowSong(s["artist"], s["title"], look=s["look"], secs=s["secs"], bpm=s["bpm"], why=s.get("why", ""),
                        part=s.get("part", ""), moment=s.get("moment", ""), reason=s.get("reason", ""),
                        tag=s.get("tag", ""), tag_mine=s.get("tag_mine") is True,
                        start_at=_at(s.get("start_at")), end_at=_at(s.get("end_at")))
        lt = index.find(song.artist, song.title)
        if lt:
            song.track_id = lt.track_id
        songs.append(analyze(song, lib, cache, read_audio=read_audio))
    done = fill(songs, found=found, filed=filed, styles=styles, own=sh.get("looks"))
    return {"name": name, "title": sh["title"] or name, "note": sh["note"], "looks": sh.get("looks", {}),
            "moods": contract.moods(sh.get("moods")),   # Llano's suggestion where the show has none
            "songs": [s.public() for s in songs],
            "timeline": timeline(songs), "fixed": done["fixed"], "lengths": done["lengths"]}


# --- a show is always whole (Llano BL #11473) --------------------------------------------------------
# His first wedding compilation came in with blank spots: every song length 0, a Moments song the app did
# not know left out, songs with no part, blank looks saved while the songs were still being read. fill is
# the one guarantee, run after songs are added, when a show opens and on the app's side of Save: every
# song has a look, a part where its folder names one, a Dancing tag, and its length where its file is
# here. needs() is the list of what only he can settle, one line each, so nothing is left out unsaid.

def _label(s) -> str:
    artist, title = (getattr(s, "artist", "") or "").strip(), (getattr(s, "title", "") or "").strip()
    return f"{title} by {artist}" if artist else title


def song_key(artist: str, title: str) -> str:
    """The track key, or for a name with no a-z or 0-9 in it (a Korean or Russian title keys as "") its
    own words, so two such songs are never one song. "" only for no name at all (BL #11473)."""
    k = contract.track_key(artist, title)
    if k:
        return k
    raw = " ".join(f"{artist} {title}".casefold().split())
    return f"~{raw}" if raw else ""


def fill(songs: list[ShowSong], *, found: Optional[list] = None, filed: Optional[dict] = None,
         styles: Optional[dict] = None, own: Optional[dict] = None) -> dict:
    """Make the show whole, in place. `found` is song_folder.read_folder's songs for the show's folder on
    this laptop: a song with no part takes its folder's (a Moments-folder song no moment is known for
    plays in Dancing), a song with no length takes its file's. A song that has a look keeps its look and
    its why, always (the lead's review: his show's sing-along songs must never turn into peak); fill
    sets a look only where the look is blank, and a Dancing tag only where there is none. Running it
    twice changes nothing. Returns {"songs", "fixed": songs given a part or a look, "lengths": read}."""
    fixed: set = set()
    lengths = 0
    by: dict = {}
    for f in found or []:
        if isinstance(f, dict):
            k = song_key(f.get("artist", ""), f.get("title", ""))
            if k:
                by.setdefault(k, f)
    for i, s in enumerate(songs):
        k = song_key(s.artist, s.title)
        f = by.get(k) if k else None
        if not f:
            continue
        if not s.part and not s.moment:
            part = f.get("part") if f.get("part") in contract.SHOW_PARTS else ("dancing" if f.get("moment") == "?" else "")
            if part:
                s.part = part
                s.moment = f.get("moment") if f.get("moment") in contract.SHOW_MOMENTS else ""
                fixed.add(i)
        if s.secs <= 0:
            s.secs = float(f.get("secs") or 0)
            s.trouble = f.get("trouble") if f.get("trouble") in TROUBLES else ""
            lengths += 1 if s.secs > 0 else 0
    had = {i: (s.look, s.why) for i, s in enumerate(songs) if s.look or s.why == "your pick"}
    blank = [i for i in range(len(songs)) if i not in had]
    if blank:
        design(songs, filed, styles, keep=True)
        for i, (look, why) in had.items():   # design(keep=True) writes "kept" into an empty why
            songs[i].look, songs[i].why = look, why
        fixed.update(blank)
    for s in songs:   # a Dancing song with no tag gets one; a look it already has stays, with its why
        if s.part == "dancing" and not s.moment and s.tag not in ENERGY_TAGS:
            s.tag, _why = energy_tag(s)
            s.tag_mine = False
    return {"songs": songs, "fixed": len(fixed), "lengths": lengths}


NEEDS_EACH = 8   # lines of one kind before the rest are counted in one line


def needs(songs: list[ShowSong], moments: Optional[dict] = None, unplaced: Optional[list] = None) -> list[dict]:
    """What only he can settle, as [{"kind", "text"}], one plain line each, in the order he fixes them:
    a song with no part, a moment that plays a song and has none, a Moments-folder song tied to no
    moment, a file that would not open, a length that could not be read, a song with no file here.
    `moments` is the night panel's {moment key: {"on", "song"}} (None: the holds are not checked);
    `unplaced` the names ("Artist - Title") of Moments-folder songs no moment is known for."""
    from . import run_of_show as ros  # noqa: PLC0415
    out: list = []

    def add(kind: str, lines: list, more: str) -> None:
        out.extend({"kind": kind, "text": t} for t in lines[:NEEDS_EACH])
        if len(lines) > NEEDS_EACH:
            n = len(lines) - NEEDS_EACH
            out.append({"kind": kind, "text": more.format(n=n, s="" if n == 1 else "s")})

    add("part", [f"{_label(s)} has no part of the night: pick its part in its row." for s in songs
                 if not s.part and not s.moment],
        "{n} more song{s} have no part of the night: pick each one's part in its row.")
    boxes = moments if isinstance(moments, dict) else None
    typed = set()
    if boxes is not None:
        have = {s.moment for s in songs if s.moment}
        holds = []
        for key in ros.DEFAULT_ORDER:
            m = ros.MOMENTS.get(key)
            if not m or not m[3]:
                continue
            box = boxes.get(key) if isinstance(boxes.get(key), dict) else {}
            on = box.get("on") if isinstance(box.get("on"), bool) else key not in ros.OPTIONAL
            song = str(box.get("song") or "").strip()
            if on and not song and key not in have:
                holds.append(f"{m[0]} has no song: pick one in step 2, or untick it.")
        add("hold", holds, "{n} more moment{s} have no song: pick each one in step 2, or untick it.")
        for b in boxes.values():   # a song picked for any moment, the ones the default order leaves out too
            if isinstance(b, dict) and str(b.get("song") or "").strip():
                artist, title = _halves(str(b["song"]))
                typed.update({song_key(artist, title), song_key("", title)} - {""})
    left = []
    here = {song_key(s.artist, s.title) for s in songs} - {""}
    for name in unplaced or []:
        artist, title = _halves(str(name))
        k = song_key(artist, title)
        if not title or k not in here:   # taken out of the show: nothing left to settle
            continue
        if k not in typed and song_key("", title) not in typed:
            left.append(f"{_label(ShowSong(artist, title))} is in the Moments folder but no moment is known for it: "
                        "pick its moment in step 2. Until you do, it plays with the dancing songs.")
    add("unplaced", left, "{n} more Moments folder song{s} need a moment: pick each one's moment in step 2.")
    add("unreadable", [f"{_label(s)}: its file would not open. Replace the file, then add the folder again in step 1."
                       for s in songs if s.trouble == "unreadable"],
        "{n} more song{s} have a file that would not open: replace them, then add the folder again in step 1.")
    add("length", [f"{_label(s)} is longer than an hour, which a show cannot hold: use a shorter file."
                   for s in songs if s.trouble == "too-long" and s.secs <= 0],
        "{n} more song{s} are longer than an hour, which a show cannot hold: use shorter files.")
    add("length", [f"{_label(s)}: its length could not be read, so the night's minutes do not count it. It still plays."
                   for s in songs if s.trouble == "no-length" and s.secs <= 0],
        "{n} more song{s} have a length that could not be read, so the night's minutes do not count them. They still play.")
    none = [s for s in songs if s.secs <= 0 and not s.trouble]
    if len(none) > 3:   # his show would open to a screen of these: one line says it
        out.append({"kind": "nofile", "text": f"{len(none)} songs have no length yet: add their folder in step 1 "
                                              "and each is read from its file."})
    else:
        add("nofile", [f"{_label(s)}: its length is not known yet. Add its folder in step 1 and it is read from the file."
                       for s in none], "")
    return out


def _halves(name: str) -> tuple[str, str]:
    """("Artist", "Title") from "Artist - Title"; ("", name) when it has no artist."""
    artist, sep, title = name.partition(" - ")
    return (artist.strip(), title.strip()) if sep and title.strip() else ("", name.strip())


def _clean_sections(v) -> list:
    """Sections from the page, kept only when well formed: a bad one must never stop a show."""
    out = []
    for x in v if isinstance(v, list) else []:
        try:
            kind, start, end = x["kind"], float(x["start"]), float(x["end"])
            energy = min(1.0, max(0.0, float(x.get("energy", 0.5))))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if kind in contract.SECTIONS and math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= 7200:
            out.append({"kind": kind, "start": start, "end": end, "energy": energy})
    return out[:400]


def _at(v) -> Optional[float]:
    """A Starts at / Ends at from the page: seconds into the song file (0..3600), or None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0 <= v <= 3600):
        return None
    return round(float(v), 2)


def from_public(items: list) -> list[ShowSong]:
    """The window's song list back into ShowSongs (only the fields a song may carry)."""
    keep = ShowSong.__dataclass_fields__
    out = []
    for it in (items if isinstance(items, list) else [])[:contract.MAX_SHOW_SONGS]:
        if isinstance(it, dict) and str(it.get("title") or "").strip():
            d = {k: it[k] for k in keep if k in it}
            try:
                out.append(ShowSong(**{**d, "artist": str(d.get("artist") or "")[:80],
                                       "title": str(d["title"])[:120], "look": str(d.get("look") or ""),
                                       "secs": float(d.get("secs") or 0), "bpm": float(d.get("bpm") or 0),
                                       "track_id": int(d.get("track_id") or 0),
                                       "sections": _clean_sections(d.get("sections")),
                                       "part": d.get("part") if d.get("part") in contract.SHOW_PARTS else "",
                                       "moment": d.get("moment") if d.get("moment") in contract.SHOW_MOMENTS else "",
                                       "reason": " ".join(str(d.get("reason") or "").split())[:90],
                                       "pinned": d.get("pinned") is True,
                                       "camelot": str(d.get("camelot") or "")[:4],
                                       "year": int(d.get("year") or 0) if str(d.get("year") or "0").isdigit() else 0,
                                       "energy": min(1.0, max(0.0, float(d.get("energy") or 0))),
                                       "tag": d.get("tag") if d.get("tag") in ENERGY_TAGS else "",
                                       "tag_mine": d.get("tag_mine") is True and d.get("tag") in ENERGY_TAGS,
                                       "trouble": d.get("trouble") if d.get("trouble") in TROUBLES else "",
                                       "start_at": _at(d.get("start_at")), "end_at": _at(d.get("end_at"))}))
            except (TypeError, ValueError):
                continue
    return out


def looks_for(songs: list[ShowSong]) -> dict:
    """{track key: look name} for show_settings.set_show_looks while the show plays."""
    return {s.key: s.look for s in songs if s.key}


SOFT_PARTS = ("cocktail", "dinner")   # the parts of the night that get a soft wash and nothing else
DANCE_MOMENTS = ("first-dance", "father-daughter", "mother-son", "last-dance", "exit-prep", "exit")


def is_soft(part: str, moment: str = "") -> bool:
    """His rule, 2026-11-13: cocktail hour and dinner are a soft warm wash only (no moving heads on
    people, no spotlights, no strobe, no laser). A moment's own song is that moment's, not the part's."""
    return part in SOFT_PARTS and not moment


def soft_parts(songs: list[ShowSong]) -> dict:
    """{track key: "cocktail" | "dinner"} for the show's soft songs, so each plays its part's mood."""
    from .song_match import candidates  # noqa: PLC0415
    out: dict = {}
    for s in songs:
        if is_soft(s.part, s.moment):
            for k in candidates(s.artist, s.title):
                out.setdefault(k, s.part)
    return out


def follow(songs: list[ShowSong], own: Optional[dict] = None, moods=None) -> None:
    """The lights follow this show: its looks, its part-of-the-night limits and its moods
    (show_settings). show_settings.set_show_looks(None) ends it."""
    show_settings.set_show_looks(looks_for(songs), own, soft_keys(songs), gentle=gentle_keys(songs))
    show_settings.set_soft_parts("show", soft_parts(songs))
    show_settings.set_moods("show", moods)


# The dances that are not Dancing (Llano BL #12339): a show song tied to one of these plays with the
# moving heads moving gently by themselves (his change, 2026-11-14: the heads move on their own in the
# dances). The last dance counts as Dancing.
GENTLE_MOMENTS = ("first-dance", "father-daughter", "mother-son")


def gentle_keys(songs: list[ShowSong]) -> set:
    """Every key the show's first dance and parent dances could play under, for
    show_settings.set_show_looks(gentle=...). A song that also plays as a plain Dancing song plays as Dancing."""
    from .song_match import candidates  # noqa: PLC0415
    gentle, kept = set(), set()
    for s in songs:
        keys = set(candidates(s.artist, s.title))
        if s.moment in GENTLE_MOMENTS:
            gentle.update(keys)
        elif not is_soft(s.part, s.moment):
            kept.update(keys)
    return gentle - kept


def soft_keys(songs: list[ShowSong]) -> set:
    """Every key the show's cocktail-hour and dinner songs could play under (song_match.candidates),
    for show_settings.set_show_looks(soft=...). A song that is also a moment's song is left out."""
    from .song_match import candidates  # noqa: PLC0415
    soft, kept = set(), set()
    for s in songs:
        keys = set(candidates(s.artist, s.title))
        (soft if is_soft(s.part, s.moment) else kept).update(keys)
    return soft - kept if any(s.moment for s in songs) else soft


# The set's drops (BL #12518, his 11-17 notes): "it can't be the same thing on every song"; the blue
# drop saved for one or two special moments; no two neighbouring dance songs share a drop, and no drop
# pattern used more than twice. A song's drop is its drop cue (settings_contract DROP_STYLES; none =
# "classic"); its PATTERN is the style with its colors, so a slam in red and a slam in teal are two.
MAX_PATTERN_USES = 2
MAX_CLASSIC = 2


def drop_plan(show: dict, cues: Optional[dict]) -> list[dict]:
    """The show's dance songs in order with the drop each plays: [{i, artist, title, style, colors}].
    Soft songs and the first and parent dances have no drops and are left out."""
    from . import cues as cues_mod  # noqa: PLC0415
    out = []
    for i, s in enumerate(show.get("songs") or []):
        part, moment = s.get("part") or "", s.get("moment") or ""
        if is_soft(part, moment) or moment in GENTLE_MOMENTS or (part and part != "dancing"):
            continue
        cs = tuple((cues or {}).get(contract.track_key(s.get("artist") or "", s.get("title") or "")) or ())
        style, c1, c2 = cues_mod.drop_at(cs, None)
        out.append({"i": i, "artist": s.get("artist") or "", "title": s.get("title") or "", "style": style,
                    "colors": (c1, c2) if style != "classic" else ("", "")})
    return out


def drop_repeats(plan: list[dict]) -> list[str]:
    """What breaks the set's drop rules, one line each ([] = none): two neighbouring dance songs with the
    same style, a pattern (style and colors) on more than MAX_PATTERN_USES songs, or the classic blue drop on
    more than MAX_CLASSIC."""
    out = []
    for a, b in zip(plan, plan[1:]):
        if a["style"] == b["style"]:
            out.append(f"{a['title']} and {b['title']} are neighbours with the same drop ({a['style']})")
    uses: dict = {}
    for p in plan:
        uses.setdefault((p["style"], p["colors"]), []).append(p["title"])
    for (style, colors), titles in uses.items():
        if style == "classic":
            if len(titles) > MAX_CLASSIC:
                out.append(f"the classic blue drop plays on {len(titles)} songs (at most {MAX_CLASSIC}): "
                           + ", ".join(titles))
        elif len(titles) > MAX_PATTERN_USES:
            out.append(f"the {style} drop in {' and '.join(c for c in colors if c) or 'its colors'} plays on "
                       f"{len(titles)} songs (at most {MAX_PATTERN_USES}): " + ", ".join(titles))
    return out


def m3u(songs: list[ShowSong], lib: MixxxLibrary) -> str:
    """The show's order as an .m3u8 playlist Mixxx imports (Playlists, Import Playlist). Songs with
    no file on this laptop are listed as comments so the order still reads."""
    lines = ["#EXTM3U"]
    part = None
    for s in songs:
        if s.part and s.part != part:   # a comment Mixxx skips, so the file reads by part
            lines.append(f"# --- {PART_TITLES.get(s.part, s.part)} ---")
        part = s.part or part
        if s.moment:
            lines.append(f"# {MOMENT_TITLES.get(s.moment, s.moment)}")
        lt = track(lib, s.track_id) if s.track_id else None
        label = " - ".join(p for p in (s.artist, s.title) if p)
        if lt and lt.location:
            lines += [f"#EXTINF:{int(s.secs or -1)},{label}", str(lt.location)]
        else:
            lines.append(f"# not on this laptop: {label}")
    return "\n".join(lines) + "\n"


# --- playing a show in the window -------------------------------------------------------------------

class ShowFeed:
    """Plays a show front to back for the lights, the way demo_songs.SongFeed plays one song: the
    window plays each song (its file, or a silent clock for a song not on this laptop) and reports
    {song: "<index>", t, playing}; each song gets its real beat grid and sections, and the look the
    show gives it. With no window reporting, the show runs on its own clock, song after song."""

    def __init__(self, show, songs: list[ShowSong], clock=None):
        self.show, self.songs, self.clock = show, songs, clock
        self.index = -1
        self.feed = None
        self.t0: Optional[float] = None

    def _song_at(self, now: float) -> int:
        rep = self.clock.song if self.clock else ""
        if rep.isdigit() and int(rep) < len(self.songs) and self.clock.position(rep, now) is not None:
            return int(rep)
        if self.index >= 0 and self.feed and self.feed.anchor:   # the window went quiet: stay on its song
            return self.index
        i, t = 0, now - self.t0   # no window at all: walk the show on our own clock
        for i, s in enumerate(self.songs):
            length = s.secs or DEFAULT_SECS
            if t < length:
                break
            t -= length
        return i

    def _start(self, i: int, now: float) -> None:
        s = self.songs[i]
        bpm = s.bpm or DEFAULT_BPM
        to_beat = lambda sec: int(round((sec - s.first_beat_s) * bpm / 60))  # noqa: E731
        script = ShowScript([Section(x["kind"], to_beat(x["start"]), max(to_beat(x["start"]) + 1, to_beat(x["end"])),
                                     float(x.get("energy") or 0.5)) for x in s.sections])
        song = demo_songs.DemoSong(id=str(i), file="", title=s.title, artist=s.artist, feel="", license="",
                                   license_url="", source="", credit="", bpm=bpm, first_beat_s=s.first_beat_s,
                                   duration_s=s.secs or DEFAULT_SECS, sections=[asdict(x) for x in script.sections])
        self.feed, self.index = _SectionFeed(self.show, song, self.clock), i
        print(f"Show: song {i + 1} of {len(self.songs)}, {s.artist + ' - ' if s.artist else ''}{s.title} "
              f"({s.look or 'house'} look, {s.source} sections)")

    def __call__(self, now: float) -> None:
        if self.t0 is None:
            self.t0 = now
        i = self._song_at(now)
        if i != self.index:
            self._start(i, now)
        self.feed(now)


class _SectionFeed(demo_songs.SongFeed):
    """demo_songs.SongFeed for a show song: loudness from the section energy (a show song has no
    per-bar loudness list), and on its own clock it plays once from the top instead of looping."""

    def song_time(self, now: float):
        pos = self.clock.position(self.song.id, now) if self.clock else None
        if pos is None and not self.anchor:   # no window: seconds since this song began
            return max(0.0, now - self.t0), True
        return super().song_time(now)

    def level(self, t: float, beats: float) -> float:
        sec, _ = self.script.at(beats)
        return 0.15 + 0.7 * (sec.energy if sec else 0.5) + 0.1 * math.exp(-4 * (beats % 1))
