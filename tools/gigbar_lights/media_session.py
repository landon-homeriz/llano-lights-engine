"""What Windows says is playing: artist and title from the system media session.

Spotify, browser YouTube Music (Chrome, Edge, Firefox) and most players publish the song
to Windows' media controls (the box that pops up over the volume keys). The Global System
Media Transport Controls API reads it back. We use PyWinRT (winrt-Windows.Media.Control),
imported lazily so the app still starts where it is missing or not Windows; then this
source just reports nothing and the show runs on Mixxx and the beat it hears.

A background thread asks once a second and keeps the newest answer; the show thread only
reads that. Every WinRT call is waited on for at most a second (a frozen browser tab must
not leave the last song "playing" forever), and an answer older than STALE_S reads as none.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

POLL_S = 1.0
CALL_TIMEOUT_S = 1.0   # a WinRT call waits this long, then the app counts as not answering
STALE_S = 3.0          # an answer older than this means nothing is known: not "still playing"
# GlobalSystemMediaTransportControlsSessionPlaybackStatus: PLAYING 4, and CHANGING 2 (Spotify
# between tracks), which must not read as a pause for a moment.
PLAYING_STATES = (2, 4)
MANAGER_TIMEOUT_S = 10.0  # the first answer from the media service can be slow just after login
# A media session's app id -> the name he knows it by. Browser tabs say only the browser;
# the page under it (YouTube Music, YouTube) is not in the session.
APPS = (("spotify", "Spotify"), ("chrome", "Chrome"), ("msedge", "Edge"), ("firefox", "Firefox"),
        ("308046b0af4a39cb", "Firefox"), ("brave", "Brave"), ("opera", "Opera"),
        ("youtube", "YouTube Music"), ("zunemusic", "Media Player"), ("music.ui", "Media Player"),
        ("applemusic", "Apple Music"), ("itunes", "iTunes"), ("amazon", "Amazon Music"),
        ("tidal", "TIDAL"), ("deezer", "Deezer"), ("vlc", "VLC"), ("mixxx", "Mixxx"))
BROWSERS = {"Chrome", "Edge", "Firefox", "Brave", "Opera"}


@dataclass(frozen=True)
class NowPlaying:
    artist: str
    title: str
    app: str        # Spotify, Chrome, ...
    playing: bool

    @property
    def source(self) -> str:
        """How the page names it: "Spotify", or "browser (Chrome)" for a tab such as YouTube Music."""
        return f"browser ({self.app})" if self.app in BROWSERS else self.app

    @property
    def label(self) -> str:
        return " - ".join(p for p in (self.artist, self.title) if p)


def app_name(app_id: str) -> str:
    low = (app_id or "").lower()
    for needle, name in APPS:
        if needle in low:
            return name
    base = (app_id or "").rsplit("\\", 1)[-1].rsplit("!", 1)[-1]
    return base[:-4] if base.lower().endswith(".exe") else (base or "an app")


def choose(sessions: list[NowPlaying], current: Optional[NowPlaying] = None) -> Optional[NowPlaying]:
    """The one to follow: one that is playing (Windows' own current session first), else
    Windows' current session even when paused, so the page can say what is loaded."""
    playing = [s for s in sessions if s.playing and (s.title or s.artist)]
    if current and current.playing and (current.title or current.artist):
        return current
    if playing:
        return playing[0]
    return current if current and (current.title or current.artist) else None


def _read_windows() -> Callable[[], Optional[NowPlaying]]:
    """A reader over the WinRT API; ImportError where it is not installed. The session manager
    is asked for on the first read and again after a failure, so a slow media service at
    startup (or an Explorer restart) only costs a few polls, never the whole night."""
    from winrt.windows.media.control import (  # noqa: PLC0415 - Windows-only, optional
        GlobalSystemMediaTransportControlsSessionManager as Manager)
    try:
        from winrt import runtime  # noqa: PLC0415
        runtime.init_apartment(runtime.MTA)  # .get() refuses on a single-threaded apartment
    except Exception:  # already initialized on this thread, or an older runtime: fine
        pass

    def call(op, timeout: float = CALL_TIMEOUT_S):
        if int(op.wait(timeout)) != 1:  # AsyncStatus.COMPLETED
            try:
                op.cancel()  # don't leave a call to a hung app outstanding
            except Exception:  # noqa: BLE001
                pass
            raise TimeoutError("a media app didn't answer in time")
        return op.get()

    state = {"manager": None}

    def one(session) -> Optional[NowPlaying]:
        try:
            props = call(session.try_get_media_properties_async())
            info = session.get_playback_info()
        except (OSError, TimeoutError):  # the app closed, or hangs: skip it, ask the others
            return None
        if props is None:
            return None
        status = int(info.playback_status) if info is not None else 0
        return NowPlaying((props.artist or "").strip(), (props.title or "").strip(),
                          app_name(session.source_app_user_model_id), status in PLAYING_STATES)

    def read() -> Optional[NowPlaying]:
        if state["manager"] is None:
            state["manager"] = call(Manager.request_async(), MANAGER_TIMEOUT_S)
        manager = state["manager"]
        try:
            cur = manager.get_current_session()
            cur_id = cur.source_app_user_model_id if cur is not None else None
            current = one(cur) if cur is not None else None
            # every other session once: the current one is in this list too, so skip it (only it:
            # a second tab in the same browser shares its app id and must still be asked)
            others, skipped = [], cur_id is None
            for sess in manager.get_sessions():
                if not skipped and sess.source_app_user_model_id == cur_id:
                    skipped = True
                    continue
                others.append(one(sess))
        except OSError:
            state["manager"] = None  # ask for a fresh manager next time
            raise
        return choose([s for s in others if s], current)

    return read


class MediaSessions:
    """Polls the Windows media session on its own thread; `current()` is the newest answer."""

    def __init__(self, reader: Optional[Callable[[], Optional[NowPlaying]]] = None, poll_s: float = POLL_S):
        self._reader, self.poll_s = reader, poll_s
        self._now: Optional[NowPlaying] = None
        self._at = 0.0           # monotonic time of the newest answer
        self.error = ""          # why it is not reading, in plain words; "" when fine
        self.available = reader is not None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> "MediaSessions":
        self._thread = threading.Thread(target=self._run, name="media-session", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def current(self) -> Optional[NowPlaying]:
        return self._now if time.monotonic() - self._at < STALE_S else None

    def _run(self) -> None:
        read = self._reader
        if read is None:
            try:
                read = _read_windows()
                self.available = True
            except ImportError:
                self.error = "can't read Spotify or browser song names (the Windows media library isn't in this install)"
                return
            except Exception as e:  # noqa: BLE001 - not Windows 10+
                self.error = f"can't read Windows' now playing ({type(e).__name__}: {e})"
                return
        fails = 0
        while not self._stop.is_set():
            try:
                self._now, self._at = read(), time.monotonic()
                fails, self.error = 0, ""
            except Exception as e:  # noqa: BLE001 - keep the show running, keep retrying; say why
                fails += 1
                if fails >= 3:
                    self._now = None
                    self.error = f"Windows' now playing isn't answering ({type(e).__name__}); still trying"
            self._stop.wait(self.poll_s)
        self._now = None
