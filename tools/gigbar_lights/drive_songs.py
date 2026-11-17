"""Get my songs: his Drive song folder, brought to this laptop through the Llano link (Llano BL #12342,
design room llano-lights-music-flow).

He keeps the night's songs in Drive, one subfolder per part ("1 - Cocktail Hour", "2 - Dinner",
"3 - Dancing", "4 - Moments"), and adds or moves a song there from his phone or any computer. Once
this laptop is connected to that folder, Get my songs lists it through Llano (aios
scripts/lights/drive_songs.py, the device token names his tenant) and makes a copy of it here:

  * only what is new or changed is downloaded (Drive's md5, else size and time); a song moved to
    another part's folder is moved here, not downloaded again;
  * every file keeps its real name (a Drive zip turned each apostrophe into an underscore);
  * a song taken out of the Drive folder is taken out here, but only a file this copy wrote: a song he
    added by hand to this folder (Add a song from this laptop) is never touched;
  * a file lands under its real name only once it is whole and its md5 matches, so a dropped
    connection never leaves half a song where the build would read it.

The copy is an ordinary folder of songs, so the Shows page reads it exactly as it reads any folder
he picks (song_folder.read_folder_all): each song takes its part of the night from the folder it sits
in. Llano keeps the order, the parts and the looks in the show, never as files in his Drive.

Also here: add_file, the hand path (Add a song from this laptop): one audio file copied into the
show's song folder, into its part's subfolder, so it lands in the show in that part and the night
build finds it beside the others.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Callable, Optional

from . import song_folder

STATE = ".llano-drive.json"        # what this copy wrote, in the copy's own folder
CONNECTED = "drive_songs.json"     # the Drive folder this laptop is connected to, beside the settings
PARENT = "Llano Lights songs"      # under his Music folder
# His part folders, as he names them in Drive; a folder the copy or Add a song makes is named the same.
PART_DIRS = {"cocktail": "1 - Cocktail Hour", "dinner": "2 - Dinner", "dancing": "3 - Dancing",
             "moment": "4 - Moments"}
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


class SongsError(Exception):
    """A plain reason for the page."""


def safe(name: str) -> str:
    """A Drive name as a Windows file or folder name: the same words, an apostrophe kept, only what
    Windows cannot hold replaced; never empty, never "..", never a device name."""
    out = _BAD.sub("-", str(name or "")).strip().rstrip(". ")
    if not out or out in (".", "..") or out.split(".")[0].lower() in _RESERVED:
        out = "_" + out if out not in ("", ".", "..") else "song"
    return out[:150]


def default_root(folder_name: str) -> Path:
    return Path.home() / "Music" / PARENT / safe(folder_name or "Drive songs")


# --- which Drive folder this laptop is connected to ---------------------------------------------------

def read_connected(settings_dir) -> dict:
    """{id, name, root} or {} when not connected."""
    try:
        d = json.loads((Path(settings_dir) / CONNECTED).read_text(encoding="utf-8"))
    except (OSError, ValueError):  # ok: never connected, or a broken file = not connected
        return {}
    if not isinstance(d, dict) or not isinstance(d.get("id"), str) or not d["id"]:
        return {}
    return {"id": d["id"], "name": str(d.get("name") or ""), "root": str(d.get("root") or "")}


def connect(settings_dir, folder: dict, root: Optional[str] = None) -> dict:
    row = {"id": str(folder["id"]), "name": str(folder.get("name") or ""),
           "root": str(root or default_root(str(folder.get("name") or "")))}
    p = Path(settings_dir) / CONNECTED
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(row), encoding="utf-8")
    tmp.replace(p)
    return row


def disconnect(settings_dir) -> None:
    (Path(settings_dir) / CONNECTED).unlink(missing_ok=True)


# --- the copy ---------------------------------------------------------------------------------------------

def _read_state(root: Path) -> dict:
    try:
        d = json.loads((root / STATE).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and isinstance(d.get("files"), dict) else {"files": {}}
    except (OSError, ValueError):
        return {"files": {}}


def _write_state(root: Path, state: dict) -> None:
    tmp = root / (STATE + ".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(root / STATE)


def _rel(f: dict) -> str:
    parts = [safe(p) for p in (f.get("path") or [])][:2] + [safe(f.get("name") or "")]
    return "/".join(parts)


def _same(have: dict, f: dict) -> bool:
    if f.get("md5") and have.get("md5"):
        return have["md5"] == f["md5"]
    return have.get("size") == f.get("size") and have.get("modified") == f.get("modified")


def _md5(path: Path) -> str:
    h = hashlib.md5()  # noqa: S324 -- Drive's own checksum, compared, never a security check
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _label(rel: str) -> dict:
    artist, title = song_folder._name(Path(rel))
    return {"artist": artist, "title": title, "file": rel}


def get_songs(link, folder: dict, root, *, on_progress: Callable[[str, int, int], None] = lambda w, i, n: None) -> dict:
    """Bring the Drive folder's songs into `root`. Returns {folder, root, new, changed, moved, removed,
    kept, failed, files}: lists of {artist, title, file} (failed: {file, why}), kept a count.
    Raises SongsError when Llano or Drive cannot be read (nothing here is changed then)."""
    root = Path(root)
    try:
        listing = link.drive_songs(folder.get("id") or "")
    except Exception as e:  # noqa: BLE001 -- the reason is said on the page; the copy stays as it was
        raise SongsError(f"Llano could not list your Drive folder: {e}") from e
    files = [f for f in listing.get("files") or [] if isinstance(f, dict) and f.get("id") and f.get("name")]
    root.mkdir(parents=True, exist_ok=True)
    state = _read_state(root)
    had: dict = state["files"]
    out = {"folder": listing.get("folder") or folder, "root": str(root), "new": [], "changed": [], "moved": [],
           "removed": [], "kept": 0, "failed": [], "truncated": bool(listing.get("truncated"))}
    seen_rel: set = set()
    now: dict = {}
    for i, f in enumerate(files, 1):
        rel = _rel(f)
        if rel.casefold() in seen_rel:       # two Drive files that are one file name here: the first wins
            out["failed"].append({"file": rel, "why": "two files in Drive have this name; only the first is here"})
            continue
        seen_rel.add(rel.casefold())
        dest = root / rel
        have = had.get(f["id"])
        row = {"rel": rel, "md5": f.get("md5", ""), "size": f.get("size", 0), "modified": f.get("modified", "")}
        if have and _same(have, f):
            old = root / str(have.get("rel") or "")
            if have.get("rel") == rel and dest.is_file():
                out["kept"] += 1
                now[f["id"]] = row
                continue
            if old.is_file() and have.get("rel") != rel:     # moved to another part's folder in Drive
                dest.parent.mkdir(parents=True, exist_ok=True)
                old.replace(dest)
                out["moved"].append(_label(rel))
                now[f["id"]] = row
                continue
        on_progress(f"Downloading {f['name']}", i, len(files))
        try:
            _download(link, folder.get("id") or "", f, dest)
        except Exception as e:  # noqa: BLE001 -- one song that failed is named; the rest still come
            out["failed"].append({"file": rel, "why": str(e)[:200]})
            if have:
                now[f["id"]] = have        # keep the old copy and its record: it is retried next time
            continue
        if have and have.get("rel") and have.get("rel") != rel:
            (root / have["rel"]).unlink(missing_ok=True)
        (out["changed"] if have else out["new"]).append(_label(rel))
        now[f["id"]] = row
    # gone from Drive: only a file this copy wrote, and only when Drive answered with a full list
    if not out["truncated"]:
        for fid, have in had.items():
            if fid in now:
                continue
            rel = str(have.get("rel") or "")
            p = root / rel
            if rel and ".." not in Path(rel).parts and p.is_file():
                p.unlink()
            out["removed"].append(_label(rel))
    else:
        now.update({k: v for k, v in had.items() if k not in now})
    state = {"folder": out["folder"], "got_at": time.strftime("%Y-%m-%d %H:%M"), "files": now}
    _write_state(root, state)
    out["files"] = len(now)
    return out


def _download(link, folder_id: str, f: dict, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    try:
        md5 = link.download_song(folder_id, f["id"], tmp)
        if f.get("md5") and md5 and md5 != f["md5"]:
            raise SongsError("the download did not match Drive's copy; it is tried again next time")
        if f.get("size") and tmp.stat().st_size != int(f["size"]):
            raise SongsError("the download was cut short; it is tried again next time")
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def last_get(root) -> dict:
    st = _read_state(Path(root)) if root else {"files": {}}
    return {"got_at": st.get("got_at", ""), "files": len(st.get("files") or {})}


# --- Add a song from this laptop ---------------------------------------------------------------------------

def part_dir(root: Path, part: str) -> Path:
    """The subfolder of `root` that holds `part` ("moment" = the Moments folder): his own when the
    folder has one (any name song_folder reads as that part), else a new one named as in Drive."""
    from .shows import part_from_name
    if root.is_dir():
        for p in sorted(root.iterdir()):
            if not p.is_dir():
                continue
            if part == "moment" and song_folder._MOMENTS_DIR.search(p.name.lower()):
                return p
            if part != "moment" and part_from_name(p.name) == part:
                return p
    return root / PART_DIRS[part]


def add_file(src, root, part: str, moment: str = "") -> dict:
    """Copy one audio file into the show's song folder under its part, and the song as the page adds
    it: {artist, title, part, moment, bpm, camelot, year, file}. A file already there under that name
    is left alone when it is the same file, and refused when it is another."""
    from . import settings_contract as contract
    src = Path(str(src or "").strip().strip('"'))
    if not src.is_file():
        raise SongsError(f"no file at {src}")
    if src.suffix.lower() not in song_folder.AUDIO:
        raise SongsError("that is not a song file (mp3, flac, wav, m4a, ogg)")
    if moment and moment not in contract.SHOW_MOMENTS:
        raise SongsError("no such moment")
    if not moment and part not in contract.SHOW_PARTS:
        raise SongsError("pick its part of the night")
    root = Path(root)
    folder = part_dir(root, "moment" if moment else part)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / safe(src.name)
    if dest.exists():
        if dest.stat().st_size != src.stat().st_size or _md5(dest) != _md5(src):
            raise SongsError(f"another file named {dest.name} is already in {folder.name}: rename one of them")
    elif src.resolve() != dest.resolve():
        tmp = dest.with_name(dest.name + ".part")
        shutil.copyfile(src, tmp)
        tmp.replace(dest)
    artist, title = song_folder._name(dest)
    tags = song_folder.id3_tags(dest) if dest.suffix.lower() == ".mp3" else {}
    return {"artist": artist or tags.get("artist", ""), "title": title or tags.get("title", ""), "secs": 0.0,
            "bpm": tags.get("bpm", 0.0), "camelot": tags.get("key", ""), "year": tags.get("year", 0),
            "part": "dancing" if moment else part, "moment": moment, "file": str(dest)}
