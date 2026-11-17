"""A song's own cues on the lights (the cue timeline, Llano PM #23787).

He sets cues on a song's timeline (settings `cues`, by track key, in seconds into the original
recording; settings_contract.cue): a white hit on an instant, a section that starts where he says,
or a stretch played bigger, softer or in one color. This module turns them into what the engine
plays, for show.Show:

  - `for_song(doc, keys)`: the cues of the song playing, under any of its spellings;
  - `script_for(cues, grid, zero_s, script)`: his section list as a ShowScript on the deck's beats,
    replacing the analysis when he set any section, else the analysis as it is;
  - `feel_at(...)`: the bigger/softer/color of the stretch the song is in;
  - `hit_at(...)` and `apply_hit` / `apply_feel`: the white hit's envelope laid over a rendered frame;
  - `drop_at(...)`: the build-and-drop recipe the song plays at a moment (BL #12518).

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
# The hit's shape, by size: (seconds held at full, seconds until it is gone, strobe burst seconds).
# 1.36 held a size 1 for 0.35 s and a size 2 for 0.5 s over a drop look already at full: on Livin' on a
# Prayer he never saw it (BL #12518, "you're not even doing that"). A 2 is now the white-out pad's look
# held a second, the strobes bursting through its first 0.6 s; a 1 holds half a second.
HIT_SHAPE = {1: (0.5, 0.9, 0.0), 2: (1.0, 1.8, 0.6)}
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


def hit_at(cues: tuple, secs: Optional[float]) -> tuple[float, bool, str]:
    """(how hard 0..1, strobe burst on, color "#rrggbb" or "" for white) for the hits around `secs`
    (original-recording seconds). The strongest hit playing sets the color."""
    if secs is None:
        return 0.0, False, ""
    level, burst, color = 0.0, False, ""
    for c in cues:
        if c.get("do") != "hit":
            continue
        dt = secs - c["at"]
        hold, gone, strobe = HIT_SHAPE[2 if c.get("size") == 2 else 1]
        if dt < 0 or dt >= gone:
            continue
        e = 1.0 if dt < hold else 1.0 - (dt - hold) / (gone - hold)
        if e > level:
            level, color = e, c.get("color") or ""
        burst = burst or dt < strobe
    return level, burst, color


def drop_at(cues: tuple, secs: Optional[float]) -> tuple[str, str, str]:
    """(style, color, color2) for the builds and drops at `secs`: the last drop cue at or before it.
    The song's first drop cue also covers the song before it (a style set at 0:12 is the song's style),
    and with no clock the first one plays. ("classic", "", "") when the song has none (BL #12518)."""
    ds = [c for c in cues if c.get("do") == "drop"]
    if not ds:
        return "classic", "", ""
    pick = ds[0]
    if secs is not None:
        for c in ds:
            if c["at"] <= secs:
                pick = c
    return pick.get("style") or "classic", pick.get("color") or "", pick.get("color2") or ""


def _rgb(color: str) -> tuple[float, float, float]:
    try:
        return tuple(int(color[i:i + 2], 16) / 255.0 for i in (1, 3, 5))   # type: ignore[return-value]
    except (TypeError, ValueError, IndexError):
        return 1.0, 1.0, 1.0


def apply_hit(rig, level: float, burst: bool, color: str = "") -> None:
    """Lay a hit over a rendered frame: every wash toward full white (or the hit's color), every stick
    section lit, heads open and up, the GigBAR strobes as a white flood (the white-out pad's look)."""
    if level <= 0:
        return
    k = max(0.0, min(1.0, level))
    r, g, b = _rgb(color) if color else (1.0, 1.0, 1.0)
    washes = [*rig.tetras, *rig.sticks, *(p for bar in rig.bars for p in bar.pars)]
    for fx in washes:
        fx.red += (r - fx.red) * k
        fx.green += (g - fx.green) * k
        fx.blue += (b - fx.blue) * k
        fx.dim = max(fx.dim, k)
        if getattr(fx, "mask", None):   # a stick in sections: the whole stick lights
            fx.mask = [m + (1.0 - m) * k for m in fx.mask]
        if hasattr(fx, "amber"):
            fx.amber *= 1.0 - k
        if hasattr(fx, "uv"):
            fx.uv *= 1.0 - k
        if k >= 0.5:
            fx.strobe = 0.0   # a steady white, not a flicker
    for bar in rig.bars:
        for m in bar.movers:
            m.dim = max(m.dim, k)
            if k >= 0.5 and not color:
                m.color = 0   # open white
        if not color:   # the strobe LEDs are white: a steady flood on a white hit, as the white-out pad
            bar.strobe_white = max(bar.strobe_white, k)
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


# --- the cue workspace's stretches (Llano PM #23869) ------------------------------------------------------
# A blackout, a strobe burst, a repeat and a note last `len` seconds from `at` (settings_contract.cue).
# Live and in the workspace's picture of the show (cue_workspace.lanes) alike, the order is: the look
# renders (a repeat renders it from the earlier stretch, in its color), feel and hits go over it, a strobe
# burst over those, and a blackout last, so dark is dark.

STROBE_FLASH = 0.35   # share of a beat a strobe burst's flash stays lit


def stretch_at(cues: tuple, secs: Optional[float], do: str) -> Optional[dict]:
    """The `do` stretch playing at `secs` (the latest started wins), or None."""
    if secs is None:
        return None
    got = None
    for c in cues:
        if c.get("do") == do and c["at"] <= secs < c["at"] + float(c.get("len") or 0):
            got = c
    return got


def repeat_shift(rep: dict, grid, zero_s: Optional[float]) -> float:
    """How many beats back a repeat plays from: from `from` to `at`, in whole bars (at least one), so the
    replayed stretch keeps its place in the bar and phrase. 0 when the grid can't say."""
    a, b = _beat(grid, zero_s, rep["at"]), _beat(grid, zero_s, rep["from"])
    if a is None or b is None or a <= b:
        return 0.0
    return float(max(4, int(round((a - b) / 4.0)) * 4))


def replayed(cues: tuple, secs: Optional[float]) -> tuple[Optional[float], str]:
    """(the second a repeat replays at `secs`, its color) or (None, "") outside any repeat. The hits and
    strobe bursts of the earlier stretch play again with it, in the repeat's color."""
    rep = stretch_at(cues, secs, "repeat")
    if rep is None:
        return None, ""
    return rep["from"] + (secs - rep["at"]), rep.get("color") or ""


def apply_strobe(rig, beat: float) -> None:
    """A strobe burst: the pars at full and the GigBAR strobes flashing on every beat."""
    k = 1.0 if (beat % 1.0) < STROBE_FLASH else 0.0
    for bar in rig.bars:
        for p in bar.pars:
            p.dim = max(p.dim, k)
            if k:
                p.red, p.green, p.blue = max(p.red, 0.6), max(p.green, 0.6), max(p.blue, 0.6)
        bar.strobe_white, bar.strobe_speed = (1.0, 0.0) if k else (0.0, 0.0)
    for t in rig.tetras:
        t.dim = max(t.dim * 0.4, k)


def apply_blackout(rig) -> None:
    """Everything dark where it stands: the heads keep their aim so nothing swings on the way back."""
    for fx in (*rig.tetras, *rig.sticks, *(p for bar in rig.bars for p in bar.pars)):
        fx.dim = 0.0
        fx.red = fx.green = fx.blue = 0.0
        fx.strobe = 0.0
        if getattr(fx, "mask", None):
            fx.mask = [0.0] * len(fx.mask)
    for bar in rig.bars:
        for m in bar.movers:
            m.dim, m.strobe = 0.0, 0.0
        for d in bar.derbies:
            d.color, d.strobe = "off", 0.0
        bar.laser, bar.laser_strobe = "off", 0.0
        bar.strobe_white = bar.strobe_uv = 0.0
        bar.strobe_program = 0


def dress(rig, f) -> None:
    """Everything his cues lay over a rendered frame `f` (looks.Frame), in order: feel, hits (and the ones
    a repeat replays, in its color), a strobe burst, a blackout."""
    apply_feel(rig, f.feel[0])
    if not f.playing:
        return
    level, burst, color = hit_at(f.cues, f.secs)
    src, rep_color = replayed(f.cues, f.secs)
    if src is not None:
        lv2, b2, c2 = hit_at(f.cues, src)
        if lv2 > level:
            level, burst, color = lv2, b2, rep_color or c2
    apply_hit(rig, level, burst, color)
    if stretch_at(f.cues, f.secs, "strobe") or (src is not None and stretch_at(f.cues, src, "strobe")):
        apply_strobe(rig, f.beat)
    if stretch_at(f.cues, f.secs, "blackout"):
        apply_blackout(rig)


def place(cues: tuple, grid, zero_s: Optional[float], script: Optional[ShowScript], beat: float,
          secs: Optional[float]) -> tuple:
    """Where the look is in the song at `beat`: (beat the look plays, section, next section, feel).
    Inside a repeat the look plays the earlier stretch's beats (repeat_shift) in the repeat's color.
    Show.frame and the workspace's picture of the show (cue_workspace) both ask here."""
    look_beat = beat
    rep = stretch_at(cues, secs, "repeat") if cues else None
    if rep is not None and grid is not None:
        look_beat = beat - repeat_shift(rep, grid, zero_s)
    section, nxt = script.at(look_beat) if script else (None, None)
    feel = feel_at(cues, look_beat, secs, section, grid, zero_s) if cues and grid is not None else ("", "")
    if rep is not None and rep.get("color"):
        feel = (feel[0], rep["color"])
    return look_beat, section, nxt, feel
