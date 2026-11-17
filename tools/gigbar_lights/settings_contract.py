"""Llano Lights show settings: the one contract the laptop app and Llano share.

THIS FILE IS COPIED BYTE FOR BYTE between two repos:
  aios          scripts/lights/settings_contract.py
  llano-lights  tools/gigbar_lights/settings_contract.py
Both test suites pin its sha256 (CONTRACT_SHA256 in each test), so an edit on one
side that is not copied to the other fails CI. Stdlib only; no imports from either repo.

The settings are SETTINGS, never code: palettes, which palette each song section uses,
how hard drops and strobes hit, which autoloop looks run, overall brightness, and the
saved room layouts plus which one is in use. Schema 2 adds the show itself, section by
section (how bright the washes and movers run, how hard they pulse, derby and laser, how
often colors change, and how the movers move between NAMED positions, so a venue layout
re-aims them and a style never fights the Show Designer), plus named styles (a whole
look saved under a name) and which style each song plays. Defaults are exactly the
constants and hard-coded moves the looks engine ships with (looks.py 1.3.1), so a
laptop that never links to Llano, or an empty document, plays the same show it always did.
Shows (2026-11-08) are named, saved song line-ups: a party's playlist in order, each song
with the look it plays ("Megan's birthday party"). A show song's look is a saved style or
one of the BUILTIN_LOOKS below, so a show designed on a laptop that never saved a style
still has a different feel per song.

The rig (2026-11-08) is the hardware half: each light's DMX start address, each fixture type's
channel order by NAME (CHANNEL_NAMES), which GigBAR head is which, each head's pan/tilt invert
and swap, and the calibration defaults (pan and tilt range, the tilt that points straight
down). It syncs like every other setting, so a mapping fix made on llano.app reaches the
laptop in seconds with no app update. Defaults are exactly rig.py 1.12.3, so an empty rig
renders the same bytes it always did. Head 1 is channels 24-29, the bar's own left as it faces
out (his right from the dance floor); a saved calibration is keyed by that channel group, so
`swap_heads` stays off unless the heads really are cabled the other way round. `numbering`
(Llano BL #12396) says which end Tetra 1 and stick 1 start at ("left" or "right", seen the way the
room picture draws it): his Tetra cords run from the right, so every room the laptop draws numbers
them from there.

A change is a list of ops: {"path": "strobe.intensity", "value": 0.6}. Paths are dotted
and at most three deep; `value: null` on layouts.saved.<name>, palettes.<name>,
styles.<name> or songs.<track key> deletes that entry.
apply_ops() applies them in order, then normalize() clamps every number, drops unknown
keys and repairs dangling palette names, so whatever any side writes, both sides end up
holding the same document. Each applied op records the value it replaced (`before`),
which is what undo replays.
"""
from __future__ import annotations

import copy
import math
import re

SCHEMA = 2
SYNC_MAX_MS = 3000   # rig.sync_ms: a Bluetooth speaker runs about 0.1 to 1 s behind; nothing real is 3 s
SECTIONS = ("intro", "verse", "build", "drop", "main", "breakdown", "outro")
# How the movers travel between two named positions (the engine's looks.py does the math):
# hold sits at `from`; glide eases from -> to over `beats`, then back; snap jumps between
# them every `beats`; sweep swings smoothly, mix 0.5 + 0.5*sin(beat*pi/beats); rise goes
# from -> to across the section; circle, eight and line trace a figure around `from`,
# `size` big, one loop per `beats`.
SHAPES = ("hold", "glide", "snap", "sweep", "circle", "eight", "line", "rise")
POSITIONS = ("home", "booth", "crowd", "fan", "ceiling", "cross")
# spotlight (1.16.0): every head on ONE spot that travels the floor along the move, so they read as
# one roaming spotlight; spotlights: one spot per GigBAR, the second mirrored across the floor. Both
# need the venue's aim (Line up my lights); without a layout they play as parallel.
SPREADS = ("parallel", "mirror", "serial", "spotlight", "spotlights")
MAX_STYLES = 12
MAX_SONGS = 100   # deleting a style nulls its songs in one change: stays under MAX_OPS
STYLE_KEYS = ("palettes", "section_palette", "saturation", "sections", "drop", "strobe")
AUTOLOOPS = ("color pulse", "chase", "sweep", "rainbow")
AUTOLOOP_BARS = (4, 8, 16, 32)
# Scene pads (PM #22309): a scene takes over the show mid-song until "back to the show". It is a
# live command, not a setting (never saved, never in a style); the list lives here so Llano and the
# laptop agree on the names.
SCENES = ("calm", "party", "hype", "party-mode", "whiteout", "blackout")
# Crowd-safe strobe (PM #22309): with crowd_safe on, every strobe channel stays at the slow end of
# its range, about 3 flashes a second on GigBAR-class fixtures (estimated, not measured on his rig).
# It is a top-level guard, not part of a style, so no draft, mood or saved style can switch it off.
SAFE_STROBE_MAX = 0.1
# Full power (Llano PM #23796, the 11-16 question: with every brightness setting at max, does each light get 255?):
# master and the faders only turn a look down, and the looks write their verses and builds below full (a verse's
# heads at 60%, its Tetras peaking at 90%) and some drops at 80%. With full_power on, a dancing section whose wash
# and heads are both at full peaks at DMX 255 on every light, and a look's drop intensity is read as full. The soft
# parts of the night (cocktail hour, dinner, the first and parent dances), the held moments and a section set below
# full stay as they are. Top-level like crowd_safe, never part of a style; off by default.
MAX_PALETTES = 12
MAX_PAIRS = 8
MAX_SAVED_LAYOUTS = 24
MAX_LAYOUT_BYTES = 16 * 1024
MAX_OPS = 128   # a whole style made live is one change (one undo)
MAX_SHOWS = 16
# A whole wedding reception fits one show (BL #12087): cocktail hour, dinner and 2 h 15 of dancing
# run about 90 songs, so 120 leaves room for a long night.
MAX_SHOW_SONGS = 120
# A show as stored (ASCII-escaped JSON, the way both sides measure it). Measured 2026-11-12: a
# 90-song night is about 20 KB, and about 48 KB when every song carries a long why and reason and
# the show holds all 6 of its own looks; 120 everyday songs plus 6 looks are about 43 KB. 16 shows
# at this cap plus 24 layouts at theirs stay under Llano's document limit (store.MAX_DOC_BYTES).
MAX_SHOW_BYTES = 48 * 1024
# The set arranger (Llano PM #23177): a show song may say which part of the night it plays in and
# which wedding moment it is, and carries one line on why it sits where it does. Optional: an empty
# value (every show saved before 1.18.0) reads as "no part, no moment".
SHOW_PARTS = ("cocktail", "dinner", "dancing")
# exit-prep, exit (Llano BL #12360, his reception order for 2026-11-25): the one big sing-along before
# the grand exit and the couple's exit song; background: a song he picked to play quietly under the
# toasts and the cake cutting. "mother-son" is shown as the Mother-groom dance. toasts-background: the
# instrumentals that play quietly under the toasts and speeches, in their folder's order (his
# "Wedding Instrumentals" folder, 2026-11-14); background then plays under the cake alone.
SHOW_MOMENTS = ("first-dance", "father-daughter", "mother-son", "last-dance", "exit-prep", "exit", "background",
                "toasts-background")
