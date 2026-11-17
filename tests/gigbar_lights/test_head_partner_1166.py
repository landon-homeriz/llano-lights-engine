"""1.16.6: his 11-10 report on real lights (right GigBAR: head 3 its left head, head 4 its right head).
He re-set head 4's center and it lined up with the others, but in pan moves it went the opposite way
to head 3. A center measures where a head points, not which way it turns, and head 4 still carried
`pan_invert` from a center saved turned round. A bar's two heads are one motor type in one housing,
so a head with no measured dots now turns the way its bar partner does (venue `partner_cal`).
"""
from __future__ import annotations

from tools.gigbar_lights import demo_songs
from tools.gigbar_lights.show import Show
from tools.gigbar_lights.venue import Layout, LayoutStore


def _his(tmp_path, head4: dict | None = None, head3: dict | None = None, bar1: tuple = ({}, {})) -> Layout:
    """The default room with his 11-10 centers: head 4 (bar 2, head 0) still pan_invert from before."""
    d = LayoutStore(tmp_path / "p").current().to_dict()
    centers = {("bar1", 0): [0.34098, 0.84686], ("bar1", 1): [0.38431, 0.86676],
               ("bar2", 0): [0.2902, 0.81569], ("bar2", 1): [0.32245, 0.86382]}
    extra = {("bar1", 0): bar1[0], ("bar1", 1): bar1[1],
             ("bar2", 0): {"pan_invert": True} if head4 is None else head4, ("bar2", 1): head3 or {}}
    for fid in ("bar1", "bar2"):
        d["fixtures"][fid]["cal"] = [{"center": centers[(fid, m)], **extra[(fid, m)]} for m in (0, 1)]
    return Layout.from_dict(d)


def test_a_center_only_head_turns_the_way_its_bar_partner_does(tmp_path):
    lay = _his(tmp_path)
    assert [lay.cal(b, m).pan_invert for b in (1, 2) for m in (0, 1)] == [False] * 4
    assert lay.cal(2, 0).center == (0.2902, 0.81569)                      # where it points is kept
    assert "pan_invert" not in lay.to_dict()["fixtures"]["bar2"]["cal"][0]  # and the fix is what saves


def test_heads_3_and_4_pan_the_same_way_in_demo(tmp_path):
    lay = _his(tmp_path)
    same = opposite = 0
    for song in demo_songs.load():
        show = Show(analyze=False)
        show.set_venue(lay)
        feed = demo_songs.SongFeed(show, song, None)
        now, due, prev = 1000.0, 1000.0, None
        while now < 1040.0:
            feed(now)
            if now >= due:
                show.render(now)
                due += 0.025
                pic = show.glide.picture()
                cur = (pic[(1, 1)][0] * 255, pic[(1, 0)][0] * 255)   # raw pan: the same motor, the same sense
                if prev:
                    d3, d4 = cur[0] - prev[0], cur[1] - prev[1]
                    if abs(d3) > 0.2 and abs(d4) > 0.2:
                        same += d3 * d4 > 0
                        opposite += d3 * d4 < 0
                prev = cur
            now += 512 / 44100
    assert same > 5 and opposite == 0, (same, opposite)


def test_a_head_with_dots_keeps_its_own_turn_and_its_partner_follows_it(tmp_path):
    lay = _his(tmp_path, head4={"pan_invert": True, "points": {"near": [0.31, 0.85]}})
    assert lay.cal(2, 0).pan_invert is True    # the fit measured head 4's turn
    assert lay.cal(2, 1).pan_invert is True    # so center-only head 3 turns its way


def test_with_nothing_to_go_on_each_head_keeps_its_own(tmp_path):
    # The other bar disagrees with itself: no way to tell which of bar 2's heads is right.
    lay = _his(tmp_path, bar1=({}, {"pan_invert": True}))
    assert lay.cal(2, 0).pan_invert is True and lay.cal(2, 1).pan_invert is False


def test_the_other_bar_settles_which_partner_is_wrong(tmp_path):
    # Bar 1 both inverted (hung the other way, say): bar 2's lone inverted head is the right one.
    lay = _his(tmp_path, bar1=({"pan_invert": True}, {"pan_invert": True}))
    assert lay.cal(2, 0).pan_invert is True and lay.cal(2, 1).pan_invert is True
