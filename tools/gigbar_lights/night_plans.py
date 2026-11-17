"""Each saved show's wedding-night plan, kept by the app on this laptop (Llano BL #12426).

The plan is what step 2 of the Shows page holds for one show: the song folder on this laptop, each
moment's tick, time and song, the cocktail/dinner/dancing times, the songs to keep whole and the
Moments-folder songs not placed yet. It used to live only in the page's localStorage, which a browser
keeps per origin, and the window's origin is per port: the app takes the first free port of
8765-8784, so a restart that landed on another port opened every show with an empty folder box, no
moment times and a needs list that forgot the unplaced songs.

The plan stays on the laptop (a folder path means nothing on another machine), so it is a file next to
settings.json, not a field of the synced show. One JSON file, written whole (temp name, then rename).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

MAX_TEXT = 200       # a time, a song name, a moment key
MAX_PATH = 1000      # a Windows folder path
MAX_ITEMS = 200      # moments, songs kept whole, unplaced songs
MAX_SHOWS = 500      # plans kept; the oldest go first past this
PARTS = ("cocktail", "dinner", "dancing")


def _text(v, most: int = MAX_TEXT) -> str:
    return v.strip()[:most] if isinstance(v, str) else ""


def clean(plan) -> Optional[dict]:
    """The plan in the page's shape, every field checked; None for anything that is not a plan."""
    if not isinstance(plan, dict):
        return None
    moments = {}
    raw = plan.get("moments") if isinstance(plan.get("moments"), dict) else {}
    for k, m in list(raw.items())[:MAX_ITEMS]:
        if not isinstance(m, dict) or not _text(k):
            continue
        moments[_text(k)] = {"on": m.get("on") is not False, "at": _text(m.get("at")), "song": _text(m.get("song"))}
    times = plan.get("times") if isinstance(plan.get("times"), dict) else {}
    out = {"folder": _text(plan.get("folder"), MAX_PATH), "moments": moments,
           "keep": [_text(x) for x in (plan.get("keep") or [])[:MAX_ITEMS] if _text(x)] if isinstance(plan.get("keep"), list) else [],
           "times": {p: _text(times.get(p)) for p in PARTS}}
    if isinstance(plan.get("unplaced"), list):
        out["unplaced"] = [_text(x) for x in plan["unplaced"][:MAX_ITEMS] if _text(x)]
    return out


def empty(plan: Optional[dict]) -> bool:
    """Nothing he set: no folder, no moment touched, no time, nothing kept whole, nothing unplaced."""
    if not plan:
        return True
    return not (plan.get("folder") or plan.get("keep") or plan.get("unplaced") or any(plan.get("times", {}).values())
                or any(m.get("at") or m.get("song") or m.get("on") is False for m in plan.get("moments", {}).values()))


class NightPlans:
    """night_plans.json: {show name: plan}. Reads never fail (a missing or broken file is no plans)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def _all(self) -> dict:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return d if isinstance(d, dict) else {}

    def _write(self, d: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, name: str) -> Optional[dict]:
        if not name:
            return None
        with self.lock:
            return clean(self._all().get(name))

    def put(self, name: str, plan) -> Optional[dict]:
        """Keeps this show's plan; returns it as kept (None: no name, or not a plan)."""
        plan = clean(plan)
        if not name or plan is None:
            return None
        with self.lock:
            d = self._all()
            d.pop(name, None)
            d[name] = plan            # last written last: past MAX_SHOWS the oldest go
            while len(d) > MAX_SHOWS:
                d.pop(next(iter(d)))
            self._write(d)
        return plan

    def drop(self, name: str) -> None:
        with self.lock:
            d = self._all()
            if d.pop(name, None) is not None:
                self._write(d)