# A Dancing song's energy (Llano BL #12341): its tag picks its look (hype: peak, dance: groove, slow:
# slow dance), and tag_mine says he chose it himself so designing again keeps it. Optional, like part.
SONG_TAGS = ("hype", "dance", "slow")
# A show's own looks, designed for that night by Llano: each keeps only the settings it names and
# plays over the house show, the way BUILTIN_LOOKS do.
MAX_SHOW_LOOKS = 6

# The cue timeline (Llano PM #23787, the 2026-11-15 ask: push cues forward and back, pause and see them,
# dead simple). A song's own cues, by track key, in seconds into the ORIGINAL recording (a night's cut
# plays them at the same musical spot: set_cuts writes where the original's 0:00 sits). A cue is one of
#   {"at": s, "do": "hit", "size": 1|2}: a white hit on that instant (2 = the biggest, with a strobe burst);
#   {"at": s, "do": "section", "kind": SECTIONS}: a section starts here; any section cue means his list
#       replaces the analysis for that song;
#   {"at": s, "do": "feel", "feel": CUE_FEELS, "color": "#rrggbb" | ""}: the stretch (section) holding
#       `at` plays bigger or softer and/or in that color; the last one in a stretch wins.
# Kept per song, not per show, so a cue follows the recording into every show and into plain Mixxx
# play, and a nudge reaches the lights on the next frame (the engine reads the settings in force).
MAX_CUE_SONGS = 120
MAX_CUES = 48
MAX_CUES_BYTES = 24 * 1024   # all songs' cues as stored; 120 songs of 6 cues is about 16 KB
CUE_DOS = ("hit", "section", "feel")
CUE_FEELS = ("bigger", "softer", "")
CUE_COLOR_RE = re.compile(r"#[0-9a-f]{6}")

# The rig (2026-11-08). Fixture ids in render order (venue.FIXTURE_IDS), the kind each one is,
# and each kind's channels by name in the order rig.py 1.12.3 sends them. A channel list in the
# rig block may reorder, drop or repeat these names, or hold "=N" (a fixed byte, 0..255).
FIXTURES = {"bar1": "gigbar", "bar2": "gigbar", **{f"tetra{i}": "tetra" for i in range(1, 7)},
            **{f"stick{i}": "stick" for i in range(1, 5)}}
_HEAD = ("pan", "tilt", "dim", "strobe", "color", "gobo")
CHANNEL_NAMES = {
    "gigbar": tuple(f"par{p}.{c}" for p in (1, 2) for c in ("red", "green", "blue", "uv", "shutter"))
    + tuple(f"derby{d}.{c}" for d in (1, 2) for c in ("color", "strobe", "rotate"))
    + ("laser.color", "laser.strobe", "laser.rotate",
       "strobe.program", "strobe.white", "strobe.uv", "strobe.speed")
    + tuple(f"head{h}.{c}" for h in (1, 2) for c in _HEAD),
    "tetra": ("red", "green", "blue", "amber", "dim", "strobe"),
    "stick": ("dim", "red", "green", "blue", "macro", "strobe", "program", "speed"),
}
MAX_FOOTPRINT = 64
HEAD_FLAGS = ("pan_invert", "tilt_invert", "pan_tilt_swap")
# How many of each light tonight (BL #11606, the rig picker): the show, layout, calibration and DMX
# output use only the first N of each kind; addresses never move. Saved rigs are counts by name.
COUNT_MAX = {"bars": 2, "tetras": 6, "sticks": 4}
MAX_SAVED_RIGS = 12
# A palette or saved-layout name: the shape the app's venue.slug() produces (lowercase words
# joined by single hyphens; 48 characters leaves room for a "-2" collision suffix) and never
# a Windows device name, because a layout name becomes a file name on the laptop.
NAME_RE = re.compile(r"(?=.{1,48}$)[a-z0-9]+(?:-[a-z0-9]+)*")
WINDOWS_RESERVED = frozenset({"con", "prn", "aux", "nul", *(f"com{i}" for i in range(10)),
                              *(f"lpt{i}" for i in range(10))})


# A song's key: its artist and title as lowercase words joined by hyphens (track_key()).
SONG_RE = re.compile(r"(?=.{1,96}$)[a-z0-9]+(?:-[a-z0-9]+)*")


def good_name(name) -> bool:
    return isinstance(name, str) and bool(NAME_RE.fullmatch(name)) and name not in WINDOWS_RESERVED


def track_key(artist, title="") -> str:
    """The key a song's style is filed under: both sides compute it the same way from the
    track's artist and title (or from one "Artist - Title" string)."""
    words = re.findall(r"[a-z0-9]+", f"{artist or ''} {title or ''}".lower())
    out = ""
    for w in words:
        if len(out) + len(w) + (1 if out else 0) > 96:
            break
        out = f"{out}-{w}" if out else w
    return out


def _move(shape, a, b, beats=16) -> dict:
    return {"shape": shape, "from": a, "to": b, "size": 0.5, "beats": beats, "spread": "parallel"}


def _section_default(move, derby=False, laser=False, color_bars=0) -> dict:
    return {"wash": 1.0, "movers": 1.0, "pulse": 1.0, "strobe": 1.0, "derby": derby, "laser": laser,
            "color_bars": color_bars, "move": move}


