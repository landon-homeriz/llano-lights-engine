"""The shared fixture library (Llano BL #12136): lights read from QLC+ and the Open Fixture Library,
an override layer for what they lack, a rig of (profile, mode, address, role), and today's 12 lights
driven through it byte for byte.

The gate: rig_states.py's seeded light states (every attribute, its edges, five rig blocks) render
exactly the frames the released 1.19.3 (a788ed5) and 1.37.0 (e2f22e4) rendered with their own
hand-written rig.py, pinned below. Re-pin only with an old version's own output, never this code's.
"""
import hashlib
import json
import math
import random
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rig_states  # noqa: E402

from tools.gigbar_lights import fixture_profiles as fp  # noqa: E402
from tools.gigbar_lights import rig, settings_contract  # noqa: E402
from tools.gigbar_lights.settings_contract import CHANNEL_NAMES  # noqa: E402

LIB = HERE / "fixture_library"
OFL_TETRA_BAR = LIB / "ofl" / "venue" / "tetra-bar.json"
OFL_GIGBAR_2 = LIB / "ofl" / "chauvet-dj" / "gigbar-2.json"
QLC_GIGBAR_2 = LIB / "qlcplus" / "Chauvet-GigBAR-2.qxf"

# rig_states.digest(rig, settings_contract) as rendered by the released code's own rig.py, from
# `git archive a788ed5 tools` (1.19.3) and `git archive e2f22e4 tools` (1.37.0): the same digest.
RELEASED_FRAMES = (2000, "9b736b52ed7e643cfce8669b7e24fb81f237837ec13d089c5f8bd1900396ece7")

# The bundled QLC+ files are unmodified library copies (fixtures/qlcplus/NOTICE.md): what the app
# needs that they lack lives in overrides.json, so a fix never edits these.
# sha256 of each file as QLC+ commit 752c962 has it (and as qlcplus master had it on 2026-11-17).
LIBRARY_SHA256 = {
    "Chauvet-GigBAR-Move.qxf": "7bc5a619d9d62bce076228aedabf75aa80fd4599ca965b61015132d341e210c7",
    "Venue-Tetra-6.qxf": "d1bab5bd4725d571fe992d9dbd3e87ddf541295a234c42cc8f11364f30097fee",
    "Chauvet-Freedom-Stick.qxf": "1309d2ccd6bb4c29f10578f77fc11f95845860bd0ecba351706a4becf28b3251",
}


@pytest.fixture
def fresh_library():
    """Cached profiles cleared before and after, so a test that moves the library can't leak."""
    def clear():
        fp.builtin_profile.cache_clear()
        fp.builtin_mode.cache_clear()
        fp._overrides_doc.cache_clear()
        rig._PROFILE_MODES.clear()
    clear()
    yield
    clear()


# --- today's 12 lights, byte for byte -------------------------------------------------------------

def test_todays_rig_renders_the_released_frames_through_the_library(monkeypatch):
    monkeypatch.delenv("LLANO_LIGHTS_PROFILES", raising=False)
    calls = []
    real = fp.encode
    monkeypatch.setattr(fp, "encode", lambda mode, state: calls.append(1) or real(mode, state))
    assert rig_states.digest(rig, settings_contract) == RELEASED_FRAMES
    assert calls, "the frames came from the hand-written bytes, not the fixture library"


def test_the_kill_switch_sends_the_hand_written_bytes(monkeypatch):
    monkeypatch.setenv("LLANO_LIGHTS_PROFILES", "0")

    def boom(*_a, **_k):
        raise AssertionError("LLANO_LIGHTS_PROFILES=0 still went through the library")
    monkeypatch.setattr(fp, "encode", boom)
    assert rig_states.digest(rig, settings_contract) == RELEASED_FRAMES


@pytest.mark.parametrize("value", ["0", "off", "false", "no", " OFF "])
def test_every_off_word_turns_profiles_off(monkeypatch, value):
    monkeypatch.setenv("LLANO_LIGHTS_PROFILES", value)
    assert not fp.enabled()


def test_every_light_encodes_exactly_like_its_hand_written_channels():
    """Per light, far more states than the pinned frames: the library's bytes == channels()."""
    r = random.Random(20261117)
    for _ in range(1500):
        fresh = rig.default_rig()
        rig_states.randomize(fresh, r)
        for fx in (fresh.bars[0], fresh.tetras[0], fresh.sticks[0]):
            want = dict(zip(CHANNEL_NAMES[fx.kind], fx.channels()))
            assert fp.encode(rig.profile_mode(fx.kind), fx.attributes()) == want, fx.kind


