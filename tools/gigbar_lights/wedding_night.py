"""Build the wedding night: from a folder of songs and the night's plan to one finished folder he
plays from (Llano PM #23179).

What lands in the output folder:

  Songs/<part>/Artist - Title.flac      every song as a ready-to-play cut (set_cuts): level-matched,
                                        clean start, clean leave
  Songs/Moments/...                     the songs for the moments (entrance, first dance, ...)
  Holds/HOLD - Toasts ... .flac         an hour of silence per live moment
  1 - Cocktail hour.m3u8, 2 - ...       the playlists he starts, in night order (run_of_show)
  Run of show.html                      the one page he prints
  Listen first - Dancing handoffs.mp3   every Dancing handoff, 16 seconds each, to hear before the night
  Backup/1 - Cocktail hour.mp3 ...      each stretch of music as one file, and each moment's song, in
                                        night order, for a phone if the laptop dies
  night.json                            what was built and why (each cut's reason, the checks, and
                                        every file this build wrote: the next build removes only those),
                                        and each cut's source file and measure: the next build redoes
                                        only songs whose file or cut changed (Llano BL #12342)

It reads the originals and never changes them. Two passes over the songs: the first measures each
one (so one level can be set for the whole night), the second writes the cuts; a song is in memory
only while it is being worked on. A damaged song is named in the report and left out of the
playlists as a visible gap, never silently skipped. A sound file that is fine but cannot be cut here
(an iTunes .m4a, an hour-long mix) is copied in and played as it is, with a heads-up. The preview
and the backups come last and can never fail the night: it is whole, and saved, before they start.

Also here: check_mixxx, which reads Mixxx's own settings file (never writes it) and says whether
Auto DJ is set the way these files expect.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import unicodedata
import zlib
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Optional

from . import run_of_show as ros
from . import set_cuts as sc
from . import settings_contract as contract
from .song_match import norm

PART_DIRS = {"cocktail": "1 - Cocktail hour", "dinner": "2 - Dinner", "dancing": "3 - Dancing",
             "background": "Background",    # quiet music under the toasts and the cake (BL #12360)
             "toasts-background": "Toasts background"}   # his instrumentals under the toasts (2026-11-14)
HOLD_ARTIST = "Llano hold"
OUT_PARENT = "Llano Lights shows"      # where the app builds nights: never read back as a source of songs
SHEET_NAME = "Run of show.html"        # the run sheet, in the night's folder: the page he prints
MAX_PATH = 240                         # Windows refuses a path past 260 characters; stay clear of it
# The cut rules' version, kept with each cut in night.json: a build under new rules measures every song
# again instead of keeping a cut made by the old ones (2: where the dancing starts and stops, PM #23751).
# 3: a set's opening song keeps its intro (PM #23864).
CUT_RULES = 3
MP3_RATES = (8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000)
BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# The lights' looks for the moments, kept as saved styles: style name -> the moments.py key it is
# made from. A hold or a moment's song is filed under its style by name (settings "songs"), the way
# any song is tied to a style, so the Live show plays that look when Mixxx plays it.
MOMENT_LOOKS = {"grand-entrance": "entrance", "first-dance": "first-dance", "toast": "toast",
                "parent-dance": "father-daughter", "cake-cutting": "cake", "last-dance": "last-dance"}
# run_of_show look key -> the style ("" = the show's own look for that song, or the house show)
LOOK_FOR = {"entrance": "grand-entrance", "first-dance": "first-dance", "toast": "toast",
            "father-daughter": "parent-dance", "cake": "cake-cutting", "last-dance": "last-dance", "": ""}


class NightBusy(Exception):
    """A file from the last build is open in another program (Mixxx has it loaded), so it cannot be
    replaced. The message says what to do, in his words."""


class NeedsPart(Exception):
    """Songs with no part of the night (Llano BL #12338): a blank part used to build as Dancing, so his
    dinner songs were cut and filed as dance songs. The night waits until each one is placed.
    `songs` names them; the message says what to do, in his words."""

    def __init__(self, songs: list):
        self.songs = list(songs)
        super().__init__(needs_part_words(self.songs))


def needs_part_words(labels: list) -> str:
    n = len(labels)
    named = ", ".join(labels[:8]) + (f" and {n - 8} more" if n > 8 else "")
    return (f"Build waits: {n} song{' has' if n == 1 else 's have'} no part of the night yet ({named}). "
            "Pick each one's part under Needs a part in Review, or add their folder again in step 1.")


def needs_part(songs: list) -> list:
    """The songs that would be built with no part of the night: no part, and no dance or moment to play
    at instead. A song tied to a moment plays at that moment and needs no part."""
    return [_label(s) for s in songs
            if isinstance(s, dict) and s.get("part") not in contract.SHOW_PARTS and not s.get("moment")]


def _busy_words(path) -> str:
    return (f"Close Mixxx, then build again: {Path(path).name} is open in it, so the new version "
            "could not be saved.")


RESERVED = re.compile(r"(?i)con|prn|aux|nul|com[0-9]|lpt[0-9]|conin\$|conout\$")


def safe_name(text: str) -> str:
    """A file name Windows accepts, from an artist and title."""
    out = BAD_CHARS.sub(" ", str(text or "")).strip().rstrip(". ")
    out = re.sub(r"\s+", " ", out)[:120] or "song"
    # Windows refuses these names whatever the extension ("Con.flac", "Aux.m3u8"): a title-only song
    # named one would fail the build with a bare "could not be written" (whole-app audit, 2026-11-12)
    head, dot, tail = out.partition(".")
    return f"{head.strip()} (song){dot}{tail}" if RESERVED.fullmatch(head.strip()) else out


def fit_name(name: str, folder, suffix: str) -> str:
    """`name` shortened so folder/name+suffix stays inside MAX_PATH (never under 20 characters)."""
    room = MAX_PATH - len(str(folder)) - 1 - len(suffix)
    return name[:max(20, room)].rstrip(". ") or "song"


def name_key(artist: str, title: str) -> str:
    """The key a song and its file are matched by. It is the lights' own track key with the words
    that never tell two songs apart taken out; that key keeps only a-z and 0-9, so a name with other
    letters also carries a short mark made from the letters it would lose. Two Cyrillic titles by one
    artist are then two songs, not one. (An accented name still has to be written the same way in the
    file name and in the show: "Beyoncé" and "Beyonce" are two keys, as they always were.)"""
    base = norm(contract.track_key(artist, title))
    text = unicodedata.normalize("NFKC", f"{artist or ''} {title or ''}").casefold()
    lost = "".join(ch for ch in text if ch.isalnum() and not ("a" <= ch <= "z" or "0" <= ch <= "9"))
    if not lost and not base:
        lost = "".join(text.split())          # nothing but punctuation: the name itself is the mark
    if not lost:
        return base
    return f"{base}-u{zlib.crc32(lost.encode('utf-8')):08x}".lstrip("-")


def key_of(song: dict) -> str:
    return name_key(song.get("artist", ""), song.get("title", ""))


def _label(song: dict) -> str:
    return f"{song.get('artist', '')} - {song.get('title', '')}".strip(" -")


def index_folder(folder, exclude=()) -> dict:
    """{song key: file} for every audio file under a folder, named "Artist - Title.ext" (a file named
    by its title alone is also found by the artist in its tag, the way the Shows page names it).
    Never from a folder a night was built into (OUT_PARENT, or any of `exclude`): a cut must not be
    read back as a song."""
    from .song_folder import AUDIO, _name, id3_tags  # noqa: PLC0415

    out: dict = {}
    root = Path(folder).absolute()
    if not root.is_dir():
        return out
    skip = [Path(x) for x in exclude]
    for p in sorted(root.rglob("*")):
        if p.suffix.lower() not in AUDIO or not p.is_file():
            continue
        # anywhere on its path, so the box pointed AT that folder (or at one night inside it) finds no songs either
        if any(part.casefold() == OUT_PARENT.casefold() for part in p.parts[:-1]):
            continue
        if any(x in p.parents for x in skip):
            continue
        artist, title = _name(p)
        if not artist and p.suffix.lower() == ".mp3":
            tagged = id3_tags(p).get("artist", "")
            if tagged:
                out.setdefault(name_key(tagged, title), p)
        out.setdefault(name_key(artist, title), p)
    return out


def _is_line_dance(song: dict) -> bool:
    from . import song_canon  # noqa: PLC0415

    k = song_canon.lookup(song.get("artist", ""), song.get("title", ""))
    return bool(k and "line" in k.tags)


def _point(v) -> Optional[float]:
    """His Starts at / Ends at from the show (seconds into the original), or None for Llano's."""
    if v is None or v == "" or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, 3) if 0.0 <= f < 24 * 3600 else None


