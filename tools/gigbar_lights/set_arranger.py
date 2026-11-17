"""The set arranger (Llano PM #23177): a playlist or crate put in an order that flows, with a reason
for every song's spot, that he can talk through in plain words.

What it reads per song (song_facts): tempo, key (Camelot), energy, length, era, artist, and from the
song canon whether the room sings along, how broadly known it is, and the wedding moments it suits.
Its sections come from shows.analyze as before.

What "flows" means here, as costs the order is scored on (lower is better):
  - each song sits near the energy its spot asks for (the part's target curve, below);
  - tempo steps stay small (half and double time count as close: 70 into 140 is a clean mix);
  - keys step to a Camelot neighbour (same number, one step round the wheel, or the relative
    major/minor); a clash is allowed but costs;
  - never the same artist twice in a row (hard), and not one song apart if it can be helped;
  - eras blend: four songs in a row from one decade costs a little.

The night, for a wedding (the default event, his ruling 2026-11-12: a wedding, not an after-party):
  cocktail  warm and social: mid-low energy, gentle sway, no ballads to open it
  dinner    low and conversational: starts easy, settles lower, lifts at the end into the dancing
  dancing   the couple's dances first (first dance, father-daughter, mother-son), then a broadly
            known all-ages hype opener, then waves (climb, peak, a breather), a slow-dance window
            past the middle, a final climb, the last dance, and one big sing-along to end the night.
An after-party skips the moments and opens mid-energy instead of with a hype song.

The order is found by scoring, not by an LLM: a greedy fill against the target curve, then swaps
until no swap helps (deterministic: the same songs always give the same order). Songs he moved or
gave a moment stay where he put them when it arranges again.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Optional

from . import song_canon
from . import settings_contract as contract
from .song_match import norm

PARTS = contract.SHOW_PARTS          # ("cocktail", "dinner", "dancing")
MOMENTS = contract.SHOW_MOMENTS      # ("first-dance", "father-daughter", "mother-son", "last-dance")
PART_NAMES = {"cocktail": "Cocktail hour", "dinner": "Dinner", "dancing": "Dancing"}
MOMENT_NAMES = {"first-dance": "First dance", "father-daughter": "Father-daughter dance",
                "mother-son": "Mother-son dance", "last-dance": "Last dance",
                "exit-prep": "Grand exit sing-along", "exit": "Bride and groom exit"}
# The quiet music under the toasts and the cake: never a dance, it keeps its part and its own order
# (his instrumentals play in their folder's numbered order).
BEDS = ("background", "toasts-background")
EVENTS = {"wedding": "Wedding", "party": "After-party"}
SLOW_BPM = 92
REASON_CHARS = 90


# --- song facts -----------------------------------------------------------------------------------

_PITCH = {"c": 0, "c#": 1, "db": 1, "d": 2, "d#": 3, "eb": 3, "e": 4, "fb": 4, "e#": 5, "f": 5, "f#": 6,
          "gb": 6, "g": 7, "g#": 8, "ab": 8, "a": 9, "a#": 10, "bb": 10, "b": 11, "cb": 11, "b#": 0}
# Camelot number for a major key's pitch class (C major = 8B); a minor key is its relative major's number.
_MAJOR_NUM = {0: 8, 7: 9, 2: 10, 9: 11, 4: 12, 11: 1, 6: 2, 1: 3, 8: 4, 3: 5, 10: 6, 5: 7}


def camelot(key) -> str:
    """Any key spelling Mixxx or a tag writes, as Camelot ("8A"): "8A", "Am", "A minor", "Bbm",
    "F#", "C maj", Open Key ("1m" = 8A, "1d" = 8B). "" when it can't be read."""
    s = str(key or "").strip().replace("♯", "#").replace("♭", "b")
    if not s:
        return ""
    m = re.fullmatch(r"0?([1-9]|1[0-2])\s*([abAB])", s)
    if m:
        return f"{int(m.group(1))}{m.group(2).upper()}"
    m = re.fullmatch(r"([1-9]|1[0-2])\s*([mdMD])", s)   # Open Key: 1m = 8A ... 12m = 7A
    if m:
        n = (int(m.group(1)) + 6) % 12 + 1
        return f"{n}{'A' if m.group(2).lower() == 'm' else 'B'}"
    m = re.fullmatch(r"([A-Ga-g])\s*([#b]?)\s*(m|min|minor|maj|major|M)?", s)
    if not m:
        return ""
    pc = _PITCH.get((m.group(1) + m.group(2)).lower())
    if pc is None:
        return ""
    minor = (m.group(3) or "") in ("m", "min", "minor")
    if minor:
        return f"{_MAJOR_NUM[(pc + 3) % 12]}A"
    return f"{_MAJOR_NUM[pc]}B"


def key_step(a: str, b: str) -> float:
    """0 for a clean Camelot step (same key, one round the wheel, relative major/minor), 0.5 for
    two round or a diagonal, 1 for a clash; 0.25 when either key is unknown."""
    if not a or not b:
        return 0.25
    na, la, nb, lb = int(a[:-1]), a[-1], int(b[:-1]), b[-1]
    d = min((na - nb) % 12, (nb - na) % 12)
    if la == lb:
        return 0.0 if d <= 1 else 0.5 if d == 2 else 1.0
    return 0.0 if d == 0 else 0.5 if d == 1 else 1.0


def tempo_step(a: float, b: float) -> float:
    """How far apart two tempos are as a fraction (half and double time count as the same tempo)."""
    if a <= 0 or b <= 0:
        return 0.0
    return min(abs(math.log(b / a)), abs(math.log(b / (2 * a))), abs(math.log(2 * b / a)))