# Today's show, section by section: levels at 1.0 mean "as the built-in look plays it".
# Colors already step by phrase (looks.py 1.3.1): intro/outro every 4 bars, the rest every 8.
SECTION_DEFAULTS = {
    "intro": _section_default(_move("hold", "booth", "booth"), color_bars=4),
    "verse": _section_default(_move("glide", "crowd", "fan"), derby=True, color_bars=8),
    "build": _section_default(_move("rise", "crowd", "ceiling")),
    "drop": _section_default(_move("snap", "cross", "fan", 4), derby=True, laser=True, color_bars=8),
    "main": _section_default(_move("snap", "cross", "fan", 4), derby=True, laser=True, color_bars=8),
    "breakdown": _section_default(_move("sweep", "fan", "crowd"), color_bars=8),
    "outro": _section_default(_move("hold", "booth", "booth"), color_bars=4),
}

DEFAULTS = {
    "schema": SCHEMA,
    # (primary wash hue, secondary wash hue) pairs, hue 0..1 (0 red, 0.08 amber, 0.33 green,
    # 0.5 cyan, 0.62 blue, 0.78 violet, 0.83 magenta). One pair is picked per section.
    "palettes": {
        "warm": [[0.02, 0.08], [0.95, 0.06], [0.08, 0.0]],
        "cool": [[0.62, 0.50], [0.70, 0.55], [0.55, 0.78]],
        "hot": [[0.33, 0.83], [0.0, 0.62], [0.15, 0.75], [0.83, 0.5], [0.58, 0.08]],
        "calm": [[0.08, 0.75], [0.58, 0.08], [0.83, 0.5], [0.42, 0.75]],
    },
    "section_palette": {"intro": "calm", "verse": "warm", "build": "cool", "drop": "hot",
                        "main": "hot", "breakdown": "cool", "outro": "calm"},
    # saturation 0..1 per section: 1 = full color, lower = paler, toward white.
    "saturation": {s: 1.0 for s in SECTIONS},
    "drop": {"intensity": 1.0, "burst": True},
    "strobe": {"intensity": 1.0, "speed": 1.0, "build_ramp": True, "loop_auto": True},
    "looks": {"autoloops": list(AUTOLOOPS), "autoloop_bars": 8},
    "master": 1.0,
    "crowd_safe": True,
    "full_power": False,
    "layouts": {"in_use": "", "saved": {}},
    "sections": SECTION_DEFAULTS,
    "styles": {},
    "songs": {},
    "style_in_use": "",
    "shows": {},
    "cues": {},
    "rig": {
        "addresses": {"bar1": 1, "bar2": 41, **{f"tetra{i}": 71 + 10 * i for i in range(1, 7)},
                      **{f"stick{i}": 141 + 10 * i for i in range(1, 5)}},
        "channels": {k: list(v) for k, v in CHANNEL_NAMES.items()},
        "heads": {b: {"swap_heads": False, **{f"head{h}": {f: False for f in HEAD_FLAGS} for h in (1, 2)}}
                  for b in ("bar1", "bar2")},
        "calibration": {"pan_range": 540.0, "tilt_range": 180.0, "tilt_down": 0.5},
        "counts": dict(COUNT_MAX),
        "saved": {},
        "numbering": {"tetra": "left", "stick": "left"},
        "sync_ms": 0,
    },
}

# Built-in looks a show song can play without anyone saving a style first: partial styles laid
# over the house show (merge_style), named for the moment of the night they suit. "house" is the
# show exactly as the settings have it. A saved style with the same name wins.
_SLOW = {"wash": 0.7, "movers": 0.5, "pulse": 0.2, "strobe": 0.0, "derby": False, "laser": False,
         "color_bars": 16, "move": {"shape": "sweep", "from": "crowd", "to": "fan", "beats": 32}}
BUILTIN_LOOKS = {
    "house": {"note": "the show as it is set up"},
    "slow-dance": {"note": "first dance and ballads: soft, pale, slow, no strobe",
                   "saturation": {s: 0.45 for s in SECTIONS},
                   "section_palette": {s: "calm" for s in SECTIONS},
                   "sections": {s: _SLOW for s in SECTIONS},
                   "drop": {"intensity": 0.4, "burst": False},
                   "strobe": {"intensity": 0.0, "build_ramp": False}},
    "warm-up": {"note": "early in the night: warm colors, gentle pulse, light strobe",
                "section_palette": {"verse": "warm", "build": "warm", "drop": "warm", "main": "warm"},
                "sections": {s: {"pulse": 0.6, "strobe": 0.3, "laser": False} for s in SECTIONS},
                "drop": {"intensity": 0.6, "burst": False},
                "strobe": {"intensity": 0.4}},
    "groove": {"note": "steady dancing: cool and warm colors, full movement, no white bursts",
               "section_palette": {"drop": "cool", "main": "warm"},
               "drop": {"intensity": 0.8, "burst": False},
               "strobe": {"intensity": 0.6}},
    "peak": {"note": "the big songs: hot colors, everything moving, full drops",
             "section_palette": {s: "hot" for s in ("verse", "build", "drop", "main")},
             "sections": {s: {"derby": True, "laser": True} for s in ("verse", "drop", "main")},
             "drop": {"intensity": 1.0, "burst": True},
             "strobe": {"intensity": 1.0}},
    "sing-along": {"note": "anthems everyone sings: big warm sweeps, bright but no strobe",
                   "section_palette": {s: "warm" for s in SECTIONS},
                   "sections": {s: {"strobe": 0.0, "move": {"shape": "sweep", "from": "crowd", "to": "ceiling",
                                                           "beats": 16}} for s in SECTIONS},
                   "drop": {"intensity": 0.9, "burst": False},
                   "strobe": {"intensity": 0.0}},
}