@pytest.mark.parametrize("program", [0, 1, 5, 9, 10, 11, -3, 2.9])
@pytest.mark.parametrize("white", [0.0, 1e-9, 0.002, 0.5])
@pytest.mark.parametrize("uv", [0.0, 1e-9, 0.002, 0.7])
def test_the_bar_strobes_program_white_and_uv_rules(program, white, uv):
    """Ch20-22's rules (white wins over UV, 'All strobing' under a level with no program) in every
    combination, including levels too small to make a byte."""
    bar = rig.GigBarMove("b", 1, strobe_program=program, strobe_white=white, strobe_uv=uv)
    want = dict(zip(CHANNEL_NAMES["gigbar"], bar.channels()))
    assert fp.encode(rig.profile_mode("gigbar"), bar.attributes()) == want


def test_the_library_modes_name_the_rig_blocks_channels():
    for kind in ("gigbar", "tetra", "stick"):
        assert rig.profile_mode(kind).ids == CHANNEL_NAMES[kind]


def test_a_library_that_will_not_load_sends_the_hand_written_bytes(monkeypatch, tmp_path, fresh_library):
    monkeypatch.delenv("LLANO_LIGHTS_PROFILES", raising=False)
    monkeypatch.setattr(fp, "QLC_DIR", tmp_path)   # no .qxf files there
    assert rig.profile_mode("gigbar") is None
    assert rig_states.digest(rig, settings_contract) == RELEASED_FRAMES


def test_an_override_that_no_longer_fits_its_library_sends_the_hand_written_bytes(monkeypatch, tmp_path,
                                                                                  fresh_library):
    doc = json.loads(fp.OVERRIDES_FILE.read_text())
    doc["venue/tetra-6"]["modes"]["6 Channel"]["channels"]["Strobe Speed"] = {"hold": 0}
    bad = tmp_path / "overrides.json"
    bad.write_text(json.dumps(doc))
    monkeypatch.setattr(fp, "OVERRIDES_FILE", bad)
    assert rig.profile_mode("tetra") is None
    assert rig.profile_mode("gigbar") is not None   # one bad light never takes the others down
    assert rig_states.digest(rig, settings_contract) == RELEASED_FRAMES


def test_the_bundled_library_files_are_unmodified_copies():
    notice = (fp.QLC_DIR / "NOTICE.md").read_text()
    assert "Apache License" in notice and (fp.QLC_DIR / "LICENSE-APACHE-2.0.txt").is_file()
    for name, _mode in fp.BUILTIN.values():
        assert name in notice
        got = hashlib.sha256((fp.QLC_DIR / name).read_bytes()).hexdigest()
        assert got == LIBRARY_SHA256[name], f"{name} is not the library's copy; put app changes in overrides.json"


def test_todays_rig_as_data_renders_like_the_rig():
    """rig.profile_rig(): today's 12 lights as (profile, mode, address, role), state read live."""
    r = random.Random(7)
    cfg = settings_contract.defaults()["rig"]
    for _ in range(200):
        live = rig.default_rig()
        rig_states.randomize(live, r)
        assert rig.profile_rig(live).render() == live.render(cfg)
    pr = rig.profile_rig()
    assert pr.problems() == []
    assert [fx.address for fx in pr.fixtures] == [1, 41, 81, 91, 101, 111, 121, 131, 151, 161, 171, 181]


# --- reading QLC+ ---------------------------------------------------------------------------------

def test_qlcplus_tetra_6_reads_straight_from_the_library():
    p = fp.load_qxf(fp.QLC_DIR / "Venue-Tetra-6.qxf")
    assert (p.manufacturer, p.model, p.library, p.license) == ("Venue", "Tetra 6", "qlcplus", "Apache-2.0")
    assert list(p.modes) == ["3 Channel", "4 Channel", "5 Channel", "6 Channel"]
    assert p.mode("6 Channel").ids == ("red", "green", "blue", "amber", "dim", "strobe")
    five = p.mode("5ch")   # loose name: the only mode with 5 channels
    assert five.ids[-1] == "dimmer_strobe"
    # Dimmer/Strobe shares one channel: strobe 128-227 above 0, else the dimmer's 0-127
    assert fp.frame(five, {"dim": 1.0}) == [0, 0, 0, 0, 127]
    assert fp.frame(five, {"dim": 1.0, "strobe": 0.5}) == [0, 0, 0, 0, 178]
    with pytest.raises(KeyError, match="has no mode"):
        p.mode("12 Channel")


def test_qlcplus_heads_become_parts():
    """The Freedom Stick's 50 Channel mode lists 16 pixel heads: each is its own part."""
    p = fp.load_qxf(fp.QLC_DIR / "Chauvet-Freedom-Stick.qxf")
    m = p.mode("50 Channel")
    assert m.footprint == 50
    assert m.ids[:3] == ("head1.red", "head1.green", "head1.blue")
    assert m.ids[45:48] == ("head16.red", "head16.green", "head16.blue")
    assert m.ids[48:] == ("strobe", "dim")
    out = fp.frame(m, {"head16.blue": 1.0, "dim": 0.5})
    assert out[47] == 255 and out[49] == 128 and sum(out) == 255 + 128


