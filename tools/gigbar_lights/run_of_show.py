"""The run of show for a wedding: the night as an ordered list of steps, turned into the few Mixxx
playlists he starts by hand and a one-page sheet that says what to press (Llano PM #23179).

How a first-time DJ runs a night with one button. Mixxx's Auto DJ plays a queue on its own. Three
kinds of step fill it:

  music   a part's songs (cocktail hour, dinner, dancing). It plays until he moves on, so it is
          "elastic": the playlist carries the songs twice, the second pass in a different order, so a
          cocktail hour that runs long repeats a song an hour later instead of going silent.
  hold    a live moment with no music under it (announce the couple, toasts, cake). In the queue it
          is an hour of silence with the moment's name (set_cuts.hold): the song before it ends, the
          room goes quiet, the lights change to the moment's look. Fade Now moves on.
  song    one song for a moment (the entrance, the first dance), played whole, then on to what follows.

So the whole night is: start a playlist, and press Fade Now when a moment is over. A new playlist
starts wherever music has to be LEFT (he cannot know which cocktail song will be playing when the
couple is ready): the step after every stretch of music opens the next playlist. In Mixxx that is
right-click the playlist, "Add to Auto DJ Queue (replace)", then Fade Now (Shift+F11). Checked
against Mixxx 2.5: replacing the queue reloads the waiting deck (AutoDJProcessor::
playlistFirstTrackChanged), and Fade Now crosses to it over the transition time.

Moments on the dance floor (cake, bouquet) sit INSIDE the dancing playlist: the DJ picks that moment
anyway ("after this song, the bouquet"), so the hold arrives on its own and nothing has to be left.

Nothing here touches audio or Mixxx: it is the plan, the playlists as text and the sheet.
"""
from __future__ import annotations

import base64
import html
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

from . import settings_contract as contract

PART_NAMES = {"cocktail": "Cocktail hour", "dinner": "Dinner", "dancing": "Dancing"}
# Quiet music under a live moment (Llano BL #12360, his timeline: toasts and speeches, and the cake
# cutting, have "low-level background music"): after the moment's hold, a music step plays
# parts["background"] (wedding_night.build fills it: the songs he marked "background", or until he marks
# any, his own dinner songs again). Mixxx's volume is his: the sheet says to turn it down.
BACKGROUND = "background"
BACKGROUND_UNDER = ("toasts", "cake")
# Under the toasts and speeches, his instrumentals in their folder's order (2026-11-14, his "Wedding
# Instrumentals" folder): parts["toasts-background"]. With none, the toasts get the background bed too.
TOASTS_BED = "toasts-background"
BEDS = (BACKGROUND, TOASTS_BED)
TRANSITION_S = 2.0
AVG_DANCE_SONG_S = 215     # for "add about N songs"

# key: (name, the look from moments.py the lights play, what to say or do, a song belongs to it,
#       a hold comes first: nothing starts until he presses Fade Now)
MOMENTS = {
    "entrance":        ("Grand entrance", "entrance", "Announce the wedding party, then the couple.", True, True),
    "first-dance":     ("First dance", "first-dance", "Invite the couple to the floor for their first dance.", True, True),
    "welcome":         ("Welcome and blessing", "toast", "Hand the microphone to whoever welcomes the room or says grace.", False, True),
    "pause":           ("Quiet moment", "toast", "Nothing plays. Press Fade Now in Mixxx when you are ready to go on.", False, True),
    "toasts":          ("Toasts and speeches", "toast", "Turn the music down low, then introduce each speaker.", False, True),
    "cake":            ("Cake cutting", "cake", "Keep the music low. Send everyone to the cake and wait for the photographer's nod.", False, True),
    "father-daughter": ("Father-daughter dance", "father-daughter", "Invite the bride and her father to the floor.", True, True),
    "mother-son":      ("Mother-groom dance", "father-daughter", "Invite the groom and his mother to the floor.", True, True),
    "bouquet":         ("Bouquet toss", "toast", "Call the single ladies to the floor.", False, True),
    "garter":          ("Garter toss", "toast", "Call the single men to the floor.", False, True),
    "last-dance":      ("Last dance", "last-dance", "Tell the room this is the last song and bring everyone in.", True, True),
    "close":           ("Closing song", "", "", True, False),
    "send-off":        ("Send-off", "toast", "Thank everyone and line them up outside for the send-off.", False, True),
    "exit-prep":       ("Prepare for grand exit", "party", "Call everyone to the floor for one last big sing-along.", True, True),
    "exit":            ("Bride and groom exit", "last-dance", "Line everyone up and send the couple off.", True, True),
}
MOMENT_KEYS = tuple(MOMENTS)
# The night's order (Llano BL #12360): his printed reception timeline for 2026-11-25. Cocktail hour and
# family photos 4:50, grand entrance 5:30, dinner 5:40, first dance 6:20, a pause, father-daughter
# 6:25, mother-groom 6:30, toasts and speeches 6:40, cake 6:55, open dancing 7:05, prepare for grand
# exit 8:15, bride and groom exit 8:30. Every step is advanced by hand; the times are only a guide.
# The other moments (welcome, bouquet, garter, last dance, closing song, send-off) stay available.
# The pause on his timeline is not a default step (2026-11-15): nobody chose it, and it put a second
# silent hold right before the father-daughter dance's own hold, so he pressed Fade Now twice in
# silence. It is the optional "Quiet moment" now; a saved order that names it still loads.
DEFAULT_ORDER = ("cocktail", "entrance", "dinner", "first-dance", "father-daughter", "mother-son",
                 "toasts", "cake", "dancing", "exit-prep", "exit")