@dataclass
class Facts:
    """What the arranger knows about one song, and where each fact came from."""
    bpm: float = 0.0
    key: str = ""            # Camelot
    energy: float = 0.5      # 0..1
    year: int = 0
    sing: int = 0            # 0..3
    known: int = 0           # 0..3
    tags: frozenset = frozenset()
    in_canon: bool = False
    energy_from: str = "tempo"

    @property
    def slow(self) -> bool:
        if "slow" in self.tags:
            return True
        if self.in_canon:
            return False
        return 0 < self.bpm < SLOW_BPM and self.energy < 0.45

    @property
    def era(self) -> str:
        return f"{self.year // 10 * 10}s" if self.year else ""


def _tempo_energy(bpm: float) -> float:
    if bpm <= 0:
        return 0.5
    b = bpm
    if b > 160:     # double-counted grids read fast: 170 is a 85 groove more often than a sprint
        b /= 2
    return max(0.1, min(0.95, (b - 70) / 70))


def facts_for(song, audio_level: Optional[float] = None) -> Facts:
    """Facts for a ShowSong: its tempo and key from the library, its energy from the canon when the
    canon knows it (blended with tempo), else from its tempo and how loud and full its audio is."""
    f = Facts(bpm=float(getattr(song, "bpm", 0) or 0), key=camelot(getattr(song, "camelot", "")),
              year=int(getattr(song, "year", 0) or 0))
    k = song_canon.lookup(song.artist, song.title)
    tempo = _tempo_energy(f.bpm)
    if k:
        f.in_canon, f.sing, f.known, f.tags = True, k.sing, k.known, k.tags
        f.year = k.year or f.year   # a file's tag often holds a remaster or compilation year
        f.energy = round(0.8 * (k.energy / 10) + 0.2 * tempo, 3)
        f.energy_from = "what the song is known for, and its tempo"
    elif audio_level is not None:
        f.energy = round(0.6 * tempo + 0.4 * max(0.0, min(1.0, audio_level)), 3)
        f.energy_from = "its tempo and how full the audio is"
    else:
        f.energy = round(tempo, 3)
    return f


# --- the plan: one target per spot ---------------------------------------------------------------

@dataclass
class Slot:
    part: str
    role: str        # opener, warm, rise, peak, breather, slow, close, moment, settle, lift
    target: float
    moment: str = ""
    wave: int = 0


def _wave_roles(n: int) -> list[tuple[str, float, int]]:
    """Dance-floor waves for n spots: climb, peak, breather, repeated, each wave a touch higher."""
    out, w = [], 1
    while len(out) < n:
        size = min(6, n - len(out))
        lift = min(0.06, 0.02 * (w - 1))
        shape = [("rise", 0.74), ("rise", 0.8), ("peak", 0.88), ("peak", 0.92), ("breather", 0.62), ("rise", 0.76)]
        if size < 6:
            shape = [("rise", 0.76), ("peak", 0.88), ("peak", 0.92), ("breather", 0.64), ("rise", 0.8)][:size]
        out += [(r, min(0.97, t + lift), w) for r, t in shape[:size]]
        w += 1
    return out


def plan_part(part: str, n: int, event: str, n_slow: int) -> list[Slot]:
    """Target spots for n free songs of one part (moments are placed separately)."""
    if n <= 0:
        return []
    if part == "cocktail":
        return [Slot(part, "warm" if i else "opener", round(0.46 + 0.05 * math.sin(i / max(1, n - 1) * math.pi * 2)
                                                           + 0.04 * i / max(1, n - 1), 3)) for i in range(n)]
    if part == "dinner":
        out = []
        for i in range(n):
            x = i / max(1, n - 1)
            t = 0.36 - 0.1 * math.sin(x * math.pi) + (0.08 * (x - 0.75) / 0.25 if x > 0.75 else 0)
            out.append(Slot(part, "lift" if x > 0.8 else "settle", round(t, 3)))
        return out
    # dancing
    n_close = 0 if n < 5 else 2 if n < 12 else 3
    n_open = 1 if n >= 2 else 0
    # The slow window gets only the spots the opener and the close leave (whole-app audit, 2026-11-12):
    # capped at n - 3, a dancing part of 12+ songs nearly all slow planned one spot too many and
    # Arrange the set crashed (an untagged playlist heavy with ballads defaults to dancing).
    n_slow = min(n_slow, max(0, n - n_close - n_open))
    n_mid = n - n_slow - n_close - n_open
    pre = round(n_mid * 0.7)   # the slow window sits past the middle, once the floor is warm
    waves = _wave_roles(n_mid)
    out = []
    if n_open:
        out.append(Slot(part, "opener", 0.86 if event == "wedding" else 0.7))
    out += [Slot(part, r, t, wave=w) for r, t, w in waves[:pre]]
    out += [Slot(part, "slow", 0.3) for _ in range(n_slow)]
    out += [Slot(part, r, t, wave=w + (10 if n_slow else 0)) for r, t, w in waves[pre:]]
    out += [Slot(part, "close", 0.95 - 0.02 * i) for i in range(n_close)]
    return out


# --- scoring --------------------------------------------------------------------------------------

def _pair_cost(a: Facts, b: Facts, artist_a: str, artist_b: str) -> float:
    c = 0.0
    if artist_a and artist_a == artist_b:
        c += 50.0
    d = tempo_step(a.bpm, b.bpm)
    if d > 0.06:
        c += 4.0 * (d - 0.06)
    c += 0.35 * key_step(a.key, b.key)
    c += 1.2 * max(0.0, abs(a.energy - b.energy) - 0.25)   # no cliff edges between neighbours
    return c