# What each setting means, for the Llano page and the Conductor. Ranges are inclusive.
FIELDS = {
    "palettes": "named color palettes; each is a list of [primary hue, secondary hue] pairs, hue 0..1 "
                "(0 red, 0.04 orange-red, 0.08 amber, 0.15 yellow, 0.33 green, 0.5 cyan, 0.62 blue, "
                "0.78 violet, 0.83 magenta, 0.95 pink-red)",
    "section_palette": "which palette each song section uses: " + ", ".join(SECTIONS),
    "saturation": "color saturation per section, 0.2..1 (lower = paler, closer to white)",
    "drop.intensity": "how hard drops and main sections hit, 0.2..1",
    "drop.burst": "white strobe burst and full rig on a drop's first beat, true/false",
    "strobe.intensity": "brightness of every strobe (build ramp, loop strobe, strobe key), 0..1",
    "strobe.speed": "strobe rate, 0.1..1",
    "strobe.build_ramp": "strobe ramps in over a build's last quarter, true/false",
    "strobe.loop_auto": "a DJ loop of 1/2 beat or less strobes white while held, true/false",
    "looks.autoloops": "autoloop looks that run when a track has no sections, in order: " + ", ".join(AUTOLOOPS),
    "looks.autoloop_bars": "bars per autoloop look: " + ", ".join(map(str, AUTOLOOP_BARS)),
    "master": "overall brightness, 0.1..1",
    "crowd_safe": "crowd-safe strobe: every strobe stays at the slow end, about 3 flashes a second "
                  "(estimated for GigBAR-class fixtures), whatever a look asks, true/false; on by default",
    "full_power": "full power: a dancing section with wash and heads at full peaks at DMX 255 on every light, and "
                  "drops ignore a look's lower drop intensity; soft parts of the night stay soft, true/false; off by default",
    "layouts.in_use": "the room layout the show aims from (a preset name or a saved layout's name)",
    "layouts.saved": "his own saved room layouts by name (Show Designer)",
    "sections": "the show per song section (" + ", ".join(SECTIONS) + "), each {wash 0..1, movers 0..1, "
                "pulse 0..1, strobe 0..1 (1 = as the built-in look plays it; pulse 0 = steady), derby "
                "true/false, laser true/false, color_bars 0..32 (bars per color change, 0 = one color for "
                "the section), move {shape " + "|".join(SHAPES) + ", from and to (positions: "
                + ", ".join(POSITIONS) + "), size 0..1 (circle/eight/line), beats 1..64 per pass, spread "
                + "|".join(SPREADS) + "}}",
    "styles": "saved looks by name (at most 12), each {" + ", ".join(STYLE_KEYS) + ", note}",
    "songs": "which saved style a song plays, by track key (lowercase artist and title joined by hyphens)",
    "style_in_use": "the saved style last made the default show (a label; the settings themselves are the show)",
    "shows": "saved song line-ups by name (at most 16), each {title, note, looks: {at most 6 of the show's "
             "own looks by name, each a partial style laid over the house show}, songs: [at most 60 {artist, "
             "title, look (one of the show's looks, a saved style name, a built-in look: "
             + ", ".join(BUILTIN_LOOKS) + ", or \"\" for the house show), why (one line on why it plays that "
             "look), secs (length), bpm, and optionally part (" + ", ".join(SHOW_PARTS) + "), moment (" + \
             ", ".join(SHOW_MOMENTS) + "), reason (one line on why the song sits in its spot), tag (a Dancing song's "
             "energy: " + ", ".join(SONG_TAGS) + "), tag_mine (true when he chose the tag himself), start_at and "
             "end_at (seconds into the song file where its cut for the night starts and ends, when he set them; "
             "absent = Llano's suggestion)}] in play order}",
    "cues": "each song's cue timeline by track key (at most 120 songs, 48 cues each): a list of {at (seconds "
            "into the original recording), do: hit (with size 1 or 2: a white hit, 2 the biggest) | section (with "
            "kind: " + ", ".join(SECTIONS) + "; any section cue replaces the analysis for that song) | feel (with "
            "feel: bigger or softer or \"\", and color \"#rrggbb\" or \"\": the section holding it plays that way)}",
    "rig.addresses": "each light's DMX start address 1..512, by id: " + ", ".join(FIXTURES),
    "rig.channels": "each fixture type's channels in the order the fixture reads them (gigbar, tetra, stick), "
                    "by name, or \"=N\" for a fixed byte; names per type: "
                    + "; ".join(f"{k}: {' '.join(v)}" for k, v in CHANNEL_NAMES.items()),
    "rig.heads": "per GigBAR (bar1, bar2): swap_heads (the engine's head 1 drives the channels of head 2 and "
                 "back), and head1/head2 each {" + ", ".join(HEAD_FLAGS) + "} true/false, applied to the DMX "
                 "bytes under any calibration",
    "rig.counts": "how many of each light are set up tonight: bars 0..2, tetras 0..6, sticks 0..4 (the first N "
                  "of each; addresses never move)",
    "rig.saved": "saved rigs by name (at most 12), each {bars, tetras, sticks} counts",
    "rig.numbering": "which end light 1 starts at for tetra and stick, \"left\" or \"right\" as the room picture "
                     "draws it (his Tetra cords run from the right); every room the laptop draws numbers from there",
    "rig.sync_ms": "how long the speakers play after Mixxx sends the sound (a Bluetooth link, a mixer), 0..3000 ms; "
                   "every light waits this long so a drop lands with the music. Set by tapping along to the click",
    "rig.calibration": "defaults for every head without its own: pan_range 90..720 degrees (manual 540), "
                       "tilt_range 45..360 (manual 180), tilt_down 0..1 (the raw tilt that points a hung head "
                       "straight down, 0.5)",
}


class ContractError(ValueError):
    """A change that cannot be applied: a plain reason, safe to show."""


def defaults() -> dict:
    return copy.deepcopy(DEFAULTS)


def _num(v, lo: float, hi: float, fallback: float) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return fallback
    return round(min(hi, max(lo, float(v))), 4)


def _bool(v, fallback: bool) -> bool:
    return v if isinstance(v, bool) else fallback


def _hue(v) -> "float | None":
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return round(float(v) % 1.0, 4) % 1.0   # 0.99997 rounds to 1.0, which is 0.0 (idempotent)


def _palettes(v) -> dict:
    out = {}
    if isinstance(v, dict):
        for name, pairs in v.items():
            if len(out) >= MAX_PALETTES or not good_name(name):
                continue
            good = []
            for p in pairs if isinstance(pairs, list) else []:
                if isinstance(p, list) and len(p) == 2:
                    a, b = _hue(p[0]), _hue(p[1])
                    if a is not None and b is not None:
                        good.append([a, b])
                if len(good) >= MAX_PAIRS:
                    break
            if good:
                out[name] = good
    return out or copy.deepcopy(DEFAULTS["palettes"])


