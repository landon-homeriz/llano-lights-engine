"""Seeded light states for the fixture-library gate (Llano BL #12136, test_fixture_profiles.py).

Every attribute the looks engine can set on today's three kinds (GigBAR Move 35CH, Venue Tetra 6,
Freedom Stick 8CH), over plain values and the edges that bend a byte (0, 1, a hair either side of 0,
below 0, above 1, every derby and laser color, every wheel slot and strobe program, out-of-range
programs), rendered through several rig blocks (default, a short rig, every head flag on, the
heads swapped, reordered and fixed-byte channel lists, a moved light).

It takes the rig and settings-contract MODULES as arguments, so the same states render through any
version's rig.py: frames(rig_mod, contract_mod) with the modules of that checkout. The pins in
test_fixture_profiles.py were rendered this way by the released 1.19.3 and 1.37.0 code itself.
"""
from __future__ import annotations

import copy
import hashlib
import random

DERBY = ("off", "red", "green", "blue", "yellow", "magenta", "cyan", "white", "auto", "auto2")
LASER = ("off", "red", "green", "both", "red_flash", "green_flash", "alternate")
EDGES = (0.0, 1.0, 0.5, 1e-9, -1e-9, -0.25, 1.25, 0.001, 0.999, 0.002, 0.998,
         0.5019607843137255, 127.5 / 255, 0.25, 0.75)
PROGRAMS = (0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, -1, 3.7)
SEED = 12136
COUNT = 400


def _level(r: random.Random) -> float:
    k = r.random()
    if k < 0.25:
        return r.choice(EDGES)
    if k < 0.35:
        return 0.0
    return r.random()


def _strobe(r: random.Random) -> float:
    return 0.0 if r.random() < 0.5 else _level(r)


def _signed(r: random.Random) -> float:
    k = r.random()
    if k < 0.3:
        return 0.0
    if k < 0.45:
        return r.choice(EDGES) * r.choice((1, -1))
    return r.uniform(-1.0, 1.0)


def randomize(rig, r: random.Random) -> None:
    """Every settable attribute of every light in `rig` (a rig.default_rig()), in place."""
    for bar in rig.bars:
        for p in bar.pars:
            p.red, p.green, p.blue, p.uv = _level(r), _level(r), _level(r), _level(r)
            p.dim, p.strobe = _level(r), _strobe(r)
        for d in bar.derbies:
            d.color, d.strobe, d.rotate = r.choice(DERBY), _strobe(r), _signed(r)
        bar.laser, bar.laser_strobe, bar.laser_rotate = r.choice(LASER), _strobe(r), _signed(r)
        bar.strobe_program = r.choice(PROGRAMS)
        bar.strobe_white, bar.strobe_uv, bar.strobe_speed = _strobe(r), _strobe(r), _level(r)
        for m in bar.movers:
            m.pan, m.tilt, m.dim, m.strobe = _level(r), _level(r), _level(r), _strobe(r)
            m.color, m.gobo = r.randrange(8), r.randrange(8)
    for t in rig.tetras:
        t.red, t.green, t.blue, t.amber = _level(r), _level(r), _level(r), _level(r)
        t.dim, t.strobe = _level(r), _strobe(r)
    for s in rig.sticks:
        s.red, s.green, s.blue = _level(r), _level(r), _level(r)
        s.dim, s.strobe = _level(r), _strobe(r)


def configs(contract_mod) -> list:
    """Rig blocks the frames render through: the default plan and five that move bytes around."""
    base = contract_mod.defaults()["rig"]
    out = [copy.deepcopy(base)]
    short = copy.deepcopy(base)
    short["counts"] = {"bars": 1, "tetras": 3, "sticks": 0}
    out.append(short)
    flags = copy.deepcopy(base)
    for h in ("head1", "head2"):
        flags["heads"]["bar1"][h] = {"pan_invert": True, "tilt_invert": True, "pan_tilt_swap": True}
    flags["heads"]["bar2"]["swap_heads"] = True
    flags["heads"]["bar2"]["head2"]["pan_invert"] = True
    out.append(flags)
    order = copy.deepcopy(base)
    order["channels"]["gigbar"] = list(reversed(order["channels"]["gigbar"])) + ["=7"]
    order["channels"]["tetra"] = ["red", "=255", "green", "blue", "amber", "dim", "strobe", "red"]
    order["channels"]["stick"] = [c for c in order["channels"]["stick"] if c != "macro"]
    out.append(order)
    moved = copy.deepcopy(base)
    moved["addresses"]["tetra1"] = 300
    moved["addresses"]["stick4"] = 505   # runs off the universe's end: cut at slot 512
    out.append(moved)
    return out


def frames(rig_mod, contract_mod, seed: int = SEED, count: int = COUNT):
    """Every universe: `count` seeded rigs, each through every rig block in configs()."""
    r = random.Random(seed)
    cfgs = configs(contract_mod)
    for _ in range(count):
        rig = rig_mod.default_rig()
        randomize(rig, r)
        for cfg in cfgs:
            yield bytes(rig.render(cfg))


def digest(rig_mod, contract_mod, seed: int = SEED, count: int = COUNT) -> tuple[int, str]:
    h, n = hashlib.sha256(), 0
    for frame in frames(rig_mod, contract_mod, seed, count):
        h.update(frame)
        n += 1
    return n, h.hexdigest()
