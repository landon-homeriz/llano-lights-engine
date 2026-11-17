"""1.11.4: the live screen from his 2:40 PM recording of 1.11.0 (2026-11-08).

0:14 the app is slow to open from its desktop icon; 0:18 Tap doesn't seem to work; 0:29 a reset
beside Earlier / Later; 3:11 the button row, Scenes and Moments take too much of the screen.
"""
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
import gigbar_app  # noqa: E402
from tools.gigbar_lights import __main__ as gl  # noqa: E402
from tools.gigbar_lights.show import Show  # noqa: E402

from test_live_screen import app, wait  # noqa: E402,F401  (the running-app fixture)

PAGE = (Path(gigbar_app.__file__).parent / "app.html").read_text()


# --- 0:14 slow to open ---------------------------------------------------------------------------

class _Answer:
    def __init__(self, port):
        self.port = port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, *a):
        return ('{"product": "%s", "version": "x", "port": %d}' % (gigbar_app.updater.PRODUCT, self.port)).encode()


def test_the_other_copy_check_asks_every_port_at_once(monkeypatch):
    """Windows retries a refused local connection, so each free port took its whole 0.5 s timeout:
    20 ports one after another held the window back about 10 s on every launch."""
    lo = gigbar_app.PORTS[0]   # 8765 on the laptop; the suite runs on its own base (BL #12427)
    answering = {lo + 6, lo + 14}

    def slow_open(url, timeout):
        port = int(url.split(":")[2].split("/")[0])
        if port in answering:
            return _Answer(port)
        time.sleep(timeout)   # what Windows does on a closed port
        raise OSError("refused")
    monkeypatch.setattr(gigbar_app.NO_PROXY, "open", slow_open)
    t = time.monotonic()
    url, info = gigbar_app.running_instance()
    assert time.monotonic() - t < 1.5
    assert url == f"http://127.0.0.1:{lo + 6}/" and info["port"] == lo + 6   # the lowest, as before

    answering.clear()
    t = time.monotonic()
    assert gigbar_app.running_instance() is None
    assert time.monotonic() - t < 1.5


def test_the_log_times_each_launch_step_and_the_first_window_request(app, capsys):
    gigbar_app.startup_mark("window server up")
    assert re.search(r"Startup: window server up at \d+\.\d\ds", capsys.readouterr().out)
    app.page_seen = False
    app.touch()
    app.touch()
    out = capsys.readouterr().out
    assert out.count("Startup: the window asked for its first state") == 1


def test_gui_marks_every_step_before_the_window():
    src = Path(gigbar_app.__file__).read_text()
    body = src[src.index("def gui(opts)"):src.index("def main(")]
    steps = re.findall(r'startup_mark\("([^"]+)"', body)
    assert steps[:5] == ["code loaded", "checked for another copy", "checked the last run", "app ready",
                         "window server up"]


# --- 0:18 Tap ------------------------------------------------------------------------------------

def test_tap_never_set_the_tempo_with_music_playing_so_the_button_is_gone(app):
    """Every way the show runs feeds it a beat (the song in the window, Mixxx, or listening to the
    laptop), and a tap only counts after 2 s with none. Tapping 240 BPM left the demo on its song."""
    assert app.run("demo")[0] == 200
    assert wait(lambda: app.state()["live"] is not None and app.state()["live"]["playing"])
    for _ in range(5):
        app.preview.keys.put("t")
        time.sleep(0.25)
    time.sleep(0.3)
    assert app.state()["live"]["bpm"] < 200
    assert 'id="tap"' not in PAGE and "tapHit" not in PAGE


def test_tap_still_works_with_no_beat_at_all():
    show = Show(analyze=False)
    for t in (100.0, 100.5, 101.0, 101.5):
        show.tap_tempo(t)
    assert abs(show.clock.bpm - 120.0) < 1e-6


# --- 0:29 a reset beside Earlier / Later ---------------------------------------------------------

def test_reset_puts_the_lights_back_on_the_musics_timing():
    show = SimpleNamespace(offset_ms=0.0, looks=SimpleNamespace(overrides=SimpleNamespace()))
    for k in "[[[":
        gl.handle_key(k, show)
    assert show.offset_ms == 15
    gl.handle_key("0", show)
    assert show.offset_ms == 0
    gl.handle_key("]", show)
    gl.handle_key("0", show)
    assert show.offset_ms == 0


def test_the_window_shows_the_offset_and_a_reset_beside_earlier_and_later(app):
    assert app.run("demo")[0] == 200
    assert wait(lambda: app.state()["live"] is not None)
    assert app.state()["live"]["offset_ms"] == 0
    app.preview.keys.put("[")
    app.preview.keys.put("[")
    assert wait(lambda: app.state()["live"]["offset_ms"] == 10, 2.0)
    app.preview.keys.put("0")
    assert wait(lambda: app.state()["live"]["offset_ms"] == 0, 2.0)
    timing = PAGE[PAGE.index('id="timing"'):]
    timing = timing[:timing.index("</span>")]
    assert re.findall(r'data-k="(.)"', timing) == ["[", "]", "0"]
    assert 'id="offset"' in timing and ">Reset<" in timing


# --- 3:11 the top of the live screen -------------------------------------------------------------

def test_scenes_and_moments_share_one_row_one_set_at_a_time():
    pads = PAGE[PAGE.index('id="pads"'):PAGE.index('<iframe id="view"')]
    assert 'id="tabscenes"' in pads and 'id="tabmoments"' in pads
    assert 'id="scenes"' in pads and 'id="moments"' in pads and 'id="sceneback"' in pads
    assert re.search(r'id="moments"[^>]*hidden', pads)
    assert PAGE.count('class="scenes') == 1          # one row, not two
    assert "flex-basis:100%" not in PAGE[PAGE.index("#status {"):][:200]   # the status line no longer takes its own row


def test_line_up_opens_its_own_page_once_the_build_has_it():
    assert re.search(r'<button id="lineupbtn" hidden', PAGE)
    assert 'fetch("/lineup.html"' in PAGE and 'location.href = "/lineup.html"' in PAGE
    # only the show's own buttons wait for a show; Line up works with nothing running
    assert 'querySelectorAll("#controls button[data-k]").forEach(b => b.disabled = !S.show)' in PAGE