OPTIONAL = ("garter", "pause")     # moments that happen only when asked for


def skipped(skip) -> set:
    """The moments that are not happening: his own set when he gave one, else the optional ones."""
    return set(OPTIONAL) if skip is None else set(skip)


@dataclass
class Step:
    kind: str                 # "music", "hold", "song"
    key: str                  # a part for music; a moment key for hold and song
    name: str
    say: str = ""
    look: str = ""            # the light look (a moments.py key, or "" for the show's own looks)
    at: str = ""              # clock time he gave, "6:30" (optional)
    minutes: float = 0.0      # planned length when he gave one
    songs: list = field(default_factory=list)   # music: the songs; song: the one song
    opens: bool = False       # this step starts a new playlist (set by build)

    def public(self) -> dict:
        return {"kind": self.kind, "key": self.key, "name": self.name, "say": self.say, "look": self.look,
                "at": self.at, "minutes": self.minutes, "opens": self.opens,
                "songs": [{"artist": s.get("artist", ""), "title": s.get("title", ""), "secs": s.get("secs", 0)}
                          for s in self.songs]}


def _secs(song: dict) -> float:
    return float(song.get("plays_s") or song.get("secs") or 0)


def music_seconds(songs: list) -> float:
    """How long a run of songs lasts in Auto DJ: each handoff overlaps the two songs by the transition."""
    return max(0.0, sum(_secs(s) for s in songs) - TRANSITION_S * max(0, len(songs) - 1))


def parse_clock(text: str) -> Optional[int]:
    """Minutes past noon for a time he typed ("6", "6:30", "6.30", "6:30 pm", "18:30"); None when
    unreadable. A reception is an afternoon and evening, so a bare 1 to 11 is PM, 12 is noon and
    0:30 is half past midnight."""
    t = str(text or "").strip().lower()
    mark = re.search(r"([ap])\.?\s*(?:m\.?)?\s*$", t) if re.match(r"\s*\d", t) else None
    am = bool(mark and mark.group(1) == "a")
    if mark:
        t = t[:mark.start()]
    t = t.strip().replace(".", ":")
    try:
        h, _, m = t.partition(":")
        h, m = int(h), int(m or 0)
    except ValueError:
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    if am:
        h %= 12                                   # 12:30 am is half past midnight
        return (h + 12) * 60 + m if h < 6 else (h - 12) * 60 + m   # after midnight, or a morning hour
    if h >= 13:
        h -= 12
    elif h == 12:
        h = 0
    elif h == 0:
        h = 12                                    # 0:30 on a 24-hour clock: after midnight
    return h * 60 + m