def test_qlcplus_gigbar_bands_come_from_the_library_not_the_app():
    """What the raw library already knows (no override): the par shutter's two bands, the derby
    strobe band, the rotation's two directions."""
    m = fp.load_qxf(fp.QLC_DIR / "Chauvet-GigBAR-Move.qxf", table={}).mode("35-channel")
    ch = {c.id: c for c in m.channels}
    shutter = ch["par1.shutter"].functions
    assert [(f.attr, f.lo, f.hi, f.positive) for f in shutter] == [("strobe", 128, 239, True), ("dim", 0, 127, False)]
    assert [(f.kind, f.lo, f.hi, f.neg_lo, f.neg_hi) for f in ch["derby1.rotate"].functions] == [
        ("bipolar", 5, 127, 134, 255)]
    assert ch["derby1.strobe"].functions[0].lo == 10 and ch["derby1.strobe"].functions[0].hi == 239


def test_a_file_that_is_not_a_fixture_is_refused(tmp_path):
    f = tmp_path / "x.qxf"
    f.write_text("<?xml version='1.0'?><Workspace/>")
    with pytest.raises(ValueError, match="not a QLC\\+ fixture"):
        fp.load_qxf(f)
    j = tmp_path / "x.json"
    j.write_text('{"name": "nope"}')
    with pytest.raises(ValueError, match="not an Open Fixture Library fixture"):
        fp.load_ofl(j)


def test_a_mode_using_an_undefined_channel_is_refused():
    xml = ("<FixtureDefinition xmlns='http://www.qlcplus.org/FixtureDefinition'><Manufacturer>A</Manufacturer>"
           "<Model>B</Model><Channel Name='Red' Preset='IntensityRed'/><Mode Name='2'>"
           "<Channel Number='0'>Red</Channel><Channel Number='1'>Ghost</Channel></Mode></FixtureDefinition>")
    with pytest.raises(ValueError, match="undefined channel 'Ghost'"):
        fp.load_qxf(xml)


# --- the override layer ---------------------------------------------------------------------------

def test_the_freedom_stick_never_runs_its_own_program():
    p = fp.builtin_profile("stick")
    m = p.mode("8 Channel")
    assert m.ids == ("dim", "red", "green", "blue", "macro", "strobe", "program", "speed")
    state = {"dim": 1, "red": 1, "macro": 1, "program": 7, "speed": 1, "color": 3}
    assert fp.frame(m, state) == [255, 255, 0, 0, 0, 0, 0, 0]
    assert p.wireless == "D-Fi" and any("Hub 2" in n for n in p.notes)


def test_strobe_floors_the_libraries_lack():
    tetra = fp.builtin_mode("tetra")
    assert fp.frame(tetra, {"strobe": 1e-9})[5] == 10   # the library says 0-255; the app's floor is 10
    assert fp.frame(tetra, {"strobe": 0})[5] == 0
    bar = {c.id: c for c in fp.builtin_mode("gigbar").channels}
    assert fp.encode(fp.builtin_mode("gigbar"), {"head1.strobe": 1e-9})["head1.strobe"] == 10
    assert bar["head2.strobe"].functions[0].lo == 10


def test_choices_by_name_and_by_number():
    m = fp.builtin_mode("gigbar")
    named = fp.encode(m, {"derby1.color": "yellow", "derby2.color": "Red + Green", "laser.color": "both",
                          "head1.color": "red", "head2.color": 3, "head1.gobo": 7})
    assert named["derby1.color"] == named["derby2.color"] == 105
    assert named["laser.color"] == 125
    assert named["head1.color"] == named["head2.color"] == 3 * 32 + 4   # red is wheel slot 3 (BL #12147)
    assert named["head1.gobo"] == 7 * 32 + 4
    # an unknown name, a fraction or a slot off the wheel sends nothing rather than a wrong color
    off = fp.encode(m, {"derby1.color": "chartreuse", "head1.color": 2.5, "head2.color": 8})
    assert off["derby1.color"] == off["head1.color"] == off["head2.color"] == 0


def test_an_override_for_a_channel_the_library_lacks_raises():
    p = fp.load_qxf(fp.QLC_DIR / "Venue-Tetra-6.qxf")
    table = {"venue/tetra-6": {"modes": {"6 Channel": {"channels": {"Wobble": {"hold": 0}}}}}}
    with pytest.raises(ValueError, match="'Wobble'"):
        fp.apply_overrides(p, table)
    with pytest.raises(KeyError):
        fp.apply_overrides(p, {"venue/tetra-6": {"modes": {"9 Channel": {}}}})
    with pytest.raises(ValueError, match="unknown role"):
        fp.apply_overrides(p, {"venue/tetra-6": {"default_role": "lasers"}})
    with pytest.raises(ValueError, match="unknown function kind"):
        fp.apply_overrides(p, {"venue/tetra-6": {"modes": {"6 Channel": {"channels": {
            "Red": {"functions": [{"kind": "wobble"}]}}}}}})


