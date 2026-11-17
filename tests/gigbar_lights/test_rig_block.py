"""The rig block (Llano PM #22425): addresses, channel maps, head order, pan/tilt invert and swap,
and calibration defaults come from the synced settings, and the defaults are rig.py 1.12.3 exactly."""
import copy

from tools.gigbar_lights import looks, rig, settings_contract as contract, show_settings, venue


def _busy_rig():
    r = rig.default_rig()
    for i, b in enumerate(r.bars):
        b.pars[0].red, b.pars[1].blue, b.laser = 0.4, 0.9, "both"
        b.movers[0].pan, b.movers[0].tilt, b.movers[0].dim = 0.2 + i * 0.1, 0.7, 1.0
        b.movers[1].pan, b.movers[1].tilt, b.movers[1].gobo = 0.9, 0.3, 3
    for t in r.tetras:
        t.red, t.amber, t.dim = 1.0, 0.5, 0.8
    for s in r.sticks:
        s.green, s.dim = 0.6, 1.0
    return r


def _old_render(r) -> bytearray:
    """How 1.12.3 laid out the universe: each fixture's channels() at its own address."""
    u = bytearray(512)
    for fx in r.fixtures:
        ch = fx.channels()
        u[fx.address - 1:fx.address - 1 + len(ch)] = bytes(ch)
    return u


def _cfg():
    return copy.deepcopy(contract.defaults()["rig"])


def test_default_rig_block_renders_the_bytes_1_12_3_sent():
    r = _busy_rig()
    assert r.render() == _old_render(r)
    assert r.render(_cfg()) == _old_render(r)


def test_default_addresses_and_channel_counts_match_the_fixture_classes():
    cfg = _cfg()
    r = rig.default_rig()
    for fid, fx in zip(contract.FIXTURES, r.fixtures):
        assert cfg["addresses"][fid] == fx.address
        assert len(cfg["channels"][fx.kind]) == fx.footprint == len(contract.CHANNEL_NAMES[fx.kind])


def test_an_address_move_lands_the_bar_at_its_new_start():
    r, cfg = _busy_rig(), _cfg()
    cfg["addresses"]["bar2"] = 201
    u = r.render(cfg)
    assert u[200:235] == bytes(r.bars[1].channels())
    assert u[40:75] == bytes(35)


def test_a_channel_map_reorders_by_name_and_holds_fixed_bytes():
    r, cfg = _busy_rig(), _cfg()
    cfg["channels"]["tetra"] = ["dim", "red", "green", "blue", "amber", "strobe", "=7"]
    u = r.render(cfg)
    t = r.tetras[0].channels()   # red, green, blue, amber, dim, strobe
    assert list(u[80:87]) == [t[4], t[0], t[1], t[2], t[3], t[5], 7]


def test_swap_heads_sends_the_engines_head_1_on_head_2s_channels():
    r, cfg = _busy_rig(), _cfg()
    cfg["heads"]["bar1"]["swap_heads"] = True
    u, old = r.render(cfg), _old_render(r)
    assert u[23:29] == old[29:35] and u[29:35] == old[23:29]
    assert u[40:75] == old[40:75]   # the other bar is untouched


def test_invert_and_swap_apply_to_the_physical_head_bytes():
    r, cfg = _busy_rig(), _cfg()
    cfg["heads"]["bar1"]["head1"].update(pan_invert=True, tilt_invert=True)
    cfg["heads"]["bar2"]["head2"]["pan_tilt_swap"] = True
    u, old = r.render(cfg), _old_render(r)
    assert u[23] == 255 - old[23] and u[24] == 255 - old[24]
    assert (u[69], u[70]) == (old[70], old[69])   # bar 2 head 2: slots 70 (pan) and 71 (tilt)


def test_a_bad_channel_list_keeps_the_known_order():
    doc = contract.normalize({"rig": {"channels": {"tetra": ["red", "laser.color"]}}})
    assert doc["rig"]["channels"]["tetra"] == list(contract.CHANNEL_NAMES["tetra"])


def test_rig_paths_are_ops_and_saved_rigs_delete():
    doc, _ = contract.apply_ops(contract.defaults(), [
        {"path": "rig.heads.bar1", "value": {"swap_heads": True}},
        {"path": "rig.saved.small-gig", "value": {"bars": 1, "tetras": 3, "sticks": 0}},
        {"path": "rig.counts.bars", "value": 1}])
    assert doc["rig"]["heads"]["bar1"]["swap_heads"] is True
    assert doc["rig"]["saved"] == {"small-gig": {"bars": 1, "tetras": 3, "sticks": 0}}
    assert doc["rig"]["counts"] == {"bars": 1, "tetras": 6, "sticks": 4}
    doc, _ = contract.apply_ops(doc, [{"path": "rig.saved.small-gig", "value": None}])
    assert doc["rig"]["saved"] == {}


def test_settings_from_llano_change_the_render_on_the_next_frame():
    r = _busy_rig()
    before = r.render()
    doc = contract.defaults()
    doc["rig"]["heads"]["bar2"]["swap_heads"] = True
    try:
        show_settings.set_current(doc)
        after = r.render()
        assert after[63:69] == before[69:75]
    finally:
        show_settings.set_current(contract.defaults())


def test_calibration_defaults_reach_the_venue_and_the_looks():
    doc = contract.defaults()
    doc["rig"]["calibration"] = {"pan_range": 600.0, "tilt_range": 200.0, "tilt_down": 0.46}
    try:
        show_settings.set_current(doc)
        assert (venue.PAN_RANGE, venue.TILT_RANGE, venue.TILT_DOWN_AT_CENTER) == (600.0, 200.0, 0.46)
        assert looks.venue.TILT_DOWN_AT_CENTER == 0.46
        assert venue.HeadCal().pan_range == 600.0
    finally:
        show_settings.set_current(contract.defaults())
    assert (venue.PAN_RANGE, venue.TILT_RANGE, venue.TILT_DOWN_AT_CENTER) == (540.0, 180.0, 0.5)
