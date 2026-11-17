"""The DMX frames the default show produces across every kind of moment, for the
byte-identical gate (test_show_identical.py).

Every section kind (with a long intro, a build into a drop and one into a main, an outro
fade), autoloops at both energies, a drop burst, a build's strobe ramp, Loop Auto-Strobe,
idle and silence, the overrides, a room layout, and the settings 1.3.x already had, on
three track seeds. It takes the engine's modules as arguments, so the same code renders
any version: frames(pkg) where pkg is the imported tools.gigbar_lights of that checkout.
"""
from __future__ import annotations

import hashlib
import importlib

SCRIPT = [("intro", 0, 96), ("verse", 96, 160), ("build", 160, 192), ("drop", 192, 256),
          ("main", 256, 320), ("breakdown", 320, 352), ("build", 352, 384), ("main", 384, 416),
          ("outro", 416, 480)]
# Sections that start off the bar line, and a short intro (no groove switch).
SCRIPT_ODD = [("intro", 6, 38), ("verse", 38, 70), ("build", 70, 86), ("drop", 86, 118),
              ("breakdown", 118, 150), ("outro", 150, 170)]

# Settings 1.3.x already played correctly: each side normalizes them with its own contract.
# (1.3.x ignored saturation and section_palette for intro/verse/breakdown/outro; 1.4.0 reads
# them, so those are tested on their own in test_looks_described_show.py.)
SETTINGS = [
    {},
    {"strobe": {"intensity": 0.5, "speed": 0.6}, "drop": {"intensity": 0.6}, "master": 0.7},
    {"saturation": {"build": 0.6, "drop": 0.3, "main": 0.5}, "drop": {"burst": False},
     "strobe": {"build_ramp": False, "loop_auto": False}},
    {"section_palette": {"build": "warm", "drop": "cool", "main": "warm"},
     "looks": {"autoloops": ["sweep", "rainbow"], "autoloop_bars": 4}},
]


def _mods(pkg: str):
    m = lambda name: importlib.import_module(f"{pkg}.{name}")   # noqa: E731
    return m("looks"), m("show_script"), m("rig"), m("venue"), m("settings_contract")


def _sections(ss, spec):
    return [ss.Section(k, a, b, 0.8) for k, a, b in spec]


def _at(secs, beat):
    for i, s in enumerate(secs):
        if s.start_beat <= beat < s.end_beat:
            return s, (secs[i + 1] if i + 1 < len(secs) else None)
    return None, None


