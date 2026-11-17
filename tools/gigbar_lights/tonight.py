"""Tonight: the night in order, with Now and Next (1.20.0, the Light studio, Llano PM #23195).

A pro desk runs anything that happens in order from a cue list with one Go button. This is that
list for a wedding night. The rule, 2026-11-12: the lights change by themselves with Mixxx, and
Next is the DJ's override.

The steps come from the night he built on the Shows page (wedding_night.build writes night.json:
music, holds and moment songs, each with the look the lights play). The lights already change by
themselves: every hold and moment song is filed under its look (wedding_night.looks_ops), so when
Mixxx reaches it the show plays that look. This list adds what was missing: WHERE the night is.

  Now    the step whose song or hold Mixxx is playing (seen by the show, `see`)
  Next   the step after it. Pressing Next before Mixxx gets there holds that step's look in the
         studio (a held look, like any pad) until Mixxx arrives, then lets go: the show is playing
         the same look by then, so nothing changes on the lights at the handover.

Before the night is built, or when the show changed after it was built, the list is the show's own
night (Llano BL #12387): its songs placed exactly as the build would place them (wedding_night.arrange),
so the order he set and every song he added show at once, and the night still follows Mixxx by song.
The build is still what puts the night into Mixxx; the note under the list says so.

With no show arranged into a night either, it is a plain wedding order he steps through by hand;
nothing follows Mixxx.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from . import moments, run_of_show as ros, show_settings, song_match
from . import settings_contract as contract
from . import wedding_night

MAX_STEPS = 60
# moments that count as Dancing: the heads keep running. The last dance and closing song (slow), and
# his grand exit (BL #12360): the sing-along before it and the couple's exit song.
DANCING_MOMENTS = ("last-dance", "close", "exit-prep", "exit")
GENTLE_MOMENTS = ("first-dance", "father-daughter", "mother-son")   # the heads move by themselves, gently


def _keys(artist: str, title: str) -> set:
    try:
        return set(song_match.candidates(artist, title))
    except Exception:  # noqa: BLE001 -- ok: a name that can't be keyed never matches
        return set()


def _pad(look: str) -> str:
    """The studio pad for a step's look ("" = the lights follow the music)."""
    return f"moment:{look}" if look in moments.KEYS else ""


def _tell_presses(steps: list, plan: list) -> None:
    """Each step's words for the screens, the same the run sheet prints (run_of_show.sheet_rows):
    `wait` what Mixxx is doing there (a hold: it waits for Fade Now), `press` what to press when the
    step is over, or that nothing is needed. Playlist starts are worked out again from the kinds of
    the steps, so a night.json written before they were saved still says the right playlist."""
    if not plan:
        return
    ros.mark_opens(plan)
    for st, row in zip(steps, ros.sheet_rows(plan)):
        st["press"] = row["next"]
        st["wait"] = ros.HOLD_DETAIL if st["kind"] == "hold" else ""


