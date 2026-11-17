"""Heads glide to the show's aim instead of jumping (his 11-09 "where is the update with the smooth
panning"): glide.HeadGlide before the DMX goes out."""
import math

from tools.gigbar_lights.glide import HeadGlide, MAX_DEG_S
from tools.gigbar_lights.rig import default_rig

DT = 1 / 40


def _run(targets, snap=False, t0=0.0):
    """Feed one head's (pan, tilt) targets at 40 Hz; return what went out."""
    rig, g, out = default_rig(), HeadGlide(), []
    for i, (p, t) in enumerate(targets):
        h = rig.bars[0].movers[0]
        h.pan, h.tilt = p, t
        g.apply(rig, t0 + i * DT, snap=snap)
        out.append((h.pan, h.tilt))
    return out


def test_a_jump_becomes_a_monotone_glide_with_bounded_steps():
    out = _run([(0.5, 0.5)] * 5 + [(0.7, 0.5)] * 40)
    pans = [p for p, _ in out]
    assert pans[5] < 0.52                          # no jump on the frame the target moved
    steps = [b - a for a, b in zip(pans, pans[1:])]
    assert all(s >= -1e-9 for s in steps)           # never backs up, never overshoots
    assert max(pans) <= 0.7 + 1e-9
    assert max(steps) <= MAX_DEG_S / 540 * DT + 1e-9
    landed = next(i for i, p in enumerate(pans) if abs(p - 0.7) < 1e-6)
    assert 0.2 <= (landed - 5) * DT <= 0.5           # about a quarter second for 108 degrees
    assert all(abs(p - 0.7) < 1e-6 for p in pans[landed:])


def test_a_sweep_tracks_within_one_dmx_step_where_it_moves_and_a_few_at_its_turns():
    # A sweep over 4 s, the kind a "sweep" move draws: well inside the limits. Where it moves
    # fast enough to run the motor it is tracked step for step; at the turns, where it slows
    # below CRAWL_STEPS, the head holds within GATE_STEPS instead of ticking (No crawling); pan within
    # PAN_GATE_STEPS, then slides (Pan in slides, 1.16.9).
    from tools.gigbar_lights.glide import CRAWL_STEPS, GATE_STEPS, PAN_GATE_STEPS
    w = math.pi / 2
    targets = [(0.5 + 0.1 * math.sin(i * DT * w), 0.6 + 0.05 * math.cos(i * DT * w)) for i in range(400)]
    out = _run(targets)
    for i, ((p, t), (tp, tt)) in list(enumerate(zip(out, targets)))[20:]:
        vp, vt = abs(0.1 * w * math.cos(i * DT * w)) * 255, abs(0.05 * w * math.sin(i * DT * w)) * 255
        # (a pan held up to PAN_GATE_STEPS through the turn needs one more frame to catch up)
        assert abs(p - tp) * 255 < (1.0 if vp > 2.5 * CRAWL_STEPS else PAN_GATE_STEPS + 1)
        assert abs(t - tt) * 255 < (1.0 if vt > 2 * CRAWL_STEPS else GATE_STEPS + 1)


def test_a_snap_glides_harder_than_a_section_change():
    jump = [(0.5, 0.5)] * 3 + [(0.7, 0.5)] * 40
    land = lambda out: next(i for i, (p, _) in enumerate(out) if abs(p - 0.7) < 1e-6)
    assert land(_run(jump, snap=True)) < land(_run(jump))


def test_line_up_and_a_stall_land_at_once():
    rig, g = default_rig(), HeadGlide()
    h = rig.bars[0].movers[0]
    g.apply(rig, 0.0)
    h.pan = 0.9
    g.apply(rig, DT, smooth=False)                  # line-up / calibrating: raw pose
    assert h.pan == 0.9
    h.pan = 0.2
    g.apply(rig, DT + 1.0)                          # the laptop stalled a second
    assert h.pan == 0.2


def test_power_up_check_puts_every_head_at_dmx_middle():
    # His 11-09 note: the heads power up facing straight ahead. "middle" sends raw 128/128 so he
    # can compare it with the power-up pose; no aim, guard or venue touches it.
    from tools.gigbar_lights import settings_contract as contract
    from tools.gigbar_lights.looks import Frame, LooksEngine
    eng, rig = LooksEngine(settings=contract.normalize({})), default_rig()
    eng.overrides.lineup = (0, "middle")
    eng.overrides.lights_on = True
    eng.render(Frame(0.0, 120.0, True), rig)
    heads = [h for bar in rig.bars for h in bar.movers]
    assert len(heads) == 4
    assert all(h.channels()[:2] == [128, 128] for h in heads)
    assert "DMX middle" in eng.mode


def test_a_slow_move_holds_then_moves_in_short_runs_instead_of_ticking():
    # His 11-09 report on 1.15.0.3: a slow pan ticked one 2-degree DMX step every few frames.
    # Now the head holds, then covers a few steps in consecutive frames, and holds again: since 1.16.9
    # a pan holds until PAN_GATE_STEPS behind, then slides (Pan in slides).
    from tools.gigbar_lights.glide import PAN_GATE_STEPS
    speed = 5 / 255                                       # 5 DMX steps a second: a slow verse glide
    targets = [(0.3 + speed * i * DT, 0.5) for i in range(400)]
    pans = [round(p * 255) for p, _ in _run(targets)]
    moves = [i for i in range(1, len(pans)) if pans[i] != pans[i - 1]]
    runs, run = [], [moves[0]]
    for i in moves[1:]:
        if i - run[-1] <= 2:
            run.append(i)
        else:
            runs.append(run)
            run = [i]
    runs.append(run)
    assert len(runs) >= 4
    assert all(len(r) >= 2 for r in runs[1:-1])           # several steps as one motion, not one tick
    assert all(abs(p - round(tp * 255)) <= PAN_GATE_STEPS + 1 for p, (tp, _) in zip(pans, targets))


def test_the_trail_reports_what_the_laptop_sends():
    import sys, types
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
    import collections
    import gigbar_app
    app = types.SimpleNamespace(running="demo", preview=types.SimpleNamespace(trail=collections.deque(
        [[1000 + 25 * i, 128, 128, 0, 0, 0, 0, 0, 0] for i in range(16)])))
    m = gigbar_app.App._motion(app)
    assert m["hz"] == 40.0 and len(m["trail"]) == 16


def test_an_open_app_asks_for_updates_again():
    # His 11-09 report: the laptop sat on 1.15.0.3 all day while 1.16.1 was out, so the heads kept
    # the old stepping. The app now re-asks while open; a check never runs mid-download.
    import sys, threading, types
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
    import gigbar_app
    calls, quit = [], threading.Event()
    states = iter(["current", "downloading", "unreachable"])

    def check():
        calls.append(app.update_state)
    app = types.SimpleNamespace(quit=quit, update_state="current", check_update=check)

    class Q:
        def wait(self, s):
            try:
                app.update_state = next(states)
                return False
            except StopIteration:
                return True
    app.quit = Q()
    gigbar_app.App.watch_updates(app, every_s=0.01)
    assert calls == ["current", "unreachable"]