def split_dancing(songs: list, sets: int, breaks_after: Optional[list] = None) -> list[list]:
    """The dancing songs as `sets` runs, in order. Splits fall where the time is nearest to even,
    and prefer the gap after a calmer song (a breather), so a moment never interrupts a peak."""
    sets = max(1, min(sets, len(songs) or 1))
    if sets == 1 or len(songs) < 2:
        return [list(songs)]
    total = sum(_secs(s) for s in songs) or 1.0
    cuts, acc = [], 0.0
    targets = [total * k / sets for k in range(1, sets)]
    edges = []
    for i, s in enumerate(songs[:-1]):
        acc += _secs(s)
        edges.append((i + 1, acc))
    used = set()
    for t in targets:
        near = sorted(edges, key=lambda e: abs(e[1] - t))[:3]
        near = [e for e in near if e[0] not in used and abs(e[1] - t) <= total / sets / 2] or \
               [e for e in sorted(edges, key=lambda e: abs(e[1] - t)) if e[0] not in used][:1]
        if not near:
            continue
        # among the close gaps, the one after the calmest song
        best = min(near, key=lambda e: (float(songs[e[0] - 1].get("energy") or 0.5), abs(e[1] - t)))
        used.add(best[0])
        cuts.append(best[0])
    out, prev = [], 0
    for c in sorted(cuts):
        out.append(list(songs[prev:c]))
        prev = c
    out.append(list(songs[prev:]))
    return [r for r in out if r]


def plan(parts: dict, moment_songs: Optional[dict] = None, order: Optional[tuple] = None,
         times: Optional[dict] = None, skip: Optional[set] = None) -> list[Step]:
    """The night as steps.

    parts         {"cocktail": [song dicts in order], "dinner": [...], "dancing": [...]}
    moment_songs  {moment key: song dict} for the moments that have a song
    order         the steps in night order (parts and moment keys; "dancing" may repeat: the dancing
                  songs are split across its appearances). Default: DEFAULT_ORDER.
    times         {step key: "6:30"} clock times he knows (a repeated part: "dancing", "dancing 2")
    skip          moment keys that are not happening (None: the optional ones, see skipped())
    """
    moment_songs, times, skip = moment_songs or {}, times or {}, skipped(skip)

    def happens(k) -> bool:      # a part with songs, or a moment that puts something in the queue
        if k in MOMENTS:
            return k not in skip and bool(MOMENTS[k][4] or moment_songs.get(k))
        return bool(parts.get(k))

    asked, order = tuple(order or DEFAULT_ORDER), []
    for k in asked:
        if not happens(k) or (order and order[-1] == k and k in PART_NAMES):
            continue             # a part twice in a row (the moment between was dropped) is one run
        order.append(k)
    n_dance = sum(1 for k in order if k == "dancing")
    dance_sets = split_dancing(parts.get("dancing", []), n_dance) if n_dance else []
    while len(dance_sets) < n_dance:       # fewer songs than sets: the later sets are empty and dropped
        dance_sets.append([])
    steps, seen = [], {}
    for k in order:
        seen[k] = seen.get(k, 0) + 1
        tkey = k if seen[k] == 1 else f"{k} {seen[k]}"
        if k in PART_NAMES:
            songs = dance_sets[seen[k] - 1] if k == "dancing" else list(parts.get(k, []))
            if not songs:
                continue
            name = PART_NAMES[k] + (f", set {seen[k]}" if k == "dancing" and n_dance > 1 else "")
            steps.append(Step("music", k, name, at=times.get(tkey, ""), songs=songs))
            continue
        name, look, say, _has_song, hold_first = MOMENTS[k]
        song = moment_songs.get(k)
        if hold_first:   # nothing starts until the people are in place and he presses Fade Now
            steps.append(Step("hold", k, name, say=say, look=look, at=times.get(tkey, "")))
        bed_key = TOASTS_BED if k == "toasts" and parts.get(TOASTS_BED) else BACKGROUND
        bed = parts.get(bed_key) or []
        if k in BACKGROUND_UNDER and bed:   # quiet music under the moment, in the moment's light
            steps.append(Step("music", bed_key, f"{name}: quiet background", look=look, songs=list(bed)))
        if song:
            steps.append(Step("song", k, f"{name}: {song.get('title', '')}".strip(": "), look=look, songs=[song]))
    steps = _one_hold_at_a_time(steps)
    mark_opens(steps)
    _plan_minutes(steps)
    return steps


def mark_opens(steps: list) -> None:
    """Which steps start a new playlist: the first, and the step after every stretch of music he has
    to leave. Works on Steps and on anything with kind, key and opens (Tonight rebuilds Steps from a
    saved night and calls this, so an old night.json with no `opens` still says the right thing)."""
    for i, s in enumerate(steps):
        s.opens = i == 0 or (steps[i - 1].kind == "music" and not _inside_dancing(steps, i))