def _layouts(v) -> dict:
    v = v if isinstance(v, dict) else {}
    in_use = v.get("in_use")
    in_use = in_use if in_use == "" or good_name(in_use) else ""
    saved = {}
    raw = v.get("saved")
    for name, lay in (raw.items() if isinstance(raw, dict) else []):
        if len(saved) >= MAX_SAVED_LAYOUTS:
            break
        if not good_name(name) or not isinstance(lay, dict):
            continue
        lay = {**lay, "name": name, "preset": False}
        # Measured as stored, so a layout that passes once passes every later normalize.
        if len(_dumps(lay)) > MAX_LAYOUT_BYTES:
            continue
        # The app's Layout.from_dict is the authority on geometry; here only shape and size.
        if not isinstance(lay.get("room"), dict) or not isinstance(lay.get("fixtures"), dict):
            continue
        saved[name] = lay
    return {"in_use": in_use, "saved": saved}


def _choice(v, options, fallback):
    return v if isinstance(v, str) and v in options else fallback


def _int(v, lo: int, hi: int, fallback: int) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return fallback
    return int(min(hi, max(lo, round(v))))


def _section(v, kind: str) -> dict:
    v = v if isinstance(v, dict) else {}
    dv = SECTION_DEFAULTS[kind]
    mv = v.get("move") if isinstance(v.get("move"), dict) else {}
    dm = dv["move"]
    return {"wash": _num(v.get("wash"), 0.0, 1.0, dv["wash"]),
            "movers": _num(v.get("movers"), 0.0, 1.0, dv["movers"]),
            "pulse": _num(v.get("pulse"), 0.0, 1.0, dv["pulse"]),
            "strobe": _num(v.get("strobe"), 0.0, 1.0, dv["strobe"]),
            "derby": _bool(v.get("derby"), dv["derby"]),
            "laser": _bool(v.get("laser"), dv["laser"]),
            "color_bars": _int(v.get("color_bars"), 0, 32, dv["color_bars"]),
            "move": {"shape": _choice(mv.get("shape"), SHAPES, dm["shape"]),
                     "from": _choice(mv.get("from"), POSITIONS, dm["from"]),
                     "to": _choice(mv.get("to"), POSITIONS, dm["to"]),
                     "size": _num(mv.get("size"), 0.0, 1.0, dm["size"]),
                     "beats": _int(mv.get("beats"), 1, 64, dm["beats"]),
                     "spread": _choice(mv.get("spread"), SPREADS, dm["spread"])}}


def _sections(v) -> dict:
    v = v if isinstance(v, dict) else {}
    return {s: _section(v.get(s), s) for s in SECTIONS}


def normalize_style(v) -> dict:
    """Any input to a valid style: the show-shaping part of a settings document, plus a note."""
    v = v if isinstance(v, dict) else {}
    doc = normalize({k: v[k] for k in STYLE_KEYS if k in v})
    return {**{k: doc[k] for k in STYLE_KEYS}, "note": str(v.get("note") or "")[:300]}


def style_of(doc, note: str = "") -> dict:
    """The live show in a settings document, as a style."""
    d = normalize(doc)
    return {**{k: d[k] for k in STYLE_KEYS}, "note": str(note or "")[:300]}


def merge_style(base, partial) -> dict:
    """`partial` laid over `base` (both styles): a key `partial` names replaces the base's,
    one level down for the per-section maps, so "only the build's strobe" stays a small change."""
    out = normalize_style(base)
    p = partial if isinstance(partial, dict) else {}
    for k in STYLE_KEYS:
        if k not in p:
            continue
        if k == "palettes" and isinstance(p[k], dict):   # by name; a null drops that palette
            out[k] = {n: v for n, v in {**out[k], **p[k]}.items() if v is not None}
        elif k in ("section_palette", "saturation", "drop", "strobe") and isinstance(p[k], dict):
            out[k] = {**out[k], **p[k]}
        elif k == "sections" and isinstance(p[k], dict):
            secs = copy.deepcopy(out["sections"])
            for s, sv in p[k].items():
                if s in secs and isinstance(sv, dict):
                    mv = sv.get("move")
                    secs[s] = {**secs[s], **sv,
                               "move": {**secs[s]["move"], **mv} if isinstance(mv, dict) else secs[s]["move"]}
            out["sections"] = secs
        else:
            out[k] = p[k]
    if "note" in p:
        out["note"] = p["note"]
    return normalize_style(out)


def _styles(v) -> dict:
    out = {}
    for name, st in (v.items() if isinstance(v, dict) else []):
        if len(out) >= MAX_STYLES:
            break
        if good_name(name) and isinstance(st, dict):
            out[name] = normalize_style(st)
    return out


def _songs(v, styles: dict) -> dict:
    out = {}
    for key, name in (v.items() if isinstance(v, dict) else []):
        if len(out) >= MAX_SONGS:
            break
        if isinstance(key, str) and SONG_RE.fullmatch(key) and isinstance(name, str) and name in styles:
            out[key] = name
    return out


def _text(v, n: int) -> str:
    # rstrip after the cut, so a second normalize never trims a space the first one left (idempotent)
    return " ".join(str(v).split())[:n].rstrip() if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""


def show_look(v) -> dict:
    """A show's own look: only the settings it names, each clamped the way a style is (so it plays
    over whatever the house show is, like BUILTIN_LOOKS). Normalizing twice gives the same look."""
    p = v if isinstance(v, dict) else {}
    full = merge_style(normalize_style({}), p)
    out = {}
    for k in STYLE_KEYS:
        pk = p.get(k)
        if not isinstance(pk, dict):
            continue
        if k == "sections":
            secs = {}
            for s, sv in pk.items():
                if s in full["sections"] and isinstance(sv, dict):
                    fs = full["sections"][s]
                    one = {f: fs[f] for f in sv if f in fs and f != "move"}
                    if isinstance(sv.get("move"), dict):
                        one["move"] = {m: fs["move"][m] for m in sv["move"] if m in fs["move"]}
                    if one:
                        secs[s] = one
            if secs:
                out[k] = secs
        else:
            got = {n: full[k][n] for n in pk if n in full[k]}
            if got:
                out[k] = got
    note = _text(p.get("note"), 120)
    if note:
        out["note"] = note
    return out


def _show_looks(v) -> dict:
    out = {}
    for name, lk in (v.items() if isinstance(v, dict) else []):
        if len(out) >= MAX_SHOW_LOOKS:
            break
        if good_name(name) and name not in BUILTIN_LOOKS and isinstance(lk, dict):
            out[name] = show_look(lk)
    return out