def test_the_overrides_file_is_valid_json_with_known_keys():
    doc = json.loads(fp.OVERRIDES_FILE.read_text("utf-8"))
    allowed = {"default_role", "roles", "notes", "elements", "modes", "wireless"}
    for key, spec in doc.items():
        if key.startswith("_"):
            continue
        assert set(spec) <= allowed, key
        assert set(spec.get("roles", {}).values()) <= set(fp.ROLES)


def test_a_nan_sends_dark_never_a_full_byte():
    m = fp.builtin_mode("tetra")
    assert fp.frame(m, {"red": math.nan, "dim": math.inf, "strobe": math.nan}) == [0] * 6


def test_a_circular_condition_reads_as_zero():
    a = fp.Channel("a", "A", functions=(fp.Function("fixed", byte=9, when=("b",)),))
    b = fp.Channel("b", "B", functions=(fp.Function("fixed", byte=7, when=("a",)),))
    assert fp.frame(fp.Mode("m", (a, b)), {}) in ([0, 7], [9, 0], [0, 0])


# --- reading the Open Fixture Library -------------------------------------------------------------

def test_ofl_tetra_bar_reads_its_modes_and_pixels():
    p = fp.load_ofl(OFL_TETRA_BAR)
    assert (p.key, p.library, p.license) == ("venue/tetra-bar", "ofl", "MIT")
    six = p.mode("6-channel")
    assert six.ids == ("red", "green", "blue", "amber", "dim", "strobe")
    assert fp.frame(six, {"red": 1, "amber": 0.5, "dim": 1, "strobe": 0}) == [255, 0, 0, 128, 255, 0]
    assert fp.frame(six, {"strobe": 1e-9})[5] == 1   # its strobe band starts at 1 (0 is open)
    twelve = p.mode("12-channel")
    assert twelve.ids[:3] == ("pixel1_4.red", "pixel1_4.green", "pixel1_4.blue")
    assert twelve.ids[9:] == ("pixel4_4.red", "pixel4_4.green", "pixel4_4.blue")
    ctl = p.mode("Tetra Control 28-channel")
    assert ctl.footprint == 28 and ctl.ids[4] == "unused"
    assert fp.frame(ctl, {"pixel2_4.red": 1})[7] == 255


def test_ofl_and_qlcplus_drive_the_gigbar_2_the_same():
    """The GigBAR 2 is in both libraries: every channel's bands match, and the same values give the
    same frame (names differ: OFL knows its pixel groups, QLC+ only channel names)."""
    o, q = fp.load_ofl(OFL_GIGBAR_2), fp.load_qxf(QLC_GIGBAR_2)
    for mode in ("23-channel", "11-channel", "3-channel"):
        mo, mq = o.mode(mode), q.mode(mode)
        assert mo.footprint == mq.footprint
        pairs = []
        for co, cq in zip(mo.channels, mq.channels):
            fo = [f for f in co.functions if f.kind != "fixed"]
            fq = [f for f in cq.functions if f.kind != "fixed"]
            # "only above 0" is no difference on a band that starts at 0: 0 sends 0 either way
            shape = lambda f: (f.kind, f.lo, f.hi, f.neg_lo, f.neg_hi, f.positive and f.lo != 0,   # noqa: E731
                               tuple((b.lo, b.hi) for b in f.bands))
            assert [shape(f) for f in fo] == [shape(f) for f in fq], (mode, co.name)
            pairs.append((co, fo, cq, fq))
        r = random.Random(mode)
        for _ in range(300):
            so, sq = {}, {}
            for co, fo, cq, fq in pairs:
                for f_o, f_q in zip(fo, fq):
                    v = (r.randrange(len(f_o.bands)) if f_o.kind == "choice"
                         else r.uniform(-1, 1) if f_o.kind == "bipolar" else r.choice((0.0, r.random())))
                    so[co.key(f_o.attr)] = v
                    sq[cq.key(f_q.attr)] = v
            assert fp.frame(mo, so) == fp.frame(mq, sq), mode


def test_two_channels_never_share_an_attribute():
    """QLC+'s GigBAR 2 calls both its white and its UV strobe dimmer just 'dim'; one value must
    not set both."""
    m = fp.load_qxf(QLC_GIGBAR_2).mode("23-channel")
    by_name = {c.name: c for c in m.channels}
    assert by_name["White Strobe Dimmer"].attributes == ("dim",)
    assert by_name["UV Strobe Dimmer"].attributes == ("dim_2",)
    for mode in m, fp.builtin_mode("gigbar"), fp.load_ofl(OFL_GIGBAR_2).mode("23-channel"):
        keys = [a for c in mode.channels for a in c.attributes]
        assert len(keys) == len(set(keys)), mode.name


