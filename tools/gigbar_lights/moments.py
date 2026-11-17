"""Wedding moments and cues: ready-made shows for the moments of a wedding or a live party (PM #22309).

A copy of aios scripts/lights/moments.py (only the import differs), so the laptop window offers the
same moments as the phone with no internet (1.10.0, his recording 11:12). Change both together.

Operator, 2026-11-08 (room llano-lights-show-designer, approved): one-tap looks for dinner,
first dance, father-daughter dance, party and the reveal, plus cues for the entrance, the toast,
cake cutting, the last dance and photos; and /lights opens with them ready to try, a sample show
rather than an empty page.

Each moment is a whole show (every song section), written here as data and normalized by
settings_contract, so it can never ask the engine for something it cannot play. A moment reaches
the laptop only through the existing paths: previewed as the draft (store.try_moment, then Push
live / Save as a style / tie to a song as any draft), or made the show at once (store.moment_live,
one change that Undo puts back).

Every moment's colors live in the palettes named "moment" and "moment-2", so trying one moment
after another reuses those two names instead of piling new palettes onto the show.

  moment  song-long looks: dinner, first dance, father-daughter dance, party, the reveal, last dance
  cue     short moments of the night: entrance, toast, cake cutting, photo mode

Moving heads run by themselves only in the dances (Llano BL #12339, his rule 2026-11-14, changed the
same day to "move on their own in the dances"): the first dance and the father-daughter dance glide
them slowly over the dance floor (looks.GENTLE_MOVE); dinner, the entrance, the toast, cake cutting and
photo mode keep them off. Party, the reveal and the last dance are Dancing; the Spotlight pads are his
own controls.
"""
from __future__ import annotations

import copy

from . import settings_contract as contract

PAL, PAL2 = "moment", "moment-2"


def _mv(shape: str, a: str, b: str, beats: int = 16, spread: str = "mirror", size: float = 0.5) -> dict:
    return {"shape": shape, "from": a, "to": b, "size": size, "beats": beats, "spread": spread}


def _sec(move: dict, *, wash: float = 1.0, movers: float = 1.0, pulse: float = 1.0, strobe: float = 1.0,
         derby: bool = False, laser: bool = False, color_bars: int = 0) -> dict:
    return {"wash": wash, "movers": movers, "pulse": pulse, "strobe": strobe, "derby": derby, "laser": laser,
            "color_bars": color_bars, "move": move}


def _same(sec: dict) -> dict:
    """One look for the whole song (a cue holds steady whatever section the track is in)."""
    return {s: copy.deepcopy(sec) for s in contract.SECTIONS}


def _gentle(move: dict, **kw) -> dict:
    return _same(_sec(move, **{"pulse": 0.15, "strobe": 0.0, **kw}))


_CALM = {"intensity": 0.0, "speed": 0.3, "build_ramp": False, "loop_auto": False}
_NO_DROP = {"intensity": 0.4, "burst": False}

