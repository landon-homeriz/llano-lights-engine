"""A session's short test on the real lights (1.14.0): hold a few DMX channels for seconds.

A Llano session verifying a fix on his rig (a head that should now turn left, a laser channel
that should now light) asks for exact bytes on exact channels: {slot: value}, slot 1..512 as the
DMX box numbers them. They arrive in the settings pull (llano_sync.py), are laid over every frame
the app sends, whatever runs, and lapse on THIS laptop's clock even with no internet, never past
PROBE_MAX. When no show is running the app runs a small output loop for the probe alone (dark
except the probed channels), so a session can test with the laptop idle. Memory only: nothing is
saved, and a restart forgets it.

While a song is playing a probe is refused (his gig wins); the reason goes back in the status.
Kill switch: LLANO_LIGHTS_PROBE=0 refuses every probe.
"""
from __future__ import annotations

import os
import threading
import time

PROBE_MAX = 60.0     # seconds; Llano asks for at most 30, never longer here whatever a clock says
MAX_CHANNELS = 64

_lock = threading.Lock()
_held: dict = {}     # slot (1..512) -> byte
_until = 0.0
_by = ""
note = ""            # the last plain line about a probe, for the status Llano reads
song_playing = lambda: False   # the app sets this: a probe is never laid over a song, even one started later


def enabled() -> bool:
    return (os.environ.get("LLANO_LIGHTS_PROBE") or "1").strip().lower() not in {"0", "off", "false", "no"}


def clean(channels) -> dict:
    """{slot: byte} from what Llano sent ({"37": 255}); anything malformed is dropped."""
    out = {}
    for k, v in (channels.items() if isinstance(channels, dict) else []):
        try:
            slot, val = int(k), int(v)
        except (TypeError, ValueError):
            continue
        if 1 <= slot <= 512 and 0 <= val <= 255 and not isinstance(v, bool):
            out[slot] = val
        if len(out) >= MAX_CHANNELS:
            break
    return out


def set_probe(channels: dict, until: float, by: str = "") -> None:
    global _held, _until, _by
    with _lock:
        _held, _until, _by = dict(channels), min(float(until), time.time() + PROBE_MAX), str(by)[:80]


def clear() -> None:
    global _held, _until
    with _lock:
        _held, _until = {}, 0.0


def active(now: "float | None" = None) -> dict:
    """The channels held right now, {} once the probe lapsed (or there is none)."""
    with _lock:
        return dict(_held) if _held and (time.time() if now is None else now) < _until else {}


def left() -> float:
    return max(0.0, _until - time.time()) if active() else 0.0


def apply(universe: bytes) -> bytes:
    """`universe` with the probed channels laid over it (unchanged when no probe is live)."""
    held = active()
    if not held:
        return universe
    if song_playing():   # he pressed play while a probe held channels: the song wins, the probe ends
        clear()
        globals()["note"] = "ended: a song started"
        return universe
    u = bytearray(universe)
    if len(u) < 512:
        u.extend(bytes(512 - len(u)))
    for slot, val in held.items():
        u[slot - 1] = val
    return bytes(u)


def public() -> dict:
    held = active()
    return {"channels": {str(k): v for k, v in sorted(held.items())}, "left": round(left(), 1),
            "by": _by if held else "", "note": note}
