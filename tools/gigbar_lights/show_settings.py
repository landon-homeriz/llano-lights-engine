"""The show's settings on this laptop: what the looks engine reads every frame.

Palettes, which palette each song section uses, saturation, drop and strobe strength,
autoloop looks, overall brightness, and which room layout is in use. The shape and its
defaults are settings_contract.py, the file Llano holds byte for byte too; with no
settings file the defaults are exactly the show this app always played.

The file lives with the saved layouts in ~/.gigbar_lights/settings.json, never in the
install folder, so updates keep it. A change (from the window, or pulled from Llano by
llano_sync.py) replaces one immutable snapshot that the engine picks up on its next frame:
no restart, and no frame ever mixes two versions.

A draft Llano asks the laptop to play (llano.app/lights "Play on laptop") is held here in
memory only, never in settings.json and never pushed back: it plays until its time runs
out (or Llano stops it), then the saved show is back on the next frame.

A saved show playing on this laptop (shows.py) is held here too, in memory only: the look each
of its songs plays, by track key, so a song in "Avery's wedding" can play slow-dance while the
same song filed under a style elsewhere keeps that style the rest of the time.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

from . import settings_contract as contract

_lock = threading.Lock()
_current: dict = contract.defaults()
_play: "tuple[dict, float] | None" = None   # (style, time.time() it stops)
_play_label = ""   # a moment picked in the window (1.10.0) names itself; "" = Llano's draft
_scene: "tuple[str, float] | None" = None   # a scene pad from Llano: (name, time.time() it lapses)
_show_looks: "dict | None" = None   # a saved show playing: {track key: look name}, None when none is
_show_own: dict = {}            # the playing show's own looks, by name


def current() -> dict:
    """The snapshot in force. Never mutate it; replace it with set_current()."""
    return _current


def set_current(doc) -> dict:
    global _current
    new = contract.normalize(doc)
    with _lock:
        _current = new
    from . import venue   # here, not at the top: venue is pure geometry and imports nothing of ours
    if venue.set_calibration_defaults(new["rig"]["calibration"]):
        print("Calibration defaults from the rig settings: pan {pan_range:g} deg, tilt {tilt_range:g} deg, "
              "straight down at tilt {tilt_down:g}".format(**new["rig"]["calibration"]))
    return new


def set_play(style, until: float, label: str = "") -> dict:
    """Play `style` (a draft from Llano, or a moment named `label`) instead of the saved show
    until `until` (epoch s)."""
    global _play, _play_label
    st = contract.normalize_style(style)
    _play, _play_label = (st, float(until)), str(label or "")
    return st


def clear_play() -> None:
    global _play, _play_label
    _play, _play_label = None, ""


def play_label() -> str:
    """The moment playing (its name), "" for Llano's draft or nothing."""
    return _play_label if playing() is not None else ""


def playing(now: "float | None" = None) -> "dict | None":
    """The draft style in force, or None once it has run out (or there is none)."""
    p = _play
    if p is None:
        return None
    return p[0] if (time.time() if now is None else now) < p[1] else None


def set_scene(name: str, until: float) -> None:
    """Play scene `name` (contract.SCENES) over the show until `until` (epoch s): memory only."""
    global _scene
    _scene = (name, float(until)) if name in contract.SCENES else None


def clear_scene() -> None:
    global _scene
    _scene = None


def scene(now: "float | None" = None) -> "str | None":
    """The scene Llano asked for, or None once it has lapsed (or there is none)."""
    sc = _scene
    if sc is None:
        return None
    return sc[0] if (time.time() if now is None else now) < sc[1] else None


def set_show_looks(looks: "dict | None", own: "dict | None" = None, soft=None, still=None, gentle=None) -> None:
    """The looks of the show now playing, {track key: look name ("" = the house show)}, and the
    show's own looks by name (Llano designed them for that night); None ends it. The engine works
    each look out against the settings in force, so a change mid-show applies. `soft` names the
    show's cocktail-hour and dinner songs (shows.soft_keys), `still` its songs whose heads stay dark and
    `gentle` its first dance and parent dances (shows.gentle_keys): the part-of-the-night limits, below."""
    global _show_looks, _show_own
    _show_looks = dict(looks) if looks is not None else None
    _show_own = dict(own or {}) if looks is not None else {}
    set_soft_songs("show", soft if looks is not None else None)
    set_still_songs("show", still if looks is not None else None)
    set_gentle_songs("show", gentle if looks is not None else None)
    if looks is None:   # the show ends: its moods and parts with it
        set_moods("show", None)
        set_soft_parts("show", None)


