"""Lights from whatever the laptop plays: Spotify, YouTube Music, anything with sound.

Mixxx tells the show its exact beat over MIDI. Nothing else does, so this listens to the
laptop's own output (WASAPI loopback: what goes to the speakers, whichever app makes it),
finds the beat in it (beat_tracker.py) and reads the song name Windows shows for the
playing app (media_session.py). SystemFeed then sends the show the same messages the
Mixxx mapping would, on a deck of its own (SYSTEM_DECK), so the looks, a song's saved
style and the llano.app status all work the same way.

Who gets the lights:
  * A Mixxx deck playing and audible always wins: its beat grid is exact and its sections
    come from the file.
  * While Mixxx is running (mixxx.exe, checked twice a second, or any MIDI from it in
    the last 3 s) the loopback stream stays closed unless another app Windows says is playing
    (Spotify, a browser tab), whose own stream already holds the output in shared mode:
    a shared stream of ours could otherwise stop Mixxx (re)opening it in exclusive mode
    ("device in use"). It closes the moment Mixxx starts. Taking over from a paused Mixxx
    needs that app playing, continuous sound and a steady beat locked, so the MC's mic
    through Mixxx during the toasts does not start the show (it can't be told apart from
    the app's sound by level alone: that needs per-app metering, not done here).
  * With Mixxx not running, the speakers take over after SUSTAIN_S of continuous sound and
    let go HOLD_S after it stops. A song name alone (a muted tab that says "playing") never
    starts the show while the capture can listen; it only names what is heard.
  * A capture that can't exist here (library missing, not Windows) leaves the playing app's
    name to pick the style and keep time. A capture that is failing right now never does
    while Mixxx runs; with Mixxx not running, only after FAILING_S of failure.
The stream stays open STREAM_HOLD_S after its last reason (a Spotify track change must not
throw away the beat), and the song name carries through media gaps under SONG_HOLD_S.

Rollback: LLANO_LIGHTS_SYSTEM_AUDIO=0 (or a 1.4.0 build) leaves Mixxx as the only source.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import warnings
import zlib
from typing import Optional

import numpy as np

from .beat_tracker import BeatTracker
from .media_session import MediaSessions, NowPlaying
from .mixxx_db import TrackInfo
from .mixxx_link import SYSTEM_DECK, encode_tick, encode_track
from .show import DeckTrack, Show
from .song_match import candidates, norm

RATE = 44100
BLOCK = 1024           # about 23 ms of sound per read
BUFFER = 4096          # the stream's own buffer (about 90 ms), so a slow moment drops nothing
TICK_S = 512 / RATE    # the Mixxx mapping's tick rate
FREE_BPM = 120.0       # tempo while the beat is not found yet and the library has none
MIXXX_STALE_S = 1.0    # a deck tick older than this: that deck is not playing
MIXXX_OPEN_S = 3.0     # off Windows: any Mixxx message this recent means Mixxx is running
START_DELAY_S = 3.0    # no stream in the first seconds, while Mixxx may still be starting
STREAM_HOLD_S = 15.0   # keep the stream this long after its last reason
SONG_HOLD_S = 5.0      # keep the song name through media gaps this short
FAILING_S = 10.0       # a capture failing this long (Mixxx not running): fall back to names
MIXXX_EXE = "mixxx.exe"
SUSTAIN_S = 2.0        # sound this long before the speakers take the lights
HOLD_S = 2.0           # and this long after it stops before they let go
RETRY_SLOW_S = 30.0    # retry this slowly once a failure has lasted 30 s
REOPEN_S = 3.0         # check this often for a new default speaker (headphones in, HDMI out)
WEIGHT = 0.5           # below a Mixxx deck's, so Mixxx takes over as soon as it plays


def enabled() -> bool:
    return (os.environ.get("LLANO_LIGHTS_SYSTEM_AUDIO") or "1").strip().lower() not in {"0", "off", "false", "no"}


def _com_init() -> bool:
    """COM on this thread. soundcard only sets it up on the thread that first imports it, and
    the app starts a new capture thread for every show. True when we must uninitialize it."""
    if sys.platform != "win32":
        return False
    import ctypes  # noqa: PLC0415
    hr = ctypes.windll.ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED
    return hr in (0, 1)  # S_OK, S_FALSE; RPC_E_CHANGED_MODE: someone else owns it


_TOOLHELP: Optional[tuple] = None  # (kernel32, PROCESSENTRY32W), built once: a class per call leaks


def _toolhelp():
    global _TOOLHELP
    if _TOOLHELP is None:
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                        ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                        ("szExeFile", ctypes.c_wchar * 260)]

        k32 = ctypes.WinDLL("kernel32")  # our own handle: declaring signatures here touches no one else's
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        entry_p = ctypes.POINTER(PROCESSENTRY32W)
        for fn in (k32.Process32FirstW, k32.Process32NextW):
            fn.argtypes, fn.restype = [wintypes.HANDLE, entry_p], wintypes.BOOL
        k32.CloseHandle.argtypes, k32.CloseHandle.restype = [wintypes.HANDLE], wintypes.BOOL
        _TOOLHELP = (k32, PROCESSENTRY32W)
    return _TOOLHELP


def _mixxx_process_running() -> Optional[bool]:
    """Is mixxx.exe running? None when it can't be checked (not Windows, a failed snapshot)."""
    if sys.platform != "win32":
        return None
    import ctypes  # noqa: PLC0415
    k32, entry_t = _toolhelp()
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == ctypes.c_void_p(-1).value:  # INVALID_HANDLE_VALUE
        return None
    try:
        entry = entry_t()
        entry.dwSize = ctypes.sizeof(entry_t)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == MIXXX_EXE:
                return True
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
        return False
    finally:
        k32.CloseHandle(snap)


