"""1.16.9: the 11-10 real-lights report on 1.16.8: inner heads 2 and 3 were still jittery in some parts
of the show and smooth in others; outer heads 1 and 4 were always fluid.

On his saved layout (his_layout_1169.json, the room he runs), a slow look turns the inner heads farther
in PAN than the outer ones (his show's booth-to-crowd glide: 29 pan steps against 17), and a GigBAR pan
step is 2.1 degrees (tilt 0.7), so a slow pan can only hop. In 1.16.8 the inner heads hopped about
twice as often as the outer heads (40 pan hops a minute against 26-32), and a tilt hop dragged their
pan along 2 steps at a time. Pan in slides (glide.py): a slow pan holds until PAN_GATE_STEPS behind,
then slides there, and only another pan's slide takes it along, so every head pans on the same frames,
the same number of times. Figures keep their shape; section changes keep Arrive together.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.gigbar_lights.glide import HeadGlide
from tools.gigbar_lights.looks import FIGURES, Frame, LooksEngine
from tools.gigbar_lights.rig import default_rig
from tools.gigbar_lights.venue import Layout


@pytest.fixture(autouse=True)
def _slow_legs(monkeypatch):
    """These pin how the glide moves a head that crawls (No crawling, Together, Arrive together, Pan in slides),
    which still governs every move under its crawl line. Fluid travel (Llano BL #12400) now runs a slow glide or
    sweep above that line, so the slow legs these build are made with it off; test_heads_face_and_flow_12400.py
    pins the fluid legs."""
    monkeypatch.setenv("LLANO_LIGHTS_FLUID_TRAVEL", "0")

HIS = Layout.from_dict(json.loads((Path(__file__).parent / "his_layout_1169.json").read_text()))
INNER, OUTER = ((0, 1), (1, 0)), ((0, 0), (1, 1))   # (bar, head): heads 3 and 2, heads 4 and 1 from the floor


def _pans(mv: dict, secs: float = 64.0, bpm: float = 124.0) -> dict:
    """One move on his layout through the looks engine and the glide at 40 Hz: (bar, head) -> pan bytes."""
    eng, rig, g = LooksEngine(), default_rig(), HeadGlide()
    eng.apply_venue(HIS)
    out = {k: [] for k in (*INNER, *OUTER)}
    for i in range(int(secs * 40)):
        now = i / 40
        eng._move(Frame(beat=now * bpm / 60, bpm=bpm, playing=True), rig, mv, now / secs)
        g.apply(rig, now, snap=mv["shape"] == "snap", figure=mv["shape"] in FIGURES)
        for b, m in out:
            out[(b, m)].append(round(rig.bars[b].movers[m].pan * 255))
    return {k: v[40:] for k, v in out.items()}


def _starts(v: list) -> list:
    """Frames a pan move starts (after at least 3 still frames)."""
    ch = [i for i in range(1, len(v)) if v[i] != v[i - 1]]
    return [c for j, c in enumerate(ch) if j == 0 or c - ch[j - 1] > 3]


SLOW = {   # his saved show plays the first in every section; the rest are the house show's slow looks
    "his glide booth>crowd": {"shape": "glide", "from": "booth", "to": "crowd", "size": 0.5, "beats": 32, "spread": "mirror"},
    "verse glide crowd>fan": {"shape": "glide", "from": "crowd", "to": "fan", "size": 0.5, "beats": 16, "spread": "parallel"},
    "sweep booth>crowd": {"shape": "sweep", "from": "booth", "to": "crowd", "size": 0.5, "beats": 32, "spread": "mirror"},
    "build rise": {"shape": "rise", "from": "booth", "to": "crowd", "size": 0.5, "beats": 32, "spread": "parallel"},
    "spotlight glide": {"shape": "glide", "from": "booth", "to": "crowd", "size": 0.5, "beats": 32, "spread": "spotlight"},
}


@pytest.mark.parametrize("look", list(SLOW))
def test_inner_heads_pan_no_more_often_than_outer_and_on_the_same_frames(look):
    pans = _pans(SLOW[look])
    outer = [_starts(pans[k]) for k in OUTER]
    for k in INNER:
        inner = _starts(pans[k])
        assert len(inner) <= max(len(o) for o in outer), (look, k, len(inner), [len(o) for o in outer])
        if any(outer):   # every inner pan move starts with an outer head's (within a frame)
            lone = [s for s in inner if not any(abs(s - t) <= 1 for o in outer for t in o)]
            assert not lone, (look, k, lone[:5])


def test_the_kill_switch_brings_back_1168s_pan_hops(monkeypatch):
    monkeypatch.setenv("LLANO_LIGHTS_PAN_SLIDES", "0")
    pans = _pans(SLOW["his glide booth>crowd"])
    assert len(_starts(pans[INNER[0]])) > max(len(_starts(pans[k])) for k in OUTER)   # the report's asymmetry


@pytest.mark.parametrize("shape", FIGURES)
def test_a_figure_keeps_its_shape(monkeypatch, shape):
    mv = {"shape": shape, "from": "crowd", "to": "fan", "size": 0.5, "beats": 16, "spread": "mirror"}
    new = _pans(mv, secs=20)
    monkeypatch.setenv("LLANO_LIGHTS_PAN_SLIDES", "0")
    assert _pans(mv, secs=20) == new


def test_the_show_tells_the_glide_when_a_figure_plays(monkeypatch):
    from tools.gigbar_lights.show import Show
    show, seen = Show(analyze=False), []
    monkeypatch.setattr(show.glide, "apply", lambda rig, now, **kw: seen.append(kw["figure"]))
    for shape in ("circle", "glide"):
        monkeypatch.setattr(show.looks, "render", lambda f, rig, s=shape: (setattr(show.looks, "move_shape", s), rig)[1])
        show.render(1000.0)
    assert seen == [True, False]


def test_a_held_arrow_in_line_up_keeps_its_pace():
    # Line up my lights (calm): a pan moving slowly under a held arrow trails by GATE_STEPS at most,
    # never the slide gate.
    from tools.gigbar_lights.glide import GATE_STEPS
    rig, g = default_rig(), HeadGlide()
    h = rig.bars[0].movers[0]
    for i in range(200):
        h.pan, h.tilt = 0.3 + 4 / 255 * i / 40, 0.5
        g.apply(rig, i / 40, calm=True)
        if i > 40:
            assert abs(h.pan - (0.3 + 4 / 255 * i / 40)) * 255 <= GATE_STEPS + 1
