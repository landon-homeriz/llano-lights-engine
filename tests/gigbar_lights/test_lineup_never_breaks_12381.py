"""Line up my lights never saves a line-up it would refuse, and a head turned the other way breaks nothing
(Llano BL #12381).

His report 2026-11-14 on 1.25.0: the app said it rejected GigBAR 2's saved line-up and fell back to its
own guess, and "once I turn a head the opposite direction everything after that gets screwed up". His
one-spot line-up at 02:20Z (all four heads on 4.03, 2.55) let the bar solve fit GigBAR 2 at 2.99 m with
its tilt turning backwards; both heads then missed their own spot by 7-10 m and the next Line up refused
the line-up it had just saved. Below: his real layout (Nov 10 line-up, Tetras renumbered) and his real
poses, exactly as his laptop reported them.
"""
import json

from tools.gigbar_lights.venue import Layout

SPOT = (4.032495007277528, 2.5478116643536537)
# (bar, head index, pan, tilt): his 02:20Z poses, from the layout his laptop saved (the anchors).
HIS_POSES = [(1, 0, 0.35294117647058826, 0.69923), (1, 1, 0.41568627450980394, 0.74402),
             (2, 0, 0.26666666666666666, 0.72638), (2, 1, 0.3215686274509804, 0.69184)]
# His layout before that line-up (Llano settings rev 75): the Nov 10 line-up that worked.
NOV10 = {"bar1": [[0.33853, 0.7999], [0.39363, 0.82284]], "bar2": [[0.28529, 0.80833], [0.32686, 0.795]]}


def his_layout() -> Layout:
    fixtures = {"bar1": {"x": 2.3, "y": 0.8, "z": 2.4}, "bar2": {"x": 5.7, "y": 0.8, "z": 2.4}}
    for bar, centers in NOV10.items():
        fixtures[bar]["cal"] = [{"center": c} for c in centers]
    for i in range(6):
        fixtures[f"tetra{i + 1}"] = {"x": 6.5 - i, "y": 1.7, "z": 0.1}
    for i, (x, y) in enumerate([(1.5, 2.5), (6.5, 2.5), (1.5, 7.5), (6.5, 7.5)]):
        fixtures[f"stick{i + 1}"] = {"x": x, "y": y, "z": 0.0}
    return Layout.from_dict({"name": "small-room-gigbars-flank-the-booth-tetra", "label": "Small room (mine)",
                             "room": {"w": 8.0, "d": 10.0, "h": 3.0}, "booth": {"x": 3.0, "y": 0.3, "w": 2.0, "d": 1.0},
                             "floor": {"x": 1.5, "y": 2.5, "w": 5.0, "d": 5.0}, "fixtures": fixtures, "preset": False})


def reversed_pose(pan: float, tilt: float) -> tuple[float, float]:
    """The same beam, the head turned the other way round: pan half a turn (540 degree pan), tilt over the top."""
    return pan + 180.0 / 540.0, 1.0 - tilt


def heads_hold(lay: Layout, poses) -> None:
    for b, m, p, t in poses:
        aim = lay.aim(b, lay.heads(b)[m], (*SPOT, 0.0), m)
        assert lay._holds(b, m, {SPOT: (p, t)}) == 1, (b, m, aim, (p, t))


def no_refusals(lay: Layout) -> None:
    assert [(b, m, lay.cal_problem(b, m)) for b in (1, 2) for m in (0, 1) if lay.cal_problem(b, m)] == []


def test_his_nov10_lineup_is_accepted():
    no_refusals(his_layout())


