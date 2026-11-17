"""Who plays the music is said plainly (Llano BL #12410).

His report: he pressed Play inside Llano Lights, nothing played, and he no longer knew whether
Llano or Mixxx plays the songs. The press was the Show Designer's "Play the show here": it makes
sound only for songs that are files in his Mixxx library, and his 70 wedding songs were none, so
it ran the lights on the picture in silence with no word why. The plan is that Mixxx plays the
music and Llano Lights follows it. These pins keep that said on the Live screen (laptop and
phone share studio_console.js) and keep the Show Designer's button a lights preview that says
before the press whether it will make any sound. soundLine runs in node (skips where missing).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"
LINE = "Music plays in Mixxx. Llano Lights follows it."


def test_live_screen_says_mixxx_plays_the_music():
    console = (SRC / "studio_console.js").read_text(encoding="utf-8")
    assert LINE in console
    # in the show chip itself (static markup), so it shows whatever is or isn't running
    chip = console[console.index('lls-chip show'):]
    assert chip.index(LINE) < chip.index("</div>' +")


def test_show_designer_play_is_a_lights_preview():
    page = (SRC / "shows.html").read_text(encoding="utf-8")
    assert "Play the show here" not in page
    assert "Play the show from this song" not in page
    assert "&#9654; Preview the lights" in page
    assert LINE in page
    assert 'id="soundline"' in page and "soundLine(show.songs)" in page
    assert "(no sound here)" in page   # the playing song's line says when it is silent


PROBE = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('function soundLine'), b = src.indexOf('\n}\n', a) + 2;
const soundLine = new Function(src.slice(a, b) + '; return soundLine')();
console.log(JSON.stringify(JSON.parse(process.argv[2]).map(soundLine)));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_sound_line_says_before_the_press():
    cases = [[], [{"playable": False}] * 70, [{"playable": True}] * 3,
             [{"playable": True}, {"playable": False}, {"playable": False}]]
    res = subprocess.run(["node", "-e", PROBE, str(SRC / "shows.html"), json.dumps(cases)],
                         capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    empty, none, every, some = json.loads(res.stdout)
    assert empty == ""
    assert none.startswith("This preview is silent") and "70 songs" in none and "Mixxx" in none
    assert every.startswith("Every song makes sound")
    assert re.match(r"1 of 3 songs make sound", some) and "other 2 preview silently" in some