def _one_hold_at_a_time(steps: list[Step]) -> list[Step]:
    """No quiet moment next to another hold: each hold is a Fade Now press in silence, and the hold
    beside it already stops the music, so the quiet moment adds a second press and nothing else.
    Holds of two real moments back to back (the toasts, then the cake, with no quiet music between)
    both stay: each is something he announces."""
    out: list[Step] = []
    for i, s in enumerate(steps):
        nxt = steps[i + 1] if i + 1 < len(steps) else None
        if s.kind == "hold" and s.key == "pause" and (
                (nxt is not None and nxt.kind == "hold") or (out and out[-1].kind == "hold")):
            continue
        out.append(s)
    return out


def _inside_dancing(steps: list[Step], i: int) -> bool:
    """Step i comes between two runs of dancing: a dance-floor moment (cake, bouquet) that the DJ
    times himself, so it rides inside the dancing playlist instead of opening a new one."""
    if steps[i - 1].key != "dancing":
        return False
    nxt = next((s for s in steps[i:] if s.kind == "music"), None)
    return nxt is not None and nxt.key == "dancing"


HOLD_MIN = 3.0   # what a live moment is counted as when no time says otherwise


def windows(steps: list[Step]) -> list[dict]:
    """Each stretch between two times he gave: {"name", "minutes" it has to fill, "music" minutes of
    songs in it, "holds" live moments in it}. Dancing split into sets around a bouquet toss is one
    stretch, so its sets are weighed together against the time, not one by one."""
    clock = [(i, parse_clock(s.at)) for i, s in enumerate(steps) if s.at and parse_clock(s.at) is not None]
    out = []
    for (i, t), (j, t2) in zip(clock, clock[1:]):
        inside = steps[i:j]
        music = [s for s in inside if s.kind == "music"]
        if t2 <= t or not music:
            continue
        names = []
        for s in music:
            n = PART_NAMES.get(s.key, s.name)
            if n not in names:
                names.append(n)
        songs = sum(_secs(s.songs[0]) for s in inside if s.kind == "song") / 60
        out.append({"name": " and ".join(names), "minutes": float(t2 - t), "holds": sum(1 for s in inside if s.kind == "hold"),
                    "music": sum(music_seconds(s.songs) for s in music) / 60 + songs, "first": i})
    return out


def _plan_minutes(steps: list[Step]) -> None:
    """Each music step's planned minutes, when it is the only music in its stretch."""
    for w in windows(steps):
        inside = [s for s in steps[w["first"]:] if s.kind == "music"]
        if inside:
            inside[0].minutes = w["minutes"]


@dataclass
class Playlist:
    n: int
    name: str
    rows: list            # [{"kind", "name", "artist", "title", "secs", "look", "repeat"}]
    music_s: float = 0.0  # first pass of its music, without the safety repeat

    @property
    def file(self) -> str:
        return f"{self.n} - {self.name}.m3u8"


def _rotate(songs: list) -> list:
    """The safety pass: the same songs starting from the middle, so a repeat is as far away as it can be."""
    h = len(songs) // 2
    return list(songs[h:]) + list(songs[:h])


def playlists(steps: list[Step]) -> list[Playlist]:
    """The Mixxx playlists, in night order. Each starts at a step that `opens`."""
    out: list[Playlist] = []
    names: list[str] = []
    for s in steps:
        if s.opens or not out:
            out.append(Playlist(len(out) + 1, "", []))
            names = []
        pl = out[-1]
        short = PART_NAMES.get(s.key, s.name) if s.kind == "music" else MOMENTS[s.key][0]
        if short not in names:
            names.append(short)
        if s.kind == "hold":
            pl.rows.append({"kind": "hold", "key": s.key, "name": s.name, "artist": "Llano hold",
                            "title": hold_title(s.name), "secs": 0, "look": s.look, "repeat": False})
        else:
            for song in s.songs:
                pl.rows.append({"kind": s.kind, "key": s.key, "name": s.name, "artist": song.get("artist", ""),
                                "title": song.get("title", ""), "secs": _secs(song),
                                "look": s.look if s.kind == "song" else song.get("look", ""), "repeat": False})
            if s.kind == "music":
                pl.music_s += music_seconds(s.songs)
        pl.name = _join(names)
    # the safety pass goes on the END of a playlist that ends in music (never before a hold inside it)
    for pl, last in zip(out, _last_music(steps)):
        if last is not None and len(last.songs) > 1:
            for song in _rotate(last.songs):
                pl.rows.append({"kind": "music", "key": last.key, "name": last.name, "artist": song.get("artist", ""),
                                "title": song.get("title", ""), "secs": _secs(song), "look": song.get("look", ""),
                                "repeat": True})
    return out