def test_ofl_pixel_keys_must_be_the_fixtures_own():
    """'White / UV Strobe Speed' is template 'White / UV $pixelKey Speed' with the Strobe group, not
    'White $pixelKey' with a made-up key."""
    m = fp.load_ofl(OFL_GIGBAR_2).mode("23-channel")
    assert m.ids[-4:] == ("strobe.strobe", "strobe.white", "strobe.uv", "strobe.strobe_2")
    assert [c.name for c in m.channels[-3:]] == ["White Strobe Dimmer", "UV Strobe Dimmer", "White / UV Strobe Speed"]


# --- a rig of profiles, by role -------------------------------------------------------------------

def _mixed_rig():
    return fp.load_rig({"fixtures": [
        {"profile": f"ofl:{OFL_TETRA_BAR}", "mode": "6-channel", "address": 1, "role": "wash", "name": "Bar"},
        {"profile": "Chauvet-GigBAR-Move.qxf", "mode": "35CH", "address": 10, "role": "wash", "name": "GigBAR"},
        {"profile": "Chauvet-Freedom-Stick.qxf", "mode": "8 Channel", "address": 50, "role": "wash", "name": "Stick"},
        {"profile": "Venue-Tetra-6.qxf", "mode": "6 Channel", "address": 60, "role": "strobes", "name": "Strober"},
    ]})


def test_a_look_addresses_roles_not_brands():
    pr = _mixed_rig()
    assert pr.problems() == []
    assert pr.set_role("wash", red=1.0, dim=1.0) > 0
    u = pr.render()
    assert u[0] == 255 and u[4] == 255                     # the OFL Tetra Bar's red and dimmer
    assert u[9] == 255 and u[13] == 127                    # GigBAR par 1 red, its shutter at full dimmer
    assert u[14] == 255 and u[18] == 127                   # par 2
    assert u[49] == 255 and u[50] == 255                   # stick dimmer, red
    assert u[59] == 0                                      # the Tetra playing strobes is not a wash light
    assert u[9 + 23] == 0                                  # the heads are movers, untouched
    pr.set_role("movers", pan=1.0, tilt=0.5, dim=1.0)
    u = pr.render()
    assert (u[9 + 23], u[9 + 24], u[9 + 25]) == (255, 128, 255)   # head 1 pan, tilt, dimmer
    assert (u[9 + 29], u[9 + 30]) == (255, 128)                   # head 2
    pr.set_role("strobes", white=1.0, strobe=0.5)
    u = pr.render()
    assert u[9 + 20] == 255 and u[9 + 19] == 200           # GigBAR white strobe, ch20 "All strobing"
    assert u[59 + 5] == 132                                # the strobe Tetra: 10 + 245 * 0.5
    pr.set_role("effects", color="red", rotate=-1.0)
    u = pr.render()
    assert u[9 + 10] == 30 and u[9 + 13] == 30 and u[9 + 16] == 45   # derbies red, laser red
    assert u[9 + 12] == 255 and u[9 + 18] == 255                      # turning counter-clockwise, fast
    pr.clear()
    assert pr.render() == bytearray(512)


def test_a_rig_says_what_stops_it_playing():
    pr = fp.load_rig({"fixtures": [
        {"profile": "Venue-Tetra-6.qxf", "mode": "6 Channel", "address": 1, "role": "wash", "name": "A"},
        {"profile": "Venue-Tetra-6.qxf", "mode": "6 Channel", "address": 4, "role": "wash", "name": "B"},
        {"profile": "Venue-Tetra-6.qxf", "mode": "6 Channel", "address": 510, "role": "lasers", "name": "C"},
    ]})
    problems = pr.problems()
    assert any("B overlaps A at channel 4" in p for p in problems)
    assert any("C: channels 510-515" in p for p in problems)
    assert any("C: unknown role 'lasers'" in p for p in problems)
    with pytest.raises(ValueError, match="unknown role"):
        pr.set_role("lasers", red=1)
    assert pr.render()[509:] == bytearray(3)   # a light off the end is cut, never wraps


def test_a_bad_rig_entry_names_the_light():
    with pytest.raises(ValueError, match="light 2 \\(Nope\\)"):
        fp.load_rig({"fixtures": [
            {"profile": "Venue-Tetra-6.qxf", "mode": "6 Channel", "address": 1},
            {"profile": "Venue-Tetra-6.qxf", "mode": "40 Channel", "address": 9, "name": "Nope"}]})
    with pytest.raises(ValueError, match="light 1"):
        fp.load_rig({"fixtures": [{"profile": "No-Such-Light.qxf", "address": 1}]})


