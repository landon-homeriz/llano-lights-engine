"""BL #12518: Livin' on a Prayer's chorus is a white-out he can see, hits can be a color flash, and the
Freedom Sticks in their 48CH mode chase, bounce and fill by section."""
from __future__ import annotations

import pytest

from tools.gigbar_lights import cues as cues_mod, looks, rig as rig_mod, settings_contract as contract, stick_fx
from tools.gigbar_lights.show_script import Section


def _cfg(stick_mode: str = "48ch") -> dict:
    cfg = contract.DEFAULTS["rig"]
    cfg = {**cfg, "channels": {**cfg["channels"], "stick": list(contract.STICK_MODES[stick_mode])},
           "addresses": {**cfg["addresses"], "stick1": 151, "stick2": 199, "stick3": 247, "stick4": 295}}
    return cfg


def test_the_default_rig_still_drives_the_sticks_in_8ch():
    assert contract.DEFAULTS["rig"]["channels"]["stick"] == ["dim", "red", "green", "blue", "macro", "strobe",
                                                            "program", "speed"]
    r = rig_mod.default_rig()
    r.sticks[0].red, r.sticks[0].dim = 1.0, 1.0
    u = r.render(contract.DEFAULTS["rig"])
    assert list(u[150:158]) == [255, 255, 0, 0, 0, 0, 0, 0]
    assert u[160] == 0   # stick 2 starts at 161 and is dark: nothing spills from stick 1


def test_a_48ch_rig_block_survives_the_contract_and_an_unknown_name_falls_back_to_8ch():
    doc = contract.normalize({"rig": {"channels": {"stick": list(contract.STICK_MODES["48ch"])}}})
    assert doc["rig"]["channels"]["stick"] == list(contract.STICK_MODES["48ch"])
    flipped = [f"seg{i}.{c}" for i in range(16, 0, -1) for c in ("red", "green", "blue")]
    assert contract.normalize({"rig": {"channels": {"stick": flipped}}})["rig"]["channels"]["stick"] == flipped
    bad = contract.normalize({"rig": {"channels": {"stick": ["seg1.red", "seg17.red"]}}})
    assert bad["rig"]["channels"]["stick"] == list(contract.DEFAULT_CHANNELS["stick"])


def test_a_build_fills_the_stick_bottom_to_top_and_is_full_on_its_last_beat():
    r = rig_mod.default_rig()
    for s in r.sticks:
        s.red, s.green, s.blue, s.dim = 0.0, 0.0, 1.0, 1.0
    build = Section("build", 100, 132, 0.6)
    stick_fx.apply(r, build, 100.0)
    u = r.render(_cfg())
    lit = [u[150 + 3 * i + 2] for i in range(16)]
    assert lit[0] > 0 and lit[-1] < 40            # just started: the bottom, not the top
    stick_fx.apply(r, build, 116.5)
    u = r.render(_cfg())
    lit = [u[150 + 3 * i + 2] for i in range(16)]
    assert lit[6] == 255 and lit[12] < 60        # half way up
    stick_fx.apply(r, build, 131.1)
    u = r.render(_cfg())
    assert all(u[150 + 3 * i + 2] >= 250 for i in range(16))   # full as the drop lands


def test_a_verse_bounces_a_block_and_each_stick_runs_a_beat_behind():
    m = stick_fx.masks("verse", 8.0, 0, 64, 4)
    tops = [max(range(16), key=lambda i: mk[i]) for mk in m]
    assert tops[0] < 4                         # bar start: stick 1's block at the bottom
    assert tops[1] != tops[0]                  # stick 2 a beat behind it: somewhere else
    half = stick_fx.masks("verse", 10.0, 0, 64, 1)[0]
    assert max(range(16), key=lambda i: half[i]) > 11   # half a bar on: at the top


