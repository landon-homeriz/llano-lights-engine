"""The light library a DJ picks from on the Setup screen (Llano BL #12524).

fixture_profiles reads ONE light (a QLC+ .qxf or an Open Fixture Library .json) into a profile. This
module is the shelf those files sit on, so a DJ whose rig is not his three GigBAR-era kinds can find
their own lights by name, offline at a gig:

  fixtures/qlcplus-library.zip    every QLC+ fixture definition (mcallegari/qlcplus resources/fixtures,
                                  Apache 2.0, the commit NOTICE.md names), unmodified, zipped
  fixtures/qlcplus-library.json   its index: manufacturer, model, type and each mode's channel count,
                                  rebuilt by `python -m tools.gigbar_lights.fixture_library` and pinned
                                  against the zip by test_rig_setup.py

A light is named in the settings by a REF: "qlcplus:Chauvet/Chauvet-SlimPAR-56.qxf" (a file in the zip),
or a bundled file by its bare name ("Venue-Tetra-6.qxf", fixtures/qlcplus). resolve(ref) is the profile
with fixtures/overrides.json applied, so his three kinds keep their overrides whichever way they are named.

Fog and haze machines (QLC+ types Smoke and Hazer) are left out of search: the show would drive their
output channel like a dimmer, and a look must never fill a room with fog.

Stdlib only (the Windows app runs an embedded Python).
"""
from __future__ import annotations

import json
import re
import threading
import xml.etree.ElementTree as ET
import zipfile
from functools import lru_cache
from pathlib import Path

from . import fixture_profiles

LIBRARY_ZIP = fixture_profiles.LIBRARY_DIR / "qlcplus-library.zip"
INDEX_FILE = fixture_profiles.LIBRARY_DIR / "qlcplus-library.json"
PREFIX = "qlcplus:"
NOT_SHOW_LIGHTS = ("Smoke", "Hazer", "Fan")
# The role a light of each QLC+ type plays until the DJ picks another (Setup's role menu).
TYPE_ROLES = {"Moving Head": "movers", "Scanner": "movers", "Strobe": "strobes", "Laser": "effects",
              "Flower": "effects", "Effect": "effects"}
_NS = fixture_profiles._QLC_NS
_LOCK = threading.Lock()
_ZIP: list = []   # the library zip, opened once: reopening it reads ~1,800 directory entries each time


def _read(name: str) -> str:
    with _LOCK:
        if not _ZIP:
            _ZIP.append(zipfile.ZipFile(LIBRARY_ZIP))
        return _ZIP[0].read(name).decode("utf-8")


def _entry(name: str, text: str) -> "dict | None":
    root = ET.fromstring(text)
    kind = (root.findtext(f"{_NS}Type") or "").strip()
    if kind in NOT_SHOW_LIGHTS:
        return None
    modes = []
    for m in root.findall(f"{_NS}Mode"):
        n = len(m.findall(f"{_NS}Channel"))
        modes.append([(m.get("Name") or "").strip() or f"{n} Channel", n])
    if not modes:
        return None
    return {"ref": PREFIX + name, "manufacturer": (root.findtext(f"{_NS}Manufacturer") or "").strip(),
            "model": (root.findtext(f"{_NS}Model") or "").strip(), "type": kind, "modes": modes}


def build_index(zip_path: Path = LIBRARY_ZIP) -> list:
    """The index, read from the zip itself (slow: every file). Sorted by manufacturer then model."""
    out = []
    with zipfile.ZipFile(zip_path) as z:
        for name in sorted(z.namelist()):
            if name.endswith(".qxf"):
                e = _entry(name, z.read(name).decode("utf-8"))
                if e:
                    out.append(e)
    out.sort(key=lambda e: (e["manufacturer"].lower(), e["model"].lower(), e["ref"]))
    return out


@lru_cache(maxsize=1)
def index() -> tuple:
    """Every show light in the library (the committed index); empty when this copy has none."""
    try:
        return tuple(json.loads(INDEX_FILE.read_text("utf-8")))
    except (OSError, ValueError):
        return ()


def _words(text: str) -> list:
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w]


def search(query: str, limit: int = 40) -> list:
    """Lights whose manufacturer, model or type hold every word of `query` ("chauvet slimpar",
    "moving head", "56"), best matches first: a model that starts with a word beats one that holds it.
    Each with the role it plays by default. An empty query lists nothing (1,700 rows help nobody)."""
    words = _words(query or "")[:6]
    if not words:
        return []
    hits = []
    for e in index():
        hay = f"{e['manufacturer']} {e['model']} {e['type']}".lower()
        flat = re.sub(r"[^a-z0-9]+", "", hay)
        if not all(w in hay or w in flat for w in words):
            continue
        model = _words(e["model"])
        score = sum(2 if w in model else (1 if any(m.startswith(w) for m in model) else 0) for w in words)
        hits.append((-score, len(e["model"]), e["manufacturer"].lower(), e["model"].lower(), e))
    hits.sort(key=lambda h: h[:4])
    return [{**h[-1], "role": TYPE_ROLES.get(h[-1]["type"], "wash")} for h in hits[:max(1, min(limit, 100))]]


def entry(ref: str) -> "dict | None":
    """The index row for a ref, or None."""
    for e in index():
        if e["ref"] == ref:
            return e
    return None


@lru_cache(maxsize=128)
def resolve(ref: str) -> fixture_profiles.Profile:
    """A light's profile by its ref, overrides applied. KeyError for a ref this copy doesn't have."""
    if not isinstance(ref, str) or not ref:
        raise KeyError("no light named")
    if ref.startswith(PREFIX):
        name = ref[len(PREFIX):]
        if ".." in name or not name.endswith(".qxf"):
            raise KeyError(f"{ref!r} is not a library light")
        try:
            text = _read(name)
        except (OSError, KeyError, zipfile.BadZipFile, UnicodeDecodeError) as e:
            raise KeyError(f"the light library has no {name!r}") from e
        return fixture_profiles.load_qxf(text)
    if "/" in ref or "\\" in ref or not ref.endswith(".qxf") or not (fixture_profiles.QLC_DIR / ref).is_file():
        raise KeyError(f"{ref!r} is not a library light")
    return fixture_profiles.load_qxf(fixture_profiles.QLC_DIR / ref)


def suggested_role(ref: str) -> str:
    e = entry(ref)
    return TYPE_ROLES.get(e["type"], "wash") if e else "wash"


if __name__ == "__main__":   # rebuild the committed index after dropping in a newer zip
    rows = build_index()
    INDEX_FILE.write_text(json.dumps(rows, separators=(",", ":"), ensure_ascii=False) + "\n", "utf-8")
    print(f"{len(rows)} lights indexed into {INDEX_FILE}")