# --- library shapes found sweeping all of QLC+ (1,781 files) and OFL (653 fixtures) ---------------
# Every real fixture in both libraries loads and encodes (2026-11-17, a local sweep: the libraries are
# too big to vendor); these pin each shape the sweep needed, on small hand-made files.

def _ofl(**extra):
    d = {"name": "Test Bar", "availableChannels": {}, "modes": []}
    d.update(extra)
    return fp.load_ofl(d, "test")


def test_qlcplus_channel_names_match_like_qlcplus_does():
    """Library files name a channel 'Red ' and use 'Red' in a mode."""
    xml = ("<FixtureDefinition xmlns='http://www.qlcplus.org/FixtureDefinition'><Manufacturer>A</Manufacturer>"
           "<Model>B</Model><Channel Name='Red ' Preset='IntensityRed'/><Channel Name='Dimmer' "
           "Preset='IntensityDimmer'/><Mode Name='2'><Channel Number='0'>Red</Channel>"
           "<Channel Number='1'>dimmer</Channel></Mode></FixtureDefinition>")
    assert fp.frame(fp.load_qxf(xml).mode("2"), {"red": 1, "dim": 0.5}) == [255, 128]


def test_ofl_default_pixel_keys_and_xyz_order():
    """pixelCount keys are '1'.. in one dimension and '(x, y)' in two; eachPixelXYZ runs X fastest,
    eachPixelABC sorts numbers as numbers."""
    tpl = {"Red $pixelKey": {"capability": {"type": "ColorIntensity", "color": "Red"}}}
    one = _ofl(matrix={"pixelCount": [12, 1, 1]}, templateChannels=tpl, modes=[{"name": "12ch", "channels": [
        {"insert": "matrixChannels", "repeatFor": "eachPixelABC", "channelOrder": "perPixel",
         "templateChannels": ["Red $pixelKey"]}]}])
    assert one.mode("12ch").ids[:3] == ("pixel1.red", "pixel2.red", "pixel3.red")
    assert one.mode("12ch").ids[-1] == "pixel12.red"
    two = _ofl(matrix={"pixelCount": [2, 2, 1]}, templateChannels=tpl, modes=[{"name": "4ch", "channels": [
        {"insert": "matrixChannels", "repeatFor": "eachPixelYXZ", "channelOrder": "perPixel",
         "templateChannels": ["Red $pixelKey"]}]}])
    assert [c.name for c in two.mode("4ch").channels] == ["Red (1, 1)", "Red (1, 2)", "Red (2, 1)", "Red (2, 2)"]


def test_ofl_pixel_groups_repeat_in_order():
    tpl = {"Red $pixelKey": {"capability": {"type": "ColorIntensity", "color": "Red"}}}
    p = _ofl(matrix={"pixelKeys": [[["L", "R"]]], "pixelGroups": {"Right": ["R"], "Left": ["L"]}},
             templateChannels=tpl, modes=[{"name": "2ch", "channels": [
                 {"insert": "matrixChannels", "repeatFor": "eachPixelGroup", "channelOrder": "perPixel",
                  "templateChannels": ["Red $pixelKey"]}]}])
    assert p.mode("2ch").ids == ("right.red", "left.red")


def test_ofl_switching_channels_play_the_default_selection():
    """A mode names 'Program Speed', which is 'Speed' or 'Sensitivity' by Mode's value: the default
    (0) selects 'Speed'; a switch to nothing is an unused channel."""
    p = _ofl(availableChannels={
        "Mode": {"defaultValue": 0, "capabilities": [
            {"dmxRange": [0, 127], "type": "Maintenance", "switchChannels": {"Program Speed": "Speed", "Extra": None}},
            {"dmxRange": [128, 255], "type": "Maintenance",
             "switchChannels": {"Program Speed": "Sensitivity", "Extra": "Speed"}}]},
        "Speed": {"capability": {"type": "Speed", "speedStart": "slow", "speedEnd": "fast"}},
        "Sensitivity": {"capability": {"type": "Maintenance"}}},
        modes=[{"name": "3ch", "channels": ["Mode", "Program Speed", "Extra"]}])
    m = p.mode("3ch")
    assert m.ids[1] == "speed" and m.channels[2].functions == ()
    assert fp.frame(m, {"speed": 1.0}) == [0, 255, 0]


def test_ofl_fine_channels_and_repeated_pixel_keys():
    p = _ofl(matrix={"pixelKeys": [[["Top", "Bottom"]]]}, templateChannels={
        "Tilt $pixelKey": {"fineChannelAliases": ["Tilt $pixelKey fine"], "capability": {"type": "Tilt"}},
        "$pixelKey Red $pixelKey": {"capability": {"type": "ColorIntensity", "color": "Red"}}},
        modes=[{"name": "3ch", "channels": ["Tilt Top", "Tilt Top fine", "Bottom Red Bottom"]}])
    m = p.mode("3ch")
    assert m.ids == ("top.tilt", "top.tilt_fine", "bottom.red")
    assert fp.frame(m, {"top.tilt": 1.0, "top.tilt_fine": 0.5, "bottom.red": 1.0}) == [255, 128, 255]