def test_his_one_spot_lineup_keeps_gigbar_2_usable():
    lay = his_layout()
    found = lay.converge([(b, m, p, t, SPOT) for b, m, p, t in HIS_POSES])
    heads_hold(lay, HIS_POSES)
    no_refusals(lay)
    # GigBAR 2 stays where it hangs, its tilt turning the way it did on Nov 10 (not 2.99 m, backwards).
    bar2 = lay.spots["bar2"]
    assert bar2.z == 2.4 and not any(c.tilt_invert for c in bar2.cal)
    assert all(abs(c.center[1] - n[1]) < 0.005 for c, n in zip(bar2.cal, NOV10["bar2"]))
    assert all(r["held"] for r in found["held"]) and found["disagree"] == []
    # Saved and reopened (the next Line up), nothing is refused.
    again = Layout.from_dict(json.loads(json.dumps(lay.to_dict())))
    no_refusals(again)
    heads_hold(again, HIS_POSES)


def test_a_head_turned_the_other_way_breaks_nothing():
    for k in range(4):
        poses = [(b, m, *reversed_pose(p, t)) if i == k else (b, m, p, t) for i, (b, m, p, t) in enumerate(HIS_POSES)]
        lay = his_layout()
        lay.converge([(b, m, p, t, SPOT) for b, m, p, t in poses])
        heads_hold(lay, HIS_POSES)   # every head, the reversed one too, lands on the spot
        no_refusals(lay)
        assert not any(c.tilt_invert for b in (1, 2) for c in lay.spots[f"bar{b}"].cal), k
        # ... and lines up exactly as if he had never turned it round
        ref = his_layout()
        ref.converge([(b, m, p, t, SPOT) for b, m, p, t in HIS_POSES])
        for b in (1, 2):
            for m in (0, 1):
                a = [round(v * 255) for v in lay.aim(b, lay.heads(b)[m], (4.0, 5.0, 0.0), m)]
                r = [round(v * 255) for v in ref.aim(b, ref.heads(b)[m], (4.0, 5.0, 0.0), m)]
                assert a == r, (k, b, m, a, r)


def test_a_working_head_is_never_swapped_for_one_that_misses():
    """A pose the app can't fit cleanly never replaces a line-up that worked: the head keeps it."""
    lay = his_layout()
    before = [c.center for c in lay.spots["bar2"].cal]
    # A head left pointing at the ceiling (tilt near level) while he says it's on the spot: no sane fit.
    found = lay.converge([(1, 0, *HIS_POSES[0][2:], SPOT), (1, 1, *HIS_POSES[1][2:], SPOT),
                          (2, 0, 0.27, 0.02, SPOT), (2, 1, *HIS_POSES[3][2:], SPOT)])
    no_refusals(lay)
    if 0 in found["bars"][2].get("kept", []):
        assert lay.spots["bar2"].cal[0].center == before[0]


def test_the_picture_draws_what_the_heads_are_sent():
    """His 11-14 photos: the room picture showed GigBAR 2 aiming out while the real heads did otherwise.
    The layout the 1.25.0 line-up saved (GigBAR 2 at 2.99 m, "tilt turns the other way") is saved and sent
    to every picture as the model the heads are really driven with; a layout that already agreed is unchanged."""
    lay = his_layout()
    assert Layout.from_dict(lay.to_dict()).to_dict() == lay.to_dict()
    raw = lay.to_dict()
    raw["fixtures"]["bar2"].update(z=2.99, facing=-20.8, cal=[
        {"center": [0.31314, 0.64049], "tilt_invert": True, "anchors": [[*SPOT, *HIS_POSES[2][2:]]]},
        {"center": [0.35265, 0.58451], "tilt_invert": True, "anchors": [[*SPOT, *HIS_POSES[3][2:]]]}])
    broken = Layout.from_dict(raw)
    sent = broken.to_dict()["fixtures"]["bar2"]["cal"]
    for m in (0, 1):
        used = broken.cal(2, m)
        assert (tuple(sent[m]["center"]), sent[m].get("tilt_invert", False), sent[m].get("pan_invert", False)) == \
            (used.center, used.tilt_invert, used.pan_invert)
    again = Layout.from_dict(broken.to_dict())
    for m in (0, 1):
        for p, t in ((0.3, 0.7), (0.36, 0.86), (0.25, 0.6)):
            assert again.beam_of(2, m, p, t) == broken.beam_of(2, m, p, t)