# A mood for cocktail hour and for dinner (Llano BL #12340): what the soft wash plays instead of
# each song's colors. One color, or a slow fade through two to four colors (a one minute melt, a
# change every 2, 5 or 10 minutes), at its own brightness. Llano's suggestion fills every show that
# has none, so he only changes what he dislikes.
MOOD_PARTS = ("cocktail", "dinner")
MOOD_KINDS = ("color", "fade")
MOOD_EVERY = (2, 5, 10)                  # minutes between colors in a slow fade
MOOD_SWATCHES = {"warm white": "#ffe4c4", "amber": "#ffb347", "blush": "#f4b6c2", "gold": "#f2c14e",
                 "lavender": "#c3b1e1", "soft blue": "#9ec9f0"}
SUGGESTED_MOODS = {
    "cocktail": {"kind": "fade", "colors": ["#ffe4c4", "#f4b6c2", "#f2c14e"], "every": 5, "bright": 0.6},
    "dinner": {"kind": "color", "colors": ["#ffb347"], "every": 5, "bright": 0.45},
}
_HEX = re.compile(r"#[0-9a-f]{6}")


def part_mood(v, part: str) -> dict:
    """One part's mood, clamped; Llano's suggestion where nothing valid was given."""
    base = SUGGESTED_MOODS.get(part, SUGGESTED_MOODS["dinner"])
    if not isinstance(v, dict):
        return {**base, "colors": list(base["colors"])}
    kind = v.get("kind") if v.get("kind") in MOOD_KINDS else base["kind"]
    colors = [c.lower() for c in (v.get("colors") if isinstance(v.get("colors"), list) else [])
              if isinstance(c, str) and _HEX.fullmatch(c.lower())][:4]
    if not colors:
        colors = list(base["colors"])
    if kind == "fade" and len(colors) < 2:
        kind = "color"
    every = v.get("every") if v.get("every") in MOOD_EVERY else base["every"]
    return {"kind": kind, "colors": colors[:1] if kind == "color" else colors, "every": every,
            "bright": round(_num(v.get("bright"), 0.1, 1.0, base["bright"]), 2)}


def moods(v) -> dict:
    """Both parts' moods ({} or junk = Llano's suggestion for each)."""
    v = v if isinstance(v, dict) else {}
    return {p: part_mood(v.get(p), p) for p in MOOD_PARTS}


def _show(v, styles: dict, keep_looks: bool = False) -> "dict | None":
    if not isinstance(v, dict):
        return None
    own = _show_looks(v.get("looks"))
    songs = []
    for s in v.get("songs") if isinstance(v.get("songs"), list) else []:
        if len(songs) >= MAX_SHOW_SONGS:
            break
        if not isinstance(s, dict):
            continue
        artist, title = _text(s.get("artist"), 80), _text(s.get("title"), 120)
        if not title:
            continue
        look = s.get("look")
        songs.append({"artist": artist, "title": title,
                      "look": look if isinstance(look, str) and (keep_looks or look in own or look in styles
                                                                 or look in BUILTIN_LOOKS) else "",
                      "why": _text(s.get("why"), 120),
                      "secs": _num(s.get("secs"), 0.0, 3600.0, 0.0),
                      "bpm": _num(s.get("bpm"), 0.0, 300.0, 0.0)})
        # set arranger fields, stored only when set so older shows keep their exact bytes
        for k, ok in (("part", SHOW_PARTS), ("moment", SHOW_MOMENTS)):
            if s.get(k) in ok:
                songs[-1][k] = s[k]
        if _text(s.get("reason"), 90):
            songs[-1]["reason"] = _text(s.get("reason"), 90)
        if s.get("tag") in SONG_TAGS:
            songs[-1]["tag"] = s["tag"]
            if s.get("tag_mine") is True:
                songs[-1]["tag_mine"] = True
        # his own Starts at / Ends at for the night's cut (Llano PM #23751): seconds into the song file
        for k in ("start_at", "end_at"):
            at = s.get(k)
            if isinstance(at, (int, float)) and not isinstance(at, bool) and 0 <= at <= 3600:
                songs[-1][k] = round(float(at), 2)
    out = {"title": _text(v.get("title"), 80), "note": _text(v.get("note"), 300), "looks": own, "songs": songs}
    if isinstance(v.get("moods"), dict):   # stored only once set, so older shows keep their exact bytes
        out["moods"] = moods(v["moods"])
    # Measured as stored, so a show that passes once passes every later normalize; one over the
    # cap keeps the songs that fit, in order, rather than vanishing.
    while out["songs"] and len(_dumps_ascii(out)) > MAX_SHOW_BYTES:
        out["songs"].pop()
    return out


def cue(v) -> "dict | None":
    """One cue, well formed, or None (a bad one never reaches the lights)."""
    if not isinstance(v, dict):
        return None
    at, do = v.get("at"), v.get("do")
    if isinstance(at, bool) or not isinstance(at, (int, float)) or not (0 <= at <= 3600) or do not in CUE_DOS:
        return None
    out = {"at": round(float(at), 2), "do": do}
    if do == "hit":
        out["size"] = 2 if v.get("size") == 2 else 1
    elif do == "section":
        if v.get("kind") not in SECTIONS:
            return None
        out["kind"] = v["kind"]
    else:
        feel = v.get("feel") if v.get("feel") in CUE_FEELS else ""
        color = v.get("color").lower() if isinstance(v.get("color"), str) else ""
        color = color if CUE_COLOR_RE.fullmatch(color) else ""
        if not feel and not color:
            return None
        out["feel"], out["color"] = feel, color
    return out


def song_cues(v) -> list:
    """A song's cues: well formed, in time order, at most MAX_CUES (the earliest kept)."""
    got = [c for c in (cue(x) for x in (v if isinstance(v, list) else [])[:4 * MAX_CUES]) if c]
    return sorted(got, key=lambda c: (c["at"], CUE_DOS.index(c["do"])))[:MAX_CUES]


def _cues(v) -> dict:
    out = {}
    for key, cs in (v.items() if isinstance(v, dict) else []):
        if len(out) >= MAX_CUE_SONGS:
            break
        if isinstance(key, str) and SONG_RE.fullmatch(key):
            got = song_cues(cs)
            if got:   # a song with no cues is not stored: clearing its last cue deletes it
                out[key] = got
    # measured as stored; over the cap, the songs that fit stay (in key order) rather than all vanishing
    while out and len(_dumps_ascii(out)) > MAX_CUES_BYTES:
        out.pop(sorted(out)[-1])
    return out