MOMENTS: list[dict] = [
    {"key": "dinner", "name": "Dinner", "kind": "moment",
     "note": "Warm amber and soft rose, low and still, so people can talk.",
     "style": {"palettes": {PAL: [[0.08, 0.95], [0.06, 0.92]]}, "saturation": 0.7,
               "sections": _gentle(_mv("hold", "booth", "booth"), wash=0.6, movers=0.0),
               "drop": _NO_DROP, "strobe": _CALM}},
    {"key": "first-dance", "name": "First dance", "kind": "moment",
     "note": "Rose and violet around the couple, the heads gliding slowly on the floor, no strobe.",
     "style": {"palettes": {PAL: [[0.92, 0.78], [0.95, 0.83]]}, "saturation": 0.8,
               "sections": _gentle(_mv("glide", "booth", "crowd", 32, size=0.3), wash=0.75, movers=0.55),
               "drop": _NO_DROP, "strobe": _CALM}},
    {"key": "father-daughter", "name": "Father-daughter dance", "kind": "moment",
     "note": "Soft gold with a little blush, the heads gliding slowly on the floor, no strobe.",
     "style": {"palettes": {PAL: [[0.08, 0.11], [0.11, 0.95]]}, "saturation": 0.65,
               "sections": _gentle(_mv("glide", "booth", "crowd", 32, size=0.3), wash=0.75, movers=0.5),
               "drop": _NO_DROP, "strobe": _CALM}},
    {"key": "party", "name": "Party", "kind": "moment",
     "note": "Full color and full energy: derby and lasers in the drops, colors on the phrase.",
     "style": {"palettes": {PAL: [[0.83, 0.5], [0.0, 0.62], [0.15, 0.75], [0.33, 0.83]],
                            PAL2: [[0.62, 0.5], [0.78, 0.55]]},
               "section_palette": {"intro": PAL2, "verse": PAL, "build": PAL2, "drop": PAL, "main": PAL,
                                   "breakdown": PAL2, "outro": PAL2},
               "sections": copy.deepcopy(contract.SECTION_DEFAULTS),
               "drop": {"intensity": 1.0, "burst": True},
               "strobe": {"intensity": 0.8, "speed": 1.0, "build_ramp": True, "loop_auto": True}}},
    {"key": "reveal", "name": "Big reveal", "kind": "moment",
     "note": "Deep blue that climbs through the build, then a huge white hit on the drop.",
     "style": {"palettes": {PAL: [[0.62, 0.7]], PAL2: [[0.15, 0.08]]},
               "section_palette": {"intro": PAL, "verse": PAL, "build": PAL, "drop": PAL2, "main": PAL2,
                                   "breakdown": PAL, "outro": PAL},
               "saturation": {"drop": 0.25, "main": 0.45},
               "sections": {**_gentle(_mv("hold", "crowd", "crowd", 16), wash=0.7, movers=0.6, pulse=0.4),
                            "build": _sec(_mv("rise", "crowd", "ceiling"), strobe=1.0),
                            "drop": _sec(_mv("snap", "cross", "fan", 4), derby=True, laser=True, color_bars=4),
                            "main": _sec(_mv("snap", "cross", "fan", 4), derby=True, color_bars=8)},
               "drop": {"intensity": 1.0, "burst": True},
               "strobe": {"intensity": 1.0, "speed": 1.0, "build_ramp": True, "loop_auto": True}}},
    {"key": "last-dance", "name": "Last dance", "kind": "moment",
     "note": "Warm verses that open into violet choruses, big but no harsh strobe.",
     "style": {"palettes": {PAL: [[0.04, 0.08], [0.95, 0.06]], PAL2: [[0.78, 0.62], [0.83, 0.72]]},
               "section_palette": {"intro": PAL, "verse": PAL, "build": PAL2, "drop": PAL2, "main": PAL2,
                                   "breakdown": PAL, "outro": PAL},
               "sections": {**_same(_sec(_mv("glide", "crowd", "fan", 16), pulse=0.5, strobe=0.3, color_bars=8)),
                            "drop": _sec(_mv("sweep", "fan", "crowd", 8), derby=True, strobe=0.3, color_bars=8),
                            "main": _sec(_mv("sweep", "fan", "crowd", 8), derby=True, strobe=0.3, color_bars=8)},
               "drop": {"intensity": 0.8, "burst": False},
               "strobe": {"intensity": 0.3, "speed": 0.5, "build_ramp": False, "loop_auto": False}}},
    {"key": "entrance", "name": "Grand entrance", "kind": "cue",
     "note": "Warm white on the floor for the walk in, opening to the whole room on the drop. The moving heads stay off.",
     "style": {"palettes": {PAL: [[0.1, 0.08]]}, "saturation": {s: 0.35 for s in contract.SECTIONS},
               "sections": {**_gentle(_mv("hold", "crowd", "crowd", 16), wash=0.8, movers=0.0, pulse=0.2),
                            "build": _sec(_mv("hold", "crowd", "crowd"), movers=0.0, strobe=0.0),
                            "drop": _sec(_mv("hold", "crowd", "crowd"), movers=0.0, strobe=0.0),
                            "main": _sec(_mv("hold", "crowd", "crowd"), movers=0.0, strobe=0.0)},
               "drop": {"intensity": 1.0, "burst": True}, "strobe": _CALM}},
    {"key": "toast", "name": "Toast", "kind": "cue",
     "note": "A warm, steady wash with nothing moving, so speeches and photos look good.",
     "style": {"palettes": {PAL: [[0.08, 0.06]]}, "saturation": 0.5,
               "sections": _same(_sec(_mv("hold", "booth", "booth"), wash=0.9, movers=0.0, pulse=0.0, strobe=0.0)),
               "drop": _NO_DROP, "strobe": _CALM}},
    {"key": "cake", "name": "Cake cutting", "kind": "cue",
     "note": "Soft pink and warm white, held on the room, barely breathing.",
     "style": {"palettes": {PAL: [[0.95, 0.1]]}, "saturation": 0.45,
               "sections": _same(_sec(_mv("hold", "crowd", "crowd"), wash=0.85, movers=0.0, pulse=0.1, strobe=0.0)),
               "drop": _NO_DROP, "strobe": _CALM}},
    # Spotlights (1.16.0): the heads aim together through Line up my lights' calibration, so they
    # meet on the real floor; without a layout they play as a plain parallel move.
    {"key": "spotlight", "name": "Spotlight", "kind": "cue",
     "note": "Every moving head on one white spot that roams the dance floor slowly, the room dim around it.",
     "style": {"palettes": {PAL: [[0.66, 0.85]]}, "saturation": 0.6,
               "sections": _same(_sec(_mv("circle", "crowd", "crowd", 32, spread="spotlight", size=0.7),
                                      wash=0.25, movers=1.0, pulse=0.1, strobe=0.0)),
               "drop": _NO_DROP, "strobe": _CALM}},
    {"key": "two-spotlights", "name": "Two spotlights", "kind": "cue",
     "note": "Each GigBAR's two heads on one spot, the two spots roaming the floor as mirror images.",
     "style": {"palettes": {PAL: [[0.78, 0.8]]}, "saturation": 0.6,
               "sections": _same(_sec(_mv("eight", "crowd", "crowd", 32, spread="spotlights", size=0.6),
                                      wash=0.3, movers=1.0, pulse=0.15, strobe=0.0)),
               "drop": _NO_DROP, "strobe": _CALM}},
    {"key": "photo", "name": "Photo mode", "kind": "cue",
     "note": "Steady, flattering light for group shots: no strobe, no movement, no color shifts.",
     "style": {"palettes": {PAL: [[0.09, 0.09]]}, "saturation": 0.3,
               "sections": _same(_sec(_mv("hold", "booth", "booth"), wash=1.0, movers=0.0, pulse=0.0, strobe=0.0)),
               "drop": _NO_DROP, "strobe": _CALM}},
]