def _slot_cost(f: Facts, s: Slot) -> float:
    c = (12.0 if s.role in ("opener", "close", "peak") else 6.0) * (f.energy - s.target) ** 2
    if s.role == "slow":
        c += 0.0 if f.slow else 2.5
    elif f.slow and s.part == "dancing":
        c += 2.5
    if s.role == "opener" and s.part == "dancing":
        c += 0.5 * (3 - f.known) + (0.0 if "hype" in f.tags else 0.4)
        c += 1.5 if "line" in f.tags else 0.0     # a line dance needs a floor to start with
    if s.role == "close":
        c += 0.6 * (3 - f.sing) + (0.0 if "closer" in f.tags else 0.8)
    elif "closer" in f.tags and s.part == "dancing" and s.role in ("opener", "rise") and s.wave in (1, 2):
        c += 0.5   # an end-of-night anthem spent in the first waves is missed at the close
    if s.role == "opener" and s.part == "cocktail" and f.slow:
        c += 1.0
    if s.part in ("cocktail", "dinner") and f.energy > 0.7:
        c += 2.0 * (f.energy - 0.7)
    return c


def _artist(song) -> str:
    """The lead artist, so "Shenandoah ft. Luke Combs" and "Shenandoah" read as the same act."""
    a = re.split(r"\s+(?:ft\.?|feat\.?|featuring|x)\s+|,", str(song.artist or "").lower())[0]
    return norm(contract.track_key(a))


def order_cost(songs: list, facts: list[Facts], slots: list[Slot]) -> float:
    c = sum(_slot_cost(f, s) for f, s in zip(facts, slots))
    arts = [_artist(s) for s in songs]
    for i in range(1, len(songs)):
        c += _pair_cost(facts[i - 1], facts[i], arts[i - 1], arts[i])
        if i >= 2 and arts[i] and arts[i] == arts[i - 2]:
            c += 1.5
        if i >= 3 and facts[i].era and len({facts[j].era for j in range(i - 3, i + 1)}) == 1:
            c += 0.3
    return c


# --- arranging ------------------------------------------------------------------------------------

@dataclass
class Placed:
    song: object
    facts: Facts
    slot: Slot
    pinned: bool = False


def _part_of(song, event: str) -> str:
    p = getattr(song, "part", "") or ""
    if event != "wedding":
        return "dancing"
    return p if p in PARTS else "dancing"


def _arrange_part(items: list, slots: list[Slot], pinned_at: dict) -> list:
    """Order one part's songs into its slots: pinned songs hold their index, the rest are filled
    greedily by energy rank then improved by swaps until no swap lowers the cost."""
    n = len(slots)
    order: list = [None] * n
    for i, it in pinned_at.items():
        order[i] = it
    free_idx = [i for i in range(n) if order[i] is None]
    free = [it for it in items if it not in pinned_at.values()]
    # greedy: slow songs into slow slots first, then the rest by energy rank against target rank
    slow_slots = [i for i in free_idx if slots[i].role == "slow"]
    slow_songs = sorted([it for it in free if it[1].slow], key=lambda it: it[1].energy)
    for i, it in zip(slow_slots, slow_songs):
        order[i] = it
    rest_idx = [i for i in free_idx if order[i] is None]
    used = {id(order[i]) for i in slow_slots if order[i] is not None}
    rest = [it for it in free if id(it) not in used]
    rest_idx.sort(key=lambda i: slots[i].target)
    rest.sort(key=lambda it: (it[1].energy, it[0].title.lower()))
    for i, it in zip(rest_idx, rest):
        order[i] = it

    def cost(o):
        return order_cost([x[0] for x in o], [x[1] for x in o], slots)

    movable = [i for i in range(n) if i not in pinned_at]
    best = cost(order)
    for _ in range(40):
        improved = False
        for a in range(len(movable)):          # swap two songs
            for b in range(a + 1, len(movable)):
                i, j = movable[a], movable[b]
                order[i], order[j] = order[j], order[i]
                c = cost(order)
                if c < best - 1e-9:
                    best, improved = c, True
                else:
                    order[i], order[j] = order[j], order[i]
        for a in range(len(movable)):          # lift one song out and drop it elsewhere
            for b in range(len(movable)):
                if a == b:
                    continue
                vals = [order[i] for i in movable]
                v = vals.pop(a)
                vals.insert(b, v)
                trial = list(order)
                for i, x in zip(movable, vals):
                    trial[i] = x
                c = cost(trial)
                if c < best - 1e-9:
                    best, improved, order = c, True, trial
        if not improved:
            break
    return order


def arrange(songs: list, event: str = "wedding", levels: Optional[dict] = None) -> list[Placed]:
    """The whole set in order. `songs` are shows.ShowSong (with .part, .moment and .pinned): a song
    he placed by hand (pinned) keeps its position within its part. `levels` maps a song index to its
    audio fullness 0..1 when the audio was read."""
    event = event if event in EVENTS else "wedding"
    levels = levels or {}
    pins = {i for i, s in enumerate(songs) if getattr(s, "pinned", False)}
    facts = [facts_for(s, levels.get(i)) for i, s in enumerate(songs)]
    for s in songs:
        if event == "wedding" and getattr(s, "moment", "") in MOMENTS and s.moment not in BEDS:
            s.part = "dancing"    # the couple's dances open the dancing; the last dance closes it
    out: list[Placed] = []
    parts = PARTS if event == "wedding" else ("dancing",)
    for part in parts:
        idx = [i for i, s in enumerate(songs) if _part_of(s, event) == part]
        if not idx:
            continue
        mom = {m: [i for i in idx if getattr(songs[i], "moment", "") == m] for m in MOMENTS} if event == "wedding" else {}
        head = [i for m in ("first-dance", "father-daughter", "mother-son") for i in mom.get(m, [])]
        tail = mom.get("last-dance", [])
        beds = [i for m in BEDS for i in mom.get(m, [])]
        free = [i for i in idx if i not in head and i not in tail and i not in beds]
        n_slow = sum(1 for i in free if facts[i].slow) if part == "dancing" else 0
        slots = plan_part(part, len(free), event, n_slow)
        # a pinned song keeps its place among the free songs of its part
        pos_in_part = {i: k for k, i in enumerate([i for i in idx if i not in head and i not in tail and i not in beds])}
        pinned_at = {pos_in_part[i]: (songs[i], facts[i], i) for i in free if i in pins and pos_in_part[i] < len(slots)}
        items = [(songs[i], facts[i], i) for i in free]
        order = _arrange_part(items, slots, pinned_at) if free else []
        for i in head:
            out.append(Placed(songs[i], facts[i], Slot(part, "moment", facts[i].energy, songs[i].moment), True))
        placed = [Placed(it[0], it[1], slots[k], it[2] in pins) for k, it in enumerate(order)]
        # The last dance goes just before the night's final sing-along, so one big song still sends
        # everyone off (his wedding, 2026-11-12: Why Don't We Just Dance, then Don't Stop Believin').
        # With no close planned, it is the final song.
        at = len(placed) - 1 if placed and placed[-1].slot.role == "close" else len(placed)
        placed[at:at] = [Placed(songs[i], facts[i], Slot(part, "moment", facts[i].energy, "last-dance"), True) for i in tail]
        out += placed
        out += [Placed(songs[i], facts[i], Slot(part, "moment", facts[i].energy, songs[i].moment), True) for i in beds]
    explain_all(out, event)
    return out


