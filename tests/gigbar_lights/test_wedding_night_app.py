"""The wedding night panel on the Shows page (Llano PM #23179): build, progress, Mixxx check."""
import time

import pytest

pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")

from tests.gigbar_lights.test_shows import _call, lib, window  # noqa: E402,F401
from tests.gigbar_lights.test_wedding_night import NIGHT, PART_OF, make_folder  # noqa: E402



@pytest.fixture
def classic_night(monkeypatch):
    """The classic order with no quiet background under the toasts and cake: what these build tests were
    written against before his own order became the default (BL #12360). His order is checked in
    test_his_reception_order_is_the_default and test_his_reception_night_builds."""
    from tests.gigbar_lights.test_wedding_night import CLASSIC
    from tools.gigbar_lights import run_of_show as ros
    monkeypatch.setattr(ros, "DEFAULT_ORDER", CLASSIC)
    monkeypatch.setattr(ros, "BACKGROUND_UNDER", ())

def test_the_shows_page_builds_the_night_and_files_the_looks(window, tmp_path, monkeypatch, classic_night):  # noqa: F811
    app, url, token, tmp = window
    home = tmp_path / "home"
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    code, page = _call(url + "shows")
    assert code == 200 and b"Build the whole night for Mixxx" in page and b"nightbuild" in page
    code, h = _call(url + "api/shows-night-home", {}, token)
    assert code == 200 and h["night"] == {"state": "idle"} and h["transition_s"] == 2.0
    assert [m["key"] for m in h["moments"]][:2] == ["entrance", "first-dance"]
    assert _call(url + "api/shows-night-build", {"songs": []}, token)[0] == 400
    assert _call(url + "api/shows-night-open", {"what": "sheet"}, token)[0] == 404
    assert _call(url + "api/shows-night-open", {"what": "folder"}, token)[0] == 404   # never the app's own folder

    src = make_folder(tmp_path, NIGHT, secs=4)
    songs = [{"artist": a, "title": t, "part": PART_OF[p]} for p, a, t in NIGHT]
    body = {"songs": songs, "title": "Avery & Jordan", "folder": str(src), "extras": False,
            "times": {"cocktail": "5:00", "dinner": "6:00"},
            "moments": {"first-dance": {"on": True, "song": "Randy Travis - Forever and Ever, Amen"},
                        "last-dance": {"on": True, "song": "Josh Turner - Why Don't We Just Dance"},
                        "close": {"on": True, "song": "Journey - Don't Stop Believin'"},
                        "garter": {"on": False}, "bouquet": {"on": False}}}
    # two presses at the same moment (a double click), with a folder that takes a while to read: one
    # build starts, the other press is told it is already building
    import threading
    from tools.gigbar_lights import wedding_night
    real_index, got = wedding_night.index_folder, []

    def slow_index(*a, **k):
        time.sleep(0.4)
        return real_index(*a, **k)

    monkeypatch.setattr(wedding_night, "index_folder", slow_index)
    presses = [threading.Thread(target=lambda: got.append(_call(url + "api/shows-night-build", body, token))) for _ in range(2)]
    for t in presses:
        t.start()
    for t in presses:
        t.join()
    assert sorted(code for code, _ in got) == [200, 409]
    assert next(r for code, r in got if code == 200)["state"] == "building"
    assert _call(url + "api/shows-night-build", body, token)[0] == 409           # and a third, while it builds
    for _ in range(200):
        _, st = _call(url + "api/shows-night-status", {}, token)
        if st["state"] != "building":
            break
        time.sleep(0.1)
    assert st["state"] == "done", st
    out = home / "Music" / "Llano Lights shows" / "avery-jordan-night"
    assert st["folder"] == str(out) and (out / "Run of show.html").is_file()
    # the run sheet is findable: the page is told where it is, it has its own Print button, and the
    # last night built is still offered after the app was closed and opened again (his 2026-11-13 ask)
    assert st["sheet"] == str(out / "Run of show.html")
    sheet = (out / "Run of show.html").read_text(encoding="utf-8")
    assert 'onclick="window.print()">Print this page</button>' in sheet and ".p{display:none}" in sheet
    opened = []
    monkeypatch.setattr("os.startfile", lambda path: opened.append(path), raising=False)
    assert _call(url + "api/shows-night-open", {"what": "sheet"}, token)[1]["path"] == str(out / "Run of show.html")
    built, app.night = app.night, None   # a fresh launch: nothing built this time
    assert app.night_public() == {"state": "idle", "last": {"folder": str(out), "sheet": str(out / "Run of show.html")}}
    assert _call(url + "api/shows-night-open", {"what": "sheet"}, token)[1]["path"] == str(out / "Run of show.html")
    assert _call(url + "api/shows-night-open", {"what": "folder"}, token)[1]["path"] == str(out)
    assert opened == [str(out / "Run of show.html")] * 2 + [str(out)]
    (out / "Run of show.html").rename(out / "moved.html")   # a folder with no sheet is not offered
    assert app.night_public() == {"state": "idle"} and _call(url + "api/shows-night-open", {"what": "sheet"}, token)[0] == 404
    (out / "moved.html").rename(out / "Run of show.html")
    app.night = built
    names = [p["file"] for p in st["report"]["playlists"]]
    assert names[0] == "1 - Cocktail hour.m3u8" and names[-1].startswith("4 - Last dance, Closing song")
    two = (out / names[1]).read_text(encoding="utf-8")
    assert "Songs/Moments/Randy Travis - Forever and Ever, Amen.flac" in two     # typed on the panel: plays at its moment
    assert "Songs/2 - Dinner/Randy Travis" not in two                            # and not in dinner as well
    three = (out / names[2]).read_text(encoding="utf-8")
    assert "Bouquet" not in three and "Why Don't We Just Dance" not in three
    # cocktail hour was given 60 minutes and has seconds of music: said plainly
    assert any("Cocktail hour is planned for 60 minutes" in c["text"] for c in st["report"]["checks"])
    # the moment looks are saved styles now, and the holds are filed under them
    doc = app.link.settings.load()
    assert {"toast", "first-dance", "last-dance"} <= set(doc["styles"])
    assert "toast" in doc["songs"].values()
    # what the build changed in a song comes back for him to look over, and a kept intro is honored
    assert isinstance(st["report"]["changed"], list) and st["report"]["kept"] == []
    assert st["notes"] == []
    # the garter toss is off unless it is ticked; ticked, it is a hold after the bouquet
    assert "Garter" not in three
    body["moments"].update({"garter": {"on": True}, "bouquet": {"on": True},
                            "first-dance": {"on": True, "song": "forever and ever, amen"}})   # typed by its title alone
    monkeypatch.setattr(wedding_night, "looks_ops", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("settings locked")))
    assert _call(url + "api/shows-night-build", body, token)[0] == 200
    for _ in range(300):
        _, st = _call(url + "api/shows-night-status", {}, token)
        if st["state"] != "building":
            break
        time.sleep(0.1)
    assert st["state"] == "done", st
    three = (out / [p["file"] for p in st["report"]["playlists"]][2]).read_text(encoding="utf-8")
    assert three.index("HOLD - Bouquet toss") < three.index("HOLD - Garter toss")
    # the looks could not be saved: a note on a finished night, in plain words, never a failed build
    assert len(st["notes"]) == 1 and "could not be saved" in st["notes"][0] and "RuntimeError" not in st["notes"][0]
    # the title alone is the show's own song: it plays at its moment and not in dinner as well
    every = "".join((out / p["file"]).read_text(encoding="utf-8") for p in st["report"]["playlists"])
    assert "Songs/Moments/Randy Travis - Forever and Ever, Amen.flac" in every and "Songs/2 - Dinner/Randy Travis" not in every
    assert every.count("Forever and Ever, Amen.flac") == 1
    # a song in the Moments folder that no dance is known for is named, and never left out (Llano BL #11473):
    # it is in the show as a Dancing song with no moment until he picks its moment in step 2
    (src / "4 - Moments").mkdir()
    (src / "4 - Moments" / "Nobody - Our Song.wav").write_bytes(b"x")
    (src / "4 - Moments" / "Steven Curtis Chapman - Cinderella.wav").write_bytes(b"x")
    code, got = _call(url + "api/shows-folder", {"path": str(src)}, token)
    assert code == 200 and got["unplaced"] == ["Nobody - Our Song"] and got["left_out"] == 0
    assert [(s["part"], s["moment"]) for s in got["songs"] if s["title"] == "Our Song"] == [("dancing", "")]
    assert [s["moment"] for s in got["songs"] if s["title"] == "Cinderella"] == ["father-daughter"]
    code, chk = _call(url + "api/shows-night-check", {}, token)
    assert code == 200 and "items" in chk