def _last_music(steps: list[Step]) -> list:
    """Per playlist: its final step when that step is music, else None."""
    groups: list[list[Step]] = []
    for s in steps:
        if s.opens or not groups:
            groups.append([])
        groups[-1].append(s)
    return [g[-1] if g and g[-1].kind == "music" else None for g in groups]


def _join(names: list[str]) -> str:
    names = names[:3] + (["more"] if len(names) > 3 else [])
    text = ", ".join(names)
    return text[:60].replace("/", " ").replace(":", " ")


def hold_title(name: str) -> str:
    return f"HOLD - {name} - press Fade Now when it is over"


def m3u8(pl: Playlist, path_of) -> str:
    """The playlist as text Mixxx imports. `path_of(row)` gives the file for a row (a cut, a hold, or
    the original); a row with no file is left as a comment so the gap is visible, not silent."""
    lines = ["#EXTM3U", f"#PLAYLIST:{pl.n} - {pl.name}"]
    marked = False
    for r in pl.rows:
        if r["repeat"] and not marked:
            lines.append("# --- the same songs again, in case this part runs long ---")
            marked = True
        p = path_of(r)
        # one line per song: a line break or a control character in a tag must not split the entry
        label = " - ".join(x for x in (_one_line(r["artist"]), _one_line(r["title"])) if x)
        if not p:
            lines.append(f"# MISSING: {label}")
            continue
        lines += [f"#EXTINF:{int(round(r['secs'])) or -1},{label}", str(p)]
    return "\n".join(lines) + "\n"


def _one_line(text) -> str:
    return " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", str(text or "")).split())


# --- the checks ---------------------------------------------------------------------------------

def _count(n: float, word: str) -> str:
    """ "1 song", "3 songs", "1 minute", "12 minutes": whole number, the word fitted to what is shown."""
    shown = f"{n:.0f}"
    return f"{shown} {word}" + ("" if shown == "1" else "s")


def checks(steps: list[Step]) -> list[dict]:
    """Things about the night he should know before it starts, worst first:
    {"level": "problem" | "heads-up", "text": plain words}."""
    out: list[dict] = []
    timed = windows(steps)
    for w in timed:
        need = w["minutes"] - HOLD_MIN * w["holds"]      # the live moments fill some of it
        if w["music"] < need - 1:
            add = max(1, round((need - w["music"]) * 60 / AVG_DANCE_SONG_S))
            out.append({"level": "problem",
                        "text": f"{w['name']} is planned for {_count(w['minutes'], 'minute')} and has {_count(w['music'], 'minute')} of "
                                f"music: about {_count(add, 'more song')} would fill it. Until then "
                                f"its songs start repeating after {_count(w['music'], 'minute')}."})
    dancing = [s for s in steps if s.kind == "music" and s.key == "dancing"]
    total = sum(music_seconds(s.songs) for s in dancing) / 60
    if dancing and not any("Dancing" in w["name"] for w in timed) and total < 120:
        out.append({"level": "heads-up",
                    "text": f"Dancing has {_count(total, 'minute')} of music. Most receptions dance for two to two and a "
                            f"half hours, so check it against your timeline; about "
                            f"{_count(max(1, round((135 - total) * 60 / AVG_DANCE_SONG_S)), 'more song')} would cover 2 hours 15."})
    have_song = {s.key for s in steps if s.kind == "song"}
    for k in ("first-dance", "father-daughter", "mother-son", "last-dance", "entrance", "exit-prep", "exit"):
        if any(s.kind == "hold" and s.key == k for s in steps) and k not in have_song:
            out.append({"level": "heads-up", "text": f"{MOMENTS[k][0]} has no song yet: the hold is there, "
                                                     "and Fade Now goes straight to what follows it."})
    for s in steps:
        if s.at and parse_clock(s.at) is None:
            out.append({"level": "heads-up", "text": f'The time "{s.at}" for {s.name} could not be read, so it '
                                                     "is not used. Type it like 6:30."})
    return sorted(out, key=lambda c: c["level"] != "problem")