def frames(pkg: str = "tools.gigbar_lights", venue_run: bool = True):
    """Yield (label, universe bytes) for every scenario, in a fixed order. `venue_run=False`
    leaves out the room-layout pass (1.9.0 aims the spots forward there on purpose)."""
    looks, ss, rigm, venue, contract = _mods(pkg)
    lay = next(iter(venue.presets().values()))
    for si, raw in enumerate(SETTINGS):
        # Crowd-safe strobe (1.6.0) is on by default and caps strobe rates on purpose; the gate
        # pins everything else, so it renders with the guard off (an older contract ignores the key).
        cfg = contract.normalize({**raw, "crowd_safe": False})
        for seed in (0, 17, 12345):
            for use_venue in ((False, True) if si == 0 and venue_run else (False,)):
                eng = looks.LooksEngine(settings=cfg)
                if use_venue:
                    eng.apply_venue(lay)
                rig = rigm.default_rig()
                tag = f"s{si}/k{seed}/{'venue' if use_venue else 'plain'}"
                # A whole scripted song, off-grid steps so every beat phase shows up.
                step = 0.37 if si == 0 and seed == 0 else 1.13
                for spec, name in ((SCRIPT, "song"), (SCRIPT_ODD, "odd")):
                    secs = _sections(ss, spec)
                    b = 0.0
                    while b < spec[-1][2] + 4:
                        s, n = _at(secs, b)
                        f = looks.Frame(b, 128.0, True, level=0.8, section=s, next_section=n, track_key=seed)
                        yield f"{tag}/{name}/{b:.2f}", bytes(eng.render(f, rig).render())
                        b += step
                # Drop's first beat (the burst) and the dark beat before it, finely.
                secs = _sections(ss, SCRIPT)
                for i in range(40):
                    b = 188.0 + i * 0.1
                    s, n = _at(secs, b)
                    f = looks.Frame(b, 128.0, True, level=0.9, section=s, next_section=n, track_key=seed)
                    yield f"{tag}/burst/{b:.2f}", bytes(eng.render(f, rig).render())
                # Loop Auto-Strobe in a verse and a drop; silence; idle.
                for b in (100.0, 100.5, 200.25, 230.75):
                    s, n = _at(secs, b)
                    for lb in (0.25, 0.5, 1.0):
                        f = looks.Frame(b, 128.0, True, level=0.8, loop_beats=lb, section=s, next_section=n,
                                        track_key=seed)
                        yield f"{tag}/loop{lb}/{b}", bytes(eng.render(f, rig).render())
                for b in (10.0, 120.0, 260.0):
                    s, n = _at(secs, b)
                    yield f"{tag}/silence/{b}", bytes(eng.render(
                        looks.Frame(b, 128.0, True, level=0.0, section=s, next_section=n, track_key=seed), rig).render())
                    yield f"{tag}/idle/{b}", bytes(eng.render(
                        looks.Frame(b, 128.0, False, level=0.0, section=s, next_section=n, track_key=seed), rig).render())
                # Autoloops at low and high energy across every loop look.
                b = 0.0
                while b < 160.0:
                    lv = 0.3 if int(b // 16) % 2 else 0.75
                    f = looks.Frame(b, 126.0, True, level=lv, track_key=seed)
                    yield f"{tag}/auto/{b:.2f}", bytes(eng.render(f, rig).render())
                    b += 0.5 if si == 0 else 1.25
                if si == 0:
                    # The overrides.
                    for ov in ("color_hold", "master", "autoloop_override", "strobe", "hold_loop"):
                        eng.overrides = looks.Overrides()
                        if ov == "color_hold":
                            eng.overrides.color_hold = 0.33
                        elif ov == "master":
                            eng.overrides.master = 0.5
                        else:
                            setattr(eng.overrides, ov, True)
                        for b in (2.0, 70.0, 99.0, 170.0, 185.0, 192.2, 270.0, 330.0, 440.0):
                            s, n = _at(secs, b)
                            f = looks.Frame(b, 128.0, True, level=0.8, section=s, next_section=n, track_key=seed)
                            yield f"{tag}/{ov}/{b}", bytes(eng.render(f, rig).render())
                    eng.overrides = looks.Overrides()


# GigBAR channels 1.12.3 drives on purpose (his 11-08 report "you missed adding the channels for
# the other lights like the lasers"): derby rotation ch13/16 (now both ways), laser strobe ch18,
# laser rotation ch19 (both ways), UV strobe ch22 and white/UV strobe speed ch23 (the build's UV).
EFFECT_OFFSETS = (12, 15, 17, 18, 19, 21, 22)   # 19: ch20, 1.14.1 runs All strobing under a strobe level


def _tilts(rigm) -> list[int]:
    """Universe index of each GigBAR head's tilt channel (35CH: ch25 head 1, ch31 head 2), and of
    the effect channels 1.12.3 re-drove (EFFECT_OFFSETS)."""
    return [bar.address - 1 + off for bar in rigm.default_rig().bars for off in (24, 30, *EFFECT_OFFSETS)]


def _untilted(u: bytes, tilts: list[int]) -> bytes:
    """The frame with the moving heads' tilt bytes zeroed (1.10.1 re-modeled tilt on purpose:
    the heads hang under the bar, so 0.5 is straight down, not level), and 1.12.3's effect bytes.
    And a dark head's pan (dimmer ch26 / ch32 at 0): 1.16.7 holds a head's aim through the dark
    (looks._hold_aim) where 1.3.1 parked it at pan 0.5; a dark beam lights nothing either way."""
    b = bytearray(u)
    for i in tilts:
        b[i] = 0
    for pan, dim in _DARK_PANS:
        if u[dim] == 0:
            b[pan] = 0
    return bytes(b)


_DARK_PANS: list = []


def _dark_pans(rigm) -> list[tuple[int, int]]:
    """(pan, dimmer) universe indices of each GigBAR head (35CH: ch24/ch26 head 1, ch30/ch32 head 2)."""
    return [(bar.address - 1 + p, bar.address - 1 + d) for bar in rigm.default_rig().bars for p, d in ((23, 25), (29, 31))]


def digest(pkg: str = "tools.gigbar_lights", venue_run: bool = True, tilt: bool = True) -> tuple[int, str]:
    """`tilt=False` zeroes the moving heads' tilt bytes in every frame."""
    tilts = _tilts(_mods(pkg)[2])
    _DARK_PANS[:] = _dark_pans(_mods(pkg)[2])
    h, n = hashlib.sha256(), 0
    for _label, u in frames(pkg, venue_run):
        h.update(u if tilt else _untilted(u, tilts))
        n += 1
    return n, h.hexdigest()


def doc_digest(doc: dict, pkg: str = "tools.gigbar_lights", tilt: bool = True) -> tuple[int, str]:
    """A whole song, the odd song and the autoloops played from one settings document,
    normalized by that version's own contract (a 1.3.x settings.json read by 1.4.0)."""
    looks, ss, rigm, _venue, contract = _mods(pkg)
    eng, rig = looks.LooksEngine(settings=contract.normalize({**doc, "crowd_safe": False})), rigm.default_rig()
    tilts = _tilts(rigm)
    _DARK_PANS[:] = _dark_pans(rigm)
    h, n = hashlib.sha256(), 0
    for spec in (SCRIPT, SCRIPT_ODD, []):
        secs = _sections(ss, spec)
        b = 0.0
        while b < (spec[-1][2] + 4 if spec else 160.0):
            s, nx = _at(secs, b)
            u = bytes(eng.render(looks.Frame(b, 128.0, True, level=0.8, section=s, next_section=nx,
                                             track_key=7), rig).render())
            h.update(u if tilt else _untilted(u, tilts))
            n += 1
            b += 0.61
    return n, h.hexdigest()