def show_fits(v) -> bool:
    """True when a show saves whole (no songs cut for size or count); the laptop checks before saving."""
    return isinstance(v, dict) and isinstance(v.get("songs"), list) and \
        len(_show(v, {}, keep_looks=True)["songs"]) == len([s for s in v["songs"] if isinstance(s, dict) and _text(s.get("title"), 120)])


def _shows(v, styles: dict) -> dict:
    out = {}
    for name, sh in (v.items() if isinstance(v, dict) else []):
        if len(out) >= MAX_SHOWS:
            break
        sh = _show(sh, styles) if good_name(name) else None
        if sh is not None:
            out[name] = sh
    return out


def look_style(name: str, styles: dict, base, show_looks: "dict | None" = None) -> "dict | None":
    """The style a show song's look plays: the playing show's own look by that name, else a saved
    style, else a built-in look, each laid over the house show in `base`; else None (the house show
    as it is)."""
    if show_looks and name in show_looks:
        return merge_style(style_of(base), show_looks[name])
    if name in styles:
        return styles[name]
    if name in BUILTIN_LOOKS and name != "house":
        return merge_style(style_of(base), BUILTIN_LOOKS[name])
    return None


def _channel_list(v, kind: str) -> list:
    names = CHANNEL_NAMES[kind]
    if not isinstance(v, list) or not 1 <= len(v) <= MAX_FOOTPRINT:
        return list(names)
    out = []
    for x in v:
        if isinstance(x, str) and x in names:
            out.append(x)
        elif isinstance(x, str) and re.fullmatch(r"=(\d{1,3})", x) and int(x[1:]) <= 255:
            out.append(f"={int(x[1:])}")
        else:
            return list(names)   # one unknown name: the whole list is suspect, keep the known order
    return out


def _counts(v) -> dict:
    v = v if isinstance(v, dict) else {}
    return {k: _int(v.get(k), 0, hi, hi) for k, hi in COUNT_MAX.items()}


def _rig(v) -> dict:
    v = v if isinstance(v, dict) else {}
    dv = DEFAULTS["rig"]
    addr = v.get("addresses") if isinstance(v.get("addresses"), dict) else {}
    chans = v.get("channels") if isinstance(v.get("channels"), dict) else {}
    heads = v.get("heads") if isinstance(v.get("heads"), dict) else {}
    cal = v.get("calibration") if isinstance(v.get("calibration"), dict) else {}
    num = v.get("numbering") if isinstance(v.get("numbering"), dict) else {}
    out_heads = {}
    for bar, dh in dv["heads"].items():
        h = heads.get(bar) if isinstance(heads.get(bar), dict) else {}
        out_heads[bar] = {"swap_heads": _bool(h.get("swap_heads"), False)}
        for n in ("head1", "head2"):
            one = h.get(n) if isinstance(h.get(n), dict) else {}
            out_heads[bar][n] = {f: _bool(one.get(f), False) for f in HEAD_FLAGS}
    return {
        "addresses": {fid: _int(addr.get(fid), 1, 512, dv["addresses"][fid]) for fid in FIXTURES},
        "channels": {k: _channel_list(chans.get(k), k) for k in CHANNEL_NAMES},
        "heads": out_heads,
        "calibration": {"pan_range": _num(cal.get("pan_range"), 90, 720, 540.0),
                        "tilt_range": _num(cal.get("tilt_range"), 45, 360, 180.0),
                        "tilt_down": _num(cal.get("tilt_down"), 0.0, 1.0, 0.5)},
        "counts": _counts(v.get("counts")),
        "saved": dict([(n, _counts(c)) for n, c in (v.get("saved").items() if isinstance(v.get("saved"), dict) else [])
                       if good_name(n) and isinstance(c, dict)][:MAX_SAVED_RIGS]),
        "numbering": {k: (num.get(k) if num.get(k) in ("left", "right") else d)
                      for k, d in dv["numbering"].items()},
        "sync_ms": _int(v.get("sync_ms"), 0, SYNC_MAX_MS, 0),
    }


def _dumps(v) -> str:
    import json
    return json.dumps(v, sort_keys=True, separators=(",", ":"))


def _dumps_ascii(v) -> str:
    import json
    return json.dumps(v, separators=(",", ":"))   # ensure_ascii: the size Llano's store measures


def normalize(doc) -> dict:
    """Any input to a valid settings document; unknown keys dropped, numbers clamped."""
    d = doc if isinstance(doc, dict) else {}
    dv = DEFAULTS
    palettes = _palettes(d.get("palettes"))
    sp_in = d.get("section_palette") if isinstance(d.get("section_palette"), dict) else {}
    first = next(iter(palettes))
    section_palette = {}
    for s in SECTIONS:
        want = sp_in.get(s)
        if isinstance(want, str) and want in palettes:
            section_palette[s] = want
        else:
            fallback = dv["section_palette"][s]
            section_palette[s] = fallback if fallback in palettes else first
    sat_in = d.get("saturation") if isinstance(d.get("saturation"), dict) else {}
    drop = d.get("drop") if isinstance(d.get("drop"), dict) else {}
    strobe = d.get("strobe") if isinstance(d.get("strobe"), dict) else {}
    looks = d.get("looks") if isinstance(d.get("looks"), dict) else {}
    loops = []
    for x in looks.get("autoloops") if isinstance(looks.get("autoloops"), list) else []:
        if isinstance(x, str) and x in AUTOLOOPS and x not in loops:
            loops.append(x)
    bars = looks.get("autoloop_bars")
    styles = _styles(d.get("styles"))
    in_use = d.get("style_in_use")
    return {
        "schema": SCHEMA,
        "palettes": palettes,
        "section_palette": section_palette,
        "saturation": {s: _num(sat_in.get(s), 0.2, 1.0, 1.0) for s in SECTIONS},
        "drop": {"intensity": _num(drop.get("intensity"), 0.2, 1.0, 1.0),
                 "burst": _bool(drop.get("burst"), True)},
        "strobe": {"intensity": _num(strobe.get("intensity"), 0.0, 1.0, 1.0),
                   "speed": _num(strobe.get("speed"), 0.1, 1.0, 1.0),
                   "build_ramp": _bool(strobe.get("build_ramp"), True),
                   "loop_auto": _bool(strobe.get("loop_auto"), True)},
        "looks": {"autoloops": loops or list(AUTOLOOPS),
                  "autoloop_bars": bars if isinstance(bars, int) and not isinstance(bars, bool)
                  and bars in AUTOLOOP_BARS else 8},
        "master": _num(d.get("master"), 0.1, 1.0, 1.0),
        "crowd_safe": _bool(d.get("crowd_safe"), True),
        "full_power": _bool(d.get("full_power"), False),
        "layouts": _layouts(d.get("layouts")),
        "sections": _sections(d.get("sections")),
        "styles": styles,
        "songs": _songs(d.get("songs"), styles),
        "style_in_use": in_use if isinstance(in_use, str) and in_use in styles else "",
        "shows": _shows(d.get("shows"), styles),
        "cues": _cues(d.get("cues")),
        "rig": _rig(d.get("rig")),
    }