class Tonight:
    def __init__(self, steps: list, title: str = "", built: str = "", folder: str = "", moods=None,
                 path: Optional[Path] = None):
        self.title, self.built, self.folder = title, built, folder
        self.moods = contract.moods(moods)   # cocktail hour and dinner (BL #12340); Llano's suggestion by default
        self.path = path                     # its night.json: a mood changed on the Live screen is kept there
        self.source = "built" if built else "plain"   # "built" (night.json), "show" (from_show) or "plain"
        self.show = ""                       # the saved show's name, when the list comes from a show
        self.note = ""                       # what the screens say under the list ("" = their own words)
        self.steps = steps[:MAX_STEPS]     # {"name", "kind", "pad", "keys": set, "say"}
        self.at = -1                       # the step Mixxx is on (-1 = not seen yet)
        self.ahead: Optional[int] = None   # the step he went to with Next, until Mixxx gets there
        self._spared: Optional[frozenset] = None
        self._dancing_k: Optional[frozenset] = None

    # --- where the steps come from -------------------------------------------------------------

    @classmethod
    def from_report(cls, report: dict) -> "Tonight":
        steps, plan = [], []
        for s in report.get("steps") or []:
            if not isinstance(s, dict):
                continue
            kind, name = str(s.get("kind") or ""), str(s.get("name") or "")[:80]
            if kind not in ("music", "hold", "song") or not name:
                continue
            keys: set = set()
            if kind == "hold":
                keys |= _keys(wedding_night.HOLD_ARTIST, ros.hold_title(name))
            for song in s.get("songs") or []:
                if isinstance(song, dict):
                    keys |= _keys(str(song.get("artist") or ""), str(song.get("title") or ""))
            steps.append({"name": name, "kind": kind, "pad": _pad(str(s.get("look") or "")), "keys": keys,
                          "say": str(s.get("say") or "")[:200],
                          "part": str(s.get("key") or "") if kind == "music" else "",
                          "moment": str(s.get("key") or "") if kind != "music" else ""})
            plan.append(ros.Step(kind, str(s.get("key") or ""), name,
                                 songs=[x for x in s.get("songs") or [] if isinstance(x, dict)][:400]))
        _tell_presses(steps, plan)
        return cls(steps, title=str(report.get("title") or "")[:80], built=str(report.get("built") or ""),
                   folder=str(report.get("folder") or ""), moods=report.get("moods"))

    @classmethod
    def plain(cls) -> "Tonight":
        """No night built yet: the usual wedding order, stepped by hand."""
        steps, plan = [], []
        for key in ros.DEFAULT_ORDER:
            if key in ros.PART_NAMES:
                steps.append({"name": ros.PART_NAMES[key], "kind": "music", "pad": "", "keys": set(), "say": ""})
                plan.append(ros.Step("music", key, ros.PART_NAMES[key]))
            elif key in ros.MOMENTS and key not in ros.OPTIONAL:
                name, look, say, _song, _hold = ros.MOMENTS[key]
                steps.append({"name": name, "kind": "hold", "pad": _pad(look), "keys": set(), "say": say,
                              "moment": key})
                plan.append(ros.Step("hold", key, name))
        _tell_presses(steps, plan)
        return cls(steps)

    @classmethod
    def from_show(cls, name: str, show: dict) -> "Tonight":
        """The night a saved show arranges, before it is built: the same steps the build would make
        (wedding_night.arrange, then run_of_show.plan with the build's own defaults), with no files."""
        songs = [x for x in show.get("songs") or [] if isinstance(x, dict)]
        arranged = wedding_night.arrange(songs, skip=set(ros.OPTIONAL) | {"close"})   # as _night_plan asks
        steps = ros.plan(arranged["parts"], arranged["moment_songs"], skip=arranged["off"])
        night = cls.from_report({"title": show.get("title") or name, "built": "", "moods": show.get("moods"),
                                 "steps": [st.public() for st in steps]})
        night.source, night.show = "show", name
        return night

    @staticmethod
    def pick_show(doc: Optional[dict], prefer: str = "", title: str = "") -> str:
        """The saved show tonight is: one whose songs have parts of the night. The show the Live show
        follows first, then the one the last built night was named for, then the only one; with
        several and no hint, the first by title. "" when no show is arranged into a night."""
        found = {n: sh for n, sh in ((doc or {}).get("shows") or {}).items()
                 if isinstance(sh, dict) and any(isinstance(x, dict) and x.get("part") for x in sh.get("songs") or [])}
        if not found:
            return ""
        if prefer in found:
            return prefer
        named = [n for n, sh in found.items() if title and str(sh.get("title") or n).strip().casefold() == title.strip().casefold()]
        if named:
            return named[0]
        return sorted(found, key=lambda n: (str(found[n].get("title") or n).casefold(), n))[0]

    @staticmethod
    def covers(report: dict, show: dict) -> bool:
        """The built night (night.json) still plays every song of the show where the show puts it:
        nothing added since, no song moved to another part. A song the build could not use (no file,
        damaged, silent), or one with no part and no moment, never counts against it."""
        placed: dict = {}
        for st in report.get("steps") or []:
            if not isinstance(st, dict):
                continue
            where = str(st.get("key") or "") if st.get("kind") == "music" else "moment"
            for song in st.get("songs") or []:
                if isinstance(song, dict):
                    placed.setdefault(wedding_night.key_of(song), set()).add(where)
        unusable = {str(x) for x in report.get("missing") or []} | {str(x) for x in report.get("silent") or []} | \
            {str(d.get("song")) for d in report.get("damaged") or [] if isinstance(d, dict)}
        for song in show.get("songs") or []:
            if not isinstance(song, dict):
                continue
            mk, part = str(song.get("moment") or ""), str(song.get("part") or "")
            if mk == "?" or (not mk and not part) or wedding_night._label(song) in unusable:
                continue
            where = placed.get(wedding_night.key_of(song))
            if not where:
                return False
            if mk in ros.BEDS and mk not in where:
                return False
            if not mk and part not in where and "moment" not in where:
                return False
        return True

    @classmethod
    def load(cls, root: Optional[Path] = None, doc: Optional[dict] = None, prefer: str = "") -> "Tonight":
        """Tonight's night: the newest one built on this laptop while it still has every song of its
        show where the show puts it; else the show's own night (from_show); else the plain order.

        doc     the settings document (its saved shows); None reads only built nights, as before
        prefer  the show the Live show follows (Shows page)
        """
        built, report = None, None
        for f in cls.built_files(root)[:1]:
            try:
                report = json.loads(f.read_text(encoding="utf-8"))
                night = cls.from_report(report)
                night.path = f
                if night.steps:
                    built = night
            except (OSError, ValueError):   # ok: an unreadable night.json = no night built
                pass
        name = cls.pick_show(doc, prefer, built.title if built else "") if doc is not None else ""
        show = ((doc or {}).get("shows") or {}).get(name) if name else None
        if built is not None and (show is None or cls.covers(report, show)):
            return built
        if show is not None:
            try:
                night = cls.from_show(name, show)
            except Exception as e:  # noqa: BLE001 -- ok: a show that can't be listed never costs the built night
                print(f"Tonight: the show '{name}' could not be listed: {type(e).__name__}: {e}")
                night = None
            if night is not None and night.steps:
                title = night.title or name
                night.note = (f"{title} changed after the night was built, so this is the show's order now. "
                              "Build the night again on the Shows page to put the changes in Mixxx."
                              if built is not None else
                              f"This is {title}'s order. Build the night on the Shows page to put it in Mixxx; "
                              "the lights change by themselves as Mixxx plays its songs.")
                return night
        if built is not None:
            return built
        return cls.plain()

    @staticmethod
    def built_files(root: Optional[Path] = None) -> list:
        """The nights built on this laptop (their night.json), newest first."""
        root = Path(root) if root else Path.home() / "Music" / wedding_night.OUT_PARENT
        try:
            found = [(f.stat().st_mtime, f) for f in root.glob("*/night.json")]
        except OSError:
            return []
        return [f for _m, f in sorted(found, key=lambda x: x[0], reverse=True)]

    @classmethod
    def signature(cls, root: Optional[Path] = None, doc: Optional[dict] = None, prefer: str = "") -> tuple:
        """What tonight's list is made from, cheap to read: when it changes, load() again."""
        files = cls.built_files(root)
        try:
            newest = (str(files[0]), files[0].stat().st_mtime) if files else None
        except OSError:
            newest = None
        return newest, prefer, json.dumps((doc or {}).get("shows") or {}, sort_keys=True, default=str)

    def same_steps(self, other: "Tonight") -> bool:
        return [(s["name"], s["kind"]) for s in self.steps] == [(s["name"], s["kind"]) for s in other.steps]

    def soft_keys(self) -> set:
        """Every key the night's cocktail-hour and dinner songs could play under: those songs get a
        soft wash and nothing else on the night (show_settings.set_soft_songs). A song that is also
        a moment's song, or plays in the dancing too, keeps the fuller look."""
        soft, kept = set(), set()
        for s in self.steps:
            (soft if s.get("part") in ("cocktail", "dinner") else kept).update(s["keys"])
        return soft - kept

    def soft_parts(self) -> dict:
        """{track key: "cocktail" | "dinner"} for the night's soft songs: each plays its part's mood."""
        out: dict = {}
        for s in self.steps:
            if s["kind"] == "music" and s.get("part") in ("cocktail", "dinner"):
                for k in s["keys"]:
                    out.setdefault(k, s["part"])
        return out

    def soft_part_now(self) -> str:
        """"cocktail" or "dinner" while the night stands on one of them, else ""."""
        return self.steps[self.current()].get("part", "") if self.soft_now() else ""

    def tell_lights(self) -> None:
        """The lights know this night: its soft and still songs, which part each soft song is, and
        its moods (show_settings). Said once when the night loads or is built."""
        show_settings.set_soft_songs("night", self.soft_keys())
        show_settings.set_still_songs("night", self.still_keys())
        show_settings.set_gentle_songs("night", self.gentle_keys())
        show_settings.set_soft_parts("night", self.soft_parts())
        show_settings.set_moods("night", self.moods)

    def set_mood(self, part: str, mood) -> dict:
        """He changed a part's mood on the Live screen: it plays now and is kept in the night's file."""
        from .studio import CommandError
        if part not in contract.MOOD_PARTS:
            raise CommandError("pick cocktail hour or dinner")
        self.moods = {**self.moods, part: contract.part_mood(mood, part)}
        show_settings.set_moods("night", self.moods)
        if self.path is not None:
            try:
                doc = json.loads(self.path.read_text(encoding="utf-8"))
                doc["moods"] = self.moods
                tmp = self.path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
                tmp.replace(self.path)
            except (OSError, ValueError) as e:   # ok: it plays now; only keeping it for next time failed
                print(f"Night mood not kept in {self.path.name}: {type(e).__name__}: {e}")
        return self.moods[part]

    def soft_now(self) -> bool:
        """The night stands on a Cocktail hour or Dinner music step (Mixxx got there, or he pressed
        Next to it): every song then gets the soft wash, a request nobody listed included. A listed
        moment song moves the night to its own step (`see`), so it keeps its look. The plain order
        (no night built) names no parts and never holds anything."""
        i = self.current()
        if not 0 <= i < len(self.steps):
            return False
        step = self.steps[i]
        return step["kind"] == "music" and step.get("part") in ("cocktail", "dinner")

    def spared_keys(self) -> frozenset:
        """Every key the night lists in a step that is not cocktail hour or dinner music: a moment's
        song (even one filed in dinner's folder), a hold, the dancing. While the night stands on
        cocktail hour or dinner these keep their own look; every other song is held soft."""
        if self._spared is None:
            self._spared = frozenset(k for s in self.steps
                                     if not (s["kind"] == "music" and s.get("part") in ("cocktail", "dinner"))
                                     for k in s["keys"])
        return self._spared

    # --- moving heads by themselves only in the dances (Llano BL #12339) ----------------------------

    @staticmethod
    def _dancing(step: dict) -> bool:
        """Dancing music, or the last dance and the closing song (they count as Dancing, slow)."""
        if step["kind"] == "music":
            return step.get("part") == "dancing"
        return step.get("moment") in DANCING_MOMENTS

    @staticmethod
    def _gentle(step: dict) -> bool:
        """The first dance or a parent dance: the heads move by themselves, slowly, on the floor."""
        return step["kind"] in ("hold", "song") and step.get("moment") in GENTLE_MOMENTS

    @staticmethod
    def _still(step: dict) -> bool:
        """A hold or a moment's song that is not a dance, or the quiet music under the toasts and the
        cake (BL #12360): the heads stay dark and still."""
        if step["kind"] == "music":
            return step.get("part") in ros.BEDS
        return (step["kind"] in ("hold", "song") and step.get("moment") not in DANCING_MOMENTS
                and step.get("moment") not in GENTLE_MOMENTS)

    def _keys_where(self, pick) -> set:
        """Every key of the steps `pick` takes, less any that also plays in Dancing (it keeps Dancing's heads)."""
        out, kept = set(), set()
        for s in self.steps:
            (out if pick(s) else kept if self._dancing(s) else set()).update(s["keys"])
        return out - kept

    def still_keys(self) -> set:
        """Every key the night's holds and moment songs that are not dances could play under: those
        get no moving heads (show_settings.set_still_songs)."""
        return self._keys_where(self._still)

    def gentle_keys(self) -> set:
        """Every key the night's first dance and parent dances could play under: the heads move
        gently (show_settings.set_gentle_songs)."""
        return self._keys_where(self._gentle)

    def _stands(self, pick) -> bool:
        # Like soft_now, the plain order (no night built) never holds anything: a forgotten Next must
        # not keep the heads dark or slow.
        i = self.current()
        if not self.follows or not 0 <= i < len(self.steps):
            return False
        return pick(self.steps[i])

    def still_now(self) -> bool:
        """The night stands on a hold or a moment's song that is not a dance."""
        return self._stands(self._still)

    def gentle_now(self) -> bool:
        """The night stands on the first dance or a parent dance."""
        return self._stands(self._gentle)

    def dancing_keys(self) -> frozenset:
        """Every key the night plays in Dancing: those keep their heads while the night stands still."""
        if self._dancing_k is None:
            self._dancing_k = frozenset(k for s in self.steps if self._dancing(s) for k in s["keys"])
        return self._dancing_k

    @property
    def follows(self) -> bool:
        """It follows Mixxx: a built night, whose steps name their songs and holds."""
        return any(s["keys"] for s in self.steps)

    # --- Mixxx moves the night along --------------------------------------------------------------

    def see(self, studio, keys, now: float) -> None:
        """The show saw this song (its track keys). Moves Now, and hands back a step Next ran ahead to."""
        want = set(keys or ())
        if not want or not self.follows:
            return
        hits = [i for i, s in enumerate(self.steps) if s["keys"] & want]
        if not hits:
            return
        here = next((i for i in hits if i >= max(self.at, 0)), hits[0])   # forward through the night
        self.at = here
        if self.ahead is not None and here >= self.ahead:
            self._let_go(studio)

    def _let_go(self, studio) -> None:
        self.ahead = None
        if studio.look and studio.look.get("night"):
            studio.look = None

    # --- his override -------------------------------------------------------------------------------

    def current(self) -> int:
        return self.ahead if self.ahead is not None else self.at

    def next(self, studio, now: float) -> None:
        self.goto(studio, self.current() + 1, now)

    def goto(self, studio, i: int, now: float) -> None:
        from .studio import CommandError
        if not 0 <= i < len(self.steps):
            raise CommandError("that was the last step of the night" if i >= len(self.steps) else "pick a step of the night")
        studio._remember()
        step = self.steps[i]
        if self.follows and i == self.at:      # back to where Mixxx is
            self._let_go(studio)
            return
        self.ahead = i
        if not self.follows:
            self.at = i
            self.ahead = None
        # a moment holds its look; music lets the lights follow the music again
        studio.look = {"key": step["pad"], "since": now, "night": True} if step["pad"] else None
        studio.blackout = False
        studio.frozen, studio._frozen = False, None

    def follow(self, studio) -> None:
        self._let_go(studio)

    # --- what the screens show -----------------------------------------------------------------------

    def public(self) -> dict:
        cur = self.current()
        out = []
        for i, s in enumerate(self.steps):
            state = "done" if i < cur else "now" if i == cur else "next" if i == cur + 1 else "later"
            look = ""
            if s["pad"]:
                look = next(m["name"] for m in moments.MOMENTS if m["key"] == s["pad"][7:])
            out.append({"name": s["name"], "kind": s["kind"], "state": state, "look": look,
                        "held": s["kind"] != "music", "say": s["say"], "wait": s.get("wait", ""),
                        "press": s.get("press", "")})
        nxt = self.steps[cur + 1] if 0 <= cur + 1 < len(self.steps) else None
        return {"title": self.title, "built": self.built, "follows": self.follows, "at": self.at,
                "source": self.source, "show": self.show, "note": self.note,
                "moods": self.moods, "mood_part": self.soft_part_now(),
                "ahead": self.ahead, "steps": out,
                # what to press to move on from where the night stands ("" before Mixxx is seen)
                "press": self.steps[cur].get("press", "") if 0 <= cur < len(self.steps) else "",
                "next": {"name": nxt["name"], "held": nxt["kind"] != "music"} if nxt else None}
