"""A song's own cues on the lights (the cue timeline, Llano PM #23787).

He sets cues on a song's timeline (settings `cues`, by track key, in seconds into the original
recording; settings_contract.cue): a white hit on an instant, a section that starts where he says,
or a stretch played bigger, softer or in one color. This module turns them into what the engine
plays, for show.Show:

  - `for_song(doc, keys)`: the cues of the song playing, under any of its spellings;
  - `script_for(cues, grid, zero_s, script)`: his section list as a ShowScript on the deck's beats,
    replacing the analysis when he set any section, else the analysis as it is;
  - `feel_at(...)`: the bigger/softer/color of the stretch the song is in;
  - `hit_at(...)` and `apply_hit` / `apply_feel`: the white hit's envelope laid over a rendered frame.

Seconds are the original recording's. A night's cut (set_cuts) plays from a later point, and its file
says where the original's 0:00 sits in its own seconds (show_script.source_zero_s, `zero_s`), so the
deck's file seconds minus zero_s is the original's: a cue lands on the same note in the cut.

LLANO_LIGHTS_CUES=0 turns cues off (the lights play as 1.35 did).
"""
from __future__ import annotations

import os
from typing import Optional

from .show_script import Section, ShowScript

# A section he starts by hand plays with the energy a typical one of its kind has (shows.estimated_sections).
KIND_ENERGY = {"intro": 0.3, "verse": 0.5, "build": 0.6, "drop": 1.0, "main": 0.9, "breakdown": 0.35, "outro": 0.25}
# The white hit's shape, by size: (seconds held at full, seconds until it is gone, strobe burst seconds).
HIT_SHAPE = {1: (0.35, 0.6, 0.0), 2: (0.5, 1.0, 0.5)}
BIGGER, SOFTER = 1.35, 0.55   # level multipliers for a stretch played bigger or softer


def enabled() -> bool:
    return os.environ.get("LLANO_LIGHTS_CUES", "1") != "0"


def for_song(doc: Optional[dict], keys) -> tuple:
    """The song's cues (a tuple, so it can key a cache) under the first of its spellings that has any."""
    if not enabled():
        return ()
    table = (doc or {}).get("cues") if isinstance(doc, dict) else None
    if not isinstance(table, dict):
        return ()
    for k in keys or ():
        got = table.get(k)
        if got:
            return tuple(got)
    return ()


def _beat(grid, zero_s: Optional[float], at: float) -> Optional[float]:
    """The deck's beat at a cue's original-recording second."""
    b = grid.beat_at_seconds(at + (zero_s or 0.0)) if grid is not None else None
    return b


def script_for(cues: tuple, grid, zero_s: Optional[float], script: Optional[ShowScript]) -> Optional[ShowScript]:
    """His section list on this deck's beats, or `script` (the analysis) when he set none.
    A section starts on the nearest beat to his second and runs to the next one he set; the last runs on."""
    marks = []
    for c in cues:
        if c.get("do") != "section":
            continue
        b = _beat(grid, zero_s, c["at"])
        if b is not None:
            marks.append((int(round(b)), c["kind"]))
    if not marks:
        return script
    marks.sort()
    out: list[Section] = []
    for i, (b, kind) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else 1_000_000
        if end <= b:   # two marks on one beat: the later one is the section
            continue
        out.append(Section(kind, b, end, KIND_ENERGY.get(kind, 0.5)))
    return ShowScript(out, version=script.version if script else 1) if out else script


def feel_at(cues: tuple, beat: float, secs: Optional[float], section: Optional[Section], grid,
            zero_s: Optional[float]) -> tuple[str, str]:
    """(feel, color) for the stretch the song is in: the last feel cue inside the section playing;
    with no sections, the last feel cue at or before now. ("", "") when none."""
    feel, color = "", ""
    for c in cues:
        if c.get("do") != "feel":
            continue
        if section is not None:
            b = _beat(grid, zero_s, c["at"])
            if b is None or not (section.start_beat <= round(b) < section.end_beat):
                continue
        elif secs is None or c["at"] > secs:
            continue
        feel, color = c.get("feel") or "", c.get("color") or ""
    return feel, color


def hit_at(cues: tuple, secs: Optional[float]) -> tuple[float, bool]:
    """(how white 0..1, strobe burst on) for the hits around `secs` (original-recording seconds)."""
    if secs is None:
        return 0.0, False
    level, burst = 0.0, False
    for c in cues:
        if c.get("do") != "hit":
            continue
        dt = secs - c["at"]
        hold, gone, strobe = HIT_SHAPE[2 if c.get("size") == 2 else 1]
        if dt < 0 or dt >= gone:
            continue
        e = 1.0 if dt < hold else 1.0 - (dt - hold) / (gone - hold)
        level = max(level, e)
        burst = burst or dt < strobe
    return level, burst


def apply_hit(rig, level: float, burst: bool) -> None:
    """Lay a white hit over a rendered frame: every wash toward full white, heads open and up."""
    if level <= 0:
        return
    k = max(0.0, min(1.0, level))
    washes = [*rig.tetras, *rig.sticks, *(p for bar in rig.bars for p in bar.pars)]
    for fx in washes:
        fx.red += (1.0 - fx.red) * k
        fx.green += (1.0 - fx.green) * k
        fx.blue += (1.0 - fx.blue) * k
        fx.dim = max(fx.dim, k)
        if hasattr(fx, "amber"):
            fx.amber *= 1.0 - k
        if hasattr(fx, "uv"):
            fx.uv *= 1.0 - k
        if k >= 0.5:
            fx.strobe = 0.0   # a steady white, not a flicker
    for bar in rig.bars:
        for m in bar.movers:
            m.dim = max(m.dim, k)
            if k >= 0.5:
                m.color = 0   # open white
        if burst:
            bar.strobe_white, bar.strobe_speed = 1.0, max(bar.strobe_speed, 0.9)


def apply_feel(rig, feel: str) -> None:
    """A stretch played bigger (every level up) or softer (levels down, no strobe)."""
    if feel not in ("bigger", "softer"):
        return
    k = BIGGER if feel == "bigger" else SOFTER
    fixtures = [*rig.tetras, *rig.sticks, *(p for bar in rig.bars for p in bar.pars),
                *(m for bar in rig.bars for m in bar.movers)]
    for fx in fixtures:
        fx.dim = min(1.0, fx.dim * k)
    if feel == "softer":
        for bar in rig.bars:
            bar.strobe_white = 0.0
