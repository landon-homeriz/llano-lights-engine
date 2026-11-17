"""The Freedom Sticks go out bright (Llano PM #23790, his 11-15 "the sticks look really dim").

At master 1.0 and wash 1.0 the looks wrote the sticks' dimmer byte at 50 to 140 of 255, under the
Tetras in every section. Every look's own stick level now leaves raised by looks.STICK_LIFT, so a
verse is about 189 and the slow-dance look about 132 (its wash is 0.7); dark stays dark, full stays
full, and the wash, drop intensity, master, the soft-wash cap and the 8-channel order still hold.
"""
from tools.gigbar_lights import looks, settings_contract as contract
from tools.gigbar_lights.looks import Frame, LooksEngine
from tools.gigbar_lights.rig import default_rig
from tools.gigbar_lights.show_script import Section, ShowScript

SONG = ShowScript([Section("intro", 0, 32, 0.2), Section("verse", 32, 96, 0.5),
                   Section("build", 96, 128, 0.6), Section("drop", 128, 192, 0.9),
                   Section("main", 192, 256, 0.9), Section("outro", 256, 288, 0.2)])
STICK_DIM = [150 + 10 * k for k in range(4)]     # slot index of stick1..stick4 ch1 (addresses 151..181)
TETRA_DIM = [80 + 10 * k + 4 for k in range(6)]


def _engine(look="house", master=1.0):
    base = contract.normalize({})
    base["master"] = master
    play = None if look == "house" else contract.look_style(look, base["styles"], base, {})
    return base, LooksEngine(settings=base, isolated=True, play=play)


def _bytes(base, eng, beat, **kw):
    sec, nxt = SONG.at(beat)
    rig = default_rig()
    eng.render(Frame(beat, 124.0, True, level=0.7, section=sec, next_section=nxt, track_key=3, **kw), rig)
    return rig.render(base["rig"])


def _avg(slots, base, eng, lo, hi):
    vals = [_bytes(base, eng, b / 4)[s] for b in range(lo * 4, hi * 4) for s in slots]
    return sum(vals) / len(vals)


def test_a_verse_sends_the_sticks_near_three_quarters_not_half():
    base, eng = _engine()
    u = _bytes(base, eng, 40.0)
    assert all(u[s] >= 185 for s in STICK_DIM), [u[s] for s in STICK_DIM]   # was 140


def test_every_wedding_look_keeps_the_sticks_at_or_above_the_tetras():
    for look in ("house", "warm-up", "groove", "peak", "sing-along", "slow-dance"):
        base, eng = _engine(look)
        for lo, hi in ((32, 96), (128, 192)):   # verse, drop
            sticks, tetras = _avg(STICK_DIM, base, eng, lo, hi), _avg(TETRA_DIM, base, eng, lo, hi)
            assert sticks >= 115 and sticks > tetras, (look, lo, sticks, tetras)


def test_slow_dance_sticks_are_soft_but_seen():
    base, eng = _engine("slow-dance")
    u = _bytes(base, eng, 40.0)
    assert all(125 <= u[s] <= 140 for s in STICK_DIM), [u[s] for s in STICK_DIM]   # was 98


def test_dark_stays_dark_and_full_stays_full():
    base, eng = _engine()
    eng.overrides.blackout = True
    assert all(_bytes(base, eng, 40.0)[s] == 0 for s in STICK_DIM)
    eng.overrides.blackout = False
    eng.overrides.scene = "whiteout"
    u = _bytes(base, eng, 40.0)
    assert all(u[s] == 255 for s in STICK_DIM)
    assert all(u[s + 1] == u[s + 2] == u[s + 3] == 255 for s in STICK_DIM)   # R, G, B


def test_master_still_scales_the_lifted_level():
    base, eng = _engine(master=0.5)
    u = _bytes(base, eng, 40.0)
    assert all(90 <= u[s] <= 100 for s in STICK_DIM), [u[s] for s in STICK_DIM]   # 0.74 * 0.5


def test_a_drop_still_pulses_on_the_sticks():
    base, eng = _engine()
    vals = [_bytes(base, eng, 128 + b / 8)[STICK_DIM[0]] for b in range(64)]
    assert max(vals) == 255 and min(vals) < 200


def test_the_soft_wash_cap_still_holds_over_the_lift():
    rig = default_rig()
    for s in rig.sticks:
        s.dim = 1.0
    looks.soften(rig)
    assert all(s.dim <= looks.SOFT_WASH for s in rig.sticks)


def test_eight_channel_byte_order_is_unchanged():
    base, eng = _engine()
    u = _bytes(base, eng, 40.0)
    for s in STICK_DIM:   # dim, R, G, B, then macro 0, strobe 0, program 0, speed 0
        assert u[s] > 0 and max(u[s + 1:s + 4]) == 255 and u[s + 4:s + 8] == bytes(4)


def test_lift_off_puts_back_the_old_levels(monkeypatch):
    monkeypatch.setattr(looks, "STICK_LIFT", 1.0)
    base, eng = _engine()
    assert all(_bytes(base, eng, 40.0)[s] == 140 for s in STICK_DIM)


def test_the_section_wash_still_halves_the_sticks():
    base, eng = _engine()
    full = _bytes(base, eng, 40.0)[STICK_DIM[0]]
    base["sections"]["verse"] = {**base["sections"]["verse"], "wash": 0.5}
    eng2 = LooksEngine(settings=base, isolated=True)
    assert abs(_bytes(base, eng2, 40.0)[STICK_DIM[0]] - full / 2) <= 1


def test_the_strobe_key_at_half_wash_still_hits_full():
    base, _ = _engine()
    base["sections"]["verse"] = {**base["sections"]["verse"], "wash": 0.5}
    eng = LooksEngine(settings=base, isolated=True)
    eng.overrides.strobe = True
    assert all(_bytes(base, eng, 40.0)[s] == 255 for s in STICK_DIM)


def test_the_laptop_switch_puts_back_the_old_levels(monkeypatch):
    monkeypatch.setenv("LLANO_LIGHTS_STICK_LIFT", "0")
    base, eng = _engine()
    assert all(_bytes(base, eng, 40.0)[s] == 140 for s in STICK_DIM)