# --- the sheet ----------------------------------------------------------------------------------

# What the lights do for each look, in words he can check against the room.
LIGHT_WORDS = {"entrance": "Warm white on the floor, then the whole room", "first-dance": "Rose and violet, the heads gliding slowly on the floor",
               "toast": "Warm and steady, nothing moving", "cake": "Soft pink and warm white, still",
               "father-daughter": "Soft gold, the heads gliding slowly on the floor", "last-dance": "Warm verses, violet choruses",
               "party": "Full color and full energy, the derby and lasers in the big moments",
               "": "Each song's own look"}
HOLD_DETAIL = ("Quiet on purpose. Mixxx is playing a silent track called HOLD and waits for you. "
               "It does not move on until you press Fade Now. (It would wait up to an hour.)")   # the hold is an hour long: past that Auto DJ moves on (proof run 43688062579)


def _new_playlist(nxt: "Step", n: int, mins: float) -> str:
    again = f", and start again after {_count(mins, 'minute')}" if mins >= 0.5 else ""
    return (f"When it is time for {_lower(nxt.name)}: in Mixxx, right click playlist {n} in the list on the left, "
            f"choose Add to Auto DJ Queue (replace), then press Fade Now. Until then the songs keep playing{again}.")


def _goes_quiet(nxt: "Step", what: str = "the song") -> str:
    return f"Nothing. When {what} ends, Mixxx goes quiet by itself and waits for you. Next: {nxt.name}."


def sheet_rows(steps: list[Step]) -> list[dict]:
    """One row per thing that happens: when, what it is, what to say, how to move on, the lights.
    `next` is the only column he acts on: what to press when this step is over, or that nothing is
    needed. A hold always says it waits for Fade Now: Mixxx only moves past one by itself after its hour."""
    rows, n = [], 0
    for i, s in enumerate(steps):
        nxt = steps[i + 1] if i + 1 < len(steps) else None
        if s.opens:
            n += 1
        row = {"at": s.at, "what": s.name, "say": s.say, "lights": LIGHT_WORDS.get(s.look, LIGHT_WORDS[""]),
               "playlist": n if s.opens else 0}
        if s.kind == "music":
            mins = music_seconds(s.songs) / 60
            row["detail"] = f"{_count(len(s.songs), 'song')}, {_count(mins, 'minute')}."
            if nxt is None:
                row["next"] = "Nothing. The songs repeat until you stop."
            elif nxt.opens:
                row["next"] = _new_playlist(nxt, n + 1, mins)
            elif nxt.kind == "hold":
                row["next"] = _goes_quiet(nxt, "the last song")
            else:
                row["next"] = f"Nothing. After the last song, {_lower(nxt.name)} follows by itself."
        elif s.kind == "hold":
            row["detail"] = HOLD_DETAIL
            row["next"] = (f"When you are ready, press Fade Now in Mixxx: {_starts(nxt)}." if nxt else
                           "Nothing more: this is the end of the night, and Fade Now has nothing left to start. "
                           "When the room is empty, turn Auto DJ off in Mixxx.")
        else:
            song = s.songs[0] if s.songs else {}
            row["detail"] = f"{song.get('artist', '')}, {_mmss(_secs(song))}.".lstrip(", ")
            if nxt is None:
                row["next"] = "Nothing. It plays through."
            elif nxt.kind == "hold":
                row["next"] = _goes_quiet(nxt)
            else:
                row["next"] = f"Nothing. When it ends, {_lower(nxt.name)} follows by itself."
        rows.append(row)
    return rows


def presses(steps: list[Step]) -> tuple[int, int]:
    """(Fade Now presses, new playlists) the night takes after Enable Auto DJ starts playlist 1:
    one press to leave each hold that has something after it, and one press per new playlist."""
    holds = sum(1 for i, s in enumerate(steps) if s.kind == "hold" and i + 1 < len(steps))
    new = sum(1 for i, s in enumerate(steps) if s.opens and i > 0)
    return holds + new, new


def _lower(name: str) -> str:
    """A step's name mid-sentence: "the first dance", "dinner", "dancing, set 2"."""
    head, sep, rest = name.partition(": ")
    if rest == "quiet background":      # the bed under the toasts or the cake
        return "the quiet background music"
    if head == MOMENTS["exit-prep"][0]:  # "the prepare for grand exit" reads wrong mid-sentence
        head = "Sing-along before the grand exit"
    low = head[0].lower() + head[1:] if head else head
    article = "" if low.split(",")[0] in ("dinner", "dancing", "toasts", "cocktail hour") else "the "
    return f"{article}{low}{sep}{rest}"