TOP_KEYS = tuple(k for k in DEFAULTS if k != "schema")


def _split(path) -> list:
    if not isinstance(path, str) or not path or len(path) > 120:
        raise ContractError("each change needs a path like 'strobe.intensity'")
    parts = path.split(".")
    if parts[0] not in TOP_KEYS:
        raise ContractError(f"unknown setting '{parts[0]}' (settings: {', '.join(TOP_KEYS)})")
    if len(parts) > 3 or any(not p for p in parts):
        raise ContractError(f"'{path}' is not a setting path")
    if len(parts) == 3 and parts[:2] != ["layouts", "saved"] and parts[0] not in ("sections", "rig"):
        raise ContractError(f"'{path}' is too deep")
    return parts


#: Paths whose null value deletes the named entry.
_DELETABLE = {("layouts", "saved"), ("palettes",), ("styles",), ("songs",), ("shows",), ("cues",), ("rig", "saved")}


def get_path(doc, path: str):
    """The value at a dotted setting path, or None."""
    return _get(normalize(doc), path.split(".")) if isinstance(path, str) else None


def _get(doc: dict, parts: list):
    cur = doc
    for p in parts:
        if not (isinstance(cur, dict) and p in cur):
            return None
        cur = cur[p]
    return copy.deepcopy(cur)


def apply_ops(doc, ops) -> tuple[dict, list]:
    """(new normalized doc, applied ops each with `before`). Raises ContractError on a bad op;
    nothing is applied unless every op is well formed."""
    if not isinstance(ops, list) or not ops:
        raise ContractError("no changes given")
    if len(ops) > MAX_OPS:
        raise ContractError(f"at most {MAX_OPS} changes at once")
    work = normalize(doc)
    applied = []
    for op in ops:
        if not isinstance(op, dict):
            raise ContractError("each change is an object with a path and a value")
        parts = _split(op.get("path"))
        value = copy.deepcopy(op.get("value"))
        before = _get(work, parts)
        if value is None and tuple(parts[:-1]) not in _DELETABLE:
            raise ContractError(f"'{op.get('path')}' needs a value")
        parent = work
        for p in parts[:-1]:
            nxt = parent.get(p) if isinstance(parent, dict) else None
            if not isinstance(nxt, dict):
                nxt = {}
                parent[p] = nxt
            parent = nxt
        if value is None:
            parent.pop(parts[-1], None)
        else:
            parent[parts[-1]] = value
        applied.append({"path": op["path"], "value": value, "before": before})
    out = normalize(work)
    # Cues past their caps are never dropped quietly from another song (fresh review, PM #23787): a
    # change whose songs' cues would not all fit is refused, and the document stays as it was.
    raw = work.get("cues") if isinstance(work.get("cues"), dict) else {}
    valid = {k: [c for c in (cue(x) for x in (v if isinstance(v, list) else [])) if c]
             for k, v in raw.items() if isinstance(k, str) and SONG_RE.fullmatch(k)}
    want = {k for k, v in valid.items() if v}
    if want - set(out["cues"]) or any(len(valid[k]) > MAX_CUES for k in want):
        raise ContractError("That doesn't fit: the songs' cues are full (at most "
                            f"{MAX_CUE_SONGS} songs and {MAX_CUES} cues a song). Remove some cues first.")
    # An op on a key the document does not keep (a typo, a field this schema lacks) changed
    # nothing; recording it would leave an undo that can never apply.
    applied = [a for a in applied if not (a["before"] is None and _get(out, a["path"].split(".")) is None)]
    return out, applied


def undo_ops(applied: list) -> list:
    """The ops that put back what `applied` replaced (newest first)."""
    return [{"path": a["path"], "value": a.get("before")} for a in reversed(applied or [])
            if isinstance(a, dict) and isinstance(a.get("path"), str)]


def diff_ops(old, new) -> list:
    """Ops that turn `old` into `new` (both normalized), at the paths ops use."""
    a, b = normalize(old), normalize(new)
    out = []
    for key in TOP_KEYS:
        if key == "layouts":
            if a["layouts"]["in_use"] != b["layouts"]["in_use"]:
                out.append({"path": "layouts.in_use", "value": b["layouts"]["in_use"]})
            sa, sb = a["layouts"]["saved"], b["layouts"]["saved"]
            for name in sorted(set(sa) | set(sb)):
                if _dumps(sa.get(name)) != _dumps(sb.get(name)):
                    out.append({"path": f"layouts.saved.{name}", "value": sb.get(name)})
        elif key in ("palettes", "styles", "songs", "shows", "cues"):
            for name in sorted(set(a[key]) | set(b[key])):
                if a[key].get(name) != b[key].get(name):
                    out.append({"path": f"{key}.{name}", "value": b[key].get(name)})
        elif isinstance(b[key], dict):
            for sub in b[key]:
                if a[key].get(sub) != b[key][sub]:
                    out.append({"path": f"{key}.{sub}", "value": b[key][sub]})
        elif a[key] != b[key]:
            out.append({"path": key, "value": b[key]})
    return out


def style_ops(doc, style) -> list:
    """Ops that make `style` the live show in `doc` (only the paths that differ)."""
    cur = normalize(doc)
    st = normalize_style(style)
    want = normalize({**cur, **{k: st[k] for k in STYLE_KEYS}})
    return [o for o in diff_ops(cur, want) if o["path"].split(".")[0] in STYLE_KEYS]
