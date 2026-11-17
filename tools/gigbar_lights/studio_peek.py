"""Look before you press (1.20.0, the Light studio, Llano PM #23195).

A pro desk has Blind and Preview: see a look without sending it to the room. Here, resting the
pointer on a pad plays that pad in the room picture only. The lights keep doing what they are doing.

How: a second show that nobody is plugged into. It has its own looks engine, marked `isolated`, so it
never reads or writes anything the real show shares (the draft, the saved show's looks, Llano's scene
pad), its own studio holding just that pad, and a steady pretend beat. It is rendered only when the
picture asks for a frame, and thrown away when the pointer leaves.
"""
from __future__ import annotations

import time
from typing import Optional

from . import studio as studio_mod
from .show import Show

PEEK_S = 2.5      # a peek nobody renews ends by itself (a pointer that left without saying so)
PEEK_BPM = 120.0


class Peek:
    def __init__(self, real: "studio_mod.Studio", key: str, layout=None, bpm: float = 0.0,
                 now: Optional[float] = None):
        """Raises studio.CommandError when the pad is not one this studio has."""
        from .__main__ import FakeMixxx   # here, not at the top: __main__ imports the show
        self.key = key
        self.show = Show(analyze=False, venue=layout)
        self.show.looks.isolated = True
        st = studio_mod.Studio(live=True)
        st.fade_s = 0.0
        with real.lock:   # the pad as it would play now: his saved pads, his color, motion, speed, brightness
            st.pads = [dict(p) for p in real.pads]
            st.color, st.motion, st.speed = real.color, real.motion, real.speed
            st.masters = dict(real.masters)
        st.command({"op": "look", "key": key})
        self.name = st.public()["look"]["name"]
        self.show.studio = st
        self.feed = FakeMixxx(self.show, bpm if 40 <= bpm <= 220 else PEEK_BPM, loop=True)
        self.until = (time.monotonic() if now is None else now) + PEEK_S

    def renew(self, now: Optional[float] = None) -> None:
        self.until = (time.monotonic() if now is None else now) + PEEK_S

    def over(self, now: Optional[float] = None) -> bool:
        return (time.monotonic() if now is None else now) > self.until

    def render(self, now: Optional[float] = None) -> bytes:
        now = time.perf_counter() if now is None else now
        self.feed(now)
        self.show.control_tick(now)
        return self.show.render(now)
