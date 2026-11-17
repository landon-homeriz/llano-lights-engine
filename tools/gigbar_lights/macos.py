"""The Mac side of the few places Llano Lights talks to the computer itself (Llano BL #12517).

His ask, 2026-11-17: "we need a mac option. most djs use macs, right?" The engine, the show and the
pages are plain Python and web, so they run on a Mac unchanged; only these seams were Windows-only:

  the window      Chrome (or Edge, Brave, Chromium) in an app window over the same 127.0.0.1 server,
                  with its own profile; the default browser when none is installed. The per-launch
                  token and the Host check are the server's, so they hold whichever window it is.
  folder / file   the Mac's own Choose Folder / Choose File dialog (osascript, StandardAdditions).
  Mixxx           its settings folder: ~/Library/Containers/org.mixxx.mixxx/... for the sandboxed
                  build from mixxx.org, ~/Library/Application Support/Mixxx for a build that isn't.
  now playing     macOS has no public "what is playing" API: Spotify and Music answer AppleScript,
                  which asks him once for permission. Browser tabs aren't read on a Mac.
  hotspot         a Mac can't be a Wi-Fi hotspot for this; the phone's hotspot or a travel router is.

Every osascript call passes his words (a title, a folder) as run arguments, never inside the script,
so no folder name on his disk can change what runs. Nothing here raises into the app.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

OSASCRIPT = "/usr/bin/osascript"
PICK_WAIT_S = 15 * 60
ASK_WAIT_S = 10.0   # a first AppleScript call on a Mac can take seconds (the macOS runner: over 2 s)

# Chromium browsers that make a real app window (no tabs, no address bar) from --app=<url>, best first.
BROWSERS = (
    ("Google Chrome", "Google Chrome.app/Contents/MacOS/Google Chrome"),
    ("Microsoft Edge", "Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    ("Brave", "Brave Browser.app/Contents/MacOS/Brave Browser"),
    ("Chromium", "Chromium.app/Contents/MacOS/Chromium"),
)
MIXXX_SANDBOXED = Path("Library/Containers/org.mixxx.mixxx/Data/Library/Application Support/Mixxx")
MIXXX_PLAIN = Path("Library/Application Support/Mixxx")


def on_mac() -> bool:
    return sys.platform == "darwin"


def app_data_dir(home: Optional[Path] = None) -> Path:
    """Where a Mac app keeps its own files: never inside the .app, which an update replaces whole."""
    return (home or Path.home()) / "Library" / "Application Support" / "Llano Lights"


def _app_dirs(home: Optional[Path] = None) -> list[Path]:
    return [Path("/Applications"), (home or Path.home()) / "Applications"]


def find_browser(home: Optional[Path] = None) -> "tuple[str, Path] | None":
    """(name, program) of the first Chromium browser installed, else None."""
    for name, rel in BROWSERS:
        for d in _app_dirs(home):
            exe = d / rel
            if exe.is_file():
                return name, exe
    return None


def mixxx_settings_dir(home: Optional[Path] = None) -> Path:
    """Mixxx's settings folder (mixxxdb.sqlite, mixxx.cfg, controllers/). The mixxx.org download is
    sandboxed and keeps it in its container; a build that isn't (Homebrew, self-built) keeps it in
    Application Support. The one that holds a library wins; with neither yet, the sandboxed one."""
    home = home or Path.home()
    for rel in (MIXXX_SANDBOXED, MIXXX_PLAIN):
        if (home / rel / "mixxxdb.sqlite").is_file():
            return home / rel
    for rel in (MIXXX_SANDBOXED, MIXXX_PLAIN):
        if (home / rel).is_dir():
            return home / rel
    return home / MIXXX_SANDBOXED


def find_mixxx(home: Optional[Path] = None) -> Optional[str]:
    """Mixxx's program inside Mixxx.app, wherever he dragged it."""
    for d in _app_dirs(home):
        exe = d / "Mixxx.app" / "Contents" / "MacOS" / "mixxx"
        if exe.is_file():
            return str(exe)
    return shutil.which("mixxx")