def cut_args(song: dict, part: str, keep_whole=(), opens: bool = False) -> dict:
    """How a song is cut (set_cuts.plan's arguments), the same for the build and for Review's Starts at
    and Ends at (song_points): a moment's song, a song whose intro he kept and a line dance keep their
    music whole unless he sets a point; a dance song starts and stops where the dancing does, except the
    song that opens a set (`opens`: the first of cocktail hour, dinner or a dancing set), which plays
    from its first note (PM #23864)."""
    return {"part": "dinner" if part in ("cocktail", "dinner", "moment", *ros.BEDS) else "dancing",
            "whole": part == "moment" or key_of(song) in (keep_whole or ()) or _is_line_dance(song),
            "start_at_s": _point(song.get("start_at")), "end_at_s": _point(song.get("end_at")),
            "keep_intro": bool(opens) and part in contract.SHOW_PARTS}


def opening_keys(parts: dict, moment_songs: Optional[dict] = None, *, order: Optional[tuple] = None,
                 skip: Optional[set] = None, files: Optional[dict] = None) -> set:
    """The song keys that open a set tonight: the first song of cocktail hour, of dinner and of each
    dancing set, as run_of_show.plan places them (a song with no file is not played, so the next one
    opens). A later dancing set's split leans on song lengths, read here from the show (the cut's own
    length can move a split by a song; the first dancing set's opener never moves)."""
    def has(s) -> bool:
        return files is None or bool(files.get(key_of(s)))
    playing = {p: [s for s in lst if has(s)] for p, lst in parts.items()}
    steps = ros.plan(playing, {mk: s for mk, s in (moment_songs or {}).items() if has(s)}, order=order, skip=skip)
    return {key_of(st.songs[0]) for st in steps
            if st.kind == "music" and st.key in contract.SHOW_PARTS and st.songs}