KEYS = tuple(m["key"] for m in MOMENTS)


def style(key: str) -> dict:
    """Moment `key` as a whole, valid style (raises ContractError for an unknown key)."""
    m = next((m for m in MOMENTS if m["key"] == key), None)
    if m is None:
        raise contract.ContractError(f"no moment called {key!r}; the moments are: {', '.join(KEYS)}")
    raw = copy.deepcopy(m["style"])
    if not isinstance(raw.get("section_palette"), dict):
        raw["section_palette"] = {s: PAL for s in contract.SECTIONS}
    if isinstance(raw.get("saturation"), (int, float)):
        raw["saturation"] = {s: raw["saturation"] for s in contract.SECTIONS}
    full = contract.merge_style(contract.style_of(contract.defaults()), raw)
    # Only this moment's own palettes: the built-ins would ride along otherwise.
    full["palettes"] = {k: v for k, v in full["palettes"].items() if k in (PAL, PAL2)}
    full["note"] = f"{m['name']}: {m['note']}"
    return contract.normalize_style(full)


def catalog() -> list[dict]:
    """Every moment for the page and the Conductor, in order: key, name, kind, note, style."""
    return [{"key": m["key"], "name": m["name"], "kind": m["kind"], "note": m["note"], "style": style(m["key"])}
            for m in MOMENTS]
