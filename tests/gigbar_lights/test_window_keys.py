"""Space pauses the window's song, and never scrolls (his recording, 0:10); T taps the tempo (1.7.0).

The keyboard logic runs the window's own onKey/togglePlay from app.html in node with a fake
player (the GitHub runner has node; skips where it is missing). The show side: T taps tempo.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import types
from pathlib import Path

import pytest

from tools.gigbar_lights import __main__ as gl

APP = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src" / "app.html"

PROBE = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const grab = (name) => { const i = src.indexOf('function ' + name + '('); let d = 0, j = src.indexOf('{', i);
  for (let k = j; k < src.length; k++) { if (src[k] === '{') d++; else if (src[k] === '}' && --d === 0) return src.slice(i, k + 1); } };
const body = ['songInWindow', 'togglePlay', 'onKey'].map(grab).join('\n');
const out = [];
for (const c of JSON.parse(process.argv[2])) {
  const sent = [], audio = { paused: c.paused, play() { this.paused = false; return Promise.resolve(); }, pause() { this.paused = true; } };
  const run = new Function('S', 'audio', 'playingUrl', 'fetch', 'flash', 'TOKEN',
    body + '; return [onKey(' + JSON.stringify(c.key) + ', ' + c.repeat + '), audio.paused];');
  const [ours, paused] = run(c.S, audio, c.url, (u) => { sent.push(decodeURIComponent(u.split('k=')[1])); }, () => {}, 't');
  out.push({ours, paused, sent});
}
console.log(JSON.stringify(out));
"""

DEMO = {"running": "demo", "song": "s1", "show": True}
MIXXX = {"running": "live", "song": "", "show": True}
CASES = [
    # (case, expect ours, expect paused after, expect keys sent to the show)
    ({"key": " ", "repeat": False, "paused": False, "S": DEMO, "url": "/s1.mp3"}, True, True, []),     # pauses the song
    ({"key": " ", "repeat": False, "paused": True, "S": DEMO, "url": "/s1.mp3"}, True, False, []),     # plays it again
    ({"key": " ", "repeat": True, "paused": False, "S": DEMO, "url": "/s1.mp3"}, True, False, []),     # held: no flicker
    ({"key": " ", "repeat": False, "paused": True, "S": MIXXX, "url": ""}, True, True, [" "]),         # Mixxx: taps tempo
    ({"key": " ", "repeat": False, "paused": True, "S": None, "url": ""}, True, True, []),             # no show: no scroll
    ({"key": "t", "repeat": False, "paused": False, "S": DEMO, "url": "/s1.mp3"}, True, False, ["t"]), # T taps, song plays on
    ({"key": "b", "repeat": False, "paused": True, "S": MIXXX, "url": ""}, True, True, ["b"]),
    ({"key": "0", "repeat": False, "paused": True, "S": MIXXX, "url": ""}, True, True, ["0"]),         # timing reset (1.11.4)
    ({"key": "x", "repeat": False, "paused": True, "S": MIXXX, "url": ""}, False, True, []),           # not ours
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_space_pauses_the_windows_song_and_never_scrolls():
    res = subprocess.run(["node", "-e", PROBE, str(APP), json.dumps([c for c, *_ in CASES])],
                         capture_output=True, text=True, timeout=30, check=True)
    for (case, ours, paused, sent), got in zip(CASES, json.loads(res.stdout)):
        assert (got["ours"], got["paused"], got["sent"]) == (ours, paused, sent), (case, got)


def test_t_taps_the_tempo_like_space():
    taps = []
    show = types.SimpleNamespace(tap_tempo=lambda: taps.append(1), looks=types.SimpleNamespace(overrides=None))
    assert gl.handle_key("t", show) is True and gl.handle_key(" ", show) is True
    assert len(taps) == 2
