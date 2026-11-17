"""The local ports Llano Lights listens on, all counted from one base (Llano BL #12427).

On his laptop the base is 8765: the window's server takes the first free port of 8765-8784 and
local mode the first free one of 8790-8799, as every release has. LLANO_LIGHTS_PORT_BASE moves the
whole set somewhere else, for runs on a shared host (the test channel's publish, CI, a peer
session's suite) where other services and other app copies already hold 8765-8784. Unset, or not a
usable port number, it is 8765, so a stray value on the laptop can never stop the app opening."""
from __future__ import annotations

import os

DEFAULT_BASE = 8765
WINDOW_COUNT = 20      # 8765-8784
LOCAL_OFFSET = 25      # local mode starts at 8790
LOCAL_COUNT = 10       # 8790-8799
SPAN = LOCAL_OFFSET + LOCAL_COUNT


def base() -> int:
    raw = (os.environ.get("LLANO_LIGHTS_PORT_BASE") or "").strip()
    try:
        n = int(raw)
    except ValueError:
        return DEFAULT_BASE
    return n if 1024 <= n <= 65535 - SPAN else DEFAULT_BASE


BASE = base()
WINDOW_PORTS = range(BASE, BASE + WINDOW_COUNT)
LOCAL_PORTS = range(BASE + LOCAL_OFFSET, BASE + LOCAL_OFFSET + LOCAL_COUNT)


def span(ports: range) -> str:
    return f"{ports[0]}-{ports[-1]}"
