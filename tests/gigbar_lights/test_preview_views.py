"""The Show Designer's two views agree on left and right (his recording, 1:57).

The view from above draws room x left to right. The view from the dance floor must do the same:
when it was mirrored, dragging a light on one side in the top view seemed to move the light on
the other side in the perspective view. This runs the page's own camera() in node (the GitHub
runner has it) and skips where node is missing.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

PREVIEW = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src" / "preview.html"

PROBE = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const cam = src.slice(src.indexOf('function camera'), src.indexOf('let NEAR_Y'));
const rad = d => d * Math.PI / 180;
const out = [];
for (const L of JSON.parse(process.argv[2])) {
  // STAGE false is the Show Designer's view from the back of the room; STAGE true with the view
  // "from the DJ booth" is the Live screen's second camera, in the booth looking out (1.20.0).
  const look = (stage) => {
    const P = new Function('L', 'rad', 'STAGE', 'stageView', cam + '; return camera')(L, rad, stage, () => ({from: 'booth', turn: 0}))(800, 500);
    const z = 1, y = L.booth.y + L.booth.d + 0.5;
    return {left: P([L.room.w * 0.2, y, z])[0], right: P([L.room.w * 0.8, y, z])[0],
            floor: P([L.room.w / 2, y, 0])[1], ceiling: P([L.room.w / 2, y, L.room.h - 0.5])[1]};
  };
  out.push({back: look(false), booth: look(true)});
}
console.log(JSON.stringify(out));
"""

ROOMS = [
    {"room": {"w": 10, "d": 12, "h": 4}, "floor": {"x": 3, "y": 4, "w": 4, "d": 4}, "booth": {"x": 4, "y": 0.5, "w": 2, "d": 1}},
    {"room": {"w": 30, "d": 40, "h": 9}, "floor": {"x": 5, "y": 8, "w": 20, "d": 20}, "booth": {"x": 12, "y": 1, "w": 6, "d": 2}},
    {"room": {"w": 5, "d": 6, "h": 2.6}, "floor": {"x": 0.5, "y": 2, "w": 4, "d": 3}, "booth": {"x": 1.5, "y": 0, "w": 2, "d": 1}},
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_the_view_from_the_dance_floor_is_not_mirrored_and_stands_upright():
    res = subprocess.run(["node", "-e", PROBE, str(PREVIEW), json.dumps(ROOMS)],
                         capture_output=True, text=True, timeout=30, check=True)
    for room, both in zip(ROOMS, json.loads(res.stdout)):
        v = both["back"]
        assert v["left"] < v["right"], (room["room"], v)       # house left stays on the left
        assert v["floor"] > v["ceiling"], (room["room"], v)    # the floor is below the ceiling


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_the_view_from_the_dj_booth_is_turned_around_not_mirrored():
    """From the booth looking out he has turned around, so what was on the left is now on his right:
    the picture turns with him (the view from above turns the same half turn), and still stands upright."""
    res = subprocess.run(["node", "-e", PROBE, str(PREVIEW), json.dumps(ROOMS)],
                         capture_output=True, text=True, timeout=30, check=True)
    for room, both in zip(ROOMS, json.loads(res.stdout)):
        v = both["booth"]
        assert v["left"] > v["right"], (room["room"], v)
        assert v["floor"] > v["ceiling"], (room["room"], v)