def open_app(exe: str) -> bool:
    """Open a Mac app the way a double-click does (its .app, through LaunchServices)."""
    p = Path(exe)
    app = next((q for q in (p, *p.parents) if q.suffix == ".app"), None)
    try:
        subprocess.Popen(["/usr/bin/open", str(app)] if app else [exe], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    return True


def osascript(script: str, *args: str, timeout: float = ASK_WAIT_S) -> tuple[int, str, str]:
    """(exit code, what it printed, its error text). `args` reach the script as `argv`."""
    res = subprocess.run([OSASCRIPT, "-", *args], input=script.encode("utf-8"), capture_output=True, timeout=timeout)
    return res.returncode, res.stdout.decode("utf-8", "replace").strip(), res.stderr.decode("utf-8", "replace").strip()


# -128 is AppleScript's "User canceled": he pressed Cancel.
CANCELLED = "-128"

PICK_FOLDER = """on run argv
  set t to item 1 of argv
  if (item 2 of argv) is "" then
    set f to choose folder with prompt t
  else
    set f to choose folder with prompt t default location (POSIX file (item 2 of argv))
  end if
  return POSIX path of f
end run
"""

PICK_FILE = """on run argv
  set t to item 1 of argv
  set kinds to {"public.audio", "public.mp3", "com.microsoft.waveform-audio", "public.aiff-audio", "org.xiph.flac", "public.mpeg-4-audio"}
  if (item 2 of argv) is "" then
    set f to choose file with prompt t of type kinds
  else
    set f to choose file with prompt t of type kinds default location (POSIX file (item 2 of argv))
  end if
  return POSIX path of f
end run
"""


def pick(script: str, title: str, start: str) -> tuple[str, str]:
    """(path he chose, "") | ("", "") cancelled | ("", why) when the dialog couldn't open."""
    try:
        code, out, err = osascript(script, title[:120], start, timeout=PICK_WAIT_S)
    except subprocess.TimeoutExpired:
        return "", "The picker was left open too long and was closed. Press Browse again."
    except OSError as e:
        print(f"Mac picker could not open: {e}")
        return "", "The Mac's picker didn't open. Paste the path in the box instead."
    if code == 0:
        return out.rstrip("/") if len(out) > 1 else out, ""
    if CANCELLED in err:
        return "", ""
    print(f"Mac picker could not open: {err.splitlines()[0] if err else code}")
    return "", "The Mac's picker didn't open. Paste the path in the box instead."


# Spotify and Music: (process name, bundle id, the name he knows). Which of them is running is asked of
# the process list (pgrep), never of AppleScript: naming an app that isn't installed in a script makes
# osascript stop and show "Where is Spotify?" (the macOS runner, which has no Spotify, hung on it).
PLAYERS = (("Spotify", "com.spotify.client", "Spotify"), ("Music", "com.apple.Music", "Apple Music"))
# One running player by bundle id (argv), in raw Apple Event codes (player state, current track,
# artist, name), which Spotify shares with Music, so neither app's dictionary is loaded to compile it.
# Player state comes back as a word ("playing") or a raw constant (kPSP playing, kPSp paused).
NOW_PLAYING = """on run argv
  tell application id (item 1 of argv)
    set s to («class pPlS») as text
    set tr to «class pTrk»
    set a to («class pArt» of tr) as text
    set t to («class pnam» of tr) as text
  end tell
  return s & tab & a & tab & t
end run
"""
APPS = {name: label for name, _bid, label in PLAYERS}


def running_players() -> list[tuple[str, str, str]]:
    """The players open right now; [] when the process list can't be read."""
    out = []
    for proc, bid, label in PLAYERS:
        try:
            if subprocess.run(["/usr/bin/pgrep", "-x", proc], capture_output=True, timeout=5).returncode == 0:
                out.append((proc, bid, label))
        except (OSError, subprocess.SubprocessError):
            continue
    return out


def parse_now_playing(text: str) -> list[tuple[str, bool, str, str]]:
    """[(app name he knows, playing?, artist, title)] from NOW_PLAYING's lines."""
    rows = []
    for line in (text or "").splitlines():
        parts = line.split("\t")
        if len(parts) != 4 or parts[0] not in APPS:
            continue
        app, state, artist, title = parts
        st = state.strip()
        # kPSP is playing, kPSp paused: the codes differ only in case, so never lower-case them
        rows.append((APPS[app], st.lower() == "playing" or "kPSP" in st, artist.strip(), title.strip()))
    return rows


def read_now_playing() -> list[tuple[str, bool, str, str]]:
    """[(app, playing?, artist, title)] for each open player with a song; [] when none is open (and then
    no osascript runs at all). A player that doesn't answer is skipped (between songs, or quitting)."""
    lines = []
    for proc, bid, _label in running_players():
        code, out, _err = osascript(NOW_PLAYING, bid)
        if code == 0 and out:
            lines.append(f"{proc}\t{out}")
    return parse_now_playing("\n".join(lines))


def chrome_window_command(browser: Path, url: str, profile: Path, flags: tuple) -> list[str]:
    return [str(browser), f"--app={url}", f"--user-data-dir={profile}", *flags]


def default_browser_open(url: str) -> bool:
    try:
        subprocess.Popen(["/usr/bin/open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False
