"""The byte-identical gate: with default settings 1.4.0 puts out exactly 1.3.1's DMX.
Without a room layout; with one, 1.9.0 aims the spots forward on purpose. Every channel but the
moving heads' tilt: 1.10.1 re-modeled tilt on purpose (the heads hang under the bar, so 0.5 is
straight down, not level), pinned in test_hung_heads.py.

1.4.0 moved the show's hard-coded moves, levels and color timing into settings (contract
schema 2, SECTION_DEFAULTS). The pins below are the digests 1.3.1 itself rendered for the
scenarios in show_frames.py (every section kind, long intro, autoloops, a drop burst, a build
ramp, Loop Auto-Strobe, idle, silence, the overrides, a room layout, three track seeds and the
settings 1.3.x already played), so a mapping slip in looks.py fails here, frame for frame.
Re-pin only with the old version's own output, never with the new engine's.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import show_frames  # noqa: E402

from tools.gigbar_lights import settings_contract as contract  # noqa: E402

# Rendered by llano-lights 316f5d0 (1.3.1) with this show_frames.py, without the room-layout
# pass: 1.9.0 changed how a layout aims the spots on purpose (they face the dance floor, the
# booth position lights the DJ from the front), pinned in test_spots_face_forward.py. With the
# layout pass 1.3.1 renders (15351, "3f9f504c...20a7aa"), the pin before 1.9.0. With the tilt bytes
# zeroed (tilt=False), from the same 316f5d0 checkout; its full frames still render the pins
# before 1.10.1, (11136, "64b8502f...cf47f0591") and (1343, "e69a240c...9193210d606a").
# 1.12.3 drives six GigBAR effect channels on purpose (show_frames.EFFECT_OFFSETS: derbies and laser
# turning both ways, laser strobe, the build's UV strobe), zeroed alongside tilt; re-rendered by the
# same 316f5d0 checkout with that mask. The pins before 1.12.3, (11136, "05980314...2aa9446818") and
# (1343, "d5c4cf01...942ae0fb74dd") masked tilt only.
# 1.16.7 holds a dark head's aim (looks._hold_aim) where 1.3.1 parked it at pan 0.5: a dark head's
# pan is zeroed too (show_frames._dark_pans), re-rendered by the same 316f5d0 checkout with that mask.
# The pins before 1.16.7, (11136, "1b4892f0...a2ab2c8f60") and (1343, "7c150c7d...942ae0fb74dd").
FRAMES_131 = (11136, "c79a6d802c6f11e05ca289a922b3875015c9cf59e3bf762313c0d132872b1a9a")
SCHEMA1_DOC_131 = (1343, "8b195373185f423e7ddb05310d599fd8c41f548e4ddd2cb763534688f65ab0cd")


def test_default_show_is_byte_identical_to_1_3_1(monkeypatch):
    # Fluid travel (Llano BL #12400) changes a slow glide or sweep's heads on purpose, pinned in
    # test_heads_face_and_flow_12400.py; with it off every frame is still 1.3.1's (no re-pin)
    monkeypatch.setenv("LLANO_LIGHTS_FLUID_TRAVEL", "0")
    # The stick lift (Llano PM #23790) raises the sticks' dimmer on purpose, pinned in
    # test_stick_lift_23790.py; with it off every frame is still 1.3.1's (no re-pin)
    monkeypatch.setenv("LLANO_LIGHTS_STICK_LIFT", "0")
    assert show_frames.digest(venue_run=False, tilt=False) == FRAMES_131


def test_a_1_3_1_settings_file_plays_identically(monkeypatch):
    monkeypatch.setenv("LLANO_LIGHTS_FLUID_TRAVEL", "0")   # as above
    monkeypatch.setenv("LLANO_LIGHTS_STICK_LIFT", "0")
    doc = json.loads((HERE / "settings_schema1_131.json").read_text())
    assert doc["schema"] == 1 and "sections" not in doc
    assert show_frames.doc_digest(doc, tilt=False) == SCHEMA1_DOC_131


def test_a_schema_1_doc_reads_as_todays_sections():
    doc = json.loads((HERE / "settings_schema1_131.json").read_text())
    d = contract.normalize(doc)
    assert d["schema"] == 2 and d["sections"] == contract.SECTION_DEFAULTS
    assert d["styles"] == {} and d["songs"] == {} and d["style_in_use"] == ""
    assert d["strobe"]["intensity"] == 0.5 and "neon" in d["palettes"]
