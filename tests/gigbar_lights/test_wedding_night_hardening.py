"""The wedding night under bad input (Llano PM #23179, the fresh-eyes review of PR #77): files the
audio library cannot decode, a build pressed twice, songs that would vanish, a rebuild over the last
one, and the numbers the cuts rest on. One test per finding; each failed before its fix."""
import json
import os
import struct
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")

from tools.gigbar_lights import run_of_show as ros  # noqa: E402
from tools.gigbar_lights import set_cuts as sc  # noqa: E402
from tools.gigbar_lights import settings_contract as contract  # noqa: E402
from tools.gigbar_lights import wedding_night as wn  # noqa: E402
from tests.gigbar_lights.test_wedding_night import MOMENT_SONGS, PARTS, RATE, song  # noqa: E402


@pytest.fixture(autouse=True)
def short_holds(monkeypatch):
    """An hour of silence per hold is a second of writing each; these tests build many nights."""
    monkeypatch.setattr(sc, "HOLD_S", 5)


def folder(tmp_path, names, secs=6, rate=8000, name="Wedding"):
    """A wedding folder: [(subfolder, "Artist - Title.wav")] of short tones."""
    src = tmp_path / name
    for sub, fname in names:
        d = src / sub
        d.mkdir(parents=True, exist_ok=True)
        sf.write(str(d / fname), song(secs, rate=rate, hz=200 + 7 * len(fname)), rate)
    return src


def dance(*names):
    return [{"artist": n.split(" - ")[0], "title": n.split(" - ")[1], "part": "dancing"} for n in names]


def playlist_files(out, report):
    return [line for pl in report["playlists"] for line in (out / pl["file"]).read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")]


def m4a_bytes(seconds=200, ftyp=True):
    """The start of an MPEG-4 audio file as iTunes writes it: a file-type box and a movie header that
    carries the length. No decoder here reads it, which is the point."""
    def box(kind, body):
        return struct.pack(">I", 8 + len(body)) + kind + body
    mvhd = box(b"mvhd", bytes(4) + bytes(8) + struct.pack(">II", 1000, seconds * 1000) + bytes(80))
    head = box(b"ftyp", b"M4A \x00\x00\x00\x00M4A mp42isom") if ftyp else box(b"junk", bytes(20))
    return head + box(b"moov", mvhd) + box(b"mdat", bytes(range(256)) * 40)


# --- 1: the extras can never fail the night, and never hold a set in memory ---------------------------


@pytest.fixture
def classic_night(monkeypatch):
    """The classic order with no quiet background under the toasts and cake: what these build tests were
    written against before his own order became the default (BL #12360). His order is checked in
    test_his_reception_order_is_the_default and test_his_reception_night_builds."""
    from tests.gigbar_lights.test_wedding_night import CLASSIC
    from tools.gigbar_lights import run_of_show as ros
    monkeypatch.setattr(ros, "DEFAULT_ORDER", CLASSIC)
    monkeypatch.setattr(ros, "BACKGROUND_UNDER", ())

def test_a_failed_phone_backup_never_fails_the_night(tmp_path, monkeypatch):
    src = folder(tmp_path, [("3 - Dancing", "A - One.wav"), ("3 - Dancing", "B - Two.wav")])
    order = []

    def boom(*a, **k):
        order.append("extras")
        raise MemoryError("out of memory")

    monkeypatch.setattr(wn, "_extras", boom)
    out = tmp_path / "n"
    r = wn.build(out, dance("A - One", "B - Two"), wn.index_folder(src),
                 on_built=lambda rep: order.append("built:" + str((out / "night.json").is_file())))
    assert order == ["built:True", "extras"]          # the night was whole, and saved, before the extras ran
    assert json.loads((out / "night.json").read_text(encoding="utf-8"))["playlists"]
    assert r["backups"] == [] and r["handoffs"] == ""
    note = [c for c in r["checks"] if "phone backup" in c["text"]]
    assert note and note[0]["level"] == "heads-up" and "build again" in note[0]["text"]
    assert "MemoryError" not in note[0]["text"] and "ran out of memory" in note[0]["text"]     # his words, not Python's
    assert not any(c["level"] == "problem" for c in r["checks"])


def test_the_backup_is_joined_one_song_at_a_time():
    cuts = [sc.render(song(6, hz=h), RATE, sc.plan(song(6, hz=h), RATE)) for h in (220, 330, 440, 550)]
    n = int(sc.TRANSITION_S * RATE)
    # what Auto DJ plays, worked out the plain way with everything in memory
    want = np.zeros((sum(len(c) for c in cuts) - n * 3, 2), dtype=np.float32)
    pos = np.linspace(-1.0, 1.0, n)
    g_in = np.where(pos < 0, 1.0 - np.abs(pos), 1.0).astype(np.float32)[:, None]
    g_out = np.where(pos > 0, 1.0 - np.abs(pos), 1.0).astype(np.float32)[:, None]
    at = 0
    for k, c in enumerate(cuts):
        c = c.copy()
        if k:
            c[:n] *= g_in
        if k + 1 < len(cuts):
            c[-n:] *= g_out
        want[at:at + len(c)] += c
        at += len(c) - n
    np.clip(want, -1.0, 1.0, out=want)
    loaded = []

    def loader(i):
        def load():
            loaded.append(i)
            return cuts[i]
        return load

    pieces = sc.mixdown_pieces([loader(i) for i in range(4)], RATE)
    first = next(pieces)
    assert loaded == [0]                              # nothing is read before it is needed
    got = np.concatenate([first] + list(pieces))
    assert loaded == [0, 1, 2, 3]
    assert got.shape == want.shape and np.abs(got - want).max() < 1e-6
    assert np.abs(sc.mixdown(cuts, RATE) - want).max() < 1e-6


def test_a_file_too_long_to_cut_plays_as_it_is(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "MAX_CUT_S", 5.0)
    src = folder(tmp_path, [("3 - Dancing", "A - Short.wav")], secs=4)
    sf.write(str(src / "3 - Dancing" / "DJ - Hour Mix.wav"), song(9, rate=8000), 8000)
    out = tmp_path / "n"
    r = wn.build(out, dance("A - Short", "DJ - Hour Mix"), wn.index_folder(src), extras=False)
    assert r["damaged"] == [] and r["missing"] == []
    assert "Songs/3 - Dancing/DJ - Hour Mix.wav" in playlist_files(out, r)
    assert (out / "Songs/3 - Dancing/DJ - Hour Mix.wav").stat().st_size == (src / "3 - Dancing/DJ - Hour Mix.wav").stat().st_size
    text = " ".join(c["text"] for c in r["checks"])
    assert "DJ - Hour Mix" in text and "too long to cut" in text and "plays as it is" in text


# --- 2: a file type the audio library cannot decode is not "damaged" ----------------------------------

def test_an_itunes_file_plays_as_it_is_and_is_never_called_damaged(tmp_path):
    src = folder(tmp_path, [("3 - Dancing", "A - One.wav")])
    (src / "3 - Dancing" / "Steven Curtis Chapman - Cinderella.m4a").write_bytes(m4a_bytes(263))
    (src / "3 - Dancing" / "B - Empty.m4a").write_bytes(m4a_bytes(10, ftyp=False))
    assert sc.media_seconds(src / "3 - Dancing" / "Steven Curtis Chapman - Cinderella.m4a") == 263.0
    songs = dance("A - One", "B - Empty") + [{"artist": "Steven Curtis Chapman", "title": "Cinderella", "part": "dancing",
                                               "moment": "father-daughter"}]
    out = tmp_path / "n"
    r = wn.build(out, songs, wn.index_folder(src), extras=True)
    assert [d["song"] for d in r["damaged"]] == ["B - Empty"]        # not an MPEG-4 file at all: that one is damaged
    files = playlist_files(out, r)
    assert "Songs/Moments/Steven Curtis Chapman - Cinderella.m4a" in files
    assert (out / "Songs/Moments/Steven Curtis Chapman - Cinderella.m4a").read_bytes() == m4a_bytes(263)
    note = next(c for c in r["checks"] if "Cinderella" in c["text"])
    assert note["level"] == "heads-up" and "damaged" not in note["text"] and "plays as it is" in note["text"]
    assert "MP3" in note["text"]                                      # and how to get it cut: convert it
    step = next(s for s in r["steps"] if s["kind"] == "song" and s["key"] == "father-daughter")
    assert step["songs"][0]["secs"] == 263.0                          # the plan knows how long it runs
    left = [c["text"] for c in r["checks"] if "phone backup leaves out" in c["text"]]
    assert left and "Steven Curtis Chapman - Cinderella" in left[0] and "Keep the original on the phone" in left[0]
    assert "louder or quieter" in note["text"]
    assert [u["title"] for u in r["uncut"]] == ["Cinderella"]


# --- 4: a file named by its title only ----------------------------------------------------------------

def id3(artist, title):
    def frame(fid, text):
        body = b"\x03" + text.encode("utf-8")
        return fid + struct.pack(">I", len(body)) + b"\x00\x00" + body
    frames = frame(b"TPE1", artist) + frame(b"TIT2", title)
    size = len(frames)
    return b"ID3\x03\x00\x00" + bytes([(size >> 21) & 127, (size >> 14) & 127, (size >> 7) & 127, size & 127]) + frames


def test_a_file_named_by_its_title_alone_is_found_by_its_tag(tmp_path):
    d = tmp_path / "W" / "3 - Dancing"
    d.mkdir(parents=True)
    sf.write(str(d / "raw.mp3"), song(6, rate=44100), 44100, format="MP3")
    (d / "Perfect.mp3").write_bytes(id3("Ed Sheeran", "Perfect") + (d / "raw.mp3").read_bytes())
    (d / "raw.mp3").unlink()
    files = wn.index_folder(tmp_path / "W")
    assert wn.key_of({"artist": "Ed Sheeran", "title": "Perfect"}) in files     # as the Shows page names it
    assert wn.key_of({"artist": "", "title": "Perfect"}) in files               # and as a pasted list would
    r = wn.build(tmp_path / "n", [{"artist": "Ed Sheeran", "title": "Perfect", "part": "dancing"}], files, extras=False)
    assert r["missing"] == [] and len(r["cuts"]) == 1


# --- 5, 6: the garter toss, and dancing with no moment inside it --------------------------------------

def test_the_garter_toss_is_a_hold_when_it_is_asked_for(classic_night):
    keys = [(s.kind, s.key) for s in ros.plan(PARTS, MOMENT_SONGS, skip=set())]
    assert keys[keys.index(("hold", "bouquet")) + 1] == ("hold", "garter")
    assert ("hold", "garter") not in [(s.kind, s.key) for s in ros.plan(PARTS, MOMENT_SONGS)]   # off unless asked for


def test_dancing_is_one_run_when_nothing_happens_inside_it():
    steps = ros.plan(PARTS, MOMENT_SONGS, skip={"bouquet", "garter"})
    runs = [s for s in steps if s.kind == "music" and s.key == "dancing"]
    assert len(runs) == 1 and runs[0].name == "Dancing" and len(runs[0].songs) == 8
    assert "set 2" not in " ".join(r["next"] for r in ros.sheet_rows(steps))
    pl = ros.playlists(steps)[2]
    assert len([r for r in pl.rows if r["repeat"]]) == 8          # the whole dance floor repeats, not half of it


# --- 7: a moment's song never vanishes ---------------------------------------------------------------

def test_a_skipped_or_replaced_moment_song_still_plays(tmp_path):
    src = folder(tmp_path, [("3 - Dancing", "A - One.wav"), ("3 - Dancing", "B - Ours.wav"), ("3 - Dancing", "C - Other.wav")])
    songs = dance("A - One", "B - Ours")
    songs[1]["moment"] = "first-dance"
    files = wn.index_folder(src)
    out = tmp_path / "skipped"
    r = wn.build(out, songs, files, extras=False, skip={"first-dance"})
    assert "Songs/3 - Dancing/B - Ours.flac" in playlist_files(out, r)     # the moment is off: it is a dance song again
    out = tmp_path / "replaced"
    r = wn.build(out, songs, files, extras=False, moment_songs={"first-dance": {"artist": "C", "title": "Other"}})
    got = playlist_files(out, r)
    assert "Songs/Moments/C - Other.flac" in got and "Songs/3 - Dancing/B - Ours.flac" in got


# --- 8: names in other alphabets ----------------------------------------------------------------------

def test_two_songs_named_in_another_alphabet_are_two_songs(tmp_path):
    names = ["Кино - Группа крови", "Кино - Звезда по имени Солнце", "A - One"]
    src = folder(tmp_path, [("3 - Dancing", n + ".wav") for n in names])
    out = tmp_path / "n"
    r = wn.build(out, dance(*names), wn.index_folder(src), extras=False)
    assert r["missing"] == [] and len(r["cuts"]) == 3
    got = playlist_files(out, r)
    assert "Songs/3 - Dancing/Кино - Группа крови.flac" in got and "Songs/3 - Dancing/Кино - Звезда по имени Солнце.flac" in got
    from tools.gigbar_lights.song_match import norm
    plain = {"artist": "Journey", "title": "Don't Stop Believin' (2022 Remaster)"}
    assert wn.key_of(plain) == norm(contract.track_key(plain["artist"], plain["title"])) == "journey-don-t-stop-believin"


# --- 9, 10: mixed sample rates and a very short file in the extras -----------------------------------

def test_mixed_sample_rates_and_a_one_second_file_are_all_in_the_backup(tmp_path):
    src = folder(tmp_path, [("3 - Dancing", "A - One.wav"), ("3 - Dancing", "C - Three.wav")], secs=6, rate=8000)
    sf.write(str(src / "3 - Dancing" / "B - Two.wav"), song(6, rate=16000, hz=500), 16000)
    sf.write(str(src / "3 - Dancing" / "D - Air Horn.wav"), song(0.8, rate=8000, hz=900), 8000)
    out = tmp_path / "n"
    r = wn.build(out, dance("A - One", "B - Two", "C - Three", "D - Air Horn"), wn.index_folder(src),
                 skip={"bouquet", "garter"})
    assert not any("backup" in c["text"] for c in r["checks"]), r["checks"]
    assert len(r["backups"]) == 1 and r["handoffs"]
    secs = sf.info(str(out / r["backups"][0])).duration
    plays = sum(c["plays_s"] for c in r["cuts"])
    assert plays - 3 * sc.TRANSITION_S - 0.5 <= secs <= plays + 0.5            # every song is in it, at its own speed
    y = sc.resample(song(2, rate=16000), 16000, 8000)
    assert len(y) == 16000 and y.dtype == np.float32
    # the handoff model itself takes a file shorter than the transition
    horn = sc.render(song(0.8), RATE, sc.plan(song(0.8), RATE))
    long = sc.render(song(8), RATE, sc.plan(song(8), RATE))
    for a, b in ((long, horn), (horn, long), (horn, horn)):
        mix, _ = sc.handoff(a, b, RATE)
        assert len(mix) and np.abs(mix).max() <= 1.0
    assert len(sc.mixdown([long, horn, long], RATE)) > 2 * len(long) - 2 * int(sc.TRANSITION_S * RATE)


# --- 11, 12: a rebuild ---------------------------------------------------------------------------------

def test_a_rebuild_never_cuts_its_own_cuts(tmp_path):
    src = folder(tmp_path, [("3 - Dancing", "A - One.wav"), ("3 - Dancing", "B - Two.wav")])
    out = src / "Llano Lights shows" / "wedding-night"        # he pointed the folder box at Music itself
    r1 = wn.build(out, dance("A - One", "B - Two"), wn.index_folder(src), extras=False)
    files = wn.index_folder(src)
    assert all("Llano Lights shows" not in str(p) for p in files.values())
    again = wn.index_folder(tmp_path, exclude=[out])
    assert all(out not in p.parents for p in again.values())
    r2 = wn.build(out, dance("A - One", "B - Two"), files, extras=False)
    assert [c["plays_s"] for c in r2["cuts"]] == [c["plays_s"] for c in r1["cuts"]]


def test_a_rebuild_clears_what_the_last_build_left_and_nothing_else(tmp_path, classic_night):
    src = folder(tmp_path, [("3 - Dancing", "A - One.wav"), ("3 - Dancing", "B - Two.wav"), ("2 - Dinner", "C - Eat.wav")])
    out = tmp_path / "n"
    songs = dance("A - One", "B - Two") + [{"artist": "C", "title": "Eat", "part": "dinner"}]
    r1 = wn.build(out, songs, wn.index_folder(src), skip={"bouquet", "garter"})
    assert (out / "Songs/3 - Dancing/B - Two.flac").is_file() and len(r1["backups"]) == 2 and r1["handoffs"]
    (out / "Songs" / "my notes.txt").write_text("keep me")
    (out / "Songs" / "3 - Dancing" / "Mine - Added By Hand.flac").write_bytes(b"his own file")
    r2 = wn.build(out, songs[:1], wn.index_folder(src), extras=False)
    assert not (out / "Songs/3 - Dancing/B - Two.flac").exists()          # a song no longer in the show
    assert not (out / "Songs/2 - Dinner/C - Eat.flac").exists()
    assert not any((out / b).exists() for b in r1["backups"]) and not (out / r1["handoffs"]).exists()
    assert (out / "Songs/3 - Dancing/A - One.flac").is_file()
    assert (out / "Songs/my notes.txt").read_text() == "keep me"          # only files a build wrote are removed
    assert (out / "Songs/3 - Dancing/Mine - Added By Hand.flac").is_file()
    assert sorted(r2["files"]) == sorted(set(r2["files"])) and "Songs/3 - Dancing/A - One.flac" in r2["files"]
    assert not list(out.rglob("*.part"))


def test_a_song_open_in_mixxx_stops_the_build_with_what_to_do(tmp_path, monkeypatch):
    src = folder(tmp_path, [("3 - Dancing", "A - One.wav")])
    out = tmp_path / "n"
    wn.build(out, dance("A - One"), wn.index_folder(src), extras=False)
    before = (out / "Songs/3 - Dancing/A - One.flac").read_bytes()
    real = Path.replace

    def locked(self, target):
        if str(target).endswith("A - One.flac"):
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", locked)
    # an unchanged song is kept, not written again, so one held open in Mixxx no longer stops it (BL #12342)
    assert wn.build(out, dance("A - One"), wn.index_folder(src), extras=False)["kept"] == 1
    # a song whose file changed must be written again: held open, the build stops and says what to do
    one = src / "3 - Dancing" / "A - One.wav"
    os.utime(one, ns=(one.stat().st_atime_ns, one.stat().st_mtime_ns + 10 ** 9))
    with pytest.raises(wn.NightBusy) as e:
        wn.build(out, dance("A - One"), wn.index_folder(src), extras=False)
    assert "Close Mixxx" in str(e.value) and "build again" in str(e.value)
    assert (out / "Songs/3 - Dancing/A - One.flac").read_bytes() == before and not list(out.rglob("*.part"))


# --- 13: the looks' filings past what the settings keep ------------------------------------------------

def test_a_full_song_list_is_said_not_dropped_silently(tmp_path):
    src = folder(tmp_path, [("3 - Dancing", "A - One.wav")], secs=4)
    r = wn.build(tmp_path / "n", dance("A - One"), wn.index_folder(src), extras=False)
    doc = contract.defaults()
    doc["styles"] = {"toast": wn.looks_ops(r, doc)[0][0]["value"]}
    doc["songs"] = {f"band-song-{i}": "toast" for i in range(contract.MAX_SONGS - 2)}
    ops, notes = wn.looks_ops(r, contract.normalize(doc))
    filed = [o for o in ops if o["path"].startswith("songs.")]
    assert len(filed) == 2                                           # two fit; the rest are named, not lost
    assert len(notes) >= 1 and any(str(contract.MAX_SONGS) in n and "songs" in n for n in notes)
    new, applied = contract.apply_ops(contract.normalize(doc), ops)
    assert all(o["path"][6:] in new["songs"] for o in filed)


# --- 14, 15: silence, and one level for the night -----------------------------------------------------

def test_a_silent_file_is_a_problem_and_is_left_out(tmp_path):
    src = folder(tmp_path, [("3 - Dancing", "A - One.wav")])
    sf.write(str(src / "3 - Dancing" / "B - Nothing.wav"), np.zeros((8000 * 20, 2), dtype=np.float32), 8000)
    sf.write(str(src / "3 - Dancing" / "C - Whisper.wav"), song(20, level=0.0004, rate=8000), 8000)
    out = tmp_path / "n"
    r = wn.build(out, dance("A - One", "B - Nothing", "C - Whisper"), wn.index_folder(src), extras=False)
    got = " ".join(playlist_files(out, r))
    assert "Nothing" not in got and "Whisper" not in got and "A - One.flac" in got
    probs = [c["text"] for c in r["checks"] if c["level"] == "problem"]
    assert sum("is silent" in p for p in probs) == 2 and any("B - Nothing" in p for p in probs)


def test_one_quiet_file_or_one_bad_sample_does_not_set_the_nights_level():
    normal = [song(40, level=0.3, hz=h) for h in (220, 330)]
    glitch = song(40, level=0.05, hz=440)
    glitch[RATE * 7] = 1.0                        # one bad sample in a soft but ordinary file
    cuts = [sc.plan(x, RATE) for x in (*normal, glitch)]
    assert cuts[2].peak < 0.2                     # the bad sample is not what the song's peak is
    level = sc.set_level(cuts)
    assert level == sc.TARGET_LUFS                # so it does not decide the night's level
    outs = [sc.render(x, RATE, c) for x, c in zip((*normal, glitch), cuts)]
    lufs = [sc.loudness(y[int(sc.LEAD_S * RATE):], RATE) for y in outs]
    assert max(lufs) - min(lufs) < 0.6 and all(c.under_db == 0 for c in cuts)
    assert all(np.abs(y).max() <= sc.PEAK_CEILING + 1e-6 for y in outs)      # and what stood above is held at the ceiling
    # a recording too quiet to turn up (tall hits, almost nothing between them): the night stops at the
    # floor instead of following it down, and that one song is the one left quieter
    quiet = song(40, level=0.004)
    for k in range(6):
        quiet[k:: RATE * 2] = 0.9 * (-1) ** k
    cuts = [sc.plan(x, RATE) for x in (*normal, quiet)]
    assert sc.set_level(cuts) == sc.FLOOR_LUFS
    assert cuts[2].under_db > 3 and cuts[0].under_db == 0 and cuts[1].under_db == 0
    outs = [sc.render(x, RATE, c) for x, c in zip((*normal, quiet), cuts)]
    lufs = [sc.loudness(y[int(sc.LEAD_S * RATE):], RATE) for y in outs]
    assert abs(lufs[0] - sc.FLOOR_LUFS) < 0.5 and abs(lufs[1] - sc.FLOOR_LUFS) < 0.5
    assert lufs[2] == pytest.approx(sc.FLOOR_LUFS - cuts[2].under_db, abs=0.7)


def test_the_quiet_song_is_named_in_the_report(tmp_path):
    src = folder(tmp_path, [("3 - Dancing", "A - One.wav"), ("3 - Dancing", "B - Two.wav")], secs=20)
    q = song(20, level=0.003, rate=8000)
    for k in range(3):
        q[k:: 8000 * 2] = 0.9 * (-1) ** k
    sf.write(str(src / "3 - Dancing" / "Old - Record.wav"), q, 8000)
    r = wn.build(tmp_path / "n", dance("A - One", "B - Two", "Old - Record"), wn.index_folder(src), extras=False)
    note = [c for c in r["checks"] if "Old - Record" in c["text"]]
    assert note and note[0]["level"] == "heads-up" and "quieter" in note[0]["text"]


# --- 18, 22, 23: times, labels, long names -------------------------------------------------------------

def test_clock_times_typed_the_ways_people_type_them():
    assert ros.parse_clock("6.30") == 390 and ros.parse_clock("6.30 pm") == 390
    assert ros.parse_clock("00:30") == 750 and ros.parse_clock("0:15") == 735     # after midnight, not lunchtime
    assert ros.parse_clock("12:30") == 30 and ros.parse_clock("6") == 360
    steps = ros.plan(PARTS, MOMENT_SONGS, times={"toasts": "after dinner", "cocktail": "5:00"})
    notes = [c["text"] for c in ros.checks(steps)]
    assert any('"after dinner"' in n and "Toasts" in n and "6:30" in n for n in notes)


def test_a_title_with_a_line_break_stays_on_one_playlist_line():
    pl = ros.Playlist(1, "x", [{"kind": "music", "key": "dancing", "name": "Dancing", "artist": "A\r\nB", "title": "One\nTwo\x00",
                                "secs": 10, "look": "", "repeat": False}])
    lines = ros.m3u8(pl, lambda r: "Songs/a.flac").splitlines()
    assert lines == ["#EXTM3U", "#PLAYLIST:1 - x", "#EXTINF:10,A B - One Two", "Songs/a.flac"]


def test_a_very_long_name_still_fits_a_windows_path(tmp_path):
    deep = tmp_path / ("d" * 60) / ("e" * 60)
    title = "A Very Long Title " * 12
    src = folder(tmp_path, [("3 - Dancing", f"Band - {title.strip()}.wav")], secs=4)
    out = deep / "night"
    r = wn.build(out, [{"artist": "Band", "title": title.strip(), "part": "dancing"}], wn.index_folder(src), extras=False)
    assert r["missing"] == [] and len(r["cuts"]) == 1
    cut = out / r["cuts"][0]["file"]
    assert cut.is_file() and len(str(cut)) <= max(wn.MAX_PATH, len(str(out)) + 60)
    assert wn.fit_name("x" * 300, out / "Songs" / "3 - Dancing", ".flac").endswith("x") and wn.fit_name("ok", out, ".flac") == "ok"


# --- 19, 20, 25, 26: what the cuts rest on -------------------------------------------------------------

def test_the_lead_is_silent_to_people_and_sound_to_mixxx(tmp_path):
    y = sc.render(song(30), RATE, sc.plan(song(30), RATE))
    n = int(sc.LEAD_S * RATE)
    lead = y[:n]
    edge = int(0.012 * RATE)
    assert np.abs(lead[edge:-edge]).min() >= 0.001            # Mixxx's test for "sound": -60 dBFS per sample
    assert np.abs(lead).max() < 0.002
    assert np.abs(np.diff(lead, axis=0)).max() < 2e-5         # no hiss, no click: nothing in it moves fast
    assert lead[0].max() < 1e-4 and abs(lead[-1]).max() < 1e-4
    assert sc.first_sound(y, RATE) < 0.012
    back, _ = sc.read(sc.write(tmp_path / "lead.flac", y, RATE))      # as Mixxx reads it: 16-bit FLAC
    assert np.abs(back[edge:n - edge]).min() >= 0.001


def test_a_handoff_of_two_loud_songs_never_clips():
    a = np.full((RATE * 6, 2), 0.9, dtype=np.float32)
    mix, _ = sc.handoff(a, a, RATE, before_s=2, after_s=2)
    assert np.abs(mix).max() <= 1.0


def test_blank_stretches_are_measured_on_the_file_itself(tmp_path):
    p = tmp_path / "Tim - Broken.mp3"
    tag = b"ID3\x04\x00\x00" + bytes([0, 0, 0x10, 0]) + b"\x00" * 2048
    p.write_bytes(tag + b"\xff\xfb\x90\x00" * 50_000 + b"\x00" * 262_144 + b"\xff\xfb\x90\x00" * 50_000)
    assert sc.blank_seconds(p) == pytest.approx(262_144 / 40000, abs=0.2)       # 6.6 seconds at 320 kbps
    whole = tmp_path / "Tim - Whole.mp3"
    big_tag = b"ID3\x04\x00\x00" + bytes([0, 4, 34, 112]) + b"\x00" * 70_000   # a tag padded with more zeros than a hole needs
    whole.write_bytes(big_tag + b"\xff\xfb\x90\x00" * 100_000)
    assert sc.blank_seconds(whole) == 0.0                                       # the tag's own padding is not a hole
    with pytest.raises(sc.DamagedFile) as e:
        sc.read(p)
    assert "seconds of it are blank" in str(e.value)


def test_loudness_reads_the_standard_reference_tones():
    t = np.arange(48000 * 10) / 48000
    tone = np.sin(2 * np.pi * 997 * t).astype(np.float32)
    stereo = np.stack([tone, tone], axis=1)
    one_side = np.stack([tone, np.zeros_like(tone)], axis=1)
    assert sc.loudness(one_side, 48000) == pytest.approx(-3.01, abs=0.1)        # ITU-R BS.1770: 0 dBFS, one channel
    assert sc.loudness(stereo, 48000) == pytest.approx(0.0, abs=0.1)            # the same tone on both channels
    assert sc.loudness(stereo * np.float32(10 ** (-23 / 20)), 48000) == pytest.approx(-23.0, abs=0.1)
    assert sc.loudness(np.repeat(stereo[::2], 1, axis=0)[: 24000 * 10], 24000) == pytest.approx(0.0, abs=0.15)


def test_the_next_songs_first_note_is_at_full_level_in_the_rendered_handoff():
    quiet = np.zeros((RATE * 10, 2), dtype=np.float32)                          # the old song, already silent
    b = sc.render(song(20, hz=330), RATE, sc.plan(song(20, hz=330), RATE))
    for curve in ("additive", "cut"):
        mix, first_note = sc.handoff(quiet, b, RATE, curve=curve, before_s=2, after_s=4)
        i, lead = int(round(first_note * RATE)), int(sc.LEAD_S * RATE)
        k = int(0.5 * RATE)
        assert np.abs(mix[i:i + k] - b[lead:lead + k]).max() < 1e-6, curve      # exactly the song, at its own level
        assert np.abs(mix[:i]).max() < 0.002                                    # and nothing heard before it


# --- his Drive folder: "4 - Moments" holds the dances' songs ------------------------------------------

def test_songs_in_a_moments_folder_are_the_nights_moments(tmp_path):
    from tools.gigbar_lights import song_folder
    names = [("3 - Dancing", "ABBA - Dancing Queen.wav"), ("3 - Dancing", "Journey - Don't Stop Believin'.wav"),
             ("4 - Moments", "Rascal Flatts - My Wish.wav"), ("4 - Moments", "Steven Curtis Chapman - Cinderella.wav"),
             ("4 - Moments", "Randy Travis - Forever and Ever, Amen.wav"), ("4 - Moments", "Nobody - Some Song.wav")]
    src = folder(tmp_path, names, secs=5)
    (src / "4 - Moments" / "4 - Moments - Set Order.m3u").write_text("#EXTM3U\n")
    _, songs = song_folder.read_folder(str(src))
    got = {s["title"]: (s["part"], s.get("moment", "")) for s in songs}
    # each dance's song is known by name; My Wish suits both parent dances and takes the one still free
    assert got["Forever and Ever, Amen"] == ("dancing", "first-dance")
    assert got["Cinderella"] == ("dancing", "father-daughter") and got["My Wish"] == ("dancing", "mother-son")
    assert got["Some Song"] == ("", "?") and got["Dancing Queen"] == ("dancing", "")    # a song nobody knows stays marked
    out = tmp_path / "n"
    r = wn.build(out, songs, wn.index_folder(src), extras=False)
    files = playlist_files(out, r)
    assert not any("Some Song" in f for f in files)                    # it is his to place: never dropped onto the dance floor
    assert any("Nobody - Some Song is in the Moments folder" in c["text"] for c in r["checks"])
    for name in ("Randy Travis - Forever and Ever, Amen", "Steven Curtis Chapman - Cinderella", "Rascal Flatts - My Wish"):
        assert f"Songs/Moments/{name}.flac" in files and f"Songs/3 - Dancing/{name}.flac" not in files
    order = [(s["key"], s["songs"][0]["title"]) for s in r["steps"] if s["kind"] == "song"]
    assert order == [("first-dance", "Forever and Ever, Amen"), ("father-daughter", "Cinderella"), ("mother-son", "My Wish")]


# --- the second review ---------------------------------------------------------------------------------

def test_a_name_retyped_with_capitals_never_deletes_the_cut_just_written(tmp_path, monkeypatch):
    src = folder(tmp_path, [("3 - Dancing", "ed sheeran - perfect.wav")])
    out = tmp_path / "n"
    wn.build(out, dance("ed sheeran - perfect"), wn.index_folder(src), extras=False)
    gone = []
    real = Path.unlink

    def watch(self, *a, **k):
        gone.append(str(self))
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", watch)
    r = wn.build(out, dance("Ed Sheeran - Perfect"), wn.index_folder(src), extras=False)
    cut = out / r["cuts"][0]["file"]
    # on Windows the old spelling IS the new file: it must not be on the list of files to remove
    assert cut.name == "Ed Sheeran - Perfect.flac" and str(cut).casefold() not in [g.casefold() for g in gone]
    assert wn._stale({"Songs/3 - Dancing/ed sheeran - perfect.flac", "Songs/3 - Dancing/Old - Gone.flac"},
                     {"Songs/3 - Dancing/Ed Sheeran - Perfect.flac"}) == {"Songs/3 - Dancing/Old - Gone.flac"}


def test_a_folder_with_more_songs_than_a_show_holds_keeps_the_dances_and_says_how_many_were_left(tmp_path):
    from tools.gigbar_lights import song_folder
    src = tmp_path / "W"
    for sub, names in (("3 - Dancing", [f"Band - Song {i:02d}.mp3" for i in range(contract.MAX_SHOW_SONGS + 4)]),
                       ("4 - Moments", ["Steven Curtis Chapman - Cinderella.mp3", "Rascal Flatts - My Wish.mp3",
                                        "Randy Travis - Forever and Ever, Amen.mp3"])):
        (src / sub).mkdir(parents=True)
        for n in names:
            (src / sub / n).write_bytes(b"not read here")
    _, songs, left = song_folder.read_folder_all(str(src))
    assert left == 7 and len(songs) == contract.MAX_SHOW_SONGS
    assert {s["moment"] for s in songs if s["moment"]} == {"first-dance", "father-daughter", "mother-son"}
    assert song_folder.read_folder(str(src))[1] == songs
    assert song_folder.read_folder_all(str(src / "4 - Moments"))[2] == 0


def test_two_names_for_one_song_play_once_and_are_named(tmp_path):
    src = folder(tmp_path, [("3 - Dancing", "ABBA - Dancing Queen.wav"), ("3 - Dancing", "ABBA - Dancing Queen (Remastered).wav"),
                            ("3 - Dancing", "B - Two.wav")])
    out = tmp_path / "n"
    r = wn.build(out, dance("ABBA - Dancing Queen", "ABBA - Dancing Queen (Remastered)", "B - Two"), wn.index_folder(src),
                 extras=False, skip={"bouquet", "garter"})
    rows = [f for f in playlist_files(out, r) if "Dancing Queen" in f]
    assert len(rows) == 2 and "Remastered" not in " ".join(rows)       # once in the set, once in its safety repeat
    note = [c["text"] for c in r["checks"] if "same song" in c["text"]]
    assert note and "ABBA - Dancing Queen (Remastered)" in note[0] and "plays once" in note[0]


def test_a_stopped_build_says_what_to_do_in_his_words(tmp_path, monkeypatch):
    import errno
    assert "disk is full" in wn.plain_error(OSError(errno.ENOSPC, "No space left on device"))
    assert "ran out of memory" in wn.plain_error(MemoryError())
    assert "Close Mixxx" in wn.plain_error(PermissionError(13, "denied")) and "Close Mixxx" in wn.plain_error(wn.NightBusy("Close Mixxx, then build again: x"))
    for e in (OSError(5, "Input/output error"), KeyError("x"), ValueError("boom")):
        said = wn.plain_error(e)
        assert "Error" not in said and "Errno" not in said and "build again" in said.lower()
    # the backups stop part way (the disk fills): what was finished is still listed, and the reason is plain
    src = folder(tmp_path, [("1 - Cocktail Hour", "A - One.wav"), ("3 - Dancing", "B - Two.wav"), ("3 - Dancing", "C - Three.wav")])
    real, calls = wn._write_stream, []

    def fills(path, pieces, rate):
        calls.append(path.name)
        if len(calls) >= 3:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(path, pieces, rate)

    monkeypatch.setattr(wn, "_write_stream", fills)
    out = tmp_path / "n"
    songs = [{"artist": "A", "title": "One", "part": "cocktail"}] + dance("B - Two", "C - Three")
    r = wn.build(out, songs, wn.index_folder(src), skip={"bouquet", "garter"})
    assert r["handoffs"] and len(r["backups"]) == 1 and r["backups"][0] in r["files"] and (out / r["backups"][0]).is_file()
    note = [c["text"] for c in r["checks"] if "phone backup" in c["text"]][0]
    assert "disk is full" in note and "OSError" not in note and "night itself is built" in note


def test_the_songs_box_pointed_at_the_built_nights_finds_no_songs(tmp_path):
    src = folder(tmp_path, [("3 - Dancing", "A - One.wav")])
    music = tmp_path / "Music"
    out = music / wn.OUT_PARENT / "smith-night"
    wn.build(out, dance("A - One"), wn.index_folder(src), extras=False)
    assert wn.index_folder(music) == {} and wn.index_folder(music / wn.OUT_PARENT) == {} and wn.index_folder(out) == {}
    # a night built somewhere else is kept out by naming it
    other = tmp_path / "elsewhere" / "night"
    wn.build(other, dance("A - One"), wn.index_folder(src), extras=False)
    assert wn.index_folder(tmp_path / "elsewhere") != {} and wn.index_folder(tmp_path / "elsewhere", exclude=[other]) == {}


def test_a_file_held_open_stops_the_build_before_anything_is_written(tmp_path, monkeypatch):
    import builtins
    src = folder(tmp_path, [("3 - Dancing", "A - One.wav")])
    out = tmp_path / "n"
    wn.build(out, dance("A - One"), wn.index_folder(src), extras=False)
    stamp = (out / "night.json").stat().st_mtime_ns
    real = builtins.open

    def held(file, mode="r", *a, **k):
        if str(file).endswith("A - One.flac") and "a" in mode:
            raise PermissionError(13, "being used by another process")
        return real(file, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", held)
    read = []
    monkeypatch.setattr(sc, "read", lambda p: read.append(p) or (_ for _ in ()).throw(AssertionError("read before the check")))
    with pytest.raises(wn.NightBusy) as e:
        wn.build(out, dance("A - One"), wn.index_folder(src), extras=False)
    assert "A - One.flac" in str(e.value) and read == [] and (out / "night.json").stat().st_mtime_ns == stamp


def test_only_files_a_build_wrote_are_ever_on_the_list_to_remove(tmp_path):
    out = tmp_path / "n"
    out.mkdir()
    (out / "night.json").write_text(json.dumps({"files": [
        "Songs/3 - Dancing/A - One.flac", "Holds/h.flac", "Backup/1 - x.mp3", "Listen first - Dancing handoffs.mp3",
        "../outside.flac", "Songs/../../outside.flac", str(tmp_path / "abs.flac"), "notes.txt", "Run of show.html", "", 7]}))
    assert wn._last_files(out) == {"Songs/3 - Dancing/A - One.flac", "Holds/h.flac", "Backup/1 - x.mp3",
                                   "Listen first - Dancing handoffs.mp3"}
    (out / "night.json").write_text("not json")
    assert wn._last_files(out) == set() and wn._last_files(tmp_path / "nowhere") == set()


def test_a_song_too_big_to_measure_plays_as_it_is(tmp_path, monkeypatch):
    src = folder(tmp_path, [("3 - Dancing", "A - One.wav"), ("3 - Dancing", "B - Huge.wav"), ("3 - Dancing", "C - Big.wav")])
    real_read, real_plan = sc.read, sc.plan

    def read(p):
        if "Huge" in str(p):
            raise MemoryError()
        return real_read(p)

    def plan(x, rate, *a, **k):
        if abs(len(x) / rate - 6.0) < 0.01 and plan.big:
            plan.big -= 1
            raise MemoryError()
        return real_plan(x, rate, *a, **k)

    plan.big = 0
    monkeypatch.setattr(sc, "read", read)
    out = tmp_path / "n1"
    r = wn.build(out, dance("A - One", "B - Huge"), wn.index_folder(src), extras=False)
    assert [u["title"] for u in r["uncut"]] == ["Huge"] and "Songs/3 - Dancing/B - Huge.wav" in playlist_files(out, r)
    monkeypatch.setattr(sc, "read", real_read)
    monkeypatch.setattr(sc, "plan", plan)
    plan.big = 1                                   # the first song measured runs out of memory inside plan()
    out = tmp_path / "n2"
    r = wn.build(out, dance("C - Big", "A - One"), wn.index_folder(src), extras=False)
    assert [u["title"] for u in r["uncut"]] == ["Big"] and r["damaged"] == [] and len(r["cuts"]) == 1
    assert any("C - Big" in c["text"] and "plays as it is" in c["text"] for c in r["checks"])


def test_measuring_a_song_does_not_take_many_times_its_size():
    import tracemalloc
    x = song(240, rate=44100)                      # four minutes: 85 MB, long enough for every measurement to run
    tracemalloc.start()
    sc.plan(x, 44100, "dancing")
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert peak < 2.2 * x.nbytes, round(peak / x.nbytes, 2)      # it was five times a short song, three of a long one


def test_a_ninety_song_wedding_folder_saves_reloads_and_builds_the_whole_night(tmp_path):
    """BL #12087: a full reception (cocktail hour, dinner, 2 h 15 of dancing, the dances) is about
    90 songs. The folder reads whole, the show saves whole, survives the stored JSON both sides keep
    (the same contract bytes Llano runs), reloads, and the night built from it leaves no song out."""
    from tools.gigbar_lights import shows, song_folder
    names = ([("1 - Cocktail Hour", f"Lounge Trio - Cocktail {i:02d}.wav") for i in range(25)] +
             [("2 - Dinner", f"Dinner Quartet - Dinner {i:02d}.wav") for i in range(22)] +
             [("3 - Dancing", f"Dance Band - Floor Filler {i:02d}.wav") for i in range(40)] +
             [("4 - Moments", "Steven Curtis Chapman - Cinderella.wav"), ("4 - Moments", "Rascal Flatts - My Wish.wav"),
              ("4 - Moments", "Randy Travis - Forever and Ever, Amen.wav")])
    assert len(names) == 90 <= contract.MAX_SHOW_SONGS
    src = folder(tmp_path, names, secs=4)
    _, songs, left = song_folder.read_folder_all(str(src))
    assert left == 0 and len(songs) == 90
    for s in songs:   # a designed night: every song carries a look, a why and an arranger reason
        s.update(look="party", why="the floor is full by now, so the movers sweep and strobes hit the chorus",
                 secs=215.0, bpm=118.0, reason="keeps the energy climbing after the last slow one")
    name, ops = shows.save_ops("Avery & Jordan", songs)
    stored = json.dumps(contract.apply_ops(contract.defaults(), ops)[0])   # ASCII-escaped, as both sides keep it
    again = contract.normalize(json.loads(stored))["shows"][name]
    assert len(contract._dumps_ascii(again)) <= contract.MAX_SHOW_BYTES
    assert [(s["artist"], s["title"]) for s in again["songs"]] == [(s["artist"], s["title"]) for s in songs]
    assert all(s.get("reason") for s in again["songs"])   # whole: not even the arranger's lines were trimmed
    r = wn.build(tmp_path / "night", again["songs"], wn.index_folder(src), title=again["title"], extras=False)
    assert r["missing"] == [] and r["damaged"] == []
    played = {(x["artist"], x["title"]) for st in r["steps"] for x in st["songs"]}
    assert {(s["artist"], s["title"]) for s in songs} <= played