# --- reasons --------------------------------------------------------------------------------------

def _bpm(f: Facts) -> str:
    return f"{f.bpm:.0f} BPM" if f.bpm else ""


def _step_words(a: Facts, b: Facts) -> str:
    bits = []
    if a.bpm and b.bpm:
        d = tempo_step(a.bpm, b.bpm)
        if d <= 0.06 and abs(math.log(b.bpm / a.bpm)) > 0.5:
            bits.append(f"{a.bpm:.0f} to {b.bpm:.0f} BPM in half time")
        elif d <= 0.06:
            bits.append(f"{a.bpm:.0f} to {b.bpm:.0f} BPM")
        else:
            bits.append(f"a tempo jump, {a.bpm:.0f} to {b.bpm:.0f}")
    if a.key and b.key:
        ks = key_step(a.key, b.key)
        bits.append(f"{a.key} to {b.key}" + ("" if ks == 0 else ", a key clash" if ks >= 1 else ", a key stretch"))
    return ", ".join(bits)


def reason(p: Placed, prev: Optional[Placed], nxt: Optional[Placed], event: str, nth: dict) -> str:
    f, s = p.facts, p.slot
    t = s.part
    if s.role == "moment":
        r = {"first-dance": "The first dance: the couple's song, before the floor opens",
             "father-daughter": "Father-daughter dance, right after the first dance",
             "mother-son": "Mother-son dance, after the father-daughter dance",
             "last-dance": ("The last dance, then one sing-along to send everyone off" if nxt and nxt.slot.part == t
                            else "The last dance: the final song of the night"),
             "toasts-background": "Plays quietly under the toasts and speeches, in your folder's order",
             "background": "Plays quietly under the cake cutting"}.get(s.moment, "Its moment")
    elif p.pinned:
        r = "You put it here"
    elif t == "cocktail":
        r = ("Opens cocktail hour warm and easy" if s.role == "opener"
             else "Keeps cocktail hour warm and social" if f.energy >= 0.45 else "A softer one so people can talk")
    elif t == "dinner":
        r = ("Lifts dinner toward the dancing" if s.role == "lift" else
             "Low under dinner so tables can talk" if f.energy < 0.4 else "Easy dinner warmth, still conversational")
    elif s.role == "opener":
        r = ("Opens the dancing: a hype song every age knows" if event == "wedding" and f.known >= 3
             else "Opens the dancing" + (", well known" if f.known >= 2 else ""))
    elif s.role == "slow":
        k = nth.setdefault("slow", 0) + 1
        nth["slow"] = k
        r = f"Slow-dance window, song {k}: couples back on the floor"
    elif s.role == "close":
        r = "Big sing-along close: the room knows every word" if f.sing >= 3 else "Part of the big close"
    elif s.role == "breather":
        r = "A breather after the peak, people catch their breath"
    elif s.role == "peak":
        r = f"Top of wave {s.wave % 10}: the floor at full energy"
    else:
        r = "Builds the floor back up" if prev and prev.slot.role in ("breather", "slow") else "Keeps the floor climbing"
    if s.role != "moment" and prev and prev.slot.part == t:
        step = _step_words(prev.facts, f)
        if step and len(r) + len(step) + 2 <= REASON_CHARS:
            r += f" ({step})"
    elif s.role != "moment" and _bpm(f) and len(r) + len(_bpm(f)) + 3 <= REASON_CHARS:
        r += f" ({_bpm(f)})"
    return r[:REASON_CHARS]


def explain_all(placed: list[Placed], event: str) -> None:
    nth: dict = {}
    for k, p in enumerate(placed):
        prev = placed[k - 1] if k else None
        nxt = placed[k + 1] if k + 1 < len(placed) else None
        p.song.reason = reason(p, prev, nxt, event, nth)


# --- curves and checks --------------------------------------------------------------------------

def curves(placed: list[Placed]) -> dict:
    """{part: [{n, title, energy, target}]} for the window's energy curve per part (n is 1-based in
    the whole show)."""
    out: dict = {}
    for n, p in enumerate(placed, 1):
        out.setdefault(p.slot.part, []).append({"n": n, "title": p.song.title, "artist": p.song.artist,
                                                "energy": round(p.facts.energy, 3),
                                                "target": round(p.slot.target, 3), "role": p.slot.role})
    return out


