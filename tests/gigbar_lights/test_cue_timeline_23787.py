"""The cue timeline (Llano PM #23787, his ask 2026-11-15: push cues forward and back, pause and
see them, dead simple). A song's cues live in the settings by track key, in seconds into the original
recording, and the engine plays them on the next frame: a white hit, his own sections, a stretch
bigger, softer or in one color. A night's cut plays them on the same notes (its zero_s)."""
from __future__ import annotations

import pytest

from tools.gigbar_lights import cues as cues_mod
from tools.gigbar_lights import demo_songs, show_settings
from tools.gigbar_lights import settings_contract as contract
from tools.gigbar_lights.beat_clock import TrackGrid
from tools.gigbar_lights.show import Show
from tools.gigbar_lights.show_script import Section, ShowScript
from tools.gigbar_lights.song_match import candidates

SONG = next(s for s in demo_songs.load() if s.id == "drop")
KEY = candidates(SONG.artist, SONG.title)[0]


@pytest.fixture(autouse=True)
def _settings():
    before = show_settings.current()
    yield
    show_settings.set_current(before)


def _set_cues(cs):
    show_settings.set_current({**contract.normalize({}), "cues": {KEY: cs}})


def _play_at(at, seconds=0.25, playing=True):
    """The show following the window's report that the song is at `at` s, run for `seconds`;
    the last frame's (show, rendered rig, frame)."""
    clock = demo_songs.SongClock()
    clock.report(SONG.id, at, playing, now=1000.0)
    show = Show(analyze=False, latency_ms=0.0)
    feed = demo_songs.SongFeed(show, SONG, clock)
    now = 1000.0
    while now < 1000.0 + seconds:
        feed(now)
        now += 512 / 44100
    show.render(now)
    return show, show.rig, show.last_frame


def _white(rig) -> bool:
    return all(t.red == t.green == t.blue == 1.0 and t.dim >= 0.99 for t in rig.tetras)


# --- what is stored ---------------------------------------------------------------------------

def test_cues_are_cleaned_sorted_and_kept_per_song():
    d = contract.normalize({"cues": {"bon-jovi-livin-on-a-prayer": [
        {"at": 203.4, "do": "hit", "size": 2}, {"at": 92.72, "do": "hit"},
        {"at": 10, "do": "feel", "feel": "softer", "color": "#FF8800"},
        {"at": 5, "do": "section", "kind": "chorus"},        # not a section kind
        {"at": -1, "do": "hit"}, {"at": True, "do": "hit"},  # out of range, not a number
        {"at": 7, "do": "feel"},                              # a feel that changes nothing
    ], "Not A Key": [{"at": 1, "do": "hit"}], "empty-song": []}})
    assert d["cues"] == {"bon-jovi-livin-on-a-prayer": [
        {"at": 10.0, "do": "feel", "feel": "softer", "color": "#ff8800"},
        {"at": 92.72, "do": "hit", "size": 1}, {"at": 203.4, "do": "hit", "size": 2}]}
    assert contract.normalize(d) == d   # idempotent: a second save changes nothing


def test_a_nudge_is_one_change_and_clearing_the_last_cue_deletes_the_song():
    doc = contract.normalize({})
    doc, applied = contract.apply_ops(doc, [{"path": f"cues.{KEY}", "value": [{"at": 30.1, "do": "hit"}]}])
    assert doc["cues"][KEY][0]["at"] == 30.1 and len(applied) == 1
    doc, _ = contract.apply_ops(doc, [{"path": f"cues.{KEY}", "value": [{"at": 30.2, "do": "hit"}]}])
    assert doc["cues"][KEY][0]["at"] == 30.2
    doc, _ = contract.apply_ops(doc, [{"path": f"cues.{KEY}", "value": None}])
    assert KEY not in doc["cues"]
    assert {"path": f"cues.{KEY}", "value": None} not in contract.diff_ops(doc, doc)


def test_cues_stay_under_their_size_cap():
    many = {f"song-{i}": [{"at": j * 3.0, "do": "feel", "feel": "bigger", "color": "#123456"}
                          for j in range(contract.MAX_CUES)] for i in range(40)}
    d = contract.normalize({"cues": many})
    assert 0 < len(d["cues"]) < 40
    assert len(contract._dumps_ascii(d["cues"])) <= contract.MAX_CUES_BYTES
    assert all(len(v) == contract.MAX_CUES for v in d["cues"].values())