# The part-of-the-night limit (1.20.0, his rule 2026-11-13): a song that plays in cocktail hour or
# dinner gets a soft wash and nothing else, whatever look any design gave it. Two places say which
# songs those are: the show being followed, and the night built on this laptop (so the limit holds
# on the night with no box ticked). The engine asks once per song (looks.Looks.show_for).
_soft: dict = {"show": frozenset(), "night": frozenset()}
_soft_all: frozenset = frozenset()


def set_soft_songs(source: str, keys) -> None:
    """Every key the cocktail-hour and dinner songs could play under, from `source` ("show" or
    "night"); None or empty clears that source."""
    global _soft_all
    _soft[source] = frozenset(k for k in (keys or ()) if isinstance(k, str) and k)
    _soft_all = _soft["show"] | _soft["night"]


def soft_songs() -> frozenset:
    return _soft_all


# ...and while the night list stands on Cocktail hour or Dinner, EVERY song is held soft, a request
# nobody listed included (1.20.0). The Live show says so on every control tick (Show._tell_night)
# and clears it when it stops (__main__._run_loop). The word also lapses if nobody repeats it, as a
# backstop for a show that died without its cleanup; the lapse is long so a slow tick (a Mixxx
# library read waiting on a lock) never lets a cocktail-hour request play loud in between.
# `spared` are the songs the night lists in a step that is not cocktail hour or dinner (a moment's
# song filed in dinner's folder, the dancing, a hold): those keep their own look.
SOFT_NOW_TTL_S = 60.0
_soft_now: tuple = (False, 0.0, frozenset(), "")


def set_soft_now(on: bool, spared: frozenset = frozenset(), now: "float | None" = None, part: str = "") -> None:
    """`part` names which one the night stands on ("cocktail" or "dinner"), for its mood."""
    global _soft_now
    _soft_now = (bool(on), time.monotonic() if now is None else now, spared if on else frozenset(), part if on else "")


def soft_now(now: "float | None" = None) -> "frozenset | None":
    """None when the night does not stand on cocktail hour or dinner; else the songs it spares."""
    on, said, spared, _part = _soft_now
    return spared if on and (time.monotonic() if now is None else now) - said < SOFT_NOW_TTL_S else None


def soft_now_part() -> str:
    return _soft_now[3]


# The mood each soft part plays (Llano BL #12340): cocktail hour and dinner each get one color or a
# slow fade he picks, instead of each song's own colors. From the show being followed, else the
# night built on this laptop (and changed on the Live screen); Llano's suggestion when neither says.
# Which part a soft song belongs to: {track key: "cocktail" | "dinner"} per source.
_moods: dict = {"show": None, "night": None}
_soft_parts: dict = {"show": {}, "night": {}}


def set_moods(source: str, value) -> None:
    _moods[source] = contract.moods(value) if value is not None else None


def moods() -> dict:
    return _moods["show"] or _moods["night"] or contract.moods(None)


def set_soft_parts(source: str, parts) -> None:
    _soft_parts[source] = {k: p for k, p in (parts or {}).items()
                           if isinstance(k, str) and p in contract.MOOD_PARTS}


def soft_part(keys) -> str:
    """The part ("cocktail" / "dinner") a soft song plays in: where the night stands first, then the
    show's or the night's own list; "" when nobody says."""
    if soft_now() is not None and _soft_now[3]:
        return _soft_now[3]
    for src in ("show", "night"):
        for k in keys or ():
            if k in _soft_parts[src]:
                return _soft_parts[src][k]
    return ""