def warnings(placed: list[Placed]) -> list[str]:
    """Rule breaks in an order, in plain words (a hand-made order can have them)."""
    out = []
    for k in range(1, len(placed)):
        a, b = placed[k - 1], placed[k]
        if a.slot.part != b.slot.part:
            continue
        if _artist(a.song) and _artist(a.song) == _artist(b.song):
            out.append(f"{a.song.artist} plays twice in a row ({a.song.title}, then {b.song.title})")
        if key_step(a.facts.key, b.facts.key) >= 1 and tempo_step(a.facts.bpm, b.facts.bpm) > 0.12:
            out.append(f"{a.song.title} into {b.song.title} jumps both key and tempo")
        if b.facts.slow and b.slot.part == "dancing" and b.slot.role not in ("slow", "moment") \
                and not a.facts.slow and k + 1 < len(placed) and not placed[k + 1].facts.slow:
            out.append(f"{b.song.title} is a slow song on its own in the middle of the dancing")
    return out


def score(placed: list[Placed]) -> float:
    total = 0.0
    for part in PARTS:
        ps = [p for p in placed if p.slot.part == part]
        if ps:
            total += order_cost([p.song for p in ps], [p.facts for p in ps], [p.slot for p in ps])
    return round(total, 3)


# --- a given order, scored as it stands (after he moves something) ----------------------------------

def _sorted_by_part(songs: list, event: str) -> list:
    """The songs in their order, parts kept together in night order (stable within a part)."""
    order = {p: k for k, p in enumerate(PARTS)}
    rank = {"first-dance": 0, "father-daughter": 1, "mother-son": 2}   # the last dance stays where it is
    for s in songs:
        s.part = _part_of(s, event)
        if event == "wedding" and s.moment in MOMENTS and s.moment not in BEDS:
            s.part = "dancing"    # the couple's dances open the dancing; the last dance closes it
    return sorted(songs, key=lambda s: (order.get(s.part, len(PARTS)),
                                        rank.get(s.moment, 5) if event == "wedding" else 5))


def evaluate(songs: list, event: str = "wedding", levels: Optional[dict] = None) -> list[Placed]:
    """The order exactly as given, each song read against the spot it sits in, with its reason."""
    event = event if event in EVENTS else "wedding"
    levels = levels or {}
    keyed = {id(s): i for i, s in enumerate(songs)}
    songs = _sorted_by_part(list(songs), event)
    out: list[Placed] = []
    for part in (PARTS if event == "wedding" else ("dancing",)):
        ps = [s for s in songs if s.part == part]
        free = [s for s in ps if not (event == "wedding" and s.moment in MOMENTS)]
        facts = {id(s): facts_for(s, levels.get(keyed[id(s)])) for s in ps}
        n_slow = sum(1 for s in free if facts[id(s)].slow) if part == "dancing" else 0
        slots = iter(plan_part(part, len(free), event, n_slow))
        for s in ps:
            f = facts[id(s)]
            if event == "wedding" and s.moment in MOMENTS:
                out.append(Placed(s, f, Slot(part, "moment", f.energy, s.moment), True))
                continue
            sl = next(slots)
            if part == "dancing" and f.slow and sl.role != "slow":
                sl = Slot(part, "slow", 0.3)
            elif part == "dancing" and sl.role == "slow" and not f.slow:
                sl = Slot(part, "rise", 0.76)
            out.append(Placed(s, f, sl, bool(getattr(s, "pinned", False))))
    explain_all(out, event)
    return out


# --- talking it through ----------------------------------------------------------------------------

_ROLE_WHY = {
    "opener": "The first song of the dancing has to pull every age onto the floor at once, so it wants "
              "high energy and a song everyone knows.",
    "rise": "This stretch climbs toward a peak, so each song should lift a little on the one before.",
    "peak": "This is the top of a wave, where the floor is fullest, so it wants the most energy.",
    "breather": "Right after a peak the floor needs a breather: still danceable, a notch lower, so "
                "people catch their breath without leaving.",
    "slow": "The slow-dance window sits past the middle of the dancing, once the floor is warm, so "
            "couples come back together before the last climb.",
    "close": "The close wants the biggest sing-alongs, so the night ends with the whole room singing.",
    "warm": "Cocktail hour stays warm and social: upbeat enough to feel like a party, soft enough to talk over.",
    "settle": "Dinner sits low so tables can talk.",
    "lift": "The end of dinner lifts the energy so the dancing doesn't start cold.",
    "moment": "This is one of the wedding's moments, so it holds its place.",
}


def _pos_words(placed: list[Placed], k: int) -> str:
    p = placed[k]
    in_part = [i for i, x in enumerate(placed) if x.slot.part == p.slot.part]
    return f"song {k + 1} of the show, {in_part.index(k) + 1} of {len(in_part)} in {PART_NAMES[p.slot.part]}"


def explain(placed: list[Placed], k: int) -> str:
    """Why one song is where it is, in a few plain sentences."""
    p = placed[k]
    f = p.facts
    bits = [f"{p.song.title} is {_pos_words(placed, k)}. {p.song.reason}."]
    if p.slot.role in _ROLE_WHY and not p.pinned:
        bits.append(_ROLE_WHY[p.slot.role])
    if p.pinned and p.slot.role != "moment":
        bits.append("You placed it, so arranging again leaves it here.")
    facts = [f"{f.energy * 10:.0f} out of 10 on energy (from {f.energy_from})"]
    if f.bpm:
        facts.append(f"{f.bpm:.0f} BPM")
    if f.key:
        facts.append(f"key {f.key}")
    if f.era:
        facts.append(f"from the {f.era}")
    if f.sing >= 3:
        facts.append("a big sing-along")
    bits.append("It reads " + ", ".join(facts) + (f"; this spot asks for about {p.slot.target * 10:.0f}." if p.slot.role != "moment" else "."))
    prev = placed[k - 1] if k and placed[k - 1].slot.part == p.slot.part else None
    nxt = placed[k + 1] if k + 1 < len(placed) and placed[k + 1].slot.part == p.slot.part else None
    if prev:
        bits.append(f"Coming out of {prev.song.title}: {_step_words(prev.facts, f) or 'no tempo or key on file'}.")
    if nxt:
        bits.append(f"Into {nxt.song.title}: {_step_words(f, nxt.facts) or 'no tempo or key on file'}.")
    return " ".join(bits)