def test_the_prayer_white_out_lights_the_whole_rig_white_with_the_strobes():
    r = rig_mod.default_rig()
    for s in r.sticks:
        s.red, s.dim = 1.0, 0.6
    stick_fx.apply(r, Section("verse", 0, 64, 0.5), 3.0)
    cs = ({"at": 96.9, "do": "hit", "size": 2},)
    cues_mod.apply_hit(r, *cues_mod.hit_at(cs, 97.2))
    u = r.render(_cfg())
    assert all(u[150 + i] == 255 for i in range(48))                  # stick 1: every section white
    assert all(r.bars[0].pars[p].red == 1.0 and r.bars[0].pars[p].blue == 1.0 for p in (0, 1))
    assert r.bars[0].strobe_white == 1.0 and r.bars[0].strobe_speed >= 0.9
    assert all(m.dim == 1.0 and m.color == 0 for b in r.bars for m in b.movers)


def test_a_color_hit_flashes_the_rig_in_its_color():
    r = rig_mod.default_rig()
    cs = ({"at": 5.0, "do": "hit", "size": 1, "color": "#ff0000"},)
    level, burst, color = cues_mod.hit_at(cs, 5.1)
    assert (level, color) == (1.0, "#ff0000")
    cues_mod.apply_hit(r, level, burst, color)
    t = r.tetras[0]
    assert (t.red, t.green, t.blue, t.dim) == (1.0, 0.0, 0.0, 1.0)
    assert r.bars[0].strobe_white == 0.0    # a color flash leaves the white strobes alone


def test_slow_dances_hold_the_heads_still_unless_the_glide_is_asked_for(monkeypatch):
    cfg = {"sections": {"verse": {"movers": 1.0, "move": {"shape": "sweep"}}}}
    assert looks.gentle_settings(cfg)["sections"]["verse"]["move"]["shape"] == "hold"
    monkeypatch.setenv("LLANO_LIGHTS_GENTLE_GLIDE", "1")
    assert looks.gentle_settings(cfg)["sections"]["verse"]["move"]["shape"] == "glide"


def test_stick_fx_off_switch(monkeypatch):
    monkeypatch.setenv("LLANO_LIGHTS_STICK_FX", "0")
    r = rig_mod.default_rig()
    stick_fx.apply(r, Section("build", 0, 32, 0.6), 4.0)
    assert all(s.mask is None for s in r.sticks)


def test_a_build_lifts_a_dim_stick_so_the_fill_reads():
    r = rig_mod.default_rig()
    for s in r.sticks:
        s.blue, s.dim = 1.0, 0.05                  # the build look dims the wash between its pulses
    stick_fx.apply(r, Section("build", 0, 32, 0.6), 0.0)
    assert r.sticks[0].dim == pytest.approx(stick_fx.BUILD_FLOOR + (1 - stick_fx.BUILD_FLOOR) / 32)
    stick_fx.apply(r, Section("build", 0, 32, 0.6), 31.0)
    assert r.sticks[0].dim == pytest.approx(1.0)


def test_a_stick_mode_name_switches_the_mode_and_a_mixed_list_is_refused():
    def stick(v):
        return contract.normalize({"rig": {"channels": {"stick": v}}})["rig"]["channels"]["stick"]
    assert stick("48ch") == list(contract.STICK_MODES["48ch"])
    assert stick(" 50CH ") == list(contract.STICK_MODES["50ch"])
    assert stick("8ch") == list(contract.DEFAULT_CHANNELS["stick"])
    assert stick("49ch") == list(contract.DEFAULT_CHANNELS["stick"])
    # one stick is in one mode: 8CH whole-stick names never mix with the 48CH section names
    assert stick(["seg1.red", "seg1.green", "seg1.blue", "macro"]) == list(contract.DEFAULT_CHANNELS["stick"])
    assert stick(["seg1.red", "red"]) == list(contract.DEFAULT_CHANNELS["stick"])
    fifty = [*(f"seg{i}.{c}" for i in range(1, 17) for c in ("red", "green", "blue")), "strobe", "dim"]
    assert stick(fifty) == fifty                     # dim and strobe belong to 50CH too
    doc, _ = contract.apply_ops(contract.normalize({}), [{"path": "rig.channels.stick", "value": "48ch"}])
    assert doc["rig"]["channels"]["stick"] == list(contract.STICK_MODES["48ch"])