def _starts(s: Optional[Step]) -> str:
    if s is None:
        return "nothing follows"
    if s.kind == "music":
        return f"{_lower(s.name)} starts"
    if s.kind == "song":
        title = s.songs[0].get("title", "") if s.songs else ""
        return f"the song starts ({title})" if title else "the song starts"
    return f"the lights change for {_lower(s.name)}, still with no music"


def _mmss(s: float) -> str:
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


def _count_line(steps: list[Step]) -> str:
    fade, new = presses(steps)
    if not steps:
        return "Nothing is planned for tonight yet."
    if not fade:
        return "Tonight there is nothing to press after Enable Auto DJ: the music plays through."
    return (f"Tonight you press Fade Now {fade} time{'s' if fade != 1 else ''} and start a new playlist "
            f"{new} time{'s' if new != 1 else ''}.")

BUTTONS_PICTURE = Path(__file__).with_name("autodj_buttons.png")   # the top of Mixxx 2.5's Auto DJ page, 1 and 2 marked
BUTTONS_CAPTION = "1 is Enable Auto DJ. 2 is Fade Now."


@lru_cache(maxsize=1)
def _buttons_data_uri() -> str:
    """The button picture inline, so the printed sheet is one file that works offline."""
    try:
        return "data:image/png;base64," + base64.b64encode(BUTTONS_PICTURE.read_bytes()).decode("ascii")
    except OSError:
        return ""


def _buttons_figure() -> str:
    """Mixxx writes neither Enable Auto DJ nor Fade Now on screen: both are icons (proof run 43688062579),
    so the sheet shows him which buttons they are. No picture file, no figure: the words still say it."""
    uri = _buttons_data_uri()
    if not uri:
        return ""
    alt = ("The row of buttons at the top of Mixxx's Auto DJ page. 1 marks the first button, a power symbol. "
           "2 marks the second button, two crossing lines.")
    return (f'<figure><img src="{uri}" alt="{html.escape(alt)}" width="427" height="106">'
            f"<figcaption>{html.escape(BUTTONS_CAPTION)}</figcaption></figure>")


def sheet_html(title: str, steps: list[Step], notes: Optional[list] = None, patch: Optional[list] = None) -> str:
    """The night on one printable page: big type, one row per step, and a first line that says how
    to start. The time column only shows when he gave times. `patch` (patch_sheet.rows, BL #12378)
    adds which light is which by its DMX address, on a page of its own when printed."""
    from . import patch_sheet
    e = html.escape
    lights = (f'<h2 class=pb>Which light is which</h2><p>Set each light\'s own display to the address and mode in its row, '
              f'then put it where the row says.</p><div class=patch>{patch_sheet.table_html(patch)}</div>') if patch else ""
    rows = sheet_rows(steps)
    timed = any(r["at"] for r in rows)
    trs = "".join(
        "<tr>" + (f"<td class=t>{e(r['at'])}</td>" if timed else "")
        + f"<td><b>{e(r['what'])}</b>" + (f" <em>playlist {r['playlist']}</em>" if r["playlist"] else "")
        + f"<br><span>{e(r['detail'])}</span>" + (f"<br><i>Say: {e(r['say'])}</i>" if r["say"] else "")
        + f"</td><td class=n>{e(r['next'])}</td><td class=l>{e(r['lights'])}</td></tr>" for r in rows)
    warn = "".join(f"<li>{e(c['text'])}</li>" for c in (notes or []))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{e(title)}: run of show</title>
