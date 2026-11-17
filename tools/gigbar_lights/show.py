"""The running show: Mixxx messages in, the beat clock and looks engine in the middle, DMX out.

Threads: the MIDI callback feeds deck state and the clock; the DMX loop renders 40 times
a second; the main thread runs `control_tick()` for slower work (library lookups, section
analysis, picking the deck to follow) and the keyboard. One lock guards the shared state.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import cues as cues_mod, moments, show_settings, studio as studio_mod, venue
from .beat_clock import BeatClock, TapTempo, measured_beat
from .glide import HeadGlide
from .looks import FIGURES, Frame, LooksEngine
from .mixxx_db import MixxxLibrary, TrackInfo
from .mixxx_link import MixxxState
from .rig import default_rig, head_picture
from .mixxx_link import SYSTEM_DECK
from .song_match import candidates
from .show_script import ScriptCache, ShowScript, analyze_track, source_zero_s

NO_MIXXX_AFTER_S = 2.0
RETRY_LOOKUP_S = 5.0
DEFAULT_LATENCY_MS = 23.0  # used until Mixxx reports its own output latency


@dataclass
class DeckTrack:
    serial: int
    info: Optional[TrackInfo] = None
    script: Optional[ShowScript] = None
    analyzing: bool = False
    looked_up: float = 0.0
    song: str = ""   # track_key(artist, title): the key a saved style is filed under
    source: str = ""  # where the song comes from when it is not a Mixxx deck ("Spotify")
    keys: tuple = ()  # song_match.candidates(): every key a saved style may be filed under
    # where a night's cut says its original's 0:00 sits, in the file's seconds (show_script.source_zero_s);
    # None for a whole song: its cues (cues.py) are in the original's seconds
    zero_s: Optional[float] = None
    _cue_script: tuple = (None, None, None)   # (cues, analysis) it was made from, and his section list

    def __post_init__(self):
        if self.info is not None and not self.keys and (self.info.artist or self.info.title):
            self.keys = candidates(self.info.artist, self.info.title)
        if self.keys and not self.song:
            self.song = self.keys[0]


class Show:
    def __init__(self, library: Optional[MixxxLibrary] = None, cache: Optional[ScriptCache] = None,
                 latency_ms: Optional[float] = None, offset_ms: float = 0.0, analyze: bool = True,
                 venue=None):
        self.library, self.cache, self.analyze = library, cache, analyze
        self.latency_ms_fixed, self.offset_ms = latency_ms, offset_ms
        self.state = MixxxState()
        self.clock = BeatClock()
        self.tap = TapTempo()
        self.looks = LooksEngine()
        self.glide = HeadGlide()
        # The Light studio's layers (studio.py). The app hands every run the one it keeps for the
        # whole launch; a show made on its own gets an untouched one, which changes nothing.
        self.studio = studio_mod.Studio(live=False)
        self._studio_play = ""   # the moment the studio holds through show_settings' draft
        self._studio_dark = self._studio_strobe = self._studio_scene = False
        self._night_keys: tuple = ()
        if venue is not None:  # venue.Layout: aim and chase order follow where lights sit
            self.looks.apply_venue(venue)
        self.rig = default_rig()
        self.tracks: dict[int, DeckTrack] = {}
        self.lock = threading.Lock()
        self.last_frame: Optional[Frame] = None
        self._clock_source: Optional[tuple[int, int]] = None  # (deck, track serial) the clock follows
        self._tl_deck: Optional[int] = None   # the deck last followed: the cue timeline stays on it when paused

    # --- inputs ------------------------------------------------------------------------

    def on_midi(self, msg, now: Optional[float] = None) -> None:
        now = time.perf_counter() if now is None else now
        with self.lock:
            deck = self.state.feed(msg, now)
            if deck is None or deck.last_tick != now:
                return
            followed = self.state.pick_followed(now)
            if followed is None:
                self.clock.running = False  # paused or faded out: hold the count
                return
            if followed is not deck:
                return
            grid = self._deck_track(deck.deck)
            source = (deck.deck, deck.track_serial)
            predicted = (self.clock.predict(now)
                         if self.clock.running and source == self._clock_source else None)
            beat = measured_beat(deck.pos_frames, deck.beat_distance, deck.samplerate,
                                 deck.file_bpm or deck.bpm, grid, predicted)
            self.clock.update(beat, deck.bpm, deck.playing, now)
            self._clock_source = source

    def _deck_track(self, deck: int):
        t = self.tracks.get(deck)
        return t.info.grid if t and t.info else None

    def tap_tempo(self, now: Optional[float] = None) -> Optional[float]:
        now = time.perf_counter() if now is None else now
        bpm = self.tap.tap(now)
        if bpm and self.mixxx_silent(now):
            with self.lock:
                self.clock.free_run(bpm, round(self.clock.beat_at(now)), now)
        return bpm

    def set_venue(self, layout) -> None:
        """Switch layouts mid-show; the next frame aims from the new spots."""
        with self.lock:
            self.looks.apply_venue(layout)

    def mixxx_silent(self, now: float) -> bool:
        return now - self.state.last_message > NO_MIXXX_AFTER_S

    # --- slow work (main thread) -------------------------------------------------------

    def control_tick(self, now: Optional[float] = None) -> None:
        now = time.perf_counter() if now is None else now
        with self.lock:
            self.state.pick_followed(now)
            pending = [(d.deck, d.track_serial, d.samplerate, d.duration, d.file_bpm)
                       for d in self.state.decks.values()
                       if d.loaded and d.track_serial and self._needs_lookup(d.deck, d.track_serial, now)]
        self._tell_night(now)
        for deck, serial, rate, duration, file_bpm in pending:
            info = self.library.find_track(rate, duration, file_bpm) if self.library else None
            script = self.cache.get(info.track_id, info.location) if info and self.cache else None
            zero = source_zero_s(info.location) if info and info.location else None
            entry = DeckTrack(serial, info, script, looked_up=now, zero_s=zero)
            with self.lock:
                self.tracks[deck] = entry
            if info and info.grid and not script and self.analyze and info.location:
                entry.analyzing = True
                threading.Thread(target=self._analyze, args=(entry,), daemon=True).start()

    def _tell_night(self, now: float) -> None:
        """Tonight's list hears which song Mixxx is on (tonight.Tonight.see), once per song."""
        night = self.studio.night
        if night is None:
            show_settings.set_soft_now(False)
            show_settings.set_still_now(False)
            show_settings.set_gentle_now(False)
            return
        with self.lock:
            t = self.tracks.get(self.state.followed) if self.state.followed else None
            keys = tuple(t.keys) if t else ()
        with self.studio.lock:
            if keys != self._night_keys:
                self._night_keys = keys
                night.see(self.studio, keys, now)
            # said every tick (it lapses when not repeated): Next moves the night without a new song
            show_settings.set_soft_now(night.soft_now(), night.spared_keys(), part=night.soft_part_now())
            show_settings.set_still_now(night.still_now(), night.dancing_keys())   # heads only in the dances
            show_settings.set_gentle_now(night.gentle_now(), night.dancing_keys())

    def _needs_lookup(self, deck: int, serial: int, now: float) -> bool:
        t = self.tracks.get(deck)
        if t is None or t.serial != serial:
            return True
        # A miss is retried: Mixxx saves a new track's row (and tonight's BPM edits) lazily.
        return t.info is None and self.library is not None and now - t.looked_up > RETRY_LOOKUP_S

    def _analyze(self, entry: DeckTrack) -> None:
        try:
            script = analyze_track(entry.info.location, entry.info.grid)
        except Exception:  # unreadable file, missing decoder: stay on autoloops
            script = None
        if script and self.cache:
            self.cache.put(entry.info.track_id, script)
        with self.lock:
            entry.script, entry.analyzing = script, False

    # --- output ------------------------------------------------------------------------

    @property
    def latency_ms(self) -> float:
        """How far behind the beat clock the lights run: the sound's own path out of the laptop, plus
        the rig's Sync (rig.sync_ms, Llano PM #23787): the time the speakers take after that, which
        nothing on the laptop can see. His Bluetooth speaker played I Gotta Feeling 0.98 s after Mixxx
        (his 11-15 video), so every drop lit a second early."""
        return self._out_ms() + sync_ms()

    def _out_ms(self) -> float:
        if self.latency_ms_fixed is not None:
            return self.latency_ms_fixed
        if self.state.followed == SYSTEM_DECK:  # the speakers: Mixxx's output latency says nothing about them
            return DEFAULT_LATENCY_MS
        return self.state.output_latency_ms or DEFAULT_LATENCY_MS

    def frame(self, now: float) -> Frame:
        with self.lock:
            beat = self.clock.beat_at(now, (self.latency_ms - self.offset_ms) / 1000.0)
            deck = self.state.decks.get(self.state.followed) if self.state.followed else None
            if self.mixxx_silent(now):  # no Mixxx: tap tempo / free run on autoloops
                if self._clock_source is not None:
                    # Mixxx went quiet mid-song (crashed, froze, the MIDI port dropped): the music
                    # stopped with it, so the show does too, instead of dancing on at the last
                    # tempo (his 11-09 wedding check). A tap (tap_tempo) starts a free run again.
                    self.clock.running = False
                    self._clock_source = None
                return Frame(beat, self.clock.bpm, self.clock.running, level=0.6, now=now)
            if deck is None:
                return Frame(beat, self.clock.bpm, False, now=now)
            track = self.tracks.get(deck.deck)
            self._tl_deck = deck.deck
            script = track.script if track else None
            grid = track.info.grid if track and track.info else None
            cues = cues_mod.for_song(show_settings.current(), track.keys) if track else ()
            if cues and grid is not None:
                script = self._cue_script(track, cues, grid, script)
            section, nxt = script.at(beat) if script else (None, None)
            secs = None
            if grid is not None:
                file_s = grid.seconds_at(beat)
                secs = None if file_s is None else file_s - (track.zero_s or 0.0)
            feel = (cues_mod.feel_at(cues, beat, secs, section, grid, track.zero_s)
                    if cues and grid is not None else ("", ""))
            return Frame(beat, deck.bpm, deck.playing, level=deck.level, loop_beats=deck.loop_beats,
                         section=section, next_section=nxt,
                         track_key=track.info.track_id if track and track.info else deck.track_serial,
                         song=track.song if track else "", song_keys=track.keys if track else (), now=now,
                         secs=secs, cues=cues, feel=feel)

    @staticmethod
    def _cue_script(track: DeckTrack, cues: tuple, grid, script):
        """His section list for this deck (cues.script_for), made once per change of his cues."""
        made_from, analysis, mine = track._cue_script
        if made_from != cues or analysis is not script:
            mine = cues_mod.script_for(cues, grid, track.zero_s, script)
            track._cue_script = (cues, script, mine)
        return mine

    def render(self, now: float) -> bytes:
        f = self.frame(now)
        self.last_frame = f
        st = self.studio
        with self.lock, st.lock:  # set_venue swaps the layout under the show's lock; a command takes the studio's
            st.clock = now
            ov = self.looks.overrides
            setup = bool(ov.lineup or ov.raw_head or ov.aim_set)   # lining up: the studio stands aside
            live = not st.idle() and not setup
            self._studio_look(st if live else None)
            cued = bool(f.cues) and not setup and not (live and self._studio_holds(st)) and self._cues_play()
            if cued and f.feel[1] and ov.color is None:   # his color for this stretch (the studio's wins)
                rgb_ = studio_mod.parse_color(f.feel[1])
                ov.color = studio_mod.hue_sat(rgb_) if rgb_ else None
            rig = self.looks.render(f, self.rig)
            if cued:
                cues_mod.apply_feel(rig, f.feel[0])
                if f.playing:
                    cues_mod.apply_hit(rig, *cues_mod.hit_at(f.cues, f.secs))
            follow = False
            if live:
                # The studio's layers on the lights set up tonight: freeze, the crossfade, spots,
                # touch-ups and pins, brightness by zone, the buttons he holds; then the guards again.
                counts = (show_settings.current().get("rig") or {}).get("counts")
                st.layout, st.cfg = self.looks.venue, self.looks._cfg
                st.post(self.rig.present(counts), now, showing=self.looks.showing, mode=self.looks.mode)
                self.looks.guard(self.rig.present(counts))
                follow = st.spotting()
            # Heads glide to the show's aim (glide.py); line-up and calibration poses land raw.
            self.glide.pan_range, self.glide.tilt_range = venue.PAN_RANGE, venue.TILT_RANGE
            self.glide.rest = self._rest()
            # Line-up and calibration jumps glide calmly; a nudge lands at once (glide.py, 1.16.0).
            self.glide.apply(rig, now, calm=setup,
                             snap=self.looks.move_shape == "snap" and not follow,
                             figure=self.looks.move_shape in FIGURES and not follow,
                             follow=studio_mod.spot_gate_steps() if follow else 0.0)
            return bytes(rig.render())

    @staticmethod
    def _studio_holds(st) -> bool:
        """The studio holds the lights itself: a look or pad, a blackout, a frozen frame, a hit he
        holds, or Stop heads. Its crossfade, brightness, speed, pins and spots are not that: on the app's
        own studio the crossfade is never 0 (3 s by default), so idle() is never true there and gating
        cues on it turned every cue off on the laptop (fresh review of PM #23787)."""
        return bool(st.look or st.blackout or st.frozen or st.hits or st.heads_stop)

    def _cues_play(self) -> bool:
        """His cues play over the show's look, not over a blackout, a scene pad, a moment or look he
        holds, or a cocktail-hour/dinner song (those stay the soft wash his rule says, 2026-11-13)."""
        ov = self.looks.overrides
        return not (ov.blackout or ov.simple or ov.scene or self.looks.active_scene()
                    or self.looks.limit == "soft" or self.looks.showing == "draft")

    def _studio_look(self, st) -> None:
        """Hand the studio's held look to the looks engine through its overrides: a simple look, a
        scene pad, or a wedding moment played as the draft with no end. `st` None = the studio is
        idle (or he is lining up the lights): everything it set is taken back, and nothing it never
        set is touched (the classic window's blackout, strobe and scene keys stay his)."""
        ov = self.looks.overrides
        kind, name, rgb_, _motion = st.held() if st is not None else (None, "", None, "")
        if kind == "simple":
            base = studio_mod.parse_color(studio_mod.SIMPLE[name]["color"])
            pick = rgb_ or base
            ov.simple = {"name": name, "rgb": studio_mod.full(pick) if pick else None}
        else:
            ov.simple = None
        ov.color = studio_mod.hue_sat(rgb_) if rgb_ and kind != "simple" else None
        ov.speed = st.speed if st is not None else 1.0
        dark = bool(st is not None and st.blackout)
        if dark != self._studio_dark:
            ov.blackout, self._studio_dark = dark, dark
        strobe = bool(st is not None and "strobe" in st.hits)
        if strobe != self._studio_strobe:
            ov.strobe, self._studio_strobe = strobe, strobe
        alone = self.looks.isolated   # a pad's preview (studio_peek.py): nothing shared is touched
        if kind == "scene":
            if ov.scene != name:
                ov.scene = name
                if not alone:
                    show_settings.clear_scene()
            self._studio_scene = True
        elif self._studio_scene:
            ov.scene, self._studio_scene = None, False
        want = ""
        if kind == "moment":
            want = f"{name}|{st.motion}|{st.speed}"
            if want != self._studio_play:
                if alone:
                    self.looks.play = st.style_for(name)
                else:
                    label = next(m["name"] for m in moments.MOMENTS if m["key"] == name)
                    show_settings.set_play(st.style_for(name), float("inf"), label=label)
        elif alone:
            self.looks.play = None
        elif self._studio_play and show_settings.play_label():   # never a draft Llano sent since
            show_settings.clear_play()
        self._studio_play = want

    def timeline(self) -> "dict | None":
        """The song playing as the cue timeline draws it (Llano PM #23787), or None: its key (where its
        cues are filed), its sections and cues in the original's seconds, where it is now (`secs`), and
        `zero`, the file's offset from the original (the screen shows Mixxx's time, original + zero).
        Paused, Mixxx follows no deck, so this stays on the song last followed and reads where it stands
        from the deck itself: pausing on a note is how he places a cue on it. Playing, `secs` is the
        lights' own position (after Sync), so a cue added on the fly lands where he saw it light.
        Never fails a frame or a poll."""
        try:
            with self.lock:
                n = self.state.followed if self.state.followed is not None else self._tl_deck
                track = self.tracks.get(n) if n is not None else None
                deck = self.state.decks.get(n) if n is not None else None
                if track is None or deck is None or not track.keys or track.info is None or track.info.grid is None:
                    return None
                grid, zero, f = track.info.grid, track.zero_s or 0.0, self.last_frame
                doc = show_settings.current()
                table = doc.get("cues") or {}
                key = next((k for k in track.keys if table.get(k)), track.keys[0])
                cues = cues_mod.for_song(doc, track.keys)
                script = self._cue_script(track, cues, grid, track.script) if cues else track.script
                length = float(deck.duration or 0.0)
                if f is not None and f.playing and f.secs is not None and self.state.followed == n:
                    here = f.secs
                elif deck.samplerate:
                    here = deck.pos_frames / deck.samplerate - zero
                else:
                    here = None
                secs = []
                for sec in (script.sections if script else []):
                    a, b = grid.seconds_at(sec.start_beat), grid.seconds_at(sec.end_beat)
                    if a is None or b is None:
                        continue
                    a, b = a - zero, (min(b, length) if length else b) - zero
                    if b > a:
                        secs.append({"kind": sec.kind, "start": round(a, 2), "end": round(b, 2)})
                # a beat of the FILE (cue times are file seconds): the grid's tempo, not the pitch fader's
                bpm = grid.bpm or deck.file_bpm or deck.bpm or 120.0
                b0 = grid.seconds_at(0)
                return {"key": key, "title": track.info.label, "zero": round(zero, 3), "length": round(length, 2),
                        "secs": None if here is None else round(here, 2),
                        "playing": bool(deck.playing), "beat_s": round(60.0 / bpm, 4), "sections": secs,
                        "beat0": None if b0 is None else round(b0 - zero, 3),
                        "cues": list(table.get(key) or []), "mine": any(c.get("do") == "section" for c in cues)}
        except Exception:  # noqa: BLE001 -- a screen nicety, never a reason to drop a frame
            return None

    def picture_slots(self) -> dict:
        """The room picture's unrounded head pan/tilt (1.16.3, glide.HeadGlide.picture): universe
        slot -> 0..255, through the rig's head settings. Empty if anything about it fails: the
        picture then draws the bytes, and the output never waits on it."""
        try:
            with self.lock:
                return head_picture(self.glide.picture())
        except Exception:  # noqa: BLE001 -- a picture nicety, never a reason to drop a frame
            return {}

    def park(self, now: float) -> bytes:
        """One frame of Stop's park (1.16.0): everything dark, every head gliding calmly home to
        straight ahead and level, the pose the rig is left in, instead of slamming there in one frame.
        Straight ahead is the pan twin nearest DMX middle (venue.rest_pan, 1.16.4), never pan 0 at the
        end of the motor's range, so a head parks the short way and stays off its end stop; held the
        way round the rig's heads face their spots (`_rest`, 1.16.7)."""
        with self.lock:
            self.rig.reset()
            self.glide.rest = rest = self._rest()
            for bar in self.rig.bars:
                for head in bar.movers:
                    head.pan, head.tilt = rest
            self.glide.apply(self.rig, now, calm=True)
            return bytes(self.rig.render())

    def _rest(self) -> tuple:
        """Raw (pan, tilt) the heads rest at: the layout's (venue.Layout.rest_pose, 1.16.7: on the side
        its calibrated heads face their spots from), else straight ahead on the middle twin, tilt 0."""
        lay = getattr(self.looks, "venue", None)
        try:
            return lay.rest_pose() if lay is not None else (venue.rest_pan(venue.PAN_RANGE), 0.0)
        except Exception:  # noqa: BLE001 -- a layout that can't say parks where every version did
            return (venue.rest_pan(venue.PAN_RANGE), 0.0)

    def status(self, now: Optional[float] = None) -> str:
        now = time.perf_counter() if now is None else now
        f = self.last_frame
        if self.mixxx_silent(now):
            src = f"no Mixxx (tap tempo {self.clock.bpm:.1f})"
        elif self.state.followed is None:
            src = "Mixxx connected, nothing playing"
        else:
            t = self.tracks.get(self.state.followed)
            if self.state.followed == SYSTEM_DECK:  # Spotify, a browser tab: sections come from the beat alone
                name = t.info.label if t and t.info and t.info.label != f"track {t.info.track_id}" else "a song"
                src = f"{t.source if t else 'the speakers'}: {name}"
            else:
                name = t.info.label if t and t.info else "unknown track"
                tag = " analyzing" if t and t.analyzing else "" if t and t.script else " no script"
                src = f"deck {self.state.followed}: {name}{tag}"
        pos = f"bar {f.bar + 1} beat {int(f.beat_in_bar) + 1}" if f else ""
        playing = self.looks.showing
        scene = self.looks.active_scene()
        if scene:
            playing = f" | scene {scene}" + ("" if self.looks.overrides.scene == scene else " (from Llano)")
        elif playing == "draft" and show_settings.play_label():
            playing = f" | moment {show_settings.play_label()}"
        elif playing == "draft":
            left = max(0, int(show_settings.play_until() - time.time()))
            playing = f" | playing Llano's draft ({left // 60}:{left % 60:02d} left)"
        elif playing.startswith("show:"):
            playing = f" | show look {playing[5:]}"
        elif playing:
            playing = f" | style {playing[6:]}"
        return (f"{src} | {self.clock.bpm:.1f} BPM {pos} | {self.looks.mode}{playing} | "
                f"latency {self.latency_ms:.0f} ms offset {self.offset_ms:+.0f} ms")


def sync_ms() -> float:
    """The rig's Sync from the saved settings; 0 if they can't say (a show never stops for it).
    LLANO_LIGHTS_SYNC=0 turns it off (the lights run as 1.34 did)."""
    if os.environ.get("LLANO_LIGHTS_SYNC", "1") == "0":
        return 0.0
    try:
        v = (show_settings.current().get("rig") or {}).get("sync_ms") or 0
        return float(min(max(v, 0), 3000))
    except Exception:  # noqa: BLE001 -- a settings read never drops a frame
        return 0.0


def default_cache_dir() -> Path:
    return Path.home() / ".gigbar_lights" / "scripts"