def _words(t: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(t or "").lower().replace("'", "").replace("’", ""))


_FILLER = {"the", "a", "song", "track", "one", "by", "please", "that", "this"}


def find_song(phrase: str, songs: list) -> tuple[Optional[int], float, list[int]]:
    """(index, confidence 0..1, other close matches) for a song named in plain words: a title, part
    of one, "artist title", "title by artist", or "song 12" / "#12" / "number 12"."""
    ph = str(phrase or "").strip().strip("?.!,\"'")
    m = re.fullmatch(r"(?:song|number|no\.?|#|spot)\s*(\d{1,2})", ph.lower())
    if m:
        i = int(m.group(1)) - 1
        return (i, 1.0, []) if 0 <= i < len(songs) else (None, 0.0, [])
    w = [x for x in _words(ph) if x not in _FILLER] or _words(ph)
    if not w:
        return None, 0.0, []
    scores = []
    for i, s in enumerate(songs):
        t, a = _words(s.title), _words(s.artist)
        core_t = _words(re.sub(r"\s*[\(\[].*?[\)\]]", "", s.title))
        if w == core_t or w == t:
            sc = 1.0
        elif w == a + core_t or w == core_t + a or w == core_t + ["by"] + a:
            sc = 0.98
        elif len(w) >= 1 and " ".join(w) in " ".join(core_t) and (len(w) >= 2 or len(w[0]) >= 4):
            sc = 0.8 * len(w) / max(len(core_t), 1) + 0.15
        elif set(core_t) and set(core_t) <= set(w):
            sc = 0.85   # the title plus the artist or other words
        else:
            hit = len(set(w) & set(core_t + a)) / len(set(w))
            sc = 0.6 * hit if hit >= 0.5 else 0.0
            if w == a:
                sc = 0.55
        scores.append((sc, i))
    scores.sort(key=lambda x: (-x[0], x[1]))
    best, i = scores[0]
    if best <= 0:
        return None, 0.0, []
    close = [j for sc, j in scores[1:] if sc > 0 and best - sc < 0.05]
    return i, best, close


_PART_WORDS = {"cocktail": "cocktail", "cocktails": "cocktail", "cocktail hour": "cocktail", "dinner": "dinner",
               "dancing": "dancing", "dance floor": "dancing", "the dancing": "dancing", "party": "dancing"}
_MOMENT_WORDS = (("first dance", "first-dance"), ("father daughter", "father-daughter"),
                 ("father-daughter", "father-daughter"), ("daddy daughter", "father-daughter"),
                 ("mother son", "mother-son"), ("mother-son", "mother-son"), ("last dance", "last-dance"),
                 ("last song", "last-dance"))
_OPS = r"(right after|just after|right before|just before|after|before|to|into|in|up|down|earlier|later|first|last|next to)"


@dataclass
class Reply:
    answer: str
    songs: Optional[list] = None     # the new order when it changed
    changed: bool = False
    rearrange: bool = False
    focus: int = -1                  # the song the answer is about (index into the new order)


def _part_in(text: str) -> str:
    t = " ".join(_words(text))
    for k in sorted(_PART_WORDS, key=len, reverse=True):
        if re.search(rf"\b{k}\b", t):
            return _PART_WORDS[k]
    return ""


def _moment_in(text: str) -> str:
    t = " ".join(_words(text.replace("-", " ")))
    for words, key in _MOMENT_WORDS:
        if words.replace("-", " ") in t:
            return key
    return ""


def _moment_at(text: str) -> int:
    """Where a moment's name starts in lowercase text ("make X the first dance"), else -1."""
    best = -1
    for words, _ in _MOMENT_WORDS:
        m = re.search(r"\b" + r"[\s-]+".join(re.escape(w) for w in words.replace("-", " ").split()) + r"\b", text)
        if m and (best < 0 or m.start() > best):
            best = m.start()
    return best


def _best_spot(songs: list, s, part: str, event: str) -> int:
    """Where in `part` the song costs least, as an index into `songs` (which excludes s)."""
    idx = [i for i, x in enumerate(songs) if _part_of(x, event) == part]
    cands = list(range(idx[0], idx[-1] + 2)) if idx else [len(songs)]
    best, at = None, cands[-1]
    for i in cands:
        trial = songs[:i] + [s] + songs[i:]
        c = score(evaluate(trial, event))
        if best is None or c < best - 1e-9:
            best, at = c, i
    return at


def _split_subject(rest: str, songs: list) -> tuple[Optional[int], float, str, str, list]:
    """For "X after Y" style text: the split where X names a song most surely -> (i, conf, op, tail, close)."""
    best = (None, 0.0, "", "", [])
    for m in re.finditer(rf"\s+{_OPS}\b", rest, re.I):
        subj, op, tail = rest[:m.start()], m.group(1).lower(), rest[m.end():].strip()
        i, conf, close = find_song(subj, songs)
        if i is not None and conf > best[1]:
            best = (i, conf, op, tail, close)
    return best


