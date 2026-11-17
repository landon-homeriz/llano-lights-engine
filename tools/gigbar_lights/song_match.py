"""Find the saved style for the song that is playing, forgiving how the name is written.

A style is filed under a song key (settings_contract.track_key: lowercase words joined by
hyphens), typed on llano.app/lights as "Artist - Title". The same song arrives spelled
many ways: Mixxx reads the file's tags, Spotify says "Song - Remastered 2011" with
"Artist A, Artist B", browser YouTube Music sends "Song (feat. X)", plain YouTube sends
"Artist - Song (Official Video)" from a channel called "ArtistVEVO". candidates() turns one
artist and title into every reasonable key for that song, best first; pick() finds the
first one a saved style is filed under. Case and punctuation never mattered (track_key
drops them); this adds featured artists, version and remaster tags, "&" vs "and", a
leading "the", accents, artist order, and a style saved under the title alone.

It stays conservative on purpose: words are only dropped when they say which version
or who features, never to make two different songs look alike.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

from .settings_contract import track_key

# A bracketed or dashed tag that only says which version or who features.
_VERSION = (r"feat|ft|featuring|with|remaster(?:ed)?|\d{4}\s+remaster(?:ed)?|radio\s+edit|single\s+version|"
            r"album\s+version|original\s+mix|mono|stereo|explicit|clean|deluxe|bonus\s+track|"
            r"official|lyrics?|lyric\s+video|visuali[sz]er|audio|video|hd|hq|4k|live|acoustic|from\b")
_BRACKET = re.compile(r"\s*[(\[]([^)\]]*)[)\]]")
_FEAT = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s+.*$", re.I)
_DASH = re.compile(r"\s+[-–—]\s+")
_ARTIST_SPLIT = re.compile(r"\s*(?:,|;|/|&|\+|\s+x\s+|\s+and\s+|\s+feat\.?\s+|\s+ft\.?\s+|\s+featuring\s+|\s+with\s+)\s*", re.I)
_CHANNEL = re.compile(r"(?:\s*-\s*topic|vevo|\s+official)$", re.I)
_STOP = {"the", "a", "an", "and"}
_TAG_WORDS = {"remaster", "remastered", "explicit"}
_TAG_PAIRS = {("radio", "edit"), ("official", "video"), ("official", "audio"), ("lyric", "video")}


def _fold(s: str) -> str:
    """Accents off (Beyoncé -> Beyonce), so the key keeps the letter instead of dropping it."""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def _is_version(tag: str) -> bool:
    return bool(re.match(rf"\s*(?:{_VERSION})\b", tag, re.I))


def _titles(title: str) -> list[str]:
    """The title as given, then with version tags off, then with every trailing tag off."""
    t = (title or "").strip()
    out = [t]
    plain = _BRACKET.sub(lambda m: "" if _is_version(m.group(1)) else m.group(0), t)
    parts = _DASH.split(plain, maxsplit=1)
    if len(parts) == 2 and _is_version(parts[1]):  # Spotify: "Song - Remastered 2011", "Song - Live at ..."
        plain = parts[0]
    plain = _FEAT.sub("", plain).strip()
    out.append(plain)
    out.append(_DASH.split(_BRACKET.sub("", plain), maxsplit=1)[0].strip())  # "Song (Acoustic)" -> "Song"
    return [x for x in out if x]


def _artists(artist: str) -> list[str]:
    a = _CHANNEL.sub("", (artist or "").strip()).strip()
    out = [a]
    first = _ARTIST_SPLIT.split(a, maxsplit=1)[0].strip()
    if first and first != a:
        out.append(first)
    return [x for x in out if x]


def norm(key: str) -> str:
    """A key with the words that never tell two songs apart taken out."""
    words = [w for w in key.split("-") if w and w not in _STOP]
    out, i = [], 0
    while i < len(words):
        w = words[i]
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if (w, nxt) in _TAG_PAIRS:
            i += 2
            continue
        if w in _TAG_WORDS:
            if out and re.fullmatch(r"(19|20)\d\d", out[-1]):
                out.pop()  # "2011 remaster"
            elif re.fullmatch(r"(19|20)\d\d", nxt):
                i += 1     # "remastered 2011"
            i += 1
            continue
        out.append(w)
        i += 1
    return "-".join(out)


def candidates(artist: str, title: str, title_only: bool = True) -> tuple[str, ...]:
    """Every key this song could be filed under, best first; the first is the plain track_key.
    title_only=False leaves out the title-alone keys (a library BPM must not come from another
    artist's song with the same title)."""
    keys: list[str] = []

    def add(*parts: str) -> None:
        for fold in (False, True):
            k = track_key(*[_fold(p) if fold else p for p in parts])
            if k and k not in keys:
                keys.append(k)

    add(artist, title)
    artists, titles = _artists(artist), _titles(title)
    # Plain YouTube: the channel is the artist and the title is "Artist - Song (Official Video)".
    split = _DASH.split(_BRACKET.sub("", title or ""), maxsplit=1)
    if len(split) == 2 and split[0].strip() and split[1].strip():
        artists += [a for a in _artists(split[0]) if a not in artists]
        titles += [t for t in _titles(split[1]) if t not in titles]
    for t in titles:
        for a in artists:
            add(a, t)
    for t in titles:
        for a in artists:
            add(t, a)  # typed as "Title - Artist"
    if title_only:
        for t in titles:
            add(t)    # a style saved under the title alone
    return tuple(keys)


def pick(songs: dict, keys: Iterable[str]) -> Optional[str]:
    """The saved song key the playing song matches, or None. songs: {key: style name}."""
    keys = [k for k in keys if k]
    if not songs or not keys:
        return None
    for k in keys:
        if k in songs:
            return k
    saved: dict[str, str] = {}
    for k in songs:
        if norm(k):
            saved.setdefault(norm(k), k)
    for k in keys:
        hit = saved.get(norm(k)) if norm(k) else None
        if hit:
            return hit
    return None