# --- the engine ---------------------------------------------------------------------------------

def test_a_white_hit_holds_then_fades():
    # BL #12518: a 1 holds 0.5 s and is gone at 0.9 s; a 2 (the white-out) holds 1 s, gone at 1.8 s,
    # the strobes bursting through its first 0.6 s
    cs = ({"at": 10.0, "do": "hit", "size": 1}, {"at": 20.0, "do": "hit", "size": 2})
    assert cues_mod.hit_at(cs, 9.99) == (0.0, False, "")
    assert cues_mod.hit_at(cs, 10.1) == (1.0, False, "")
    lvl = cues_mod.hit_at(cs, 10.7)[0]
    assert 0.4 < lvl < 0.6
    assert cues_mod.hit_at(cs, 10.9)[0] == pytest.approx(0.0, abs=1e-9)
    assert cues_mod.hit_at(cs, 20.2) == (1.0, True, "")     # the big one strobes
    assert cues_mod.hit_at(cs, 20.9) == (1.0, False, "")    # and is still full white
    assert cues_mod.hit_at(cs, 21.8)[0] == pytest.approx(0.0, abs=1e-9)


def test_his_sections_replace_the_analysis_and_a_cut_lands_them_on_the_same_beat():
    grid = TrackGrid(samplerate=44100, first_beat=0.5 * 44100, bpm=120)   # a beat every 0.5 s from 0.5 s
    analysis = ShowScript([Section("intro", 0, 64, 0.3), Section("drop", 64, 128, 1.0)])
    cs = ({"at": 8.5, "do": "section", "kind": "build"}, {"at": 16.5, "do": "section", "kind": "drop"})
    mine = cues_mod.script_for(cs, grid, None, analysis)
    assert [(s.kind, s.start_beat, s.end_beat) for s in mine.sections][:1] == [("build", 16, 32)]
    assert mine.sections[1].kind == "drop" and mine.sections[1].start_beat == 32
    # the same song cut 4 s in with a 1 s lead: the original's 0:00 sits at -3 s in the cut
    cut_grid = TrackGrid(samplerate=44100, first_beat=1.5 * 44100, bpm=120)
    on_cut = cues_mod.script_for(cs, cut_grid, -3.0, None)
    assert cut_grid.seconds_at(on_cut.sections[0].start_beat) - (-3.0) == pytest.approx(8.5)
    # no section cue: the analysis plays as it is
    assert cues_mod.script_for(({"at": 3.0, "do": "hit", "size": 1},), grid, None, analysis) is analysis


def test_the_lights_go_white_on_his_hit_and_not_before():
    _set_cues([{"at": 40.0, "do": "hit", "size": 1}])
    _show, rig, f = _play_at(39.5)
    assert f.secs == pytest.approx(39.75, abs=0.05) and not _white(rig)
    _show, rig, f = _play_at(39.9)
    assert f.secs == pytest.approx(40.15, abs=0.05)
    assert _white(rig)


def test_a_hit_waits_for_the_speakers_sync():
    show_settings.set_current({**contract.normalize({}), "rig": {**contract.normalize({})["rig"], "sync_ms": 500},
                               "cues": {KEY: [{"at": 40.0, "do": "hit", "size": 1}]}})
    clock = demo_songs.SongClock()
    clock.report(SONG.id, 39.9, True, now=1000.0)
    show = Show(analyze=False, latency_ms=None)
    show.state.output_latency_ms = 0.0
    feed = demo_songs.SongFeed(show, SONG, clock)
    now = 1000.0
    while now < 1000.25:
        feed(now)
        now += 512 / 44100
    show.render(now)
    assert show.last_frame.secs < 40.0 and not _white(show.rig)   # the music reaches the room 0.5 s later