def discuss(text: str, songs: list, event: str = "wedding") -> Reply:
    """One plain-words turn about the set. `songs` are in show order (ShowSongs); a move returns the
    new order with the moved song pinned so arranging again keeps it there."""
    q = " ".join(str(text or "").split())[:300]
    low = q.lower()
    if not songs:
        return Reply("There are no songs in this show yet. Add a playlist first.")
    placed = evaluate(list(songs), event)
    order = [p.song for p in placed]

    def name(s):
        return f"{s.title}" + (f" by {s.artist}" if s.artist else "")

    def unsure(close, i):
        opts = ", ".join(order[j].title for j in [i] + close[:3])
        return Reply(f"Which one do you mean: {opts}?")

    if re.search(r"\b(arrange|re-?arrange|reorder|redo|start over)\b", low) and not re.search(r"\bwhy\b", low):
        return Reply("Arranging the whole set again; songs you placed by hand stay put.", rearrange=True)

    m = re.match(r"^(?:why|how come|explain)\b\s*(?:is|does|did|do|are|was|you put|put|have)?\s*(.*)$", low)
    if m:
        rest = re.sub(r"\b(here|there|where it is|where it sits|in this spot|in that spot|placed|play|plays|"
                      r"playing|come|comes|go|goes|sit|sits|at|so early|so late|early|late|now|number \d+|spot \d+)\b",
                      " ", m.group(1)).strip(" ?.")
        part = _part_in(rest)
        i, conf, close = find_song(rest, order) if rest else (None, 0.0, [])
        if i is None or conf < 0.5 or (part and conf < 0.9):
            if part:
                ps = [p for p in placed if p.slot.part == part]
                return Reply(f"{PART_NAMES[part]} has {len(ps)} songs. " + _part_shape(part, ps, event))
            return Reply("Which song? Ask like: why is Wagon Wheel here?")
        if close and conf < 0.95:
            return unsure(close, i)
        return Reply(explain(placed, i), focus=i)

    m = re.match(r"^(?:make|set|use|have)\s+(.+)$", low)
    mom_at = _moment_at(m.group(1)) if m else -1
    if m and mom_at > 0:
        subj = re.sub(r"\s+(?:as|be|for)?\s*(?:the|our|their|a)?\s*$", "", m.group(1)[:mom_at]).strip()
        i, conf, close = find_song(subj, order)
        if i is None or conf < 0.5:
            return Reply("Which song? Say it like: make Amazed the first dance.")
        if close and conf < 0.95:
            return unsure(close, i)
        mom = _moment_in(m.group(1)[mom_at:])
        for s in order:
            if s.moment == mom:
                s.moment = ""
        s = order.pop(i)
        s.moment, s.part, s.pinned = mom, "dancing", True
        if mom == "last-dance":   # just before the final song of the dancing, which sends everyone off
            dancing = [j for j, x in enumerate(order) if _part_of(x, event) == "dancing"]
            order.insert(dancing[-1] if dancing else len(order), s)
        else:
            order.append(s)
        new = evaluate(order, event)
        k = next(j for j, p in enumerate(new) if p.song is s)
        return Reply(f"{name(s)} is the {MOMENT_NAMES[mom].lower()} now. {s.reason}.", [p.song for p in new], True, focus=k)

    m = re.match(r"^(?:swap|switch|trade)\s+(.+?)\s+(?:and|with|for)\s+(.+)$", low)
    if m:
        a, ca, cla = find_song(m.group(1), order)
        b, cb, clb = find_song(m.group(2), order)
        if a is None or b is None or ca < 0.5 or cb < 0.5:
            return Reply("Which two songs? Say it like: swap Wagon Wheel and My Maria.")
        if a == b:
            return Reply("That's the same song twice.")
        sa, sb = order[a], order[b]
        sa.part, sb.part = sb.part, sa.part
        order[a], order[b] = sb, sa
        sa.pinned = sb.pinned = True
        return _after_move(order, event, sa, f"Swapped {sa.title} and {sb.title}.", placed)

    m = re.match(r"^(?:move|put|play|bring|drop|slide|place|have)\s+(.+)$", low)
    if m:
        i, conf, op, tail, close = _split_subject(m.group(1), order)
        if i is None or conf < 0.5:
            return Reply("Which song, and where to? Say it like: move Wagon Wheel after Boot Scootin' Boogie.")
        if close and conf < 0.95:
            return unsure(close, i)
        s = order.pop(i)
        tail = tail.strip(" ?.!")
        by = re.search(r"\b(?:by\s+)?(\d{1,2}|one|two|three|four|five)\s*(?:spots?|songs?|places?)?\b", tail)
        nums = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
        steps = (int(by.group(1)) if by.group(1).isdigit() else nums[by.group(1)]) if by else 1
        target_part = _part_in(tail)
        if op in ("up", "earlier") or (op == "down" or op == "later"):
            j = max(0, min(len(order), i - steps if op in ("up", "earlier") else i + steps))
            if order and 0 < j <= len(order):
                s.part = order[j - 1].part if op in ("down", "later") or j == len(order) else order[j].part
            order.insert(j, s)
        elif op in ("first", "last") or re.fullmatch(r"(the )?(very )?(start|top|beginning|end|bottom)( of .*)?", tail or ""):
            part = target_part or s.part or "dancing"
            idx = [k for k, x in enumerate(order) if x.part == part]
            at_start = op == "first" or re.match(r"(the )?(very )?(start|top|beginning)", tail or "")
            j = (idx[0] if idx else len(order)) if at_start else (idx[-1] + 1 if idx else len(order))
            s.part = part
            order.insert(j, s)
        elif op in ("to", "into", "in") and re.fullmatch(r"(?:song|number|spot|position|#)?\s*(\d{1,2})", tail or ""):
            j = max(1, min(len(order) + 1, int(re.search(r"\d+", tail).group(0)))) - 1
            ref = order[j] if j < len(order) else order[-1]
            s.part = ref.part
            order.insert(j, s)
        elif op in ("to", "into", "in") and target_part and find_song(tail, order)[1] < 0.95:
            s.part = target_part
            j = _best_spot(order, s, target_part, event)
            order.insert(j, s)
        else:
            j, cj, clj = find_song(tail, order)
            if j is None or cj < 0.5:
                order.insert(i, s)
                return Reply(f"Move {s.title} where? Say after or before another song, earlier or later, "
                             "or into cocktail hour, dinner or dancing.")
            ref = order[j]
            s.part = ref.part
            after = op in ("after", "right after", "just after", "to", "into", "in", "next to", "down", "later")
            order.insert(j + 1 if after else j, s)
        s.pinned = True
        return _after_move(order, event, s, None, placed)

    return Reply("I can explain or move songs. Try: why is Wagon Wheel here? / move Shout after September / "
                 "swap Amazed and I Swear / put Fireflies in dinner / make Amazed the first dance / arrange again.")