def test_ofl_a_moved_fixture_says_where_it_went():
    with pytest.raises(ValueError, match="moved it to 'cameo/ts-60-rgbw'"):
        fp.load_ofl({"name": "ts60", "redirectTo": "cameo/ts-60-rgbw", "reason": "FixtureRenamed"})


def test_a_shutter_with_an_open_band_opens_when_nothing_strobes():
    """A moving head's shutter is closed at 0: with no strobe asked for it sends its open byte, so
    the light shows (Intimidator-style: 0-3 closed, 4-7 open, 8-76 strobe)."""
    p = _ofl(availableChannels={"Strobe": {"capabilities": [
        {"dmxRange": [0, 3], "type": "ShutterStrobe", "shutterEffect": "Closed"},
        {"dmxRange": [4, 7], "type": "ShutterStrobe", "shutterEffect": "Open"},
        {"dmxRange": [8, 76], "type": "ShutterStrobe", "shutterEffect": "Strobe", "speedStart": "slow",
         "speedEnd": "fast"}]}}, modes=[{"name": "1ch", "channels": ["Strobe"]}])
    m = p.mode("1ch")
    assert fp.frame(m, {}) == [4] and fp.frame(m, {"strobe": 0}) == [4]
    assert fp.frame(m, {"strobe": 1.0}) == [76]


# --- from the fresh review of PR #194 -------------------------------------------------------------

def _qxf(channels: str, mode: str) -> fp.Profile:
    return fp.load_qxf("<FixtureDefinition xmlns='http://www.qlcplus.org/FixtureDefinition'>"
                       "<Manufacturer>T</Manufacturer><Model>M</Model>" + channels
                       + "<Mode Name='m'>" + mode + "</Mode></FixtureDefinition>", table={})


def test_a_qlcplus_pan_or_tilt_without_a_preset_still_moves():
    p = _qxf("<Channel Name='Pan'><Group Byte='0'>Pan</Group><Capability Min='0' Max='255'>Pan 0-540</Capability>"
             "</Channel><Channel Name='Tilt'><Group Byte='0'>Tilt</Group><Capability Min='0' Max='255'>Tilt"
             "</Capability></Channel>", "<Channel Number='0'>Pan</Channel><Channel Number='1'>Tilt</Channel>")
    rig_ = fp.ProfileRig([fp.RigFixture(p, p.mode("m"), 1)])
    rig_.set_role("movers", pan=1.0, tilt=0.5)
    assert list(rig_.render()[:2]) == [255, 128]


def test_a_shutter_that_only_opens_and_closes_sends_open():
    p = _qxf("<Channel Name='Shutter'><Group Byte='0'>Shutter</Group><Capability Min='0' Max='9'>Shutter closed"
             "</Capability><Capability Min='10' Max='255'>Shutter open</Capability></Channel>",
             "<Channel Number='0'>Shutter</Channel>")
    assert fp.frame(p.mode("m"), {"dim": 1.0}) == [10]


def test_a_wheel_plays_its_slot_unless_it_is_asked_to_turn():
    """Color wheel: slots 0-127, CW 128-189, CCW 190-251, stop at 252. Unset or 0 rotation lets the
    slot play; with nothing set the wheel stops (never spins at byte 0)."""
    p = fp.load_ofl({"name": "W", "availableChannels": {"Color Wheel": {"capabilities": [
        {"dmxRange": [0, 63], "type": "WheelSlot", "slotNumber": 1, "comment": "Open"},
        {"dmxRange": [64, 127], "type": "WheelSlot", "slotNumber": 2, "comment": "Red"},
        {"dmxRange": [128, 189], "type": "WheelRotation", "speedStart": "slow CW", "speedEnd": "fast CW"},
        {"dmxRange": [190, 251], "type": "WheelRotation", "speedStart": "slow CCW", "speedEnd": "fast CCW"},
        {"dmxRange": [252, 255], "type": "WheelRotation", "speed": "stop"}]}},
        "modes": [{"name": "1ch", "channels": ["Color Wheel"]}]}, "t")
    m = p.mode("1ch")
    assert fp.frame(m, {"color": "red"}) == [95]
    assert fp.frame(m, {"color": "red", "rotate": 0}) == [95]
    assert fp.frame(m, {"color": "red", "rotate": 1.0}) == [189]
    assert fp.frame(m, {}) == [252] and fp.frame(m, {"rotate": 0}) == [252]


