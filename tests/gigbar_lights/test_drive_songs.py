"""Get my songs (Llano BL #12342): a linked laptop brings his Drive song folder here through the Llano
link, and the show follows the folder; and the hand paths stay (a folder on this laptop, Add a song from
this laptop).

The Drive side is a fake link here (aios scripts/lights/drive_songs.py is the real one, with its own
tests in aios). What is proven: only new or changed files are downloaded, under their real names; a song
taken out of Drive is taken out here, but a song he added by hand never is; a song moved to another part
in Drive moves here; a broken download never lands; a song added to a Drive folder comes into the show
with that folder's part; and the night build redoes only the songs that changed.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest

llano_sync = pytest.importorskip("tools.gigbar_lights.llano_sync", reason="the Llano link is not in this edition")
from tools.gigbar_lights import drive_songs, song_folder  # noqa: E402

FOLDER = {"id": "folderROOT000001", "name": "Avery & Jordan Wedding Songs"}


class FakeLink:
    """The two Llano calls Get my songs makes, over an in-memory Drive folder."""

    def __init__(self):
        self.linked = True
        self.files: dict = {}        # id -> {"path": [...], "name": str, "data": bytes, "modified": str}
        self.downloads: list = []
        self.corrupt: set = set()    # ids whose download arrives damaged
        self.truncated = False
        self.folders = [FOLDER]

    def put(self, fid, path, name, data, modified="t1"):
        self.files[fid] = {"path": path, "name": name, "data": data, "modified": modified}

    def drive_folders(self):
        return list(self.folders)

    def drive_songs(self, folder_id=""):
        return {"folder": FOLDER, "folders": self.folders, "truncated": self.truncated,
                "files": [{"id": k, "name": v["name"], "path": v["path"], "size": len(v["data"]),
                           "md5": hashlib.md5(v["data"]).hexdigest(), "modified": v["modified"]}
                          for k, v in self.files.items()]}

    def download_song(self, folder_id, file_id, dest, timeout=60):
        self.downloads.append(file_id)
        data = self.files[file_id]["data"]
        if file_id in self.corrupt:
            data = data[: len(data) // 2] + b"?" * (len(data) - len(data) // 2)
        Path(dest).write_bytes(data)
        return hashlib.md5(data).hexdigest()


def wedding(link: FakeLink) -> None:
    link.put("c1", ["1 - Cocktail Hour"], "Alabama - The Closer You Get.mp3", b"cocktail-1")
    link.put("d1", ["2 - Dinner"], "Clint Black - Killin' Time.mp3", b"dinner-1")
    link.put("x1", ["3 - Dancing"], "Journey - Don't Stop Believin'.mp3", b"dance-1")
    link.put("m1", ["4 - Moments"], "Rascal Flatts - Bless the Broken Road.mp3", b"moment-1")
    link.put("e1", ["Extra"], "Fireflies - Owl City.mp3", b"extra-1")


def names(got, kind):
    return sorted(Path(x["file"]).name for x in got[kind])


# --- the copy ------------------------------------------------------------------------------------------------

def test_first_get_brings_every_song_with_its_real_name(tmp_path):
    link = FakeLink()
    wedding(link)
    root = tmp_path / "copy"
    got = drive_songs.get_songs(link, FOLDER, root)
    assert len(got["new"]) == 5 and got["removed"] == [] and got["kept"] == 0 and got["failed"] == []
    # an apostrophe stays an apostrophe (a Drive zip made it "Killin_ Time")
    assert (root / "2 - Dinner" / "Clint Black - Killin' Time.mp3").read_bytes() == b"dinner-1"
    assert (root / "3 - Dancing" / "Journey - Don't Stop Believin'.mp3").is_file()
    assert not list(root.rglob("*.part"))


def test_second_get_downloads_nothing_and_a_new_dinner_song_lands_in_dinner(tmp_path):
    link = FakeLink()
    wedding(link)
    root = tmp_path / "copy"
    drive_songs.get_songs(link, FOLDER, root)
    link.downloads.clear()
    again = drive_songs.get_songs(link, FOLDER, root)
    assert link.downloads == [] and again["kept"] == 5 and again["new"] == [] and again["removed"] == []
    # he drops a song in Dinner from his phone, then presses Get my songs
    link.put("d2", ["2 - Dinner"], "Right for You - Song.mp3", b"dinner-2")
    got = drive_songs.get_songs(link, FOLDER, root)
    assert link.downloads == ["d2"] and names(got, "new") == ["Right for You - Song.mp3"] and got["kept"] == 5
    # the show takes the song in with Dinner as its part, read from the folder it sits in
    _name, songs, _left = song_folder.read_folder_all(str(root))
    part = {s["title"]: s["part"] for s in songs}
    assert part["Song"] == "dinner" and part["Killin' Time"] == "dinner" and part["The Closer You Get"] == "cocktail"


def test_a_changed_song_is_downloaded_again_and_a_moved_one_is_moved(tmp_path):
    link = FakeLink()
    wedding(link)
    root = tmp_path / "copy"
    drive_songs.get_songs(link, FOLDER, root)
    link.downloads.clear()
    link.put("d1", ["2 - Dinner"], "Clint Black - Killin' Time.mp3", b"dinner-1-better-copy", modified="t2")
    link.files["x1"]["path"] = ["2 - Dinner"]          # Journey moved from Dancing to Dinner in Drive
    got = drive_songs.get_songs(link, FOLDER, root)
    assert link.downloads == ["d1"]                      # the move cost no download
    assert names(got, "changed") == ["Clint Black - Killin' Time.mp3"]
    assert names(got, "moved") == ["Journey - Don't Stop Believin'.mp3"]
    assert (root / "2 - Dinner" / "Journey - Don't Stop Believin'.mp3").is_file()
    assert not (root / "3 - Dancing" / "Journey - Don't Stop Believin'.mp3").exists()
    assert (root / "2 - Dinner" / "Clint Black - Killin' Time.mp3").read_bytes() == b"dinner-1-better-copy"


def test_a_song_taken_out_of_drive_goes_but_a_song_added_by_hand_stays(tmp_path):
    link = FakeLink()
    wedding(link)
    root = tmp_path / "copy"
    drive_songs.get_songs(link, FOLDER, root)
    mine = root / "1 - Cocktail Hour" / "Me - My Own.mp3"   # Add a song from this laptop put it here
    mine.write_bytes(b"mine")
    del link.files["c1"]
    got = drive_songs.get_songs(link, FOLDER, root)
    assert names(got, "removed") == ["Alabama - The Closer You Get.mp3"]
    assert got["removed"][0]["artist"] == "Alabama" and got["removed"][0]["title"] == "The Closer You Get"
    assert not (root / "1 - Cocktail Hour" / "Alabama - The Closer You Get.mp3").exists()
    assert mine.read_bytes() == b"mine"


def test_a_partial_list_removes_nothing(tmp_path):
    link = FakeLink()
    wedding(link)
    root = tmp_path / "copy"
    drive_songs.get_songs(link, FOLDER, root)
    del link.files["c1"]
    link.truncated = True
    got = drive_songs.get_songs(link, FOLDER, root)
    assert got["removed"] == [] and (root / "1 - Cocktail Hour" / "Alabama - The Closer You Get.mp3").is_file()
    link.truncated = False                                # the next full list does take it out
    assert names(drive_songs.get_songs(link, FOLDER, root), "removed") == ["Alabama - The Closer You Get.mp3"]


def test_a_broken_download_never_lands_and_is_tried_again(tmp_path):
    link = FakeLink()
    wedding(link)
    link.corrupt.add("d1")
    root = tmp_path / "copy"
    got = drive_songs.get_songs(link, FOLDER, root)
    assert [f["file"] for f in got["failed"]] == ["2 - Dinner/Clint Black - Killin' Time.mp3"]
    assert not (root / "2 - Dinner" / "Clint Black - Killin' Time.mp3").exists() and not list(root.rglob("*.part"))
    link.corrupt.clear()
    got = drive_songs.get_songs(link, FOLDER, root)
    assert names(got, "new") == ["Clint Black - Killin' Time.mp3"]


def test_llano_unreachable_changes_nothing(tmp_path):
    link = FakeLink()
    wedding(link)
    root = tmp_path / "copy"
    drive_songs.get_songs(link, FOLDER, root)

    def down(folder_id=""):
        raise llano_sync.LinkError("couldn't reach Llano (timed out)")
    link.drive_songs = down
    with pytest.raises(drive_songs.SongsError, match="couldn't reach Llano"):
        drive_songs.get_songs(link, FOLDER, root)
    assert len(list(root.rglob("*.mp3"))) == 5


def test_names_windows_cannot_hold_are_made_safe_and_never_climb_out(tmp_path):
    link = FakeLink()
    link.put("a1", ["../..", "Dinner: main"], 'AC/DC - "Thunder"?.mp3', b"x")
    link.put("a2", [], "CON.mp3", b"y")
    root = tmp_path / "copy"
    drive_songs.get_songs(link, FOLDER, root)
    files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.mp3"))
    assert files == ["..-/Dinner- main/AC-DC - -Thunder--.mp3", "_CON.mp3"]
    assert all(root in p.resolve().parents for p in root.rglob("*.mp3"))


# --- Add a song from this laptop ------------------------------------------------------------------------------

def test_add_a_song_from_this_laptop_lands_in_its_part_and_the_moments(tmp_path):
    root = tmp_path / "copy"
    (root / "2 - Dinner").mkdir(parents=True)
    src = tmp_path / "Downloads" / "George Strait - Check Yes or No.mp3"
    src.parent.mkdir()
    src.write_bytes(b"strait")
    song = drive_songs.add_file(src, root, "dinner")
    assert song["part"] == "dinner" and song["moment"] == "" and song["artist"] == "George Strait"
    assert (root / "2 - Dinner" / src.name).read_bytes() == b"strait"       # his own Dinner folder
    song = drive_songs.add_file(src, root, "", "first-dance")
    assert song["moment"] == "first-dance" and (root / "4 - Moments" / src.name).is_file()
    song = drive_songs.add_file(src, root, "cocktail")
    assert (root / "1 - Cocktail Hour" / src.name).is_file()
    assert drive_songs.add_file(src, root, "dinner")["part"] == "dinner"     # the same file again: fine
    other = tmp_path / "George Strait - Check Yes or No.mp3"
    other.write_bytes(b"another recording")
    with pytest.raises(drive_songs.SongsError, match="already in"):
        drive_songs.add_file(other, root, "dinner")
    for bad, part, moment in ((tmp_path / "nope.mp3", "dinner", ""), (tmp_path / "Downloads", "dinner", ""),
                              (src, "", ""), (src, "brunch", ""), (src, "", "bouquet")):
        with pytest.raises(drive_songs.SongsError):
            drive_songs.add_file(bad, root, part, moment)
    notes = tmp_path / "notes.txt"
    notes.write_text("x")
    with pytest.raises(drive_songs.SongsError, match="not a song"):
        drive_songs.add_file(notes, root, "dinner")


# --- the link: list and download through llano.app ------------------------------------------------------------

class _Resp:
    def __init__(self, body: bytes):
        self.body, self.headers = body, {}

    def read(self, n=-1):
        if n is None or n < 0:
            n = len(self.body)
        out, self.body = self.body[:n], self.body[n:]
        return out

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Opener:
    def __init__(self, answers):
        self.answers, self.reqs = answers, []

    def open(self, req, timeout=0):
        self.reqs.append(req)
        return _Resp(self.answers.pop(0))


def test_the_link_lists_and_downloads_with_its_token(tmp_path):
    from tools.gigbar_lights import show_settings
    op = _Opener([json.dumps({"folders": [FOLDER]}).encode(), json.dumps({"files": []}).encode(), b"ID3song"])
    link = llano_sync.LlanoLink(show_settings.SettingsFile(tmp_path / "settings.json"), version="9.9.9",
                                path=tmp_path / "llano_link.json", url="https://llano.test/v1/", opener=op)
    with pytest.raises(llano_sync.LinkError, match="link this laptop"):
        link.drive_songs()
    link.token = "t" * 40
    assert link.drive_folders() == [FOLDER]
    assert link.drive_songs(FOLDER["id"]) == {"files": []}
    md5 = link.download_song(FOLDER["id"], "fileID000001", tmp_path / "x.part")
    assert md5 == hashlib.md5(b"ID3song").hexdigest() and (tmp_path / "x.part").read_bytes() == b"ID3song"
    urls = [r.full_url for r in op.reqs]
    assert urls[:2] == ["https://llano.test/v1/songs"] * 2
    assert urls[2] == f"https://llano.test/v1/song?folder={FOLDER['id']}&id=fileID000001"
    assert json.loads(op.reqs[0].data) == {"folders_only": True}
    assert all(r.get_header("X-llano-lights-token") == "t" * 40 for r in op.reqs)


# --- the Shows page's actions ----------------------------------------------------------------------------------

from tests.gigbar_lights.test_shows import _call, lib, window  # noqa: E402,F401


def test_connect_get_and_read_from_the_shows_page(window, tmp_path, monkeypatch):  # noqa: F811
    app, url, token, _tmp = window
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    fake = FakeLink()
    wedding(fake)
    real = app.link
    app.link = fake
    try:
        code, h = _call(url + "api/shows-drive-home", {}, token)
        assert code == 200 and h["connected"] == {} and h["linked"] is True
        assert _call(url + "api/shows-drive-get", {}, token)[0] == 409               # not connected yet
        code, r = _call(url + "api/shows-drive-connect", {}, token)                  # one folder: connects
        assert code == 200 and r["connected"]["id"] == FOLDER["id"]
        root = Path(r["connected"]["root"])
        assert root == tmp_path / "home" / "Music" / "Llano Lights songs" / "Avery & Jordan Wedding Songs"
        st = {}
        for _ in range(100):
            _, st = _call(url + "api/shows-drive-status", {}, token)
            if st["get"]["state"] != "getting":
                break
            time.sleep(0.05)
        assert st["get"]["state"] == "done" and len(st["get"]["new"]) == 5
        code, rd = _call(url + "api/shows-drive-read", {"have": []}, token)
        assert code == 200 and rd["folder"] == str(root) and rd["title"] == FOLDER["name"]
        got = {s["title"]: s["part"] for s in rd["songs"]}
        assert got["Killin' Time"] == "dinner" and got["The Closer You Get"] == "cocktail"
        assert "Owl City" not in got and rd["aside"] == ["Fireflies - Owl City (Extra)"]   # Extra stays out of the night
        # two connected folders: he picks one
        fake.folders = [FOLDER, {"id": "folderPARTY00001", "name": "Party"}]
        code, r = _call(url + "api/shows-drive-connect", {}, token)
        assert code == 200 and [f["name"] for f in r["pick"]] == [FOLDER["name"], "Party"]
        # Add a song from this laptop, into the copy's Dinner folder
        src = tmp_path / "Brooks & Dunn - Neon Moon.mp3"
        src.write_bytes(b"neon")
        code, a = _call(url + "api/shows-add-file", {"path": str(src), "part": "dinner", "folder": str(root)}, token)
        assert code == 200 and a["song"]["part"] == "dinner" and a["song"]["title"] == "Neon Moon"
        assert (root / "2 - Dinner" / src.name).is_file()
        code, a = _call(url + "api/shows-add-file", {"path": str(src), "part": "", "moment": "last-dance"}, token)
        assert code == 200 and a["song"]["moment"] == "last-dance"
        assert _call(url + "api/shows-add-file", {"path": str(tmp_path / "gone.mp3"), "part": "dinner"}, token)[0] == 400
        # the hand-added song survives the next Get my songs
        _call(url + "api/shows-drive-get", {}, token)
        for _ in range(100):
            _, st = _call(url + "api/shows-drive-status", {}, token)
            if st["get"]["state"] != "getting":
                break
            time.sleep(0.05)
        assert st["get"]["removed"] == [] and (root / "2 - Dinner" / src.name).is_file()
        # unlinked: Get my songs says so
        fake.linked = False
        assert _call(url + "api/shows-drive-get", {}, token)[0] == 409
    finally:
        app.link = real


def test_the_page_has_both_drive_and_hand_paths(window):  # noqa: F811
    _app, url, _token, _tmp = window
    code, page = _call(url + "shows")
    assert code == 200
    for want in (b"Connect my Drive folder", b"Get my songs", b"Add a song from this laptop", b"From your phone",
                 b'id="browse"', b'id="addfolder"'):
        assert want in page, want


# --- the night build redoes only what changed --------------------------------------------------------------------

def test_the_night_build_redoes_only_songs_that_changed(tmp_path):
    pytest.importorskip("numpy")
    sf = pytest.importorskip("soundfile")
    from tests.gigbar_lights.test_wedding_night import NIGHT, PART_OF, make_folder, song
    from tools.gigbar_lights import wedding_night
    src = make_folder(tmp_path, NIGHT, secs=4)
    songs = [{"artist": a, "title": t, "part": PART_OF[p]} for p, a, t in NIGHT]
    files = wedding_night.index_folder(src)
    out = tmp_path / "night"
    first = wedding_night.build(out, songs, files, title="AJ", extras=False)
    n = first["redone"]
    assert n == len(first["cuts"]) and first["kept"] == 0
    stamp = {p: p.stat().st_mtime_ns for p in (out / "Songs").rglob("*.flac")}
    again = wedding_night.build(out, songs, files, title="AJ", extras=False)
    assert again["redone"] == 0 and again["kept"] == n
    assert {p: p.stat().st_mtime_ns for p in (out / "Songs").rglob("*.flac")} == stamp   # not one cut rewritten
    assert again["files"] == first["files"]
    # Get my songs brought a new copy of one dinner song: only that one is redone
    time.sleep(0.01)
    sf.write(str(src / "2 - Dinner" / "C - Eat.wav"), song(4, level=0.2, rate=8000, hz=300), 8000)
    third = wedding_night.build(out, songs, wedding_night.index_folder(src), title="AJ", extras=False)
    assert third["redone"] >= 1 and third["kept"] >= n - 1 - (third["redone"] - 1)
    redone = {p for p, t in ((p, p.stat().st_mtime_ns) for p in (out / "Songs").rglob("*.flac")) if stamp.get(p) != t}
    assert any("Eat" in p.name for p in redone)
    # a song moved to another part is cut again for that part
    moved = [{**s, "part": "dancing"} if s["title"] == "Sip" else s for s in songs]
    fourth = wedding_night.build(out, moved, wedding_night.index_folder(src), title="AJ", extras=False)
    assert fourth["redone"] >= 1


def test_get_my_songs_and_add_a_song_in_a_real_browser(window, tmp_path, monkeypatch):  # noqa: F811
    pw = pytest.importorskip("playwright.sync_api")
    app, url, _token, _tmp = window
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    fake = FakeLink()
    wedding(fake)
    real = app.link
    app.link = fake
    mine = tmp_path / "Brooks & Dunn - Neon Moon.mp3"
    mine.write_bytes(b"neon")
    errors: list = []
    try:
        with pw.sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception as e:  # noqa: BLE001 -- no browser on this machine
                pytest.skip(f"no headless chromium: {e}")
            try:
                page = browser.new_page()
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(url + "shows")
                page.wait_for_selector("#driveconnect")
                assert page.is_visible("#driveconnect") and not page.is_visible("#driveget")
                assert "From your phone" in page.inner_text("#drivebox")
                assert page.eval_on_selector_all("#addfilepart option", "els => els.map(e => e.value)")[:3] == \
                    ["part:cocktail", "part:dinner", "part:dancing"]
                page.click("#driveconnect")                  # connects, gets, and puts the songs in the show
                page.wait_for_function("document.querySelector('#driveline').innerText.includes('added to the show')",
                                       timeout=15000)
                line = page.inner_text("#driveline")
                assert "5 new, 0 removed" in line and "4 songs added to the show" in line and "Owl City" in line
                assert page.is_visible("#driveget") and "Avery & Jordan" in page.inner_text("#drivename")
                assert page.input_value("#folder").endswith("Avery & Jordan Wedding Songs")
                songs = page.inner_text("#songs")
                assert "Killin' Time" in songs and "Owl City" not in songs
                # he takes a song out in Drive and adds one from his phone: Get my songs follows the folder
                del fake.files["c1"]
                fake.put("d2", ["2 - Dinner"], "Randy Travis - Forever and Ever, Amen.mp3", b"amen")
                page.click("#driveget")
                page.wait_for_function("document.querySelector('#driveline').innerText.includes('1 new, 1 removed')"
                                       " && document.querySelector('#driveline').innerText.includes('taken out')",
                                       timeout=15000)
                songs = page.inner_text("#songs")
                assert "Forever and Ever, Amen" in songs and "The Closer You Get" not in songs
                # Add a song from this laptop, into Dinner
                page.fill("#addfile", f'"{mine}"')
                page.select_option("#addfilepart", "part:dinner")
                page.click("#addfilego")
                page.wait_for_function("document.body.innerText.includes('Neon Moon is in Dinner')", timeout=10000)
                assert "Neon Moon" in page.inner_text("#songs")
            finally:
                browser.close()
    finally:
        app.link = real
    assert errors == []
