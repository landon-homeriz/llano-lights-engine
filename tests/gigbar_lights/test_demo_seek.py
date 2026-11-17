"""The real-music demo (1.2.2): the lights follow the beat in the calm sections, change color on
each phrase, and follow a seek in the window at once: beat, bar and section look."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]  # the repo
sys.path.insert(0, str(ROOT))

from tools.gigbar_lights import demo_songs  # noqa: E402
from tools.gigbar_lights.show import Show  # noqa: E402

SONGS = [s.id for s in demo_songs.load()]
DT = 0.01


class Demo:
    """A demo run with the window's player reporting every quarter second, like app.html."""

    def __init__(self, song_id):
        self.song = demo_songs.find(song_id)
        self.show = Show(analyze=False, latency_ms=0)
        self.clock = demo_songs.SongClock()
        self.feed = demo_songs.SongFeed(self.show, self.song, self.clock)
        self.now, self.t = 1000.0, 0.0
        self.next_report = self.now

    def play(self, seconds):
        for _ in range(int(round(seconds / DT))):
            if self.now >= self.next_report:
                self.clock.report(self.song.id, self.t, True, self.now)
                self.next_report = self.now + 0.25
            self.feed(self.now)
            self.now += DT
            self.t += DT
        self.show.render(self.now)
        return self.show.last_frame

    def seek(self, t):
        """What app.html's seekTo does: move the player, report at once."""
        self.t = t
        self.clock.report(self.song.id, t, True, self.now)
        self.next_report = self.now + 0.25

    def beat_at(self, t):
        return (t - self.song.first_beat_s) * self.song.bpm / 60


def first(song, kind):
    return next(s for s in song.sections if s["kind"] == kind)


def target(song, kind):
    """A spot in the middle of the song's first section of this kind (the last section for 'outro'
    when a song has none: it ends on its drop)."""
    sec = next((s for s in song.sections if s["kind"] == kind), song.sections[-1] if kind == "outro" else None)
    mid_beat = (sec["start_beat"] + sec["end_beat"]) / 2
    return sec["kind"], song.first_beat_s + mid_beat * 60 / song.bpm


@pytest.mark.parametrize("song_id", SONGS)
@pytest.mark.parametrize("kind", ["build", "drop", "outro"])
def test_seek_lands_on_the_new_section_at_once(song_id, kind):
    d = Demo(song_id)
    d.play(3.0)
    assert d.show.looks.mode == "scripted:intro"
    want, t = target(d.song, kind)
    d.seek(t)
    f = d.play(0.1)  # a tenth of a second later
    expect = d.beat_at(d.t)
    assert abs(f.beat - expect) < 0.3, (f.beat, expect)
    assert f.bar == int(expect // 4)
    assert f.section is not None and f.section.kind == want
    assert d.show.looks.mode == f"scripted:{want}"


@pytest.mark.parametrize("song_id", SONGS)
def test_seek_back_to_the_intro_and_ten_second_steps(song_id):
    d = Demo(song_id)
    _, t = target(d.song, "drop")
    d.seek(t)
    d.play(1.0)
    d.seek(1.0)  # back to the top
    f = d.play(0.1)
    assert d.show.looks.mode == "scripted:intro" and abs(f.beat - d.beat_at(d.t)) < 0.3
    for step in (10, 10, -10):  # the window's 10 s buttons
        d.seek(d.t + step)
        f = d.play(0.1)
        assert abs(f.beat - d.beat_at(d.t)) < 0.3


@pytest.mark.parametrize("song_id", SONGS)
def test_every_section_is_reached_in_order(song_id):
    d = Demo(song_id)
    seen = []
    while d.t < d.song.duration_s - 0.5:
        d.play(0.5)
        mode = d.show.looks.mode
        if mode.startswith("scripted:") and (not seen or seen[-1] != mode):
            seen.append(mode)
    assert seen == [f"scripted:{s['kind']}" for s in d.song.sections]


@pytest.mark.parametrize("song_id", SONGS)
def test_intro_pulses_on_the_beat_and_changes_color_each_phrase(song_id):
    d = Demo(song_id)
    intro = first(d.song, "intro")
    on, off = [], []
    colors = set()
    d.seek(d.song.first_beat_s + 4 * 60 / d.song.bpm)
    while d.beat_at(d.t) < min(intro["end_beat"], 72) - 1:
        f = d.play(0.02)
        t1 = d.show.rig.tetras[0]
        phase = f.beat % 1
        if phase < 0.08:
            on.append(t1.dim)
        elif 0.45 < phase < 0.75:
            off.append(t1.dim)
        colors.add((round(t1.red, 2), round(t1.green, 2), round(t1.blue, 2)))
    assert sum(on) / len(on) > sum(off) / len(off) + 0.1  # brighter on the beat than between
    if intro["end_beat"] - intro["start_beat"] > 32:  # an intro longer than one 8-bar phrase
        assert len(colors) > 1


def test_window_going_quiet_keeps_the_song_position():
    d = Demo(SONGS[0])
    _, t = target(d.song, "drop")
    d.seek(t)
    d.play(0.5)
    before = d.show.last_frame.beat
    for _ in range(300):  # 3 s with no reports (a hidden, throttled window)
        d.feed(d.now)
        d.now += DT
        d.t += DT
    d.show.render(d.now)
    assert abs(d.show.last_frame.beat - d.beat_at(d.t)) < 0.3 and d.show.last_frame.beat > before


# --- 1.2.3: what his 1.2.2 screen recording showed -----------------------------------------------

def hue_family(rgb):
    import colorsys
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    return None if s < 0.3 or v < 0.1 else int(((h + 1 / 12) % 1) * 6)  # red, yellow, green, cyan, blue, magenta


@pytest.mark.parametrize("song_id", SONGS)
def test_no_rainbow_flash_at_the_start_or_after_a_seek_to_zero(song_id):
    d = Demo(song_id)  # a song starts before its first beat, like switching songs
    modes = []
    for _ in range(20):
        d.play(0.05)
        modes.append(d.show.looks.mode)
    _, t = target(d.song, "drop")
    d.seek(t)
    d.play(0.5)
    d.seek(0.0)  # his back-10s press near the top
    for _ in range(20):
        d.play(0.05)
        modes.append(d.show.looks.mode)
    assert not [m for m in modes if m.startswith("autoloop")], modes


@pytest.mark.parametrize("song_id", SONGS)
def test_intro_colors_leave_the_reds(song_id):
    d = Demo(song_id)
    intro = first(d.song, "intro")
    fams = set()
    d.seek(d.song.first_beat_s)
    while d.beat_at(d.t) < min(intro["end_beat"], 64):
        d.play(0.25)
        fams.add(hue_family(tuple(getattr(d.show.rig.tetras[0], c) for c in ("red", "green", "blue"))))
    fams.discard(None)
    assert len(fams) >= 3, fams  # 1.2.2: red and orange only


def test_a_long_intro_moves_like_a_groove_after_16_bars():
    d = Demo("slow")  # Basi Beta: its analyzed intro is 160 beats, about 2 of its 3 minutes
    assert first(d.song, "intro")["end_beat"] > 96
    pans = set()
    d.seek(d.song.first_beat_s + 70 * 60 / d.song.bpm)
    for _ in range(40):
        d.play(0.25)
        pans.add(round(d.show.rig.bars[0].movers[0].pan, 2))
    # the heads glide (1 value if they held on the booth, as in the first 16 bars); since 1.16.9 a slow
    # pan holds, then slides (glide.py, Pan in slides), so 10 s of it is a few pan values, not every frame
    assert len(pans) >= 3