def song_points(song: dict, part: str, path, opens: bool = False) -> dict:
    """Review's Starts at and Ends at for one song, read from its file: what the build would do with no
    point of his (start_s / end_s, as where the music is at full volume and where it has gone), and
    Llano's reading of where the dancing starts and stops (suggest_*: the same for a dance song, kept
    as a suggestion for a line dance and for a set's opening song, `opens`). Raises what set_cuts.read
    raises."""
    a = cut_args(song, part, opens=opens)
    x, rate = sc.read(path)
    c = sc.plan(x, rate, a["part"], whole=a["whole"], keep_intro=a["keep_intro"])
    del x
    return {"key": key_of(song), "source_s": c.source_s, "start_s": round(c.start_s + c.fade_in_s, 3),
            "end_s": c.end_s, "suggest_start_s": c.suggest_start_s, "suggest_end_s": c.suggest_end_s,
            "intro_s": c.intro_s, "outro_s": c.outro_s, "bar_s": c.bar_s, "follows": not a["whole"] and a["part"] == "dancing",
            "dancing": a["part"] == "dancing", "long_intro": c.intro_s > sc.LONG_INTRO_S,
            "long_outro": c.outro_s > sc.LONG_OUTRO_S, "opens": a["keep_intro"]}


class PointsCache:
    """song_points, read once per song file: a song is measured again only when its file, its part or
    the cut rules change. Kept in one small JSON file beside the settings; a file that cannot be read
    or written only means measuring again."""

    MAX = 600

    def __init__(self, path):
        self.path = Path(path)
        try:
            got = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            got = {}
        self.rows: dict = got if isinstance(got, dict) else {}

    def get(self, song: dict, part: str, path, opens: bool = False) -> dict:
        a = cut_args(song, part, opens=opens)
        sig = json.dumps([_source_sig(path), a["part"], a["whole"], a["keep_intro"], CUT_RULES])
        hit = self.rows.get(sig)
        if isinstance(hit, dict) and hit.get("key") == key_of(song):
            return hit
        got = song_points(song, part, path, opens)
        self.rows[sig] = got
        while len(self.rows) > self.MAX:            # the oldest go first
            self.rows.pop(next(iter(self.rows)))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".part")
            tmp.write_text(json.dumps(self.rows), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as e:
            print(f"Song points not kept ({type(e).__name__}: {e}); they are measured again next time")
        return got


def _in_use(out: Path):
    """The first file of the last build that another program holds open (Windows refuses to open it
    for writing), or None. A plain check before anything is written: best effort, the build also
    catches the refusal where it happens."""
    for sub in ("Songs", "Holds"):
        for p in sorted((out / sub).rglob("*")) if (out / sub).is_dir() else ():
            if p.is_file():
                try:
                    with open(p, "ab"):
                        pass
                except PermissionError:
                    if os.access(p, os.W_OK):     # writable, yet refused: another program holds it
                        return p
                except OSError:
                    continue
    return None


def _source_sig(path) -> list:
    """What a song file is, for the next build to tell whether it changed: its path, size and time."""
    p = Path(path)
    st = p.stat()
    return [str(p.resolve()), st.st_size, st.st_mtime_ns]


def _last_reuse(out: Path) -> dict:
    """The last build's cuts that a build may keep (night.json "reuse"): {song key: {sig, args, cut, file,
    album}}. Nothing when the last build kept none, or its night.json cannot be read."""
    try:
        old = json.loads((out / "night.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    got = old.get("reuse")
    return got if isinstance(got, dict) else {}


def _last_files(out: Path) -> set:
    """The files the last build here wrote (from its night.json), as paths relative to the folder.
    Only names a build writes are ever returned: under Songs, Holds or Backup, or the preview."""
    try:
        old = json.loads((out / "night.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    names = old.get("files")
    if not isinstance(names, list):      # a build from before the list was kept
        names = [c.get("file", "") for c in old.get("cuts", []) if isinstance(c, dict)] \
            + list(old.get("backups") or []) + [old.get("handoffs") or ""]
    keep = set()
    for n in names:
        parts = Path(str(n)).parts
        if not n or ".." in parts or Path(str(n)).is_absolute():
            continue
        if parts[0] in ("Songs", "Holds", "Backup") or (len(parts) == 1 and parts[0].startswith("Listen first - ")):
            keep.add(Path(str(n)).as_posix())
    return keep


def plain_error(e: BaseException) -> str:
    """Why a build stopped, in words for the person at the laptop (the log keeps the technical ones)."""
    import errno  # noqa: PLC0415

    if isinstance(e, (NightBusy, NeedsPart)):
        return str(e)
    if isinstance(e, MemoryError):
        return "This laptop ran out of memory. Close other programs and build again."
    if isinstance(e, OSError) and e.errno == errno.ENOSPC:
        return "The disk is full. Free some space and build again."
    if isinstance(e, PermissionError):
        return "Windows would not let a file be written. Close Mixxx and any open window on that folder, then build again."
    if isinstance(e, OSError):
        return "A file could not be written. Build again; if it happens twice, the log has the details for Llano."
    return "Something went wrong that the build did not expect. Build again; if it happens twice, the log has the details for Llano."


def _copy(src: Path, dest: Path) -> None:
    """Copy a song that plays as it is into the night's folder (through a temp name, like a cut)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and src.resolve() == dest.resolve():
        return
    tmp = dest.with_name(dest.name + ".part")
    try:
        shutil.copyfile(src, tmp)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    sc._into_place(tmp, dest)


def arrange(songs: list[dict], moment_songs: Optional[dict] = None, *, order: Optional[tuple] = None,
            skip: Optional[set] = None) -> dict:
    """Where each of the show's songs plays tonight, before any file is read: {"parts": {part or bed:
    [songs in order]}, "moment_songs": {moment key: song}, "off": the moments not happening,
    "unplaced": labels of Moments-folder songs tied to no dance, "need": labels of songs with no part
    of the night, "twins": [(first, second)] songs that are one song to the lights}.

    build() cuts and plays exactly this; Tonight.from_show lists it on the Live screen before the
    night is built (Llano BL #12387), so the two can never disagree about the order.
    """
    asked, off = tuple(order or ros.DEFAULT_ORDER), ros.skipped(skip)

    def happening(mk) -> bool:
        return mk in ros.MOMENTS and mk in asked and mk not in off

    moment_songs = {mk: s for mk, s in (moment_songs or {}).items() if happening(mk)}
    # The last dance plays just before the night's final sing-along (set arranger 1.18.1), but the
    # last dance has its own step after all the dancing, so the sing-along the show puts after it
    # stayed in the dancing (and its repeat) and the last dance ended the night (whole-app audit,
    # 2026-11-12). With no closing song of his own, the last song the show orders after the last
    # dance is the closing song.
    if happening("last-dance") and "close" in asked and not moment_songs.get("close"):
        ld = moment_songs.get("last-dance") or next((s for s in songs if s.get("moment") == "last-dance"), None)
        at = next((i for i, s in enumerate(songs) if ld is not None and key_of(s) == key_of(ld)), None)
        after = [s for s in songs[at + 1:] if not s.get("moment") and s.get("part") == "dancing"] \
            if at is not None else []
        if after:
            moment_songs["close"] = after[-1]
            off = off - {"close"}
    parts: dict = {p: [] for p in (*contract.SHOW_PARTS, *ros.BEDS)}
    unplaced: list = []     # from a Moments folder, tied to no dance: not a dance-floor song either
    need: list = []         # no part of the night: the build waits for them (NeedsPart)
    for s in songs:
        mk = s.get("moment")
        if mk == "?":
            unplaced.append(_label(s))
        elif mk in ros.BEDS:      # he picked it to play quietly under the toasts (and the cake), in his order
            parts[mk].append(s)
        elif happening(mk) and key_of(moment_songs.get(mk, s)) == key_of(s):
            moment_songs[mk] = s
        elif s.get("part") in parts:    # no moment, a moment that is off tonight, or one he gave another song
            parts[s["part"]].append(s)
        else:    # no part of the night: it waits to be placed, never built as Dancing (BL #12338)
            need.append(_label(s))
    taken = {key_of(s) for s in moment_songs.values()}    # a moment's song plays at its moment only
    parts = {p: [s for s in lst if key_of(s) not in taken] for p, lst in parts.items()}
    if not parts[ros.BACKGROUND]:   # nothing picked for under the toasts and cake yet: his dinner songs again
        parts[ros.BACKGROUND] = list(parts["dinner"])
    # Two songs that are one song to the lights ("Dancing Queen" and "Dancing Queen (Remastered)")
    # share a cut. It plays once, where it first comes, and the pair is named so he can tell if
    # they were meant to be two.
    seen: dict = {}
    twins: list = []
    for p, lst in parts.items():
        keep = []
        for s in lst:
            first = seen.setdefault(key_of(s), s)
            if first is s:
                keep.append(s)
            elif _label(first) != _label(s):
                twins.append((_label(first), _label(s)))
        parts[p] = keep

    return {"parts": parts, "moment_songs": moment_songs, "off": off, "unplaced": unplaced, "need": need,
            "twins": twins}


def build(out_dir, songs: list[dict], files: dict, *, title: str = "Wedding",
          moment_songs: Optional[dict] = None, order: Optional[tuple] = None,
          times: Optional[dict] = None, skip: Optional[set] = None, leave: Optional[dict] = None,
          short: bool = False, extras: bool = True, keep_whole: Optional[set] = None, moods: Optional[dict] = None,
          on_progress: Optional[Callable[[str, int, int], None]] = None,
          on_built: Optional[Callable[[dict], None]] = None, patch: Optional[list] = None) -> dict:
    """Build the night into out_dir and return the report (also written as night.json).

    songs         the show's songs in play order: dicts with artist, title, part, and optionally
                  moment, look, energy. A song with a moment plays at that moment, not in its part;
                  when that moment is not happening, or has another song, it plays in its part.
    files         {song key (key_of): path} of the originals (index_folder of his wedding folder)
    moment_songs  {moment key: song dict} for moments beyond the four a show song can carry
                  (entrance, close, send-off ...), or his own pick for one of the four
    order, times, skip   as run_of_show.plan
    leave         {song key: seconds} his own leave points
    short         take the suggested short cut for every dancing song that has one
    moods         cocktail hour and dinner's moods, kept in night.json (Llano's suggestion when None)
    keep_whole    song keys whose soft intro must stay (a dancing cut otherwise starts where the
                  band comes in)
    extras        also write the handoff preview and the phone backups
    on_built      called with the report once the night is whole and saved, before the extras

    Raises NightBusy when a file of the last build is open in Mixxx and cannot be replaced, and
    NeedsPart, before anything is written, when a song that plays in a part has no part of the night.
    """
    t0 = time.time()
    out = Path(out_dir)
    leave = leave or {}
    say = on_progress or (lambda what, i, n: None)
    held = _in_use(out)
    if held:
        raise NightBusy(_busy_words(held))
    before = _last_files(out)
    last = _last_reuse(out)
    arranged = arrange(songs, moment_songs, order=order, skip=skip)
    if arranged["need"]:
        raise NeedsPart(arranged["need"])
    parts, moment_songs, off = arranged["parts"], arranged["moment_songs"], arranged["off"]
    unplaced, twins = arranged["unplaced"], arranged["twins"]

    # the songs that open a set play from their first note (PM #23864)
    openers = opening_keys(parts, moment_songs, order=order, skip=off, files=files)

    # every song that plays, once, with the part its cut is made for
    every: dict = {}
    for part, lst in parts.items():
        for s in lst:
            every.setdefault(key_of(s), (s, part))
    for mk, s in moment_songs.items():
        every.setdefault(key_of(s), (s, "moment"))

    # pass 1: measure. A song whose file and cut settings are the same as the last build's is not read
    # again: its measure comes from night.json (Get my songs, BL #12342: only what changed is redone).
    cuts: dict = {}
    sigs: dict = {}
    args_of: dict = {}
    measured_again: set = set()
    uncut: dict = {}        # fine files that cannot be cut here: they play as they are
    damaged, missing, silent = [], [], []
    todo = list(every.items())
    for i, (k, (s, part)) in enumerate(todo, 1):
        label = _label(s)
        say(f"Reading {label}", i, len(todo))
        path = files.get(k)
        if not path or not Path(path).is_file():
            missing.append(label)
            continue
        ca = cut_args(s, part, keep_whole, opens=k in openers)
        soft, whole = ca["part"], ca["whole"]
        args = [soft, round(float(leave.get(k) or 0), 3), bool(short and part == "dancing"), bool(whole),
                ca["start_at_s"], ca["end_at_s"], ca["keep_intro"], CUT_RULES]
        try:
            sigs[k] = _source_sig(path)
        except OSError:
            sigs[k] = None
        args_of[k] = args
        was = last.get(k) if isinstance(last.get(k), dict) else None
        if was and sigs[k] and was.get("sig") == sigs[k] and was.get("args") == args and isinstance(was.get("cut"), dict):
            try:
                cuts[k] = sc.Cut(**was["cut"])
                continue
            except TypeError:   # a night.json from another version: measure it again
                pass
        measured_again.add(k)
        try:
            x, rate = sc.read(path)
        except sc.CannotCut as e:
            uncut[k] = {"why": e.why, "secs": e.seconds or float(s.get("secs") or 0)}
            continue
        except sc.DamagedFile as e:
            damaged.append({"song": label, "why": str(e)})
            continue
        except MemoryError:     # too big for this laptop to hold: the same outcome as too long
            uncut[k] = {"why": "long", "secs": sc.media_seconds(path) or float(s.get("secs") or 0)}
            continue
        except Exception as e:  # noqa: BLE001 -- ok: one unreadable file is reported and the rest are built
            damaged.append({"song": label, "why": f"{Path(path).name} could not be read ({type(e).__name__}). Replace the file."})
            continue
        try:
            c = sc.plan(x, rate, soft, leave_at_s=float(leave.get(k) or 0),
                        short=short and part == "dancing", whole=whole,
                        start_at_s=ca["start_at_s"], end_at_s=ca["end_at_s"], keep_intro=ca["keep_intro"])
        except MemoryError:     # too big for this laptop to measure: "plays as it is" too
            c = None
        del x
        if c is None:
            uncut[k] = {"why": "long", "secs": sc.media_seconds(path) or float(s.get("secs") or 0)}
            continue
        if c.silent:
            silent.append(label)
            continue
        cuts[k] = c
    level = sc.set_level(list(cuts.values()))

    # pass 2: write the cuts, and copy in the songs that play as they are
    rel: dict = {}
    used: set = set()

    def place(sub: str, label: str, suffix: str) -> Path:
        folder = out / "Songs" / sub
        name = fit_name(safe_name(label), folder, suffix)
        dest, n = folder / (name + suffix), 2
        while str(dest).casefold() in used:      # two songs whose names differ only in what a file name drops
            dest = folder / (f"{name} ({n})" + suffix)
            n += 1
        used.add(str(dest).casefold())
        return dest

    doing = [t for t in todo if t[0] in cuts or t[0] in uncut]
    kept: set = set()
    for i, (k, (s, part)) in enumerate(doing, 1):
        label = _label(s)
        say(f"Writing {label}", i, len(doing))
        sub = "Moments" if part == "moment" else PART_DIRS[part]
        src = Path(files[k])
        dest = place(sub, label, ".flac" if k in cuts else src.suffix.lower())
        was = last.get(k) if isinstance(last.get(k), dict) else {}
        # the same cut at the same level, under the same name and album, is already on disk: keep it
        if (k in cuts and k not in measured_again and was.get("file") == dest.relative_to(out).as_posix()
                and was.get("album") == title and isinstance(was.get("cut"), dict)
                and was["cut"].get("gain_db") == cuts[k].gain_db and dest.is_file()
                and was.get("zero_s") == sc.source_zero_s(cuts[k])):   # a cut from before 1.35 has no tag
            rel[k] = dest.relative_to(out).as_posix()
            kept.add(k)
            continue
        try:
            if k in cuts:
                x, rate = sc.read(src)
                sc.write(dest, sc.render(x, rate, cuts[k]), rate, s.get("artist", ""), s.get("title", ""), title,
                         zero_s=sc.source_zero_s(cuts[k]))
                del x
            else:
                _copy(src, dest)
        except PermissionError:
            raise NightBusy(_busy_words(dest)) from None
        rel[k] = dest.relative_to(out).as_posix()

    # songs as the plan sees them: only what can play, with the time each really takes
    def secs_of(k) -> float:
        return cuts[k].plays_s if k in cuts else uncut[k]["secs"]

    def playable(lst):
        return [{**s, "plays_s": secs_of(key_of(s)), "secs": secs_of(key_of(s))} for s in lst if key_of(s) in rel]

    steps = ros.plan({p: playable(lst) for p, lst in parts.items()},
                     {mk: playable([s])[0] for mk, s in moment_songs.items() if key_of(s) in rel},
                     order=order, times=times, skip=off)

    # holds
    hold_rel: dict = {}
    holds = [s for s in steps if s.kind == "hold"]
    for n, st in enumerate(holds):
        t = ros.hold_title(st.name)
        dest = out / "Holds" / (safe_name(f"{HOLD_ARTIST} - {t}") + ".flac")   # Mixxx reads "Artist - Title" names too
        say(f"Writing the hold for {st.name}", n + 1, len(holds))
        try:
            sc.hold(dest, n, t)
        except PermissionError:
            raise NightBusy(_busy_words(dest)) from None
        hold_rel[t] = dest.relative_to(out).as_posix()

    def path_of(row):
        if row["kind"] == "hold":
            return hold_rel.get(row["title"])
        return rel.get(key_of(row))

    pls = ros.playlists(steps)
    for old in out.glob("*.m3u8"):         # a rebuilt night must not leave last time's playlists beside it
        old.unlink()
    for pl in pls:
        (out / pl.file).write_text(ros.m3u8(pl, path_of), encoding="utf-8")

    problems = [{"level": "problem", "text": f"{m} has no file in the folder yet, so it is not in the playlists."}
                for m in missing]
    problems += [{"level": "problem", "text": d["why"]} for d in damaged]
    problems += [{"level": "problem", "text": f"{m} is silent: there is nothing in the file to hear, so it is "
                                              "not in the playlists. Replace the file."} for m in silent]
    heads = []
    for k, u in uncut.items():
        s = every[k][0]
        name = Path(files[k]).name
        if u["why"] == "type":
            heads.append(f"{name} is a kind of file this laptop cannot cut (the kind iTunes sells), so it plays as it "
                         "is: not level-matched, so it may play louder or quieter than the other songs, and its "
                         "first second fades in. Save it as MP3 or FLAC and build again for a clean start.")
        else:
            heads.append(f"{_label(s)} is {u['secs'] / 60:.0f} minutes long, too long to cut here, so it plays as it "
                         "is: not level-matched, so it may play louder or quieter than the other songs.")
    for name in unplaced:
        heads.append(f"{name} is in the Moments folder but is not tied to a dance, so it is not in the playlists. "
                     "Type it beside its moment and build again.")
    for one, two in twins:
        heads.append(f"{two} is the same song as {one} to Llano Lights (the names differ only in words like "
                     "Remastered), so it plays once. If they are two different songs, rename one file and its song.")
    for k, c in cuts.items():
        if c.under_db >= 1.5:
            heads.append(f"{_label(every[k][0])} is a quiet recording that cannot be turned up to match: it plays "
                         f"about {c.under_db:.0f} dB quieter than the other songs.")
    checks = sorted(problems + ros.checks(steps) + [{"level": "heads-up", "text": h} for h in heads],
                    key=lambda c: c["level"] != "problem")
    (out / SHEET_NAME).write_text(ros.sheet_html(title, steps, checks, patch=patch), encoding="utf-8")

    written = set(rel.values()) | set(hold_rel.values())
    report = {
        "title": title, "built": time.strftime("%Y-%m-%d %H:%M"), "seconds": round(time.time() - t0, 1),
        "folder": str(out), "level_lufs": level, "transition_s": sc.TRANSITION_S,
        "playlists": [{"file": pl.file, "name": pl.name, "rows": len(pl.rows), "music_min": round(pl.music_s / 60, 1)}
                      for pl in pls],
        "moods": contract.moods(moods),   # cocktail hour and dinner's moods (BL #12340): the Live show plays them
        "steps": [s.public() for s in steps], "checks": checks, "damaged": damaged, "missing": missing,
        "silent": silent,
        "cuts": [{"key": k, "artist": every[k][0].get("artist", ""), "title": every[k][0].get("title", ""),
                  "part": every[k][1], "file": rel.get(k, ""), **c.public(),
                  # what Review and the list for him say: seconds of the original not played at each end
                  "cut_start_s": round(c.start_s, 1), "cut_end_s": round(max(0.0, c.source_s - c.end_s), 1),
                  "long_intro": c.intro_s > sc.LONG_INTRO_S, "long_outro": c.outro_s > sc.LONG_OUTRO_S,
                  "opens": k in openers}
                 for k, c in cuts.items()],
        "uncut": [{"key": k, "artist": every[k][0].get("artist", ""), "title": every[k][0].get("title", ""),
                   "part": every[k][1], "file": rel.get(k, ""), **u} for k, u in uncut.items()],
        "show_songs": [{**s, "look": LOOK_FOR.get(s["look"], s["look"])} for s in ros.show_songs(steps)],
        "moment_looks": MOMENT_LOOKS, "handoffs": "", "backups": [], "files": sorted(written),
        "redone": len([k for k in rel if k in cuts and k not in kept]), "kept": len(kept),
        "reuse": {k: {"sig": sigs.get(k), "args": args_of.get(k), "cut": asdict(c), "file": rel[k], "album": title,
                      "zero_s": sc.source_zero_s(c)}
                  for k, c in cuts.items() if k in rel and sigs.get(k)},
    }

    def save() -> None:
        (out / "night.json").write_text(json.dumps(report, indent=1), encoding="utf-8")

    # The night is whole here. It is saved, and its looks filed, before the preview and the backups
    # start: those are the heavy part, and nothing that goes wrong in them may cost him the night.
    _clear(out, _stale(before, written) - {f for f in before if f.startswith("Backup/") or "/" not in f})
    save()
    if on_built:
        on_built(report)
    if extras:
        made = {"handoffs": "", "backups": [], "left_out": []}    # filled as it goes, so a part-way stop is still listed
        try:
            _extras(out, steps, rel, say, set(uncut), made)
        except Exception as e:  # noqa: BLE001 -- ok: said as a heads-up; the night itself is built
            print(f"Wedding night extras failed: {type(e).__name__}: {e}")
            checks.append({"level": "heads-up",
                           "text": "The phone backup and the handoff preview were not finished. " + plain_error(e)
                                   + " The night itself is built and complete."})
        if made.get("left_out"):
            names = ", ".join(dict.fromkeys(made["left_out"]))
            checks.append({"level": "heads-up", "text": f"The phone backup leaves out {names}: this laptop cannot "
                                                        "read that file. Keep the original on the phone too."})
        report["handoffs"], report["backups"] = made["handoffs"], made["backups"]
        written |= set(made["backups"]) | ({made["handoffs"]} if made["handoffs"] else set())
    _clear(out, _stale(before, written))
    report["files"], report["seconds"] = sorted(written), round(time.time() - t0, 1)
    save()
    return report


def _stale(before: set, written: set) -> set:
    """Files the last build wrote that this one did not. Names are compared without regard to
    capitals, as Windows' disk compares them: a song retyped "Ed Sheeran" after "ed sheeran" is the
    same file there, and removing the old spelling would remove the cut just written."""
    now = {w.casefold() for w in written}
    return {f for f in before if f.casefold() not in now}


def _clear(out: Path, names) -> None:
    """Remove files a previous build wrote that this one did not (a song dropped from the show, an
    old backup), and any folder that leaves empty. Never anything a build did not write."""
    for n in sorted(names):
        p = out / n
        try:
            p.unlink()
        except OSError:
            continue
        try:
            p.parent.rmdir()            # only succeeds when the folder is empty
        except OSError:
            pass


def looks_ops(report: dict, doc: dict) -> tuple[list, list]:
    """(settings changes, notes) that give the night's holds and moment songs their looks: each
    moment style saved once (a style he already has under that name is left alone), and every hold
    and moment song filed under its style. Notes say, in plain words, what could not be done: no
    room for a style, or for a song's look (the settings keep contract.MAX_SONGS of them)."""
    from . import moments  # noqa: PLC0415

    ops, notes = [], []
    have = dict(doc.get("styles") or {})
    filed = dict(doc.get("songs") or {})
    room = contract.MAX_STYLES - len(have)
    unfiled = []
    for s in report.get("show_songs", []):
        style = s.get("look", "")
        is_moment = s.get("artist") == HOLD_ARTIST or s.get("moment_key")
        if style not in MOMENT_LOOKS or not is_moment:
            continue
        if style not in have:
            if room <= 0:
                note = (f"No room to save the {style} look: Llano Lights keeps {contract.MAX_STYLES} styles. "
                        "Delete one you don't use and build again.")
                if note not in notes:
                    notes.append(note)
                continue
            have[style] = True
            room -= 1
            ops.append({"path": f"styles.{style}", "value": moments.style(MOMENT_LOOKS[style])})
        key = contract.track_key(s.get("artist", ""), s.get("title", ""))
        if key and filed.get(key) != style:
            if key not in filed and len(filed) >= contract.MAX_SONGS:
                unfiled.append(s.get("title", "") if s.get("artist") != HOLD_ARTIST else s.get("why", "")[15:] or "a hold")
                continue
            filed[key] = style
            ops.append({"path": f"songs.{key}", "value": style})
    if unfiled:
        notes.append(f"Llano Lights remembers a look for {contract.MAX_SONGS} songs and that list is full, so the "
                     f"lights will not change for: {', '.join(unfiled)}. Clear a few songs' looks and build again.")
    return ops, notes


def _music_runs(steps: list) -> list[tuple[str, list]]:
    """[(name, [song dicts])] for everything that plays, in night order: each stretch of music, and
    each moment's song on its own (the first dance has to be on the phone too if the laptop dies)."""
    return [(s.name, s.songs) for s in steps if s.kind in ("music", "song") and s.songs]


def _write_stream(path: Path, pieces, rate: int) -> Optional[Path]:
    """Write audio that arrives a piece at a time: MP3 when this build of the audio library can write
    it (a phone plays it anywhere), else FLAC. Through a temp name; None when there was nothing."""
    import soundfile  # noqa: PLC0415

    path.parent.mkdir(parents=True, exist_ok=True)
    mp3 = "MP3" in soundfile.available_formats()
    dest = path.with_name(path.name + (".mp3" if mp3 else ".flac"))
    tmp = dest.with_name(dest.name + ".part")
    frames = 0
    try:
        with soundfile.SoundFile(str(tmp), "w", samplerate=rate, channels=2, format="MP3" if mp3 else "FLAC",
                                 subtype="MPEG_LAYER_III" if mp3 else "PCM_16") as f:
            for y in pieces:
                if len(y):
                    f.write(y)
                    frames += len(y)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if not frames:
        tmp.unlink(missing_ok=True)
        return None
    sc._into_place(tmp, dest)
    return dest


def _extras(out: Path, steps: list, rel: dict, say, uncut: Optional[set] = None, made: Optional[dict] = None) -> dict:
    """The handoff preview for the dancing, and one backup file per stretch of music. One cut is in
    memory at a time (a set of twenty songs is over a gigabyte held all at once); a cut at another
    sample rate is brought to its run's; a song that plays as it is cannot be read here and is left
    out by name."""
    import numpy as np  # noqa: PLC0415
    import soundfile  # noqa: PLC0415

    uncut = uncut or set()
    if made is None:
        made = {"handoffs": "", "backups": [], "left_out": []}
    runs = [(name, [s for s in songs if key_of(s) in rel]) for name, songs in _music_runs(steps)]

    def rate_for(songs) -> int:
        for s in songs:
            if key_of(s) not in uncut:
                rate = int(soundfile.info(str(out / rel[key_of(s)])).samplerate)
                return rate if rate in MP3_RATES else 44100
        return 0

    def cut_at(s, rate_out: int):
        y, rate = sc.read(out / rel[key_of(s)])
        return sc.resample(y, rate, rate_out)

    # every Dancing handoff: 6 s of the old song, the 2 s handoff, 8 s of the new one, a short gap
    dance = [songs for name, songs in runs if name.startswith("Dancing")]
    rate_out = next((r for r in (rate_for(songs) for songs in dance) if r), 0)

    def clips():
        n = int(sc.TRANSITION_S * rate_out)
        for songs in dance:
            tail = None
            for s in songs:
                if key_of(s) in uncut:
                    tail = None
                    continue
                cur = cut_at(s, rate_out)
                if tail is not None:
                    yield sc.handoff(tail, cur[: n + int(8.0 * rate_out)], rate_out, before_s=6.0, after_s=8.0)[0]
                    yield np.zeros((int(0.7 * rate_out), 2), dtype=np.float32)
                tail = cur[-(n + int(6.0 * rate_out)):].copy()
                del cur

    if rate_out:
        say("Writing the handoff preview", 1, 1)
        p = _write_stream(out / "Listen first - Dancing handoffs", clips(), rate_out)
        made["handoffs"] = p.name if p else ""
    for n, (name, songs) in enumerate(runs, 1):
        say(f"Writing the backup for {name}", n, len(runs))
        rate_out = rate_for(songs)
        made["left_out"] += [_label(s) for s in songs if key_of(s) in uncut]
        loaders = [(lambda s=s, r=rate_out: cut_at(s, r)) for s in songs if key_of(s) not in uncut]
        if not rate_out or not loaders:
            continue
        p = _write_stream(out / "Backup" / safe_name(f"{n} - {name}"), sc.mixdown_pieces(loaders, rate_out), rate_out)
        if p:
            made["backups"].append(p.relative_to(out).as_posix())
    return made


# --- Mixxx's settings ----------------------------------------------------------------------------

def mixxx_cfg_path() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", "")) / "Mixxx" / "mixxx.cfg"
    if sys.platform == "darwin":
        from .macos import mixxx_settings_dir  # noqa: PLC0415
        return mixxx_settings_dir() / "mixxx.cfg"
    return Path.home() / ".mixxx" / "mixxx.cfg"


def read_cfg(path) -> dict:
    """Mixxx's settings as {"[Group]": {key: value}} (its own format: a group line, then "key value")."""
    out: dict = {}
    group = None
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            group = out.setdefault(line, {})
        elif group is not None and line:
            k, _, v = line.partition(" ")
            group[k] = v.strip()
    return out


MODES = {"0": "Full Intro + Outro", "1": "Fade At Outro Start", "2": "Full Track", "3": "Skip Silence"}


def check_mixxx(path=None) -> dict:
    """Is Mixxx's Auto DJ set the way the cut files expect? Read-only.

    {"found": bool, "ok": bool, "items": [{"ok", "name", "is", "want", "fix"}]}: the transition must
    be TRANSITION_S seconds (the cuts' lead and tail are half of it each); the mode should be Full
    Track (it ignores stray cue marks; the other modes behave the same on these files unless a cue
    was moved by hand); played songs must not be put back in the queue (a hold would come round
    again); random songs must be off."""
    path = Path(path) if path else mixxx_cfg_path()
    cfg = read_cfg(path)
    if not cfg:
        return {"found": False, "ok": False, "path": str(path), "items": [
            {"ok": False, "name": "Mixxx's settings", "is": "not found", "want": "Mixxx opened once on this laptop",
             "fix": "Open Mixxx once, close it, and check again."}]}
    adj = cfg.get("[Auto DJ]", {})
    items = []
    secs = adj.get("Transition", "10")          # Mixxx's own default when the key was never written
    want = f"{sc.TRANSITION_S:g}"
    try:
        good = float(secs) == sc.TRANSITION_S
    except ValueError:
        good = False
    items.append({"ok": good, "name": "Auto DJ transition", "is": f"{secs} seconds", "want": f"{want} seconds",
                  "fix": f"In Mixxx open Auto DJ and set the box marked sec. beside Full Track to {want}."})
    mode = adj.get("TransitionMode", "0")
    items.append({"ok": mode == "2", "name": "Auto DJ mode", "is": MODES.get(mode, mode), "want": "Full Track",
                  "fix": "In Mixxx open Auto DJ and pick Full Track in the mode menu."})
    requeue = adj.get("Requeue", "0")
    items.append({"ok": requeue == "0", "name": "Re-queue played songs", "is": "on" if requeue != "0" else "off",
                  "want": "off", "fix": "Mixxx Preferences, Auto DJ: untick Re-queue tracks after playback."})
    rnd = adj.get("EnableRandomQueue", "0")
    items.append({"ok": rnd == "0", "name": "Add random songs", "is": "on" if rnd != "0" else "off", "want": "off",
                  "fix": "Mixxx Preferences, Auto DJ: untick Enable random track addition."})
    rev = cfg.get("[Mixer Profile]", {}).get("xFaderReverse", "0")
    items.append({"ok": rev == "0", "name": "Crossfader direction", "is": "reversed" if rev != "0" else "normal",
                  "want": "normal", "fix": "Mixxx Preferences, Mixer: untick Reverse crossfader."})
    return {"found": True, "ok": all(i["ok"] for i in items), "path": str(path), "items": items}