class MixxxWatch:
    """Whether Mixxx is running, checked twice a second on its own thread (a snapshot costs ~1 ms). `running` is None
    where it can't be checked; SystemFeed then goes by Mixxx's MIDI."""

    def __init__(self, probe=_mixxx_process_running, every_s: float = 0.5):
        self.probe, self.every_s = probe, every_s
        self.running: Optional[bool] = None
        self._stop = threading.Event()

    def start(self) -> "MixxxWatch":
        threading.Thread(target=self._run, name="mixxx-watch", daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                found = self.probe()
            except Exception:  # noqa: BLE001
                found = None
            if found is not None:  # a failed check keeps the last answer (None only until the first)
                self.running = found
            self._stop.wait(self.every_s)


class LoopbackCapture:
    """Records what the default speaker plays, on its own thread, into a BeatTracker, while
    `want` is set; the stream is closed the rest of the time."""

    def __init__(self, tracker: Optional[BeatTracker] = None):
        self.tracker = tracker or BeatTracker(RATE)
        self.error = ""          # plain words when it can't listen; "" when fine
        self.unavailable = False # it can never listen here: the library is missing, or not Windows
        self.failing_since: Optional[float] = None  # perf_counter time the current failure began
        self.device = ""
        self.open = False        # the loopback stream is open right now
        self.want = threading.Event()
        self.kick = threading.Event()   # set when Mixxx stops: retry a held device now, not in 30 s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> "LoopbackCapture":
        self._thread = threading.Thread(target=self._run, name="loopback", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self.want.set()  # wake it so it can leave
        self.kick.set()

    def _run(self) -> None:
        if sys.platform == "darwin":
            # A Mac has no speaker loopback for soundcard to open (Llano BL #12517); hearing Spotify or
            # YouTube there needs Core Audio's process tap (macOS 14.2+). Until then the lights follow
            # Mixxx, and Spotify or Music's song name still reaches the show.
            self.error = "on a Mac the lights follow Mixxx; they can't hear Spotify or YouTube yet"
            self.unavailable = True
            return
        com = False
        try:
            com = _com_init()
            import soundcard as sc  # noqa: PLC0415 - optional
        except ImportError:
            self.error = "can't hear Spotify or YouTube Music (the sound capture library isn't in this install)"
            self.unavailable = True
            return
        except Exception as e:  # noqa: BLE001 - no audio service, not Windows
            self.error = f"can't open the sound system ({type(e).__name__}: {e})"
            self.unavailable = True
            return
        warnings.filterwarnings("ignore", message="data discontinuity")  # soundcard warns on every overrun
        told = ""
        try:
            while not self._stop.is_set():
                self.want.wait()
                if self._stop.is_set():
                    break
                try:
                    speaker = sc.default_speaker()
                    mic = sc.get_microphone(speaker.id, include_loopback=True)
                    with mic.recorder(samplerate=RATE, blocksize=BUFFER) as rec:
                        self.device, self.error, self.open, self.failing_since = speaker.name, "", True, None
                        self.tracker.reset()  # what it heard before the stream closed is old now
                        if told != speaker.name:
                            told = speaker.name
                            print(f"Listening to what plays on {speaker.name}.")
                        checked = time.monotonic()
                        while self.want.is_set() and not self._stop.is_set():
                            data = rec.record(numframes=BLOCK)
                            self.tracker.feed(np.asarray(data, dtype=np.float32).mean(axis=1), time.perf_counter())
                            if time.monotonic() - checked > REOPEN_S:
                                checked = time.monotonic()
                                if sc.default_speaker().id != speaker.id:
                                    break  # the sound moved to another output: follow it
                except Exception as e:  # noqa: BLE001 - device unplugged or held exclusively: retry
                    self.error = f"can't hear the speakers right now ({type(e).__name__}: {e})"
                    if self.failing_since is None:
                        self.failing_since = time.perf_counter()
                    # held by Mixxx (or anyone) for a while: retry slowly; each failed open leaks a
                    # little inside soundcard, and the device won't free itself in 3 s
                    long = time.perf_counter() - self.failing_since > 30
                    self.kick.clear()
                    self.kick.wait(RETRY_SLOW_S if long else REOPEN_S)
                finally:
                    self.open = False
        finally:
            if com:
                import ctypes  # noqa: PLC0415
                ctypes.windll.ole32.CoUninitialize()


class SystemFeed:
    """Called by the show loop every few ms: decides whether the speakers have the lights
    (see the module doc) and, while they do, sends the show what they play and what Windows
    says the song is, as Mixxx messages on SYSTEM_DECK."""

    def __init__(self, show: Show, capture: Optional[LoopbackCapture] = None,
                 media: Optional[MediaSessions] = None, library=None, use_audio: Optional[bool] = None,
                 watch: Optional[MixxxWatch] = None):
        self.show, self.capture, self.media, self.watch = show, capture, media, watch
        self.use_audio = enabled() if use_audio is None else use_audio
        self.mixxx_seen = -1e9          # last message from the real Mixxx mapping (saw_mixxx)
        self.mixxx_link = True          # False: the MIDI port could not be opened
        self.started: Optional[float] = None
        self.stream_until = -1e9        # keep the loopback stream wanted until then
        self.not_running_since: Optional[float] = None  # Mixxx not running since then
        self.last_app: tuple = (None, -1e9)  # (NowPlaying, at) the last time another app was playing
        self.active = False
        self.loaded = False
        self.song: Optional[tuple] = None   # (artist, title, app) the deck carries now
        self.last_tick = -1.0
        self.sound_since: Optional[float] = None
        self.quiet_since: Optional[float] = None
        self.hint = 0.0                     # the playing song's BPM from his Mixxx library, 0 = unknown
        self.bpms: dict = {}                # norm(song key) -> library BPM, built off the show thread
        self.free = (0.0, -1.0)             # (beat, at) of the free-running count
        self.sent: Optional[tuple] = None   # (beat, bpm, at) last sent: the count stays continuous
        self.offset = 0.0
        self.now_playing: Optional[NowPlaying] = None
        self.reading = None                 # the tracker's last reading, from the show loop
        self.told: set = set()              # notes already written to the log
        self.source = ""                    # "Mixxx", "Spotify", "browser (Chrome)", "" = nothing
        if library is not None:
            threading.Thread(target=self._index, args=(library,), name="bpm-index", daemon=True).start()

    def _index(self, library) -> None:
        try:
            self.bpms = library.bpm_index()
        except Exception:  # noqa: BLE001 - no library: no hints
            self.bpms = {}

    def saw_mixxx(self, now: Optional[float] = None) -> None:
        """The MIDI callback calls this for every message from the real Mixxx mapping."""
        self.mixxx_seen = time.perf_counter() if now is None else now

    def mixxx_playing(self, now: float) -> bool:
        with self.show.lock:
            return any(d.deck != SYSTEM_DECK and d.playing and d.weight > 0 and now - d.last_tick < MIXXX_STALE_S
                       for d in self.show.state.decks.values())

    def problems(self) -> list:
        out = [p for p in (self.capture.error if (self.capture and self.use_audio) else "",
                           self.media.error if self.media else "") if p]
        if not self.mixxx_link:
            out.append("Mixxx isn't connected (fine for Spotify and YouTube Music)")
        return out

    # --- the show loop -----------------------------------------------------------------------

    def __call__(self, now: float) -> None:
        try:
            self._tick(now)
        except Exception as e:  # noqa: BLE001 - never let a song name or a sound glitch end the show
            note = f"the Spotify / YouTube Music follower hit {type(e).__name__}: {e}"
            if note not in self.told:
                self.told.add(note)
                print(f"Note: {note}. The show keeps running.")

    def mixxx_running(self, now: float) -> bool:
        known = self.watch.running if self.watch else None
        return bool(known) or now - self.mixxx_seen < MIXXX_OPEN_S

    def _tick(self, now: float) -> None:
        for p in self.problems():
            if p not in self.told:  # once each, into the app's log
                self.told.add(p)
                print(f"Note: {p}.")
        if self.started is None:
            self.started = now
        np_ = self.media.current() if self.media else None
        self.now_playing = np_
        if np_ and np_.playing and np_.app != "Mixxx" and (np_.title or np_.artist):
            self.last_app = (np_, now)
        app = self.last_app[0] if now - self.last_app[1] < SONG_HOLD_S else None  # through short gaps
        running = self.mixxx_running(now)
        if not running and self.not_running_since is None:
            self.not_running_since = now
            if self.capture is not None:
                self.capture.kick.set()  # Mixxx let go of the device: try it now
        elif running:
            self.not_running_since = None
        if self.mixxx_playing(now):
            self.stream_until = -1e9
            self._want_audio(False)
            self._stop(now)
            self.sound_since = None
            self.source = "Mixxx"
            return
        if not self.use_audio:  # switched off: Mixxx only, exactly as 1.4.0
            self._want_audio(False)
            self._stop(now)
            self.source = ""
            return
        # The loopback stream (see the module doc for why it is this careful).
        if not running and now - self.started >= START_DELAY_S:
            self.stream_until = now + STREAM_HOLD_S
        # Mixxx running: only while another app plays (its track gaps are covered by SONG_HOLD_S),
        # so a Retry in Mixxx after pausing Spotify finds the device free within seconds.
        self._want_audio(app is not None if running else now < self.stream_until)
        if running:
            self.stream_until = -1e9
        cap = self.capture
        listens = bool(cap and self.use_audio and not cap.unavailable)
        # failing long = failing for FAILING_S while Mixxx was not running (not while it held the device)
        failing_long = bool(listens and cap.error and cap.failing_since is not None and not running
                            and now - max(cap.failing_since, self.not_running_since) >= FAILING_S)
        names_only = not listens or (failing_long and not running)
        reading = self.reading = cap.tracker.reading(now) if listens else None
        heard = bool(reading and reading.playing)
        sounding = bool(reading and reading.sounding)
        self.sound_since = (self.sound_since or now) if sounding else None
        if names_only:
            want = app is not None
            keep = want
        elif running:  # a paused Mixxx: only another playing app, heard, with a steady beat
            keep = heard and app is not None
            want = keep and sounding and bool(reading and reading.locked)
        else:
            keep = heard
            want = sounding
        if self.active:
            self.quiet_since = None if keep else (self.quiet_since or now)
            take = keep or now - self.quiet_since < HOLD_S
        else:
            self.quiet_since = None
            take = want and (names_only or now - self.sound_since >= SUSTAIN_S)
        if not take:
            self._stop(now)
            self.source = ""
            return
        if not self.loaded:  # one "track loaded" message makes the deck exist, like Mixxx
            self.show.on_midi(encode_track(SYSTEM_DECK, RATE, 0.0, 0.0), now)
            self.loaded = True
        self._set_song(app, now)
        self.source = app.source if app else "the speakers"
        if now - self.last_tick < TICK_S:
            return
        self.last_tick = now
        self._send(reading if not names_only else None, heard, now)

    def _want_audio(self, on: bool) -> None:
        if self.capture is None:
            return
        if on:
            self.capture.want.set()
        else:
            self.capture.want.clear()

    def _set_song(self, np_: Optional[NowPlaying], now: float) -> None:
        artist, title, app = (np_.artist, np_.title, np_.app) if np_ else ("", "", "")
        if self.song == (artist, title, app):
            return
        self.song = (artist, title, app)
        keys = candidates(artist, title, title_only=False) if artist else ()
        self.hint = next((self.bpms[norm(k)] for k in keys if norm(k) in self.bpms), 0.0)
        if self.capture is not None:
            self.capture.tracker.hint_bpm = self.hint
        info = TrackInfo(zlib.crc32(f"{artist}\n{title}".encode()) & 0x7FFFFFFF, artist, title, None)
        with self.show.lock:
            serial = self.show.state.decks[SYSTEM_DECK].track_serial
            self.show.tracks[SYSTEM_DECK] = DeckTrack(serial, info, looked_up=now,
                                                      source=np_.source if np_ else "the speakers")

    def _send(self, reading, heard: bool, now: float) -> None:
        if reading and reading.locked:
            bpm, raw, level = reading.bpm, reading.beat, reading.level
            self.free = (0.0, -1.0)
        else:  # no beat yet (or nothing to hear it with): keep time at the song's tempo so its style plays
            bpm = self.hint or FREE_BPM
            b, at = self.free
            raw = b + (now - at) * bpm / 60.0 if at >= 0 else 0.0
            self.free = (raw, now)
            level = reading.level if heard else (0.6 if reading is None else 0.0)
        bpm = round(bpm, 2)  # what the wire carries; the position below must agree with it
        # One count from start to end: when its source changes (free-running -> heard, a new
        # song, a gap) shift it by whole beats so it carries on from the last beat sent.
        beat = raw + self.offset
        if self.sent is not None:
            b, sb, at = self.sent
            expected = b + (now - at) * sb / 60.0
            if abs(beat - expected) > 0.5:  # adopting a new phase moves it at most half a beat
                self.offset += round(expected - beat)
                beat = raw + self.offset
        beat = max(0.0, beat)
        self.sent = (beat, bpm, now)
        self.active = True
        self.show.on_midi(encode_tick(SYSTEM_DECK, True, True, bpm, beat % 1.0, int(beat * 60.0 / bpm * RATE),
                                      WEIGHT, level), now)

    def _stop(self, now: float) -> None:
        if self.active:
            self.show.on_midi(encode_tick(SYSTEM_DECK, False, True, 0.0, 0.0, 0, 0.0), now)
            self.active = False

    def public(self) -> dict:
        """What llano.app/lights shows: the song the lights follow, where it comes from, the
        style it picked, and how the beat is found ("grid" from Mixxx, "heard" from the
        speakers, "finding" while it listens, "steady" when it can only keep time). Names
        only the song the lights follow, never what other apps have open."""
        with self.show.lock:
            followed = self.show.state.followed
            track = self.show.tracks.get(followed) if followed else None
            showing = self.show.looks.showing
        info = track.info if track else None
        out = {"source": "", "artist": info.artist if info else "", "title": info.title if info else "",
               "song_key": track.song if track else "",
               "style": showing[6:] if showing and showing.startswith("style:") else ""}
        if followed == SYSTEM_DECK:
            reading = self.reading
            out["source"] = self.source
            out["beat"] = "heard" if reading and reading.locked else "finding" if reading and reading.playing else "steady"
        elif followed:
            out["source"], out["beat"] = "Mixxx", "grid"
        problems = self.problems()
        if problems:
            out["problems"] = problems
        return out