def _part_shape(part: str, ps: list[Placed], event: str) -> str:
    if part == "cocktail":
        return "It stays warm and social, a gentle sway around the middle of the energy range, nothing too slow to open it."
    if part == "dinner":
        return "It starts easy, settles low under conversation, then lifts at the end so the dancing doesn't start cold."
    roles = [p.slot.role for p in ps]
    bits = []
    if "moment" in roles[:1]:
        bits.append("the couple's dances first")
    if "opener" in roles:
        bits.append("a hype opener everyone knows" if event == "wedding" else "a mid-energy opener")
    waves = len({p.slot.wave for p in ps if p.slot.role in ("rise", "peak", "breather")})
    if waves:
        bits.append(f"{waves} waves that climb, peak and take a breather")
    if "slow" in roles:
        bits.append(f"a slow-dance window of {roles.count('slow')}")
    last = any(p.slot.moment == "last-dance" for p in ps)
    if "close" in roles:
        bits.append("a sing-along close" + (" with the last dance just before the final song" if last else ""))
    elif last:
        bits.append("the last dance")
    return "In order: " + ", then ".join(bits) + "." if bits else ""


def _after_move(order: list, event: str, s, lead: Optional[str], before: list[Placed]) -> Reply:
    new = evaluate(order, event)
    k = next(j for j, p in enumerate(new) if p.song is s)
    old, now = score(before), score(new)
    lead = lead or f"Moved {s.title} to {_pos_words(new, k)}."
    p = new[k]
    prev = new[k - 1] if k and new[k - 1].slot.part == p.slot.part else None
    nxt = new[k + 1] if k + 1 < len(new) and new[k + 1].slot.part == p.slot.part else None
    bits = [lead]
    if prev or nxt:
        bits.append("It sits " + " and ".join(
            x for x in [f"after {prev.song.title} ({_step_words(prev.facts, p.facts) or 'no tempo or key on file'})" if prev else "",
                        f"before {nxt.song.title}" if nxt else ""] if x) + ".")
    gap = p.facts.energy - p.slot.target
    if p.slot.role not in ("moment",) and abs(gap) > 0.15:
        bits.append(f"Its energy is {'above' if gap > 0 else 'below'} what that spot usually wants "
                    f"({p.facts.energy * 10:.0f} vs about {p.slot.target * 10:.0f}).")
    if now > old + 0.5:
        bits.append("The flow scores a little rougher than before; the curve shows where.")
    elif now < old - 0.5:
        bits.append("The flow scores smoother than before.")
    warn = [w for w in warnings(new) if s.title in w]
    if warn:
        bits.append("Heads up: " + "; ".join(warn) + ".")
    bits.append("It stays here when you arrange again.")
    return Reply(" ".join(bits), [x.song for x in new], True, focus=k)


def suggestions(placed: list[Placed], event: str = "wedding") -> list[dict]:
    """Things worth his call, each with the plain words that do it: a song that suits an empty
    wedding moment, a slow-dance window with no slow songs, songs the arranger had to judge by tempo."""
    out: list[dict] = []
    if event == "wedding":
        taken = {p.song.moment for p in placed if p.song.moment}
        for mom in MOMENTS:
            if mom in taken or mom not in MOMENT_NAMES:
                continue
            fits = [p for p in placed if mom in p.facts.tags and not p.song.moment]
            fits.sort(key=lambda p: (-p.facts.known, -p.facts.sing, p.song.title))
            for p in fits[:2]:
                out.append({"text": f"{p.song.title} suits the {MOMENT_NAMES[mom].lower()}.",
                            "say": f"make {p.song.title} the {MOMENT_NAMES[mom].lower()}"})
        dancing = [p for p in placed if p.slot.part == "dancing" and p.slot.role != "moment"]
        if len(dancing) >= 8 and not any(p.facts.slow for p in dancing):
            slow = sorted([p for p in placed if p.facts.slow and p.slot.part != "dancing" and not p.song.moment],
                          key=lambda p: (-p.facts.known, p.song.title))
            if slow:
                out.append({"text": f"Dancing has no slow songs, so there is no slow-dance window. "
                                    f"{slow[0].song.title} would open one.",
                            "say": f"put {slow[0].song.title} in dancing"})
    unknown = [p.song.title for p in placed if not p.facts.in_canon]
    if unknown:
        out.append({"text": f"{len(unknown)} song{'s' if len(unknown) != 1 else ''} the arranger doesn't know by "
                            f"reputation ({', '.join(unknown[:3])}{'...' if len(unknown) > 3 else ''}): their energy "
                            "comes from tempo alone, so check where they landed.", "say": ""})
    return out


def public(placed: list[Placed], event: str = "wedding") -> dict:
    """What the window draws: the songs in order with reason and energy, the curves, the checks."""
    for p in placed:
        p.song.energy = round(p.facts.energy, 3)
        p.song.camelot = p.facts.key or p.song.camelot
        p.song.year = p.facts.year or p.song.year
    return {"songs": [p.song.public() for p in placed], "curves": curves(placed), "warnings": warnings(placed),
            "suggestions": suggestions(placed, event), "score": score(placed), "event": event,
            "roles": [p.slot.role for p in placed]}
