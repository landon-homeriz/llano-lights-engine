"""Freedom Stick sections on the beat (BL #12518, his 11-16 "the sticks are only doing color").

In its 48CH/50CH mode a Freedom Stick is 16 sections, each its own RGB (rig.FreedomStick.mask). The
looks engine still sets each stick's color and level; this lays a shape over it, by the section of
the song playing:

  verse, main, intro past a count-in, breakdown: a lit block bounces bottom to top and back, one
      trip a bar, each stick a beat behind the one before (a chase across the four);
  build: the stick fills bottom to top through the build, rising from 40% to full brightness with
      the top section flickering on the beat, so it is full exactly when the drop lands ("whoa, we're halfway there" on Livin' on a Prayer);
  drop: the whole stick, a fast fill on each beat's first quarter;
  outro: the whole stick (the look fades it).

Never on a soft part of the night, a still or gentle look, a scene, a held look or a moment (the
caller decides), and an 8-CH stick never reads its mask, so nothing changes there.
LLANO_LIGHTS_STICK_FX=0 turns it off (every section lit, as before).
"""
from __future__ import annotations

import os

from .rig import STICK_SEGMENTS

BLOCK = 4            # sections lit in the bouncing block
FLOOR = 0.12         # how lit the rest of the stick stays under the block (a dark stick reads as off)
BUILD_FLOOR = 0.4    # a stick's level as a build starts; it rises to full with the fill


def enabled() -> bool:
    return os.environ.get("LLANO_LIGHTS_STICK_FX", "1") != "0"


def _bounce(phase: float) -> list:
    """The block's mask for a bar phase 0..1: up in the first half, down in the second."""
    pos = phase * 2 if phase < 0.5 else 2 - phase * 2          # 0 bottom .. 1 top
    centre = pos * (STICK_SEGMENTS - BLOCK) + BLOCK / 2 - 0.5
    out = []
    for i in range(STICK_SEGMENTS):
        d = abs(i - centre)
        out.append(max(FLOOR, 1.0 - max(0.0, d - (BLOCK / 2 - 1)) / 1.5) if d < BLOCK / 2 + 1 else FLOOR)
    return out


def _fill(amount: float, top_flash: float = 0.0) -> list:
    """Lit from the bottom up to `amount` (0..1) of the stick; the topmost lit section at top_flash."""
    lit = max(0.0, min(1.0, amount)) * STICK_SEGMENTS
    out = []
    for i in range(STICK_SEGMENTS):
        k = 1.0 if i + 1 <= lit else (lit - i if i < lit else 0.0)
        out.append(max(FLOOR * 0.5, k))
    top = min(STICK_SEGMENTS - 1, max(0, int(lit) - 1))
    if top_flash and lit >= 1:
        out[top] = max(out[top], top_flash)
    return out


def masks(kind: str, beat: float, start_beat: float, end_beat: float, n: int) -> list:
    """The mask of each of `n` sticks for a section `kind` at `beat` (absolute beats)."""
    if kind == "build":
        span = max(1.0, end_beat - start_beat)
        done = (beat - start_beat + 1.0) / span                 # full on the build's last beat
        flash = 1.0 if (beat % 1.0) < 0.25 else 0.7
        return [_fill(done, flash) for _ in range(n)]
    if kind == "drop":
        q = beat % 1.0
        m = _fill(min(1.0, q / 0.25)) if q < 0.25 else [1.0] * STICK_SEGMENTS
        return [list(m) for _ in range(n)]
    if kind == "outro":
        return [None] * n
    out = []
    for i in range(n):   # each stick a beat behind the one before: the block chases across them
        out.append(_bounce(((beat - i) / 4.0) % 1.0))
    return out


def apply(rig, section, beat: float) -> None:
    """Lay the section's shapes over the sticks of a rendered frame (no section: whole sticks)."""
    sticks = list(rig.sticks)
    if not sticks:
        return
    if not enabled() or section is None:
        for s in sticks:
            s.mask = None
        return
    for s, m in zip(sticks, masks(section.kind, beat, section.start_beat, section.end_beat, len(sticks))):
        s.mask = m
    if section.kind == "build":   # the fill has to read: the stick rises with it, never fading under it
        done = max(0.0, min(1.0, (beat - section.start_beat + 1.0) / max(1.0, section.end_beat - section.start_beat)))
        for s in sticks:
            s.dim = max(s.dim, BUILD_FLOOR + (1.0 - BUILD_FLOOR) * done)
