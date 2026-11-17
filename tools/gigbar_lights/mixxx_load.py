"""Load Mixxx: put a built night (wedding_night.build) into Mixxx's own library, then open Mixxx (BL #12343).

What it does, with Mixxx closed:
  1. copies mixxxdb.sqlite and mixxx.cfg into "Llano Lights backups" beside them, stamped
  2. adds every file the night's numbered playlists name to the library (track_locations + library);
     a file Mixxx already knows keeps its row, cue points and analysis
  3. adds the numbered playlists ("1 - Cocktail hour", ...) in the night's order
  4. fills the Auto DJ queue (Mixxx's hidden=1 playlist) with playlist 1, like
     "Add to Auto DJ Queue (replace)"
  5. sets Auto DJ to Full Track and the cuts' transition (2 seconds) in mixxx.cfg
  6. opens Mixxx

What it never does: write while Mixxx runs (Mixxx keeps its library in memory and would overwrite
or fight the change), write to a library whose schema it does not know (Mixxx 2.5 is revision 39;
anything else is refused untouched), change or remove his own tracks or playlists. It only adds,
and it replaces only playlists it made itself: their ids are kept in Mixxx's own settings table
(MARK_KEY), so the record travels with the library and its backups. A playlist of his with the same
name is never taken over; the load is refused and says which one.

Mixxx has no API for another program to do this; this writes the same rows Mixxx's own
PlaylistDAO/TrackDAO write (Mixxx 2.5 src/library/dao). Today's hand import stays the fallback.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from . import mixxx_db
from . import set_cuts as sc
from . import wedding_night

KNOWN_SCHEMAS = {"39": "Mixxx 2.5"}   # mixxx.schema.version -> the Mixxx that writes it
MARK_KEY = "llano_lights.playlists"   # settings row: {"<playlist name>": id} for the playlists Llano made
BACKUP_DIR = "Llano Lights backups"
AUTODJ_NAME = "Auto DJ"               # Mixxx AUTODJ_TABLE
HIDDEN_NONE, HIDDEN_AUTODJ = 0, 1     # Mixxx PlaylistDAO::HiddenType: 0 shown, 1 Auto DJ, 2 history
FULL_TRACK = "2"                      # [Auto DJ] TransitionMode: 2 = Full Track (wedding_night.MODES)
KEEP_BACKUPS = 10


class LoadRefused(Exception):
    """Nothing was written; the message says, in his words, what to do."""


def mixxx_running() -> Optional[bool]:
    """Is Mixxx running? None when it can't be told, which load() treats as a refusal."""
    if sys.platform == "win32":
        from .system_audio import _mixxx_process_running  # noqa: PLC0415 -- Windows only
        return _mixxx_process_running()
    try:
        r = subprocess.run(["pgrep", "-x", "mixxx"], capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.returncode == 0


def find_mixxx() -> Optional[str]:
    """Mixxx's program, where the installer puts it (or on PATH)."""
    if sys.platform == "win32":
        for root in (os.environ.get("ProgramW6432"), os.environ.get("ProgramFiles"),
                     os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
            if root:
                for sub in ("Mixxx", "Programs/Mixxx"):
                    exe = Path(root) / sub / "mixxx.exe"
                    if exe.is_file():
                        return str(exe)
        return shutil.which("mixxx.exe")
    return shutil.which("mixxx")


def open_mixxx() -> bool:
    exe = find_mixxx()
    if not exe:
        return False
    try:
        if sys.platform == "win32":
            os.startfile(exe)  # noqa: S606 -- Mixxx's own installed program
        else:
            subprocess.Popen([exe], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    return True


# --- the built night -------------------------------------------------------------------------------

def night_playlists(night_dir) -> list[tuple[str, list[Path]]]:
    """[(playlist name, [file, ...])] in night order, read from the night's own files."""
    night_dir = Path(night_dir)
    try:
        report = json.loads((night_dir / "night.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise LoadRefused("Build the night first: there is no built night in that folder.") from None
    out = []
    for pl in report.get("playlists") or []:
        f = night_dir / str(pl.get("file") or "")
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            raise LoadRefused(f"The playlist {f.name} is missing from the night's folder. Build the night again.") from None
        files = []
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                p = Path(line) if Path(line).is_absolute() else night_dir / line
                files.append(p.resolve())
        out.append((f.stem, files))
    if not out:
        raise LoadRefused("The built night has no playlists. Build the night again.")
    gone = [p for _, files in out for p in files if not p.is_file()]
    if gone:
        raise LoadRefused(f"{len(gone)} of the night's files are missing, like {gone[0].name}. Build the night again.")
    return out


def _location(p: Path) -> str:
    return p.as_posix()        # Mixxx stores forward slashes on Windows too (C:/Users/...)


def _audio_facts(p: Path) -> dict:
    """Duration, rate and channels for the library row, so the library shows lengths before Mixxx
    reads the file itself (it re-reads tags and analyzes on first load anyway)."""
    try:
        import soundfile  # noqa: PLC0415 -- optional here; the app ships it
        info = soundfile.info(str(p))
        return {"duration": float(info.duration), "samplerate": int(info.samplerate), "channels": int(info.channels)}
    except Exception:  # noqa: BLE001 -- ok: Mixxx fills these when it reads the file
        return {"duration": 0.0, "samplerate": 0, "channels": 0}


def _tags(p: Path) -> tuple[str, str]:
    """Artist and title from the build's own file name ("Artist - Title.flac")."""
    artist, sep, title = p.stem.partition(" - ")
    return (artist, title) if sep else ("", p.stem)


# --- Mixxx's library ---------------------------------------------------------------------------------

def schema_version(conn: sqlite3.Connection) -> str:
    try:
        row = conn.execute("SELECT value FROM settings WHERE name = 'mixxx.schema.version'").fetchone()
    except sqlite3.Error:
        return ""
    return str(row[0]) if row and row[0] is not None else ""


def _marks(conn) -> dict:
    row = conn.execute("SELECT value FROM settings WHERE name = ?", (MARK_KEY,)).fetchone()
    try:
        got = json.loads(row[0]) if row and row[0] else {}
    except ValueError:
        got = {}
    return {str(k): int(v) for k, v in got.items()} if isinstance(got, dict) else {}


def _save_marks(conn, marks: dict) -> None:
    conn.execute("DELETE FROM settings WHERE name = ?", (MARK_KEY,))
    conn.execute("INSERT INTO settings (name, value) VALUES (?, ?)", (MARK_KEY, json.dumps(marks, sort_keys=True)))


def _forget_old_cut(conn, lib_id: int, loc_id: int, stored_s, p: Path) -> bool:
    """A cut built again under the same name is a different recording to Mixxx: when it starts later
    (Starts at, Llano PM #23751), every beat and cue Mixxx measured on the old one sits in the wrong
    place, and the lights read the beat from Mixxx's grid. Mixxx keeps the old analysis for a file it
    already knows, so when the file's real length is no longer the length Mixxx stored, its beat grid,
    tempo, cue points and waveform are cleared and its length set: Mixxx measures it again the first
    time it loads it. Only a length both sides know is compared (a row Mixxx never filled stays as it
    is). True when it cleared one."""
    try:
        stored = float(stored_s or 0)
    except (TypeError, ValueError):
        stored = 0.0
    facts = _audio_facts(p)
    if stored <= 0 or facts["duration"] <= 0 or abs(stored - facts["duration"]) <= 0.5:
        return False
    conn.execute("UPDATE library SET duration = ?, samplerate = ?, channels = ?, bpm = 0, beats = NULL, "
                 "beats_version = NULL, beats_sub_version = '', cuepoint = 0, header_parsed = 0 WHERE id = ?",
                 (facts["duration"], facts["samplerate"], facts["channels"], lib_id))
    conn.execute("DELETE FROM cues WHERE track_id = ?", (lib_id,))
    conn.execute("DELETE FROM track_analysis WHERE track_id = ?", (loc_id,))
    return True


def _track_id(conn, p: Path) -> tuple[int, bool]:
    """The library id for a file, adding it when Mixxx doesn't know it. (id, added)."""
    loc = _location(p)
    row = conn.execute("SELECT id FROM track_locations WHERE location = ?", (loc,)).fetchone()
    size = p.stat().st_size
    if row:
        loc_id = row[0]
        conn.execute("UPDATE track_locations SET fs_deleted = 0, filesize = ? WHERE id = ?", (size, loc_id))
        lib = conn.execute("SELECT id, duration FROM library WHERE location = ? ORDER BY id LIMIT 1", (loc_id,)).fetchone()
        if lib:
            # a song of this night that he hid from the library is back while it is in a playlist
            conn.execute("UPDATE library SET mixxx_deleted = 0 WHERE id = ?", (lib[0],))
            _forget_old_cut(conn, lib[0], loc_id, lib[1], p)
            return lib[0], False
    else:
        loc_id = conn.execute(
            "INSERT INTO track_locations (location, filename, directory, filesize, fs_deleted, needs_verification) "
            "VALUES (?, ?, ?, ?, 0, 0)", (loc, p.name, p.parent.as_posix(), size)).lastrowid
    artist, title = _tags(p)
    facts = _audio_facts(p)
    lib_id = conn.execute(
        "INSERT INTO library (artist, title, album, location, duration, samplerate, channels, bitrate, filetype, "
        "datetime_added, mixxx_deleted, played, timesplayed, cuepoint, bpm, header_parsed) "
        "VALUES (?, ?, '', ?, ?, ?, ?, 0, ?, datetime('now'), 0, 0, 0, 0, 0, 0)",
        (artist, title, loc_id, facts["duration"], facts["samplerate"], facts["channels"],
         p.suffix.lstrip(".").lower() or "?")).lastrowid
    return lib_id, True


def _fill(conn, playlist_id: int, track_ids: list[int]) -> None:
    conn.execute("DELETE FROM PlaylistTracks WHERE playlist_id = ?", (playlist_id,))
    conn.executemany("INSERT INTO PlaylistTracks (playlist_id, track_id, position, pl_datetime_added) "
                     "VALUES (?, ?, ?, datetime('now'))",
                     [(playlist_id, t, i) for i, t in enumerate(track_ids, start=1)])
    conn.execute("UPDATE Playlists SET date_modified = datetime('now') WHERE id = ?", (playlist_id,))


def _new_playlist(conn, name: str, hidden: int) -> int:
    pos = (conn.execute("SELECT MAX(position) FROM Playlists").fetchone()[0] or 0) + 1
    return conn.execute("INSERT INTO Playlists (name, position, hidden, date_created, date_modified, locked) "
                        "VALUES (?, ?, ?, datetime('now'), datetime('now'), 0)", (name, pos, hidden)).lastrowid


# --- mixxx.cfg ------------------------------------------------------------------------------------------

def set_autodj(cfg_path: Path, values: dict) -> None:
    """Set keys in [Auto DJ], keeping every other line of Mixxx's settings as it was."""
    lines = cfg_path.read_text(encoding="utf-8", errors="replace").splitlines()
    group, start, end = None, None, len(lines)
    for i, raw in enumerate(lines):
        s = raw.strip()
        if s.startswith("[") and s.endswith("]"):
            if group == "[Auto DJ]":
                end = i
                break
            group = s
            if s == "[Auto DJ]":
                start = i
    todo = dict(values)
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", "[Auto DJ]"] + [f"{k} {v}" for k, v in todo.items()]
    else:
        for i in range(start + 1, end):
            k = lines[i].strip().partition(" ")[0]
            if k in todo:
                lines[i] = f"{k} {todo.pop(k)}"
        last = end
        while last - 1 > start and not lines[last - 1].strip():
            last -= 1
        lines[last:last] = [f"{k} {v}" for k, v in todo.items()]
    tmp = cfg_path.with_name(cfg_path.name + ".llano-tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, cfg_path)


# --- the load ---------------------------------------------------------------------------------------------

def _backup(db: Path, cfg: Path) -> Path:
    stamp = time.strftime("%Y-%m-%d %H-%M-%S")
    folder = db.parent / BACKUP_DIR
    folder.mkdir(exist_ok=True)
    dest = folder / f"mixxxdb {stamp}.sqlite"
    src = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        out = sqlite3.connect(dest)
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    shutil.copy2(cfg, folder / f"mixxx {stamp}.cfg")
    for pattern in ("mixxxdb *.sqlite", "mixxx *.cfg"):   # the newest few; a load a day never fills the disk
        for old in sorted(folder.glob(pattern))[:-KEEP_BACKUPS]:
            old.unlink(missing_ok=True)
    return dest


_AUTO = object()


def load(night_dir, *, db_path=None, cfg_path=None, running: Optional[Callable[[], Optional[bool]]] = None,
         opener=_AUTO) -> dict:
    """Load a built night into Mixxx. Raises LoadRefused (nothing written) when it must not.
    `running` defaults to mixxx_running, `opener` to open_mixxx (None: don't open Mixxx)."""
    running = running or mixxx_running
    opener = open_mixxx if opener is _AUTO else opener
    db = Path(db_path) if db_path else mixxx_db.default_db_path()
    cfg = Path(cfg_path) if cfg_path else wedding_night.mixxx_cfg_path()
    state = running()
    if state:
        raise LoadRefused("Mixxx is open. Close Mixxx, then press Load Mixxx again.")
    if state is None:   # can't tell: never write a library Mixxx may have open
        raise LoadRefused("Llano Lights could not tell whether Mixxx is open. Close Mixxx and press Load Mixxx again.")
    if not db.is_file() or not cfg.is_file():
        raise LoadRefused("Mixxx's library wasn't found on this laptop. Open Mixxx once, close it, "
                          "then press Load Mixxx again.")
    playlists = night_playlists(night_dir)

    conn = sqlite3.connect(db, timeout=2, isolation_level=None)
    try:
        version = schema_version(conn)
        if version not in KNOWN_SCHEMAS:
            raise LoadRefused(f"This Mixxx's library is a version Llano Lights doesn't know (schema {version or 'unknown'}; "
                              "it knows Mixxx 2.5). Nothing was changed. The by-hand steps are on the Shows page under Build the night.")
        marks = _marks(conn)
        mine_now = {}
        for name, _ in playlists:
            rows = conn.execute("SELECT id FROM Playlists WHERE name = ? AND hidden = ?", (name, HIDDEN_NONE)).fetchall()
            theirs = [r[0] for r in rows if marks.get(name) != r[0]]
            if theirs:
                raise LoadRefused(f"You already have a playlist named \"{name}\" in Mixxx that Llano Lights didn't make. "
                                  "Rename it in Mixxx, close Mixxx, then press Load Mixxx again. Nothing was changed.")
            mine_now[name] = rows[0][0] if rows else None
        backup = _backup(db, cfg)

        conn.execute("BEGIN IMMEDIATE")
        try:
            added = known = 0
            ids_of: dict = {}
            report_lists = []
            first: list[int] = []
            for n, (name, files) in enumerate(playlists):
                ids = []
                for p in files:
                    if p not in ids_of:
                        ids_of[p], new = _track_id(conn, p)
                        added, known = added + new, known + (not new)
                    ids.append(ids_of[p])
                pid = mine_now[name]
                if pid is None:
                    pid = _new_playlist(conn, name, HIDDEN_NONE)
                _fill(conn, pid, ids)
                marks[name] = pid
                report_lists.append({"name": name, "songs": len(ids), "replaced": mine_now[name] is not None})
                if n == 0:
                    first = ids
            row = conn.execute("SELECT id FROM Playlists WHERE name = ? AND hidden = ? ORDER BY id LIMIT 1",
                               (AUTODJ_NAME, HIDDEN_AUTODJ)).fetchone()
            autodj = row[0] if row else _new_playlist(conn, AUTODJ_NAME, HIDDEN_AUTODJ)
            queue_had = conn.execute("SELECT COUNT(*) FROM PlaylistTracks WHERE playlist_id = ?", (autodj,)).fetchone()[0]
            _fill(conn, autodj, first)
            _save_marks(conn, marks)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()

    set_autodj(cfg, {"TransitionMode": FULL_TRACK, "Transition": f"{sc.TRANSITION_S:g}"})
    opened = bool(opener()) if opener else False
    return {"ok": True, "backup": str(backup), "added": added, "known": known, "playlists": report_lists,
            "autodj": len(first), "queue_had": queue_had, "opened": opened, "mixxx": KNOWN_SCHEMAS[version],
            "transition_s": sc.TRANSITION_S}
