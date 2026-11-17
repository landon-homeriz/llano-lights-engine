"""The laptop-only stand-in for the Llano link: the same seam with no network behind it.

The engine (DMX out, the beat link, the looks, the house show, the fixture library, the phone
remote on the local Wi-Fi) needs none of llano.app. The app talks to its settings sync through one
object, `LlanoLink` in llano_sync.py; an edition built without that module (the open-source engine)
gets this class instead, so every change made on the laptop still lands in force and on disk the
same way, and nothing ever leaves the machine.

- `local_change` applies the ops, puts them in force and saves settings.json, exactly like the
  linked path; there is just no queue for a server.
- `public()` says the link is off (`enabled: False`), so the window hides its "Link to Llano" box.
- Linking and getting songs from a cloud folder refuse with a plain reason; the songs a show uses
  come from a folder on this laptop.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from . import settings_contract as contract
from . import show_settings

DEFAULT_URL = ""
LINE = "This edition runs on this laptop only: settings live in settings.json"


class LinkError(Exception):
    pass


def enabled() -> bool:
    return False


def frame_slots() -> int:
    return 0


class LlanoLink:
    """Same constructor and surface the app uses; every cloud hook is accepted and never called."""

    def __init__(self, settings: "show_settings.SettingsFile", *, version: str, path: Optional[Path] = None,
                 **_hooks) -> None:
        self.settings, self.version = settings, version
        self.path = Path(path) if path else settings.path.parent / "llano_link.json"
        self.studio_seen = 0
        self.clock_skew = 0.0
        self.online, self.rev, self.pending, self.landed = False, 0, [], {}

    @property
    def linked(self) -> bool:
        return False

    def public(self) -> dict:
        # A moment picked on the laptop is not a draft (it holds until Back to the show, play_until is
        # infinite); with no Llano there is never a draft from elsewhere, so only a timed play counts.
        until = 0 if show_settings.play_label() else show_settings.play_until()
        left = max(0, int(until - time.time())) if until and until != float("inf") else 0
        return {"enabled": False, "linked": False, "online": False, "line": LINE,
                "draft": {"playing": bool(until), "left": left}, "pending": 0, "rev": 0,
                "last_sync": 0, "landed": {}}

    def landed_ok(self) -> dict:
        return self.public()

    def link(self, code: str, name: str = "") -> dict:
        raise LinkError("this edition has no Llano link; it runs on this laptop's settings")

    def unlink(self, tell_llano: bool = True) -> dict:
        return self.public()

    def drive_folders(self) -> list:
        raise LinkError("getting songs from a cloud folder isn't in this edition; pick a song folder on this laptop")

    def drive_songs(self, folder_id: str = "") -> dict:
        raise LinkError("getting songs from a cloud folder isn't in this edition; pick a song folder on this laptop")

    def download_song(self, folder_id: str, file_id: str, dest, timeout: float = 60) -> str:
        raise LinkError("getting songs from a cloud folder isn't in this edition; pick a song folder on this laptop")

    def local_change(self, ops: list) -> dict:
        """A change made on the laptop: in force now and saved (no server to queue it for)."""
        new, _applied = contract.apply_ops(show_settings.current(), ops)
        show_settings.set_current(new)   # in force first; the disk copy is best effort
        try:
            self.settings.save(new)
        except OSError as e:  # disk full, file locked: the show already runs on the new settings
            print(f"Llano settings: couldn't save settings.json ({e}); they apply until the app closes")
        return new

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass
