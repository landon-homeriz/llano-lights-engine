"""The wedding night (Llano PM #23179): ready-to-play cuts that hand off cleanly in Mixxx's Auto DJ,
holds for the live moments, and the run of show a first-time DJ follows with one button."""
import math

import pytest

np = pytest.importorskip("numpy")

from tools.gigbar_lights import run_of_show as ros  # noqa: E402
from tools.gigbar_lights import set_cuts as sc  # noqa: E402

RATE = 22050


def song(secs=60.0, level=0.3, fade_out=0.0, lead_silence=0.0, hz=220.0, rate=RATE):
    """A steady tone with a click every half second (so there are hits to snap to)."""
    n = int(secs * rate)
    t = np.arange(n) / rate
    x = level * np.sin(2 * np.pi * hz * t)
    x[:: rate // 2] += level
    if fade_out:
        k = int(fade_out * rate)
        x[-k:] *= np.linspace(1, 0, k) ** 2
    if lead_silence:
        x = np.concatenate([np.zeros(int(lead_silence * rate)), x])
    return np.stack([x, x], axis=1).astype(np.float32)


# --- the cut ---------------------------------------------------------------------------------------


@pytest.fixture
def classic_night(monkeypatch):
    """The classic order with no quiet background under the toasts and cake: what these build tests were
    written against before his own order became the default (BL #12360). His order is checked in
    test_his_reception_order_is_the_default and test_his_reception_night_builds."""
    from tests.gigbar_lights.test_wedding_night import CLASSIC
    from tools.gigbar_lights import run_of_show as ros
    monkeypatch.setattr(ros, "DEFAULT_ORDER", CLASSIC)
    monkeypatch.setattr(ros, "BACKGROUND_UNDER", ())

def test_a_cut_starts_at_the_first_sound_and_keeps_a_whole_song_whole():
    x = song(60, lead_silence=1.5)
    c = sc.plan(x, RATE, "dancing")
    assert abs(c.start_s - 1.48) < 0.05          # 20 ms before the first sound
    assert c.kind == "whole" and c.end_s > 61.0  # a hard stop is not trimmed
    y = sc.render(x, RATE, c)
    assert abs(len(y) / RATE - c.plays_s) < 0.01


def test_the_first_note_lands_at_full_volume_as_auto_dj_finishes_fading_in():
    a = sc.render(song(40), RATE, sc.plan(song(40), RATE))
    b = sc.render(song(40, hz=330), RATE, sc.plan(song(40, hz=330), RATE))
    for curve in ("additive", "cut"):
        mix, first_note = sc.handoff(a, b, RATE, curve=curve, before_s=4, after_s=4)
        i = int(first_note * RATE)
        # the mix never drops out across the handoff (that b's first note is at full level is
        # measured on the rendered audio in test_wedding_night_hardening.py)
        env = sc.envelope(mix, RATE, 0.25)
        assert env.min() > -30, (curve, env.min())
        assert np.abs(mix).max() <= 1.0
        assert i < len(mix)


def test_mixxx_stock_crossfader_fades_in_then_out():
    assert sc.xfade_gains(-1.0) == (1.0, 0.0)
    assert sc.xfade_gains(-0.5) == (1.0, 0.5)
    assert sc.xfade_gains(0.0) == (1.0, 1.0)
    assert sc.xfade_gains(0.5) == (0.5, 1.0)
    assert sc.xfade_gains(1.0) == (0.0, 1.0)
    left, right = sc.xfade_gains(-0.9, "cut")    # fast cut: both decks full almost everywhere
    assert left == 1.0 and right > 0.99


def test_a_long_studio_fade_is_left_before_it_dies():
    x = song(90, fade_out=25)
    c = sc.plan(x, RATE, "dancing")
    assert c.kind == "left the fade"
    assert 60 < c.end_s < 85                     # well before the 90 s end, after the full part
    assert "fading out" in c.why
    quiet = sc.plan(x, RATE, "dinner")           # background parts leave later and fade longer
    assert quiet.end_s >= c.end_s and quiet.fade_s >= sc.TAIL_S


def test_his_own_leave_point_wins_and_lands_on_a_hit():
    x = song(200)
    c = sc.plan(x, RATE, "dancing", leave_at_s=150.2)
    assert c.kind == "yours" and abs(c.end_s - 150.2) <= 0.41     # the nearest hit either side
    assert abs((c.end_s * 2) - round(c.end_s * 2)) < 0.05      # snapped to a half-second click
    assert sc.plan(x, RATE, leave_at_s=5).kind == "whole"       # a leave point 5 s in is ignored


def test_a_dance_cut_starts_where_the_band_comes_in_and_leaves_when_the_music_has_gone():
    # 6 s of soft intro (22 dB under the song), 40 s of song, then 5 s of quiet ring-out
    intro, body, ring = song(6, level=0.02), song(40, level=0.25), song(5, level=0.004)
    x = np.concatenate([intro, body, ring])
    c = sc.plan(x, RATE, "dancing")
    assert c.kind == "trimmed" and 5.0 <= c.start_s <= 6.0 and c.fade_in_s > 0
    assert "where the music arrives" in c.why
    assert 46.0 <= c.end_s <= 47.2                       # the ring-out is not played out
    y = sc.render(x, RATE, c)
    assert abs(y[int(sc.LEAD_S * RATE)]).max() < 0.01    # faded in from the trim point: no click
    # dinner keeps the soft intro and more of the ring-out; a kept-whole dance song keeps its intro
    assert sc.plan(x, RATE, "dinner").start_s < 0.1
    whole = sc.plan(x, RATE, "dancing", whole=True)
    assert whole.start_s < 0.1 and whole.kind == "whole" and whole.end_s <= 47.2
    # two such songs back to back: no dead air at the handoff
    a = sc.render(x, RATE, c)
    mix, _ = sc.handoff(a, a, RATE, before_s=3, after_s=4)
    env = sc.envelope(mix, RATE, 0.1)
    assert (env < -40).sum() * 0.1 <= 1.5


def test_a_line_dance_is_never_cut_short():
    x = song(200, fade_out=30)
    assert sc.plan(x, RATE, whole=True).kind == "whole"


def test_one_level_for_the_set_that_every_song_can_reach():
    loud, quiet = song(40, level=0.5), song(40, level=0.05)
    # an old recording: quiet body, one tall drum hit
    old = song(40, level=0.04)
    old[RATE * 10] = 0.95
    cuts = [sc.plan(x, RATE) for x in (loud, quiet, old)]
    level = sc.set_level(cuts)
    assert level <= sc.TARGET_LUFS
    outs = [sc.render(x, RATE, c) for x, c in zip((loud, quiet, old), cuts)]
    lufs = [sc.loudness(y[int(sc.LEAD_S * RATE):], RATE) for y in outs]
    assert max(lufs) - min(lufs) < 0.6           # all three within about half a dB
    assert all(np.abs(y).max() <= sc.PEAK_CEILING + 1e-3 for y in outs)   # and none clips


def test_loudness_follows_level():
    a, b = sc.loudness(song(20, level=0.2), RATE), sc.loudness(song(20, level=0.1), RATE)
    assert a - b == pytest.approx(6.02, abs=0.2)
    assert sc.loudness(np.zeros((RATE * 5, 2), dtype=np.float32), RATE) == -70.0


def test_mixdown_is_every_cut_joined_as_auto_dj_joins_them():
    cuts = [sc.render(song(20, hz=h), RATE, sc.plan(song(20, hz=h), RATE)) for h in (220, 330, 440)]
    out = sc.mixdown(cuts, RATE)
    assert len(out) == sum(len(c) for c in cuts) - 2 * int(sc.TRANSITION_S * RATE)
    assert np.abs(out).max() <= 1.0
    assert len(sc.mixdown([], RATE)) == 0


# --- files ---------------------------------------------------------------------------------------

def test_cut_and_hold_files_read_back(tmp_path):
    pytest.importorskip("soundfile")
    x = song(12, rate=44100)
    c = sc.plan(x, 44100)
    p = sc.write(tmp_path / "a" / "Artist - Title.flac", sc.render(x, 44100, c), 44100, "Artist", "Title", "Cuts")
    y, rate = sc.read(p)
    assert rate == 44100 and abs(len(y) / rate - c.plays_s) < 0.01
    import soundfile
    with soundfile.SoundFile(str(p)) as f:
        assert (f.artist, f.title) == ("Artist", "Title")
    assert not list(tmp_path.glob("**/*.part"))           # written under a temp name, then renamed


def test_each_hold_is_an_hour_of_silence_of_its_own_length(tmp_path):
    pytest.importorskip("soundfile")
    import soundfile
    a = sc.hold(tmp_path / "h0.flac", 0, "HOLD - Toasts", rate=8000)
    b = sc.hold(tmp_path / "h1.flac", 1, "HOLD - Cake", rate=8000)
    ia, ib = soundfile.info(str(a)), soundfile.info(str(b))
    assert ia.frames / 8000 == 3600 and ib.frames / 8000 == 3607   # the lights tell tracks apart by length
    assert a.stat().st_size < 200_000                               # an hour of silence is a tiny file
    assert len({sc.hold_seconds(n) for n in range(12)}) == 12


def test_a_blanked_out_mp3_is_caught_by_name(tmp_path):
    pytest.importorskip("soundfile")
    p = tmp_path / "Tim - Broken.mp3"
    # an ID3 tag (its padding is zeros and must not count), some "audio", then a 256 KB hole
    tag = b"ID3\x04\x00\x00" + bytes([0, 0, 0x10, 0]) + b"\x00" * 2048
    p.write_bytes(tag + b"\xff\xfb\x90\x00" * 50_000 + b"\x00" * 262_144 + b"\xff\xfb\x90\x00" * 50_000)
    assert sc.blank_seconds(tmp_path / "x.flac") == 0.0
    with pytest.raises(sc.DamagedFile) as e:
        sc.read(p)
    assert "Tim - Broken.mp3" in str(e.value) and "Replace the file" in str(e.value)


# --- the run of show ------------------------------------------------------------------------------

def S(artist, title, secs=200, **kw):
    return {"artist": artist, "title": title, "secs": secs, **kw}


PARTS = {
    "cocktail": [S("A", f"Cocktail {i}") for i in range(4)],
    "dinner": [S("B", f"Dinner {i}") for i in range(4)],
    "dancing": [S("C", f"Dance {i}", energy=e) for i, e in enumerate((0.9, 0.7, 0.8, 0.9, 0.5, 0.8, 0.9, 0.95))],
}
MOMENT_SONGS = {"first-dance": S("Randy Travis", "Forever and Ever, Amen", 213),
                "last-dance": S("Josh Turner", "Why Don't We Just Dance", 193)}


# The order most wedding DJs use, which DEFAULT_ORDER was until his own timeline replaced it (BL #12360).
# The run-of-show mechanics below (sets split around the bouquet, holds inside the dancing, the sheet's
# words) are checked on it; his own order is checked in test_his_reception_order_is_the_default.
CLASSIC = ("cocktail", "entrance", "first-dance", "welcome", "dinner", "toasts", "cake",
           "father-daughter", "mother-son", "dancing", "bouquet", "garter", "dancing", "last-dance", "close",
           "send-off")


def test_his_reception_order_is_the_default():
    """His printed timeline for 2026-11-25 (BL #12360): every part its own step he advances himself."""
    exit_songs = {**MOMENT_SONGS, "exit-prep": S("Journey", "Don't Stop Believin'", 250),
                  "exit": S("Neil Diamond", "Sweet Caroline", 201)}
    steps = ros.plan({**PARTS, "background": PARTS["dinner"][:2]}, exit_songs)
    assert [(s.kind, s.key) for s in steps] == [
        ("music", "cocktail"), ("hold", "entrance"), ("music", "dinner"), ("hold", "first-dance"),
        ("song", "first-dance"), ("hold", "father-daughter"), ("hold", "mother-son"),
        ("hold", "toasts"), ("music", "background"), ("hold", "cake"), ("music", "background"),
        ("music", "dancing"), ("hold", "exit-prep"), ("song", "exit-prep"), ("hold", "exit"), ("song", "exit")]
    names = [s.name for s in steps]
    assert "Mother-groom dance" in names and "Toasts and speeches: quiet background" in names
    assert "Last dance" not in " ".join(names) and "Closing song" not in names
    bed = [s for s in steps if s.key == "background"]
    assert all(s.look in ("toast", "cake") and [x["title"] for x in s.songs] == ["Dinner 0", "Dinner 1"] for s in bed)
    show = ros.show_songs(steps)
    assert [x["title"] for x in show if x.get("moment") == "background"] == [], "a dinner song again is not a new show song"
    # no songs picked for the exit yet: the holds stay, and the sheet says so
    texts = [c["text"] for c in ros.checks(ros.plan(PARTS, MOMENT_SONGS))]
    assert any("Prepare for grand exit has no song yet" in t for t in texts)
    assert any("Bride and groom exit has no song yet" in t for t in texts)


def test_the_default_night_runs_in_the_order_dj_s_use():
    steps = ros.plan(PARTS, MOMENT_SONGS, order=CLASSIC)
    assert [(s.kind, s.key) for s in steps] == [
        ("music", "cocktail"), ("hold", "entrance"), ("hold", "first-dance"), ("song", "first-dance"),
        ("hold", "welcome"), ("music", "dinner"), ("hold", "toasts"), ("hold", "cake"),
        ("hold", "father-daughter"), ("hold", "mother-son"), ("music", "dancing"), ("hold", "bouquet"),
        ("music", "dancing"), ("hold", "last-dance"), ("song", "last-dance"), ("hold", "send-off")]
    # a new playlist opens only where music has to be left
    assert [s.name for s in steps if s.opens] == ["Cocktail hour", "Grand entrance", "Toasts and speeches", "Last dance"]


def test_dancing_splits_at_a_breather_not_a_peak():
    a, b = ros.split_dancing(PARTS["dancing"], 2)
    assert a[-1]["title"] == "Dance 4"            # the 0.5-energy song ends set 1
    assert [s["title"] for s in a + b] == [s["title"] for s in PARTS["dancing"]]
    assert ros.split_dancing(PARTS["dancing"], 1) == [PARTS["dancing"]]
    assert len(ros.split_dancing(PARTS["dancing"][:1], 3)) == 1


def test_playlists_carry_holds_songs_and_a_safety_pass():
    pls = ros.playlists(ros.plan(PARTS, MOMENT_SONGS, order=CLASSIC))
    assert [p.n for p in pls] == [1, 2, 3, 4]
    assert pls[0].file == "1 - Cocktail hour.m3u8"
    one = pls[0].rows
    assert [r["title"] for r in one if not r["repeat"]] == [f"Cocktail {i}" for i in range(4)]
    assert [r["title"] for r in one if r["repeat"]] == ["Cocktail 2", "Cocktail 3", "Cocktail 0", "Cocktail 1"]
    two = pls[1].rows
    assert [r["kind"] for r in two[:4]] == ["hold", "hold", "song", "hold"]
    assert two[2]["title"] == "Forever and Ever, Amen" and two[2]["look"] == "first-dance"
    three = [r for r in pls[2].rows if not r["repeat"]]
    assert [r["key"] for r in three if r["kind"] == "hold"] == ["toasts", "cake", "father-daughter", "mother-son", "bouquet"]
    # the bouquet hold sits INSIDE the dancing, between the two sets, and only the last set repeats
    kinds = [r["kind"] for r in three]
    assert kinds.index("hold", 4) > kinds.index("music")
    assert {r["title"] for r in pls[2].rows if r["repeat"]} == {"Dance 5", "Dance 6", "Dance 7"}
    assert [r["kind"] for r in pls[3].rows] == ["hold", "song", "hold"]   # the night ends on a hold: nothing plays after


def test_m3u8_names_every_file_and_shows_a_gap_instead_of_hiding_it():
    pl = ros.playlists(ros.plan(PARTS, MOMENT_SONGS, order=CLASSIC))[1]
    text = ros.m3u8(pl, lambda r: None if r["title"] == "Dinner 2" else f"cuts/{r['artist']} - {r['title']}.flac")
    assert text.startswith("#EXTM3U\n#PLAYLIST:2 - Grand entrance, First dance, Welcome and blessing, more\n")
    assert "cuts/Llano hold - HOLD - Grand entrance - press Fade Now when it is over.flac" in text
    assert "# MISSING: B - Dinner 2" in text
    assert "# --- the same songs again, in case this part runs long ---" in text


def test_a_skipped_moment_and_his_own_order():
    steps = ros.plan(PARTS, MOMENT_SONGS, skip={"mother-son", "bouquet", "welcome", "cake", "send-off"},
                     order=("cocktail", "entrance", "dinner", "toasts", "first-dance", "father-daughter",
                            "mother-son", "dancing", "last-dance"))
    assert [s.key for s in steps] == ["cocktail", "entrance", "dinner", "toasts", "first-dance", "first-dance",
                                      "father-daughter", "dancing", "last-dance", "last-dance"]
    assert len([s for s in steps if s.key == "dancing"][0].songs) == 8      # one set: nothing splits it


def test_clock_times_and_the_not_enough_music_warning():
    assert ros.parse_clock("6") == 360 and ros.parse_clock("6:30 pm") == 390 and ros.parse_clock("18:30") == 390
    assert ros.parse_clock("12:15") == 15 and ros.parse_clock("12:30 am") == 750 and ros.parse_clock("soon") is None
    steps = ros.plan(PARTS, MOMENT_SONGS, order=CLASSIC, times={"cocktail": "5:00", "entrance": "6:00", "dancing": "8:00",
                                                 "bouquet": "9:00", "dancing 2": "9:10", "last-dance": "10:25"})
    cocktail = steps[0]
    assert cocktail.minutes == 60
    found = ros.checks(steps)
    assert found[0]["level"] == "problem" and "Cocktail hour is planned for 60 minutes and has 13 minutes" in found[0]["text"]
    # the two dance sets around the bouquet are weighed together against 8:00 to 10:25, not one by one
    w = [x for x in ros.windows(steps) if x["name"] == "Dancing"]
    assert [x["minutes"] for x in w] == [60, 75] and round(w[0]["music"]) == 17          # 8:00 to the bouquet at 9:00, then on
    whole = ros.windows(ros.plan(PARTS, MOMENT_SONGS, order=CLASSIC, times={"dancing": "8:00", "last-dance": "10:25"}))
    assert len(whole) == 1 and whole[0]["minutes"] == 145 and round(whole[0]["music"]) == 26 and whole[0]["holds"] == 1
    texts = [c["text"] for c in ros.checks(ros.plan(PARTS, MOMENT_SONGS, order=CLASSIC, times={"dancing": "8:00", "last-dance": "10:25"}))]
    assert sum("Dancing is planned for 145 minutes and has 26 minutes" in x for x in texts) == 1
    assert not any("set 1" in x for x in texts)
    assert any("Father-daughter dance has no song yet" in c["text"] for c in found)
    # no times given: a general heads-up about a short dance floor, not a made-up problem
    loose = ros.checks(ros.plan(PARTS, MOMENT_SONGS, order=CLASSIC))
    assert loose and all(c["level"] == "heads-up" for c in loose)
    assert any("Dancing has 26 minutes of music" in c["text"] for c in loose)


def test_music_time_counts_the_overlap_between_songs():
    assert ros.music_seconds([S("a", "b", 100)] * 3) == 300 - 2 * ros.TRANSITION_S
    assert ros.music_seconds([]) == 0
    assert ros.TRANSITION_S == sc.TRANSITION_S


def test_the_sheet_says_how_to_move_on_at_every_step():
    steps = ros.plan(PARTS, MOMENT_SONGS, order=CLASSIC, times={"cocktail": "5:00"})
    rows = ros.sheet_rows(steps)
    assert len(rows) == len(steps)
    by = {r["what"]: r for r in rows}
    # music he has to leave: how to start the next playlist, and what happens if he waits
    assert by["Cocktail hour"]["next"].startswith("When it is time for the grand entrance: in Mixxx, right click playlist 2 "
                                                  "in the list on the left, choose Add to Auto DJ Queue (replace), then press Fade Now.")
    assert "start again after 13 minutes" in by["Cocktail hour"]["next"] and by["Cocktail hour"]["playlist"] == 1
    # a hold: say this, then Fade Now, and what that starts
    ent = by["Grand entrance"]
    assert ent["say"].startswith("Announce the wedding party") and ent["playlist"] == 2
    assert ent["next"] == "When you are ready, press Fade Now in Mixxx: the lights change for the first dance, still with no music."
    assert by["First dance"]["next"] == "When you are ready, press Fade Now in Mixxx: the song starts (Forever and Ever, Amen)."
    assert by["Welcome and blessing"]["next"] == "When you are ready, press Fade Now in Mixxx: dinner starts."
    assert "waits for you. It does not move on until you press Fade Now." in ent["detail"]
    # a song and music inside a playlist need nothing
    assert by["First dance: Forever and Ever, Amen"]["next"] == ("Nothing. When the song ends, Mixxx goes quiet by itself "
                                                                 "and waits for you. Next: Welcome and blessing.")
    assert by["Dancing, set 1"]["next"] == ("Nothing. When the last song ends, Mixxx goes quiet by itself and waits for you. "
                                            "Next: Bouquet toss.")
    assert by["Send-off"]["next"].startswith("Nothing more: this is the end of the night")
    # the lights, in words he can check against the room
    assert by["Toasts and speeches"]["lights"] == "Warm and steady, nothing moving" and by["Dinner"]["lights"] == "Each song's own look"
    assert by["Bouquet toss"]["lights"] == by["Toasts and speeches"]["lights"]
    page = ros.sheet_html("Avery & Jordan", steps, ros.checks(steps))
    assert "Avery &amp; Jordan: run of show" in page and "To start the night:" in page and "Enable Auto DJ" in page
    assert page.count("<tr>") == len(steps) + 1 and "<th class=t>Time</th>" in page
    assert "<th class=t>Time</th>" not in ros.sheet_html("x", ros.plan(PARTS, MOMENT_SONGS, order=CLASSIC))    # no times: no empty column


def test_the_show_gives_every_hold_and_moment_its_look():
    songs = ros.show_songs(ros.plan(PARTS, MOMENT_SONGS, order=CLASSIC))
    holds = [s for s in songs if s["artist"] == "Llano hold"]
    assert {s["look"] for s in holds} == {"entrance", "first-dance", "toast", "cake", "father-daughter", "last-dance"}
    fd = next(s for s in songs if s["title"] == "Forever and Ever, Amen")
    assert fd["look"] == "first-dance" and fd["moment"] == "first-dance"
    assert next(s for s in songs if s["title"] == "Dinner 0")["part"] == "dinner"
    assert math.isclose(sum(s["secs"] for s in songs if s.get("part") == "cocktail"), 800)


# --- the build: a folder of songs in, a night he plays from out ------------------------------------

from tools.gigbar_lights import settings_contract as contract  # noqa: E402
from tools.gigbar_lights import wedding_night as wn  # noqa: E402


def make_folder(tmp_path, names, secs=8):
    sf = pytest.importorskip("soundfile")
    src = tmp_path / "Wedding"
    for part, artist, title in names:
        d = src / part
        d.mkdir(parents=True, exist_ok=True)
        sf.write(str(d / f"{artist} - {title}.wav"), song(secs, rate=8000, hz=200 + 13 * len(title)), 8000)
    return src


NIGHT = [("1 - Cocktail Hour", "A", "Sip"), ("1 - Cocktail Hour", "B", "Mingle"),
         ("2 - Dinner", "C", "Eat"), ("2 - Dinner", "Randy Travis", "Forever and Ever, Amen"),
         ("3 - Dancing", "D", "Jump"), ("3 - Dancing", "E", "Spin"), ("3 - Dancing", "F", "Shout"),
         ("3 - Dancing", "Josh Turner", "Why Don't We Just Dance"), ("3 - Dancing", "Journey", "Don't Stop Believin'")]
PART_OF = {"1 - Cocktail Hour": "cocktail", "2 - Dinner": "dinner", "3 - Dancing": "dancing"}


def night_songs():
    songs = [{"artist": a, "title": t, "part": PART_OF[p]} for p, a, t in NIGHT if a != "Journey"]
    songs[3]["moment"] = "first-dance"
    songs[-1]["moment"] = "last-dance"
    return songs


def test_the_night_is_built_into_one_folder_he_plays_from(tmp_path, classic_night):
    sf = pytest.importorskip("soundfile")
    src = make_folder(tmp_path, NIGHT)
    (src / "1 - Cocktail Hour" / "A - Sip.wav").write_bytes(b"RIFF this is not audio")     # one broken file
    seen = []
    out = tmp_path / "night"
    r = wn.build(out, night_songs() + [{"artist": "Nobody", "title": "Not Here", "part": "dinner"}],
                 wn.index_folder(src), title="Avery & Jordan",
                 moment_songs={"close": {"artist": "Journey", "title": "Don't Stop Believin'"}},
                 on_progress=lambda what, i, n: seen.append(what))
    # the broken and the missing song are named, in plain words, and left out as a visible gap
    assert [d["song"] for d in r["damaged"]] == ["A - Sip"] and r["missing"] == ["Nobody - Not Here"]
    assert r["checks"][0]["level"] == "problem" and any("Replace the file" in c["text"] for c in r["checks"])
    assert [p["file"] for p in r["playlists"]] == [
        "1 - Cocktail hour.m3u8", "2 - Grand entrance, First dance, Welcome and blessing, more.m3u8",
        "3 - Toasts and speeches, Cake cutting, Father-daughter dance, mo.m3u8", "4 - Last dance, Closing song, Send-off.m3u8"]
    one = (out / "1 - Cocktail hour.m3u8").read_text(encoding="utf-8")
    assert "Songs/1 - Cocktail hour/B - Mingle.flac" in one and "A - Sip" not in one
    two = (out / r["playlists"][1]["file"]).read_text(encoding="utf-8")
    assert "Holds/Llano hold - HOLD - Grand entrance - press Fade Now when it is over.flac" in two
    assert "Songs/Moments/Randy Travis - Forever and Ever, Amen.flac" in two          # the first dance, out of dinner
    assert "Songs/2 - Dinner/C - Eat.flac" in two and "Forever and Ever, Amen.flac" not in two.rsplit("Welcome and blessing - press", 1)[1]
    last = (out / r["playlists"][3]["file"]).read_text(encoding="utf-8").splitlines()
    files = [x for x in last if not x.startswith("#")]
    assert [Path(f).name.split(" - ")[1] for f in files] == ["HOLD", "Why Don't We Just Dance.flac", "Don't Stop Believin'.flac", "HOLD"]
    # every file a playlist names is there, plays, and the same loudness as its neighbours
    for pl in r["playlists"]:
        for line in (out / pl["file"]).read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                assert (out / line).is_file(), line
    cuts = [sc.read(out / c["file"]) for c in r["cuts"]]
    lufs = [sc.loudness(y[int(sc.LEAD_S * rate):], rate) for y, rate in cuts]
    assert max(lufs) - min(lufs) < 1.0
    assert (out / "Run of show.html").read_text(encoding="utf-8").count("Fade Now") > 5
    # a backup for a phone: each stretch of music, and each moment's song, numbered in night order
    assert (out / r["handoffs"]).is_file() and all((out / b).is_file() for b in r["backups"])
    assert [Path(b).stem for b in r["backups"]] == [
        "1 - Cocktail hour", "2 - First dance Forever and Ever, Amen", "3 - Dinner", "4 - Dancing, set 1", "5 - Dancing, set 2",
        "6 - Last dance Why Don't We Just Dance", "7 - Closing song Don't Stop Believin'"]
    assert json_load(out / "night.json")["title"] == "Avery & Jordan"
    assert any(w.startswith("Reading") for w in seen) and any(w.startswith("Writing the backup") for w in seen)
    assert (src / "2 - Dinner" / "C - Eat.wav").stat().st_size > 1000 and not list(src.rglob("*.flac"))   # originals untouched
    # building again replaces last time's playlists instead of leaving them beside the new ones
    (out / "9 - Old.m3u8").write_text("#EXTM3U\n")
    wn.build(out, night_songs(), wn.index_folder(src), title="Avery & Jordan", extras=False)
    assert not (out / "9 - Old.m3u8").exists()
    assert sf.info(str(out / "Holds" / "Llano hold - HOLD - Toasts and speeches - press Fade Now when it is over.flac")).duration >= 3600


def json_load(p):
    import json
    return json.loads(Path(p).read_text(encoding="utf-8"))


from pathlib import Path  # noqa: E402



def test_the_sing_along_the_arranger_puts_after_the_last_dance_closes_the_night(tmp_path, classic_night):
    """Whole-app audit (2026-11-12): the arranger plays the last dance just before the final
    sing-along (1.18.1), but the build kept the sing-along in the dancing (and its repeat) and the
    last dance ended the night. The page sends the close off with no song unless he types one."""
    pytest.importorskip("soundfile")
    src = make_folder(tmp_path, NIGHT)
    songs = [{"artist": a, "title": t, "part": PART_OF[p]} for p, a, t in NIGHT]   # Journey last, as arranged
    songs[3]["moment"] = "first-dance"
    songs[-2]["moment"] = "last-dance"
    out = tmp_path / "night"
    r = wn.build(out, songs, wn.index_folder(src), skip={"garter", "close"}, extras=False,
                 moment_songs={"last-dance": {"artist": "Josh Turner", "title": "Why Don't We Just Dance"}})
    last = (out / r["playlists"][-1]["file"]).read_text(encoding="utf-8").splitlines()
    names = [Path(f).name.split(" - ")[1] for f in last if f and not f.startswith("#")]
    assert names == ["HOLD", "Why Don't We Just Dance.flac", "Don't Stop Believin'.flac", "HOLD"]
    dancing = "".join((out / p["file"]).read_text(encoding="utf-8") for p in r["playlists"][:-1])
    assert "Don't Stop Believin'" not in dancing     # once, at the end, never before the last dance
    # a closing song of his own still wins, and the arranged sing-along plays in the dancing
    r = wn.build(tmp_path / "night2", songs, wn.index_folder(src), skip={"garter"}, extras=False,
                 moment_songs={"close": {"artist": "F", "title": "Shout"}})
    last = (tmp_path / "night2" / r["playlists"][-1]["file"]).read_text(encoding="utf-8")
    assert "Shout.flac" in last and "Don't Stop Believin'" not in last

def test_holds_and_moment_songs_get_their_looks_through_saved_styles(tmp_path, classic_night):
    pytest.importorskip("soundfile")
    src = make_folder(tmp_path, NIGHT, secs=4)
    r = wn.build(tmp_path / "n", night_songs(), wn.index_folder(src), extras=False,
                 moment_songs={"close": {"artist": "Journey", "title": "Don't Stop Believin'"}})
    doc = contract.defaults()
    ops, notes = wn.looks_ops(r, doc)
    assert notes == []
    styles = {o["path"][7:] for o in ops if o["path"].startswith("styles.")}
    assert styles == {"grand-entrance", "first-dance", "toast", "parent-dance", "cake-cutting", "last-dance"}
    new, applied = contract.apply_ops(doc, ops)                     # the contract takes every change
    assert len(applied) == len(ops) and set(new["styles"]) == styles
    hold = contract.track_key("Llano hold", ros.hold_title("Toasts and speeches"))
    assert new["songs"][hold] == "toast"
    assert new["songs"][contract.track_key("Randy Travis", "Forever and Ever, Amen")] == "first-dance"
    assert contract.track_key("Journey", "Don't Stop Believin'") not in new["songs"]   # the closer keeps its own look
    assert wn.looks_ops(r, new) == ([], [])                         # a second build changes nothing
    # no room for another style: said in plain words, nothing half done
    full = contract.apply_ops(doc, [{"path": f"styles.s{i}", "value": new["styles"]["toast"]} for i in range(contract.MAX_STYLES)])[0]
    ops2, notes2 = wn.looks_ops(r, full)
    assert ops2 == [] and len(notes2) == 6 and "Delete one you don't use" in notes2[0]


def test_mixxx_auto_dj_settings_are_read_and_judged(tmp_path):
    cfg = tmp_path / "mixxx.cfg"
    assert wn.check_mixxx(cfg)["found"] is False
    cfg.write_text("[Auto DJ]\nTransition 10\nTransitionMode 0\nRequeue 1\n\n[Mixer Profile]\nxFaderReverse 0\n")
    got = wn.check_mixxx(cfg)
    assert got["found"] and not got["ok"]
    bad = {i["name"]: i for i in got["items"] if not i["ok"]}
    assert set(bad) == {"Auto DJ transition", "Auto DJ mode", "Re-queue played songs"}
    assert bad["Auto DJ transition"]["is"] == "10 seconds" and "set the box marked sec. beside Full Track" in bad["Auto DJ transition"]["fix"]
    assert bad["Auto DJ mode"]["is"] == "Full Intro + Outro"
    cfg.write_text("[Auto DJ]\nTransition 2\nTransitionMode 2\nRequeue 0\nEnableRandomQueue 0\n")
    assert wn.check_mixxx(cfg)["ok"]
    cfg.write_text("[Auto DJ]\nTransitionMode 2\n")                 # never set: Mixxx's own default is 10
    assert wn.check_mixxx(cfg)["items"][0]["is"] == "10 seconds"
    assert cfg.read_text() == "[Auto DJ]\nTransitionMode 2\n"       # it only reads



@pytest.mark.parametrize("title", ["Con", "aux", "NUL", "Com1", "LPT9", "con.mix"])
def test_a_song_named_like_a_windows_device_gets_a_name_windows_accepts(title):
    """Whole-app audit (2026-11-12): Windows refuses CON, AUX, NUL, COM1... with any extension."""
    name = wn.safe_name(title)
    assert not wn.RESERVED.fullmatch(name.split(".")[0].strip()) and name.startswith(title.split(".")[0])
    assert wn.safe_name("Contact") == "Contact" and wn.safe_name("Aux Cord - Nul Points") == "Aux Cord - Nul Points"

def test_a_kept_intro_is_built_whole_and_the_report_says_which_song(tmp_path):
    sf = pytest.importorskip("soundfile")
    src = tmp_path / "W" / "3 - Dancing"
    src.mkdir(parents=True)
    soft = np.concatenate([song(6, level=0.02, rate=8000), song(30, level=0.25, rate=8000)])
    sf.write(str(src / "A - Soft Start.wav"), soft, 8000)
    sf.write(str(src / "B - Plain.wav"), song(30, rate=8000), 8000)
    # Plain opens the dancing (a set's first song keeps its intro, PM #23864), so Soft Start's is cut
    songs = [{"artist": "B", "title": "Plain", "part": "dancing"}, {"artist": "A", "title": "Soft Start", "part": "dancing"}]
    files = wn.index_folder(tmp_path / "W")
    r = wn.build(tmp_path / "n1", songs, files, extras=False)
    cut = {c["title"]: c for c in r["cuts"]}
    assert cut["Soft Start"]["kind"] == "trimmed" and cut["Soft Start"]["start_s"] > 4 and cut["Plain"]["kind"] == "whole"
    assert cut["Soft Start"]["key"] == wn.key_of(songs[1])
    r2 = wn.build(tmp_path / "n2", songs, files, extras=False, keep_whole={cut["Soft Start"]["key"]})
    kept = {c["title"]: c for c in r2["cuts"]}["Soft Start"]
    assert kept["kind"] == "whole" and kept["start_s"] < 0.1 and kept["plays_s"] > cut["Soft Start"]["plays_s"] + 4


def test_file_names_are_safe_on_windows():
    assert wn.safe_name('AC/DC - Who Made Who?') == "AC DC - Who Made Who"
    assert wn.safe_name("  a:b*c|d  ") == "a b c d" and wn.safe_name("...") == "song"