<style>
body{{font:15px/1.4 system-ui,Segoe UI,Arial,sans-serif;margin:24px;color:#111;background:#fff}}
h1{{font-size:24px;margin:0 0 4px}} p{{margin:4px 0 10px;color:#333}}
table{{border-collapse:collapse;width:100%;table-layout:fixed}} td,th{{border:1px solid #bbb;padding:7px 9px;vertical-align:top;text-align:left;overflow-wrap:anywhere}}
th{{background:#eee}} th.t,td.t{{white-space:nowrap;font-weight:700;width:58px}} th.l,td.l{{width:21%}} th.n,td.n{{width:37%}}
span{{color:#444}} em{{font-style:normal;font-size:12px;border:1px solid #888;border-radius:4px;padding:0 5px;margin-left:4px;white-space:nowrap}}
ul{{margin:6px 0 14px 18px;padding:0}} .k{{border:1px solid #111;border-radius:4px;padding:1px 6px;font-weight:700;white-space:nowrap}}
@media (max-width:640px){{body{{margin:10px;font-size:13px}} td,th{{padding:5px 6px}} th.l,td.l{{width:22%}} th.n,td.n{{width:36%}} th.t,td.t{{width:40px}}}}
.p{{float:right;font:inherit;font-weight:700;padding:8px 16px;border:1px solid #111;border-radius:6px;background:#111;color:#fff;cursor:pointer}}
@media print{{body{{margin:10mm}} tr{{break-inside:avoid}} .p{{display:none}} .pb{{break-before:page}}}}
h2{{font-size:20px;margin:22px 0 4px}}
figure{{margin:4px 0 12px}} figure img{{display:block;width:100%;max-width:427px;height:auto;border:1px solid #bbb}}
figcaption{{font-weight:700;margin-top:3px}}
{patch_sheet._STYLE if patch else ''}
</style></head><body>
<button class=p type=button onclick="window.print()">Print this page</button>
<h1>{e(title)}: run of show</h1>
<p>Mixxx plays the music. Llano Lights listens to Mixxx and runs the lights. Everything you press tonight is in Mixxx.</p>
<p><b>To start the night:</b> open Mixxx and click Auto DJ in the list on the left. At the top of that page is a row
of small buttons with no words on them (picture below). Click the first one, a power symbol: that is
<span class=k>Enable Auto DJ</span>, and it turns orange. If you pressed Load Mixxx at home, playlist 1 is already waiting
in the list. If the list is empty, right click playlist 1 in the list on the left, choose Add to Auto DJ Queue (replace),
then click that first button.</p>
<p><b>What a HOLD is:</b> a silent track Llano Lights put in the playlist so the music stops for a live moment (an
announcement, a toast, the cake). Mixxx shows its name, like HOLD - Toasts and speeches. It waits until you press Fade Now.
It waits up to an hour.</p>
<p><b><span class=k>Fade Now</span></b> is the second button in that row, with two crossing lines. Mixxx does not write
Fade Now on it; rest the mouse on it and it says Trigger the transition to the next track. Click it with the mouse.
<span class=k>Shift</span> + <span class=k>F11</span> may do the same on your laptop, but the click always works.</p>
{_buttons_figure()}
<p><b>{e(_count_line(steps))}</b></p>
<p>After you choose Add to Auto DJ Queue (replace), the first row of the list may still be the song Mixxx had lined up.
That is fine: Fade Now goes to the new playlist.</p>
<p><b>If anything goes wrong:</b> turn the main volume down, breathe, and press Fade Now again. Nothing here can break the night.</p>
{f'<ul>{warn}</ul>' if warn else ''}
<table><tr>{'<th class=t>Time</th>' if timed else ''}<th>What happens</th><th class=n>To move on</th><th class=l>Lights</th></tr>{trs}</table>
{lights}
</body></html>
"""


def show_songs(steps: list[Step]) -> list[dict]:
    """The steps as show songs for the contract (artist, title, secs, look, part, moment), holds
    included, so the saved show gives each hold and moment its look when Mixxx plays it."""
    out = []
    for s in steps:
        if s.kind == "hold":
            out.append({"artist": "Llano hold", "title": hold_title(s.name), "secs": 0, "look": s.look,
                        "why": f"The lights for {s.name.lower()}"})
            continue
        for song in s.songs:
            d = {"artist": song.get("artist", ""), "title": song.get("title", ""), "secs": _secs(song),
                 "look": s.look if s.kind == "song" else song.get("look", "")}
            if s.kind == "music" and s.key in BEDS:
                if any(o["artist"] == d["artist"] and o["title"] == d["title"] for o in out):
                    continue   # a dinner song played again under the toasts is already in the show
                d["moment"] = s.key
            if s.kind == "music" and s.key in contract.SHOW_PARTS:
                d["part"] = s.key
            if s.kind == "song":
                d["moment_key"] = s.key
                if s.key in contract.SHOW_MOMENTS:
                    d["moment"], d["part"] = s.key, "dancing"
            out.append(d)
    return out
