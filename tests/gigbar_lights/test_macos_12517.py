"""Llano Lights on a Mac (Llano BL #12517): the Mac seams, the Mac update feed, and the .app swap.

These run on any computer (the Mac calls are faked); test_macos_smoke.py runs the real ones on a
GitHub macOS runner.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import types
import zipfile
from pathlib import Path

import pytest

from tools.gigbar_lights import ed25519, enttec, folder_picker, hotspot, macos, media_session, system_audio, updater

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows"))
import history  # noqa: E402

SEED = bytes(range(32))
KEY = ed25519.public_key(SEED)


# --- the seams ---------------------------------------------------------------------------------

def test_mixxx_settings_follow_the_library_sandboxed_or_not(tmp_path):
    assert macos.mixxx_settings_dir(tmp_path) == tmp_path / macos.MIXXX_SANDBOXED   # nothing yet: the mixxx.org build
    plain = tmp_path / macos.MIXXX_PLAIN
    plain.mkdir(parents=True)
    assert macos.mixxx_settings_dir(tmp_path) == plain                             # a Homebrew Mixxx's folder
    box = tmp_path / macos.MIXXX_SANDBOXED
    box.mkdir(parents=True)
    (plain / "mixxxdb.sqlite").write_bytes(b"")
    assert macos.mixxx_settings_dir(tmp_path) == plain                             # the one with a library wins
    (box / "mixxxdb.sqlite").write_bytes(b"")
    assert macos.mixxx_settings_dir(tmp_path) == box


def test_mixxx_paths_on_a_mac_use_that_folder(tmp_path, monkeypatch):
    from tools.gigbar_lights import mixxx_db, mixxx_load, wedding_night
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert mixxx_db.default_db_path() == tmp_path / macos.MIXXX_SANDBOXED / "mixxxdb.sqlite"
    assert wedding_night.mixxx_cfg_path() == tmp_path / macos.MIXXX_SANDBOXED / "mixxx.cfg"
    exe = tmp_path / "Applications" / "Mixxx.app" / "Contents" / "MacOS" / "mixxx"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert mixxx_load.find_mixxx() == str(exe)


def test_the_window_browser_is_the_first_chromium_installed(tmp_path):
    assert macos.find_browser(tmp_path) is None or macos.find_browser(tmp_path)[1].is_relative_to("/Applications")
    brave = tmp_path / "Applications" / "Brave Browser.app" / "Contents" / "MacOS" / "Brave Browser"
    brave.parent.mkdir(parents=True)
    brave.write_text("")
    found = macos.find_browser(tmp_path)
    assert found is not None
    cmd = macos.chrome_window_command(found[1], "http://127.0.0.1:8765/", tmp_path / "p", ("--no-first-run",))
    assert cmd[1:] == ["--app=http://127.0.0.1:8765/", f"--user-data-dir={tmp_path / 'p'}", "--no-first-run"]


def test_the_mac_window_opens_chrome_as_an_app_window(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))
    import gigbar_app
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(gigbar_app.macos, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(gigbar_app.macos, "find_browser", lambda: ("Google Chrome", Path("/Applications/Chrome")))
    seen = []
    monkeypatch.setattr(gigbar_app.subprocess, "Popen", lambda cmd, **kw: seen.append(cmd) or "proc")
    assert gigbar_app.open_window("http://127.0.0.1:8765/") == "proc"
    assert seen[0][:2] == ["/Applications/Chrome", "--app=http://127.0.0.1:8765/"]
    assert f"--user-data-dir={tmp_path / gigbar_app.WINDOW_PROFILE}" in seen[0]
    # no Chromium browser: the default browser, and nothing to watch
    monkeypatch.setattr(gigbar_app.macos, "find_browser", lambda: None)
    opened = []
    monkeypatch.setattr(gigbar_app.macos, "default_browser_open", lambda url: opened.append(url) or True)
    assert gigbar_app.open_window("http://127.0.0.1:8765/") is None and opened == ["http://127.0.0.1:8765/"]


def test_the_mac_picker_passes_his_words_as_arguments(monkeypatch):
    calls = []

    def fake(script, *args, timeout):
        calls.append((script, args))
        return fake.result

    monkeypatch.setattr(macos, "osascript", fake)
    fake.result = (0, "/Users/dj/Music/Wedding/", "")
    assert macos.pick(macos.PICK_FOLDER, 'Songs "tonight"', "/Users/dj") == ("/Users/dj/Music/Wedding", "")
    assert calls[0][1] == ('Songs "tonight"', "/Users/dj") and "tonight" not in calls[0][0]
    fake.result = (1, "", "execution error: User canceled. (-128)")
    assert macos.pick(macos.PICK_FOLDER, "x", "") == ("", "")
    fake.result = (1, "", "execution error: something else (-1700)")
    path, why = macos.pick(macos.PICK_FOLDER, "x", "")
    assert path == "" and "Paste" in why


def test_folder_picker_uses_the_mac_dialog_on_a_mac(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(macos, "pick", lambda script, title, start: (str(tmp_path), ""))
    assert folder_picker.pick("Choose") == (str(tmp_path), "")
    song = tmp_path / "a.mp3"
    song.write_bytes(b"")
    monkeypatch.setattr(macos, "pick", lambda script, title, start: (str(song), "") if script is macos.PICK_FILE else ("", "x"))
    assert folder_picker.pick_file("Choose") == (str(song), "")


def test_now_playing_reads_spotify_and_music_lines():
    out = "Spotify\tplaying\tBon Jovi\tLivin' On A Prayer\nMusic\tpaused\tABBA\tDancing Queen\nnonsense\n"
    rows = macos.parse_now_playing(out)
    assert rows == [("Spotify", True, "Bon Jovi", "Livin' On A Prayer"), ("Apple Music", False, "ABBA", "Dancing Queen")]
    raw = "Spotify\t«constant ****kPSP»\tA\tB\nMusic\t«constant ****kPSp»\tC\tD\n"   # raw player-state codes
    assert [r[1] for r in macos.parse_now_playing(raw)] == [True, False]


def test_now_playing_asks_only_players_that_are_open(monkeypatch):
    calls = []
    monkeypatch.setattr(macos, "running_players", lambda: [])
    monkeypatch.setattr(macos, "osascript", lambda script, *args, **kw: calls.append(args) or (0, "playing\tA\tB", ""))
    assert macos.read_now_playing() == [] and calls == []          # nothing open: no osascript at all
    assert "Spotify" not in macos.NOW_PLAYING                        # never named in a script (Where is Spotify?)
    monkeypatch.setattr(macos, "running_players", lambda: [macos.PLAYERS[0]])
    assert macos.read_now_playing() == [("Spotify", True, "A", "B")] and calls == [("com.spotify.client",)]


def test_the_media_poller_uses_the_mac_reader_on_a_mac(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(macos, "read_now_playing", lambda: [("Apple Music", False, "ABBA", "Dancing Queen"),
                                                            ("Spotify", True, "Bon Jovi", "Prayer")])
    m = media_session.MediaSessions(poll_s=0.01).start()
    deadline = time.monotonic() + 3
    while m.current() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    m.stop()
    now = m.current()
    assert now is not None and (now.app, now.title, now.playing) == ("Spotify", "Prayer", True)


def test_a_mac_says_use_the_phone_hotspot(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    ok, why = hotspot.start()
    assert not ok and "phone's hotspot" in why and "Mac" in why


def test_a_mac_never_tries_speaker_loopback(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    cap = system_audio.LoopbackCapture()
    cap._run()
    assert cap.unavailable and "Mixxx" in cap.error


def test_the_enttec_cu_port_beats_the_tty_one(monkeypatch):
    def port(dev):
        return types.SimpleNamespace(vid=enttec.FTDI_VID, pid=enttec.FT232R_PID, serial_number="EN123456", device=dev)
    fake = types.SimpleNamespace(comports=lambda: [port("/dev/tty.usbserial-EN123456"), port("/dev/cu.usbserial-EN123456")])
    monkeypatch.setitem(sys.modules, "serial.tools.list_ports", fake)
    monkeypatch.setitem(sys.modules, "serial.tools", types.SimpleNamespace(list_ports=fake))
    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(tools=types.SimpleNamespace(list_ports=fake)))
    assert enttec.find_port() == "/dev/cu.usbserial-EN123456"


# --- the Mac update feed -----------------------------------------------------------------------

def signed(manifest: dict) -> bytes:
    return json.dumps(updater.sign_manifest(manifest, SEED)).encode()


def manifest(**over) -> dict:
    m = {"product": updater.PRODUCT, "version": "99.0.0", "zip": "Llano-Lights-99.0.0-mac.zip",
         "sha256": "0" * 64, "size": 10, "platform": "mac"}
    m.update(over)
    return m


def test_each_platform_reads_its_own_file(monkeypatch):
    monkeypatch.delenv("LLANO_LIGHTS_UPDATE_URL", raising=False)
    monkeypatch.setattr(updater, "UPDATE_URL", "https://example.invalid/dl/k/latest.json")
    assert updater.update_url("windows") == "https://example.invalid/dl/k/latest.json"
    assert updater.test_url("windows") == "https://example.invalid/dl/k/test.json"
    assert updater.update_url("mac") == "https://example.invalid/dl/k/latest-mac.json"
    assert updater.test_url("mac") == "https://example.invalid/dl/k/test-mac.json"
    monkeypatch.setattr(updater, "UPDATE_URL", "")   # the open-source edition: no feed anywhere
    assert updater.update_url("mac") == "" and updater.test_url("mac") == ""


def test_a_mac_file_never_reaches_windows_and_back():
    base = "https://example.invalid/dl/k/latest-mac.json"
    offer = updater.parse_update_file(signed(manifest()), base, "1.0.0", KEY, platform="mac")
    assert offer and offer.zip_url.endswith("/Llano-Lights-99.0.0-mac.zip")
    with pytest.raises(updater.UpdateError, match="another kind of computer"):
        updater.parse_update_file(signed(manifest()), base, "1.0.0", KEY, platform="windows")
    win = manifest(zip="Llano-Lights-99.0.0.zip")
    del win["platform"]   # every Windows file before the Mac existed
    assert updater.parse_update_file(signed(win), base, "1.0.0", KEY, platform="windows")
    with pytest.raises(updater.UpdateError, match="another kind of computer"):
        updater.parse_update_file(signed(win), base, "1.0.0", KEY, platform="mac")


def fake_bundle(app: Path, tag: str, marker: Path, comes_up: bool = True) -> Path:
    """A .app whose launcher records which copy started and with what flag, and writes the ready
    file it is handed once it is up (like the real app)."""
    inner = app / updater.MAC_INNER
    (inner / "app").mkdir(parents=True)
    (inner / "runtime" / "bin").mkdir(parents=True)
    (inner / "app" / "gigbar_app.py").write_text(tag)
    exe = app / updater.MAC_LAUNCHER
    exe.parent.mkdir(parents=True)
    ready = '[ "$2" = "--ready-file" ] && echo up > "$3"\n' if comes_up else "sleep 30\n"
    exe.write_text(f"#!/bin/sh\necho {tag} \"$1\" >> '{marker}'\n{ready}")
    exe.chmod(0o755)
    return app


def run_swap(cmd, **plan_over):
    plan = json.loads(Path(cmd[-1]).read_text())
    plan.setdefault("pid", None)
    plan["pid"] = plan_over.pop("pid", None)   # the test runner is not the old app: nothing to wait for
    plan.update(plan_over)
    Path(cmd[-1]).write_text(json.dumps(plan))
    subprocess.run([sys.executable, *cmd[1:]], check=False, timeout=90)  # cmd[0] is the bundle's Python
    return json.loads(Path(cmd[-1]).read_text())


def wait_for(marker: Path, lines: int, s: float = 15):
    deadline = time.time() + s
    while time.time() < deadline and (not marker.exists() or len(marker.read_text().split("\n")) <= lines):
        time.sleep(0.1)
    return marker.read_text().split() if marker.exists() else []


posix_only = pytest.mark.skipif(sys.platform == "win32", reason="the fake launcher is a shell script")


def test_install_root_inside_an_app_is_known_as_a_bundle(tmp_path):
    app = fake_bundle(tmp_path / "Applications" / updater.MAC_APP, "x", tmp_path / "m")
    inner = app / updater.MAC_INNER
    assert updater.is_installed(inner)
    assert updater.app_bundle(inner) == app and updater.swap_root(inner) == app
    assert updater.stable_path(inner) == Path(str(app) + ".stable")
    plain = tmp_path / "Llano-Lights"
    assert updater.app_bundle(plain) is None and updater.swap_root(plain) == plain


def test_a_translocated_or_disk_image_app_refuses_to_update(tmp_path):
    assert "Applications" in updater.mac_update_refusal(Path("/private/var/folders/x/AppTranslocation/ABC/d/Llano Lights.app"))
    assert "Applications" in updater.mac_update_refusal(Path("/Volumes/Llano Lights/Llano Lights.app"))
    assert updater.mac_update_refusal(tmp_path / "Llano Lights.app") == ""


@posix_only
def test_the_mac_swap_replaces_the_whole_app_and_starts_it(tmp_path):
    marker = tmp_path / "started.txt"
    apps = tmp_path / "Applications"
    root = fake_bundle(apps / updater.MAC_APP, "old", marker)
    new = fake_bundle(apps / (updater.MAC_APP + ".new"), "new", marker)
    cmd = updater.stage_swap(root, new, "99.0.0", wait_s=2)
    assert cmd[0] == str(root / updater.MAC_INNER / "runtime" / "bin" / "python3")
    assert "-B" in cmd[1:-2]   # the bundle's own Python writes no .pyc into the signed bundle
    plan = run_swap(cmd)
    assert plan["mac"] is True
    assert (root / updater.MAC_INNER / "app" / "gigbar_app.py").read_text() == "new"
    assert not new.exists() and not Path(str(root) + ".old").exists()
    assert wait_for(marker, 1) == ["new", "--updated"]


@posix_only
def test_the_mac_swap_puts_the_old_app_back_when_the_new_one_never_comes_up(tmp_path):
    marker = tmp_path / "started.txt"
    apps = tmp_path / "Applications"
    root = fake_bundle(apps / updater.MAC_APP, "old", marker)
    new = fake_bundle(apps / (updater.MAC_APP + ".new"), "new", marker, comes_up=False)
    cmd = updater.stage_swap(root, new, "99.0.0", wait_s=2)
    run_swap(cmd, ready_s=2)
    assert (root / updater.MAC_INNER / "app" / "gigbar_app.py").read_text() == "old"
    assert "old --update-failed" in " ".join(wait_for(marker, 2))


@posix_only
def test_the_mac_swap_waits_for_the_old_app_to_exit_first(tmp_path):
    """A Mac lets a running app's folder be renamed, so the swap waits for the old copy's process
    (the plan's pid) before it moves anything; the new copy never meets it holding the lights box."""
    marker = tmp_path / "started.txt"
    apps = tmp_path / "Applications"
    root = fake_bundle(apps / updater.MAC_APP, "old", marker)
    new = fake_bundle(apps / (updater.MAC_APP + ".new"), "new", marker)
    # the "old app": not this test's child, so it is reaped when it ends (a zombie still answers kill 0)
    pid = int(subprocess.run(["sh", "-c", "sleep 1.5 >/dev/null 2>&1 & echo $!"], capture_output=True,
                             text=True).stdout)
    cmd = updater.stage_swap(root, new, "99.0.0", wait_s=10)
    assert json.loads(Path(cmd[-1]).read_text())["pid"] == os.getpid()   # the app that prepared it
    t = time.monotonic()
    run_swap(cmd, pid=pid)
    took = time.monotonic() - t
    assert 1.2 <= took < 8, took
    assert wait_for(marker, 1) == ["new", "--updated"]


def test_the_swap_program_imports_nothing_windows_runtime_lacks():
    """BL #12517 review: Windows' swap runs on a few runtime files copied to temp (no select.pyd), so
    its unconditional imports must stay within what python312.zip and the built-ins hold."""
    import ast
    tree = ast.parse(updater.SWAP_PROGRAM)
    top = {a.name.split(".")[0] for node in tree.body if isinstance(node, ast.Import) for a in node.names}
    top |= {node.module.split(".")[0] for node in tree.body if isinstance(node, ast.ImportFrom)}
    assert top <= {"json", "os", "shutil", "subprocess", "sys", "time"}, top


def test_a_mac_zip_with_a_link_inside_is_refused(tmp_path):
    z = tmp_path / "Llano-Lights-99.0.0-mac.zip"
    with zipfile.ZipFile(z, "w") as w:
        link = zipfile.ZipInfo(f"{updater.MAC_APP}/Contents/x")
        link.external_attr = (0o120777) << 16
        w.writestr(link, "/Users/dj/Library/LaunchAgents")
    with pytest.raises(updater.UpdateError, match="unexpected layout"):
        updater.unpack_mac(z, tmp_path / "staging.app")


def test_a_mac_zip_with_a_strange_layout_is_refused_before_anything_unpacks(tmp_path):
    z = tmp_path / "Llano-Lights-99.0.0-mac.zip"
    for bad in ("Other.app/Contents/MacOS/x", f"{updater.MAC_APP}/../evil", "/abs"):
        with zipfile.ZipFile(z, "w") as w:
            w.writestr(bad, "x")
        with pytest.raises(updater.UpdateError, match="unexpected layout"):
            updater.unpack_mac(z, tmp_path / "staging.app")
        assert not (tmp_path / "staging.app").exists()


# --- releases.json: the Mac build rides its version's row -----------------------------------------

def mac_manifest(**over):
    m = {"version": "1.40.0", "zip": "Llano-Lights-1.40.0-mac.zip", "sha256": "a" * 64, "size": 5,
         "built": "2026-11-18T00:00:00Z", "commit": "c" * 40, "notarized": True}
    m.update(over)
    return m


def test_a_mac_build_joins_its_windows_release_row():
    h = {"product": "llano-lights", "releases": [{"version": "1.40.0", "zip": "Llano-Lights-1.40.0.zip",
                                                  "commit": "c" * 40, "download": "", "built_ct": "x", "notes": "n"}]}
    with pytest.raises(ValueError, match="release the Windows build first"):
        history.add_mac(h, mac_manifest(version="1.41.0"))
    with pytest.raises(ValueError, match="from that commit"):
        history.add_mac(h, mac_manifest(commit="d" * 40))
    history.add_mac(h, mac_manifest(), {"name": "Llano-Lights-1.40.0-mac.dmg", "sha256": "b" * 64, "size": 9})
    mac = h["releases"][0]["mac"]
    assert mac["dmg"] == "Llano-Lights-1.40.0-mac.dmg" and mac["notarized"] is True
    with pytest.raises(ValueError, match="already has a Mac build"):
        history.add_mac(h, mac_manifest())
    history.set_download(h, "Llano-Lights-1.40.0-mac.dmg", "https://example.invalid/mac")
    history.set_download(h, "Llano-Lights-1.40.0-mac.zip", "https://example.invalid/mac-zip")
    assert mac["dmg_download"] == "https://example.invalid/mac" and mac["download"] == "https://example.invalid/mac-zip"
    assert h["releases"][0]["download"] == ""
    assert '"mac"' in json.dumps(h)                                 # what BL #12517's end-state probe reads
    assert "[Mac](https://example.invalid/mac)" in history.render(h)


def test_the_build_stamp_and_ticket_are_read_from_a_mac_zip(tmp_path):
    z = tmp_path / "Llano-Lights-1.40.0-mac.zip"
    with zipfile.ZipFile(z, "w") as w:
        w.writestr(history.MAC_BUILD_INFO, "BUILT_UTC = '2026-11-18T00:00:00Z'\nBUILT_CT = 'Nov 17'\n"
                                           f"BUILT_COMMIT = '{'c' * 40}'\n")
    assert history.build_time_in(z) == ("2026-11-18T00:00:00Z", "Nov 17")
    assert history.build_commit_in(z) == "c" * 40
    assert not history.notarized_in(z)
    with zipfile.ZipFile(z, "a") as w:
        w.writestr(history.MAC_TICKET, "ticket")
    assert history.notarized_in(z)