def test_a_fast_to_slow_rotation_band_runs_backwards_both_ways():
    p = fp.load_ofl({"name": "R", "availableChannels": {"Rot": {"capabilities": [
        {"dmxRange": [0, 127], "type": "Rotation", "speedStart": "fast CW", "speedEnd": "slow CW"},
        {"dmxRange": [128, 128], "type": "Rotation", "speed": "stop"},
        {"dmxRange": [129, 255], "type": "Rotation", "speedStart": "fast CCW", "speedEnd": "slow CCW"}]}},
        "modes": [{"name": "1ch", "channels": ["Rot"]}]}, "t")
    m = p.mode("1ch")
    assert fp.frame(m, {"rotate": 0.1})[0] > 100 and fp.frame(m, {"rotate": 1.0}) == [0]   # slow near 127
    assert fp.frame(m, {"rotate": -0.1})[0] > 240 and fp.frame(m, {"rotate": -1.0}) == [129]
    q = _qxf("<Channel Name='Rot'><Group Byte='0'>Speed</Group><Capability Min='5' Max='127'>Rotation CW fast to "
             "slow</Capability><Capability Min='128' Max='133'>Stop</Capability><Capability Min='134' Max='255'>"
             "Rotation CCW slow to fast</Capability></Channel>", "<Channel Number='0'>Rot</Channel>")
    assert fp.frame(q.mode("m"), {"rotate": 0.1})[0] > 110 and fp.frame(q.mode("m"), {"rotate": -1.0}) == [255]


@pytest.mark.parametrize("bad", [
    {"kind": "fixed", "byte": 200, "when": "strobe.white"},       # a string, not a list
    {"kind": "choice", "attr": "program", "offset": "5"},          # a string offset
    {"kind": "level", "attr": "uv", "lo": 300},                    # off the byte range
    {"kind": "level", "attr": "uv", "postive": True},              # a misspelt field
    {"kind": "level"},                                             # no attribute
])
def test_an_override_typo_raises_at_load(bad):
    p = fp.load_qxf(fp.QLC_DIR / "Chauvet-GigBAR-Move.qxf", table={})
    with pytest.raises(ValueError):
        fp.apply_overrides(p, {"chauvet/gigbar-move": {"modes": {"35-channel": {"channels": {
            "UV Strobe Dimmer": {"functions": [bad]}}}}}})


def test_a_library_that_fails_mid_show_sends_the_hand_written_bytes(monkeypatch, fresh_library):
    monkeypatch.delenv("LLANO_LIGHTS_PROFILES", raising=False)

    def boom(mode, state):
        raise TypeError("a bad override")
    monkeypatch.setattr(fp, "encode", boom)
    bar = rig.GigBarMove("b", 1, strobe_white=0.5)
    assert rig.named_bytes(bar) == dict(zip(CHANNEL_NAMES["gigbar"], bar.channels()))
    assert rig._PROFILE_MODES["gigbar"] is None    # and from then on, without trying again
    assert rig_states.digest(rig, settings_contract) == RELEASED_FRAMES


def test_todays_rig_as_data_follows_the_rig_blocks_addresses_and_counts():
    r = random.Random(11)
    blocks = rig_states.configs(settings_contract)
    short, moved = blocks[1], blocks[4]
    for _ in range(50):
        live = rig.default_rig()
        rig_states.randomize(live, r)
        for cfg in (short, moved):
            assert rig.profile_rig(live, cfg).render() == live.render(cfg)
    assert len(rig.profile_rig(config=short).fixtures) == 4


def test_a_light_given_a_role_plays_it():
    """A moving head is one part: the role the rig gives it wins; with none it plays movers."""
    p = _qxf("<Channel Name='Pan' Preset='PositionPan'/><Channel Name='Dimmer' Preset='IntensityDimmer'/>",
             "<Channel Number='0'>Pan</Channel><Channel Number='1'>Dimmer</Channel>")
    as_wash = fp.ProfileRig([fp.RigFixture(p, p.mode("m"), 1, "wash")])
    assert as_wash.set_role("wash", dim=1.0) == 1 and as_wash.render()[1] == 255
    assert fp.RigFixture(p, p.mode("m"), 1).element_roles() == {"": "movers"}


@pytest.mark.parametrize("doc, says", [
    ({"fixtures": ["Venue-Tetra-6.qxf"]}, "is not a light"),
    ({"fixtures": "Venue-Tetra-6.qxf"}, "a rig is"),
    ([], "a rig is"),
])
def test_a_rig_that_is_not_a_rig_says_so(doc, says):
    with pytest.raises(ValueError, match=says):
        fp.load_rig(doc)


def test_a_profile_with_no_modes_is_a_bad_light():
    with pytest.raises(ValueError, match="no modes"):
        fp.load_rig({"fixtures": [{"profile": "x", "address": 1}]},
                    resolve=lambda _r: fp.Profile("T", "M", {}, "qlcplus", "", "Apache-2.0"))