# The heads-only-in-the-dances limit (Llano BL #12339; his rule 2026-11-14, changed the same day: "I'd
# like the heads to move on their own in the dances with the option to stop them or take over").
# Moving heads run by themselves in Dancing, and gently in the first dance and the parent dances. A
# hold or a moment's song that is not a dance (the entrance, toasts, cake) keeps every head dark and
# still ("still"); the first dance and the parent dances keep them moving slowly on the dance floor
# ("gentle": looks.gentle_settings); the last dance and the closing song count as Dancing. Built like
# the soft limit: by song (the show's and the night's moment songs) and by where the night stands
# (set_still_now / set_gentle_now, said every control tick). His own controls stay his: a pad he
# presses, the Spotlight pads, Follow someone, Stop heads (looks.Looks.render, studio.Studio).
_still: dict = {"show": frozenset(), "night": frozenset()}
_still_all: frozenset = frozenset()
_still_now: tuple = (False, 0.0, frozenset())


def set_still_songs(source: str, keys) -> None:
    """Every key the moment songs that are not Dancing could play under, from `source` ("show" or
    "night"); None or empty clears that source."""
    global _still_all
    _still[source] = frozenset(k for k in (keys or ()) if isinstance(k, str) and k)
    _still_all = _still["show"] | _still["night"]


def still_songs() -> frozenset:
    return _still_all


def set_still_now(on: bool, spared: frozenset = frozenset(), now: "float | None" = None) -> None:
    """The night stands on a step that is not Dancing (a hold, a moment's song): every song is held
    still except `spared`, the songs the night plays in Dancing. Lapses like soft_now."""
    global _still_now
    _still_now = (bool(on), time.monotonic() if now is None else now, spared if on else frozenset())


def still_now(now: "float | None" = None) -> "frozenset | None":
    """None when the night does not stand on a step that is not Dancing; else the songs it spares."""
    on, said, spared = _still_now
    return spared if on and (time.monotonic() if now is None else now) - said < SOFT_NOW_TTL_S else None


_gentle: dict = {"show": frozenset(), "night": frozenset()}
_gentle_all: frozenset = frozenset()
_gentle_now: tuple = (False, 0.0, frozenset())


def set_gentle_songs(source: str, keys) -> None:
    """Every key the first dance and the parent dances could play under, from `source` ("show" or
    "night"); None or empty clears that source."""
    global _gentle_all
    _gentle[source] = frozenset(k for k in (keys or ()) if isinstance(k, str) and k)
    _gentle_all = _gentle["show"] | _gentle["night"]


def gentle_songs() -> frozenset:
    return _gentle_all


def set_gentle_now(on: bool, spared: frozenset = frozenset(), now: "float | None" = None) -> None:
    """The night stands on the first dance or a parent dance: every song moves the heads gently except
    `spared`, the songs the night plays in Dancing. Lapses like soft_now."""
    global _gentle_now
    _gentle_now = (bool(on), time.monotonic() if now is None else now, spared if on else frozenset())


def gentle_now(now: "float | None" = None) -> "frozenset | None":
    """None when the night does not stand on a gentle dance; else the songs it spares."""
    on, said, spared = _gentle_now
    return spared if on and (time.monotonic() if now is None else now) - said < SOFT_NOW_TTL_S else None


def show_looks() -> "dict | None":
    return _show_looks


def show_own_looks() -> dict:
    """The playing show's own looks ({} when none is playing or it has none)."""
    return _show_own


def play_until() -> float:
    """When the draft stops (epoch s), 0 if none is playing."""
    p = _play
    return p[1] if p is not None and playing() is not None else 0.0


def default_path() -> Path:
    from .venue import default_dir
    return default_dir() / "settings.json"


class SettingsFile:
    """settings.json: read at launch, written after every change (temp name, then rename)."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else default_path()

    def load(self) -> dict:
        try:
            return contract.normalize(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):  # ok: no file yet, or a hand-broken one = the shipped show
            return contract.defaults()

    def save(self, doc) -> dict:
        doc = contract.normalize(doc)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        tmp.replace(self.path)
        return doc


def load_into_current(path: Optional[Path] = None) -> dict:
    return set_current(SettingsFile(path).load())