def test_no_hit_over_a_blackout_a_pause_or_with_cues_off(monkeypatch):
    _set_cues([{"at": 40.0, "do": "hit", "size": 1}])
    show, rig, _f = _play_at(39.9, playing=False)
    assert not _white(rig)
    clock = demo_songs.SongClock()
    clock.report(SONG.id, 39.9, True, now=1000.0)
    show = Show(analyze=False, latency_ms=0.0)
    show.looks.overrides.blackout = True
    feed = demo_songs.SongFeed(show, SONG, clock)
    now = 1000.0
    while now < 1000.25:
        feed(now)
        now += 512 / 44100
    show.render(now)
    assert not _white(show.rig)
    monkeypatch.setenv("LLANO_LIGHTS_CUES", "0")
    _show, rig, f = _play_at(39.9)
    assert not _white(rig) and f.cues == ()


def test_a_softer_stretch_dims_and_a_color_takes_over():
    _show, plain, f0 = _play_at(50.0)
    lvl = sum(t.dim for t in plain.tetras)
    sec = f0.section   # the cue sits in the stretch playing at 50 s
    at = SONG.first_beat_s + (sec.start_beat + 1) * 60.0 / SONG.bpm
    _set_cues([{"at": round(at, 2), "do": "feel", "feel": "softer", "color": "#0000ff"}])
    show, soft, f = _play_at(50.0)
    assert f.feel == ("softer", "#0000ff")
    assert sum(t.dim for t in soft.tetras) <= lvl * cues_mod.SOFTER + 1e-6
    assert all(b.strobe_white == 0 for b in soft.bars)
    lit = [t for t in soft.tetras if t.dim > 0]
    assert lit and all(t.blue >= t.red and t.blue >= t.green for t in lit)


def test_a_feel_covers_only_the_section_it_sits_in():
    secs = SONG.sections
    first, second = secs[0], secs[1]
    assert first["end_beat"] == second["start_beat"]
    beat_s = 60.0 / SONG.bpm
    mid_first = SONG.first_beat_s + (first["start_beat"] + 2) * beat_s
    in_second = SONG.first_beat_s + (second["start_beat"] + 2) * beat_s
    _set_cues([{"at": round(mid_first, 2), "do": "feel", "feel": "bigger", "color": ""}])
    _s, _r, f = _play_at(mid_first + 0.5)
    assert f.feel == ("bigger", "")
    _s, _r, f = _play_at(in_second)
    assert f.feel == ("", "")


def test_cues_play_under_the_apps_own_studio_and_stand_aside_for_a_held_look(tmp_path):
    """Fresh review: the app's studio is live with a 3 s crossfade, so it is never idle(); cues must
    still play there, and stand aside only while he holds something (a look, a blackout)."""
    from tools.gigbar_lights import studio as studio_mod
    _set_cues([{"at": 40.0, "do": "hit", "size": 1}])

    def run(prepare):
        clock = demo_songs.SongClock()
        clock.report(SONG.id, 39.9, True, now=1000.0)
        show = Show(analyze=False, latency_ms=0.0)
        show.studio = studio_mod.Studio(path=tmp_path / "studio.json", live=True)
        assert show.studio.fade_s > 0 and not show.studio.idle()
        prepare(show.studio)
        feed = demo_songs.SongFeed(show, SONG, clock)
        now = 1000.0
        while now < 1000.25:
            feed(now)
            now += 512 / 44100
        show.render(now)
        return show.rig

    assert _white(run(lambda st: None))
    assert not _white(run(lambda st: setattr(st, "blackout", True)))


def test_a_cue_write_that_does_not_fit_is_refused_not_dropped_from_another_song():
    doc = contract.normalize({})
    full = [{"at": j * 3.0, "do": "feel", "feel": "bigger", "color": "#123456"} for j in range(contract.MAX_CUES)]
    refused = None
    for i in range(40):
        try:
            doc, _ = contract.apply_ops(doc, [{"path": f"cues.song-{i}", "value": full}])
        except contract.ContractError as e:
            refused = (i, str(e))
            break
    assert refused and "full" in refused[1]
    assert len(doc["cues"]) == refused[0] and all(len(v) == contract.MAX_CUES for v in doc["cues"].values())
    with pytest.raises(contract.ContractError):
        contract.apply_ops(contract.normalize({}), [{"path": f"cues.{KEY}", "value": full + [{"at": 999.0, "do": "hit"}]}])
