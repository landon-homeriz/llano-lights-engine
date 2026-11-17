"""The test channel (1.14.0): test builds are offered, never installed without his click, and Go back
to stable puts the stable copy kept on disk back with no internet and no working test build."""
import base64
import datetime
import json
import sys
import time
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_updater import PUB, SEED, fake_install, offer_for, posix_only, run_swap, signed, wait_for  # noqa: E402

from tools.gigbar_lights import probe, rollback, show_settings, updater  # noqa: E402
try:   # the Llano link; the open-source engine ships without it
    from tools.gigbar_lights import llano_sync
except ImportError:   # ok: those tests skip
    llano_sync = None
needs_sync = pytest.mark.skipif(llano_sync is None, reason="the Llano link is not in this edition")
from tools.gigbar_lights import settings_contract as contract  # noqa: E402

WINDOWS = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows"
sys.path.insert(0, str(WINDOWS))
import history  # noqa: E402


# --- the signed test feed ------------------------------------------------------------------------

def test_a_test_build_manifest_is_offered_with_its_channel_and_number():
    m = {"product": "llano-lights", "version": "1.14.0.7", "zip": "Llano-Lights-1.14.0.7.zip",
         "sha256": "ab" * 32, "size": 1000, "channel": "test", "build": 7, "commit": "c" * 40}
    offer = updater.parse_update_file(signed(m), "https://example.invalid/dl/k/test.json", "1.14.0", PUB)
    assert (offer.version, offer.channel, offer.build, offer.commit) == ("1.14.0.7", "test", 7, "c" * 40)
    assert offer.zip_url == "https://example.invalid/dl/k/Llano-Lights-1.14.0.7.zip"
    assert updater.is_newer("1.14.0.7", "1.14.0") and updater.is_newer("1.14.1", "1.14.0.7")


def test_a_release_manifest_is_never_a_test_build():
    m = {"product": "llano-lights", "version": "1.15.0", "zip": "Llano-Lights-1.15.0.zip",
         "sha256": "ab" * 32, "size": 1000, "build": 9}
    offer = updater.parse_update_file(signed(m), "https://example.invalid/dl/k/latest.json", "1.14.0", PUB)
    assert (offer.channel, offer.build) == ("stable", 0)


def test_the_test_feed_sits_beside_the_release_feed(monkeypatch):
    monkeypatch.setenv("LLANO_LIGHTS_UPDATE_URL", "https://example.invalid/dl/k/latest.json")
    assert updater.test_url() == "https://example.invalid/dl/k/test.json"


def test_build_stamps_name_the_channel_and_number(tmp_path):
    when = datetime.datetime(2026, 11, 9, 2, 30, tzinfo=datetime.timezone.utc)
    test_src = history.build_info_source(when, "c" * 40, channel="test", build=7)
    assert "CHANNEL = 'test'\nBUILD = 7\n" in test_src
    assert "CHANNEL" not in history.build_info_source(when, "c" * 40)
    for name, src, want in (("t.zip", test_src, 7), ("s.zip", history.build_info_source(when, "c" * 40), 0)):
        with zipfile.ZipFile(tmp_path / name, "w") as z:
            z.writestr(history.BUILD_INFO, src)
        assert history.build_number_in(tmp_path / name) == want


# --- keep stable, go back --------------------------------------------------------------------------

@posix_only
def test_updating_from_stable_into_a_test_build_keeps_the_stable_copy(tmp_path):
    marker = tmp_path / "started.txt"
    root = fake_install(tmp_path / "Llano-Lights", "stable", marker)
    new = fake_install(tmp_path / "Llano-Lights.new", "test7", marker)
    run_swap(updater.stage_swap(root, new, "1.14.0.7", wait_s=2, keep=updater.stable_path(root)))
    assert (root / "app" / "gigbar_app.py").read_text() == "test7"
    assert (updater.stable_path(root) / "app" / "gigbar_app.py").read_text() == "stable"
    assert updater.stable_copy(root) == updater.stable_path(root)
    assert wait_for(marker, 1) == ["test7", "--updated"]


@posix_only
def test_go_back_puts_the_stable_copy_back_and_drops_the_test_build(tmp_path):
    marker = tmp_path / "started.txt"
    root = fake_install(tmp_path / "Llano-Lights", "test7", marker)
    fake_install(updater.stable_path(root), "stable", marker)
    cmd = updater.stage_rollback(root)
    # it runs on the stable copy's Python, never the test build's
    assert Path(cmd[0]).read_text() == (updater.stable_path(root) / "runtime" / "pythonw.exe").read_text()
    run_swap(cmd, wait_s=2)
    assert (root / "app" / "gigbar_app.py").read_text() == "stable"
    assert not updater.stable_path(root).exists() and not Path(str(root) + ".old").exists()
    assert wait_for(marker, 1) == ["stable", "--updated"]


@posix_only
def test_go_back_works_when_the_test_build_folder_is_gone(tmp_path):
    marker = tmp_path / "started.txt"
    root = tmp_path / "Llano-Lights"
    fake_install(updater.stable_path(root), "stable", marker)
    run_swap(updater.stage_rollback(root), wait_s=2)
    assert (root / "app" / "gigbar_app.py").read_text() == "stable"
    assert wait_for(marker, 1) == ["stable", "--updated"]


def test_go_back_with_no_stable_copy_says_so(tmp_path):
    root = fake_install(tmp_path / "Llano-Lights", "test7", tmp_path / "m")
    assert updater.stable_copy(root) is None
    with pytest.raises(updater.UpdateError, match="no stable copy"):
        updater.stage_rollback(root)


def test_only_stable_to_test_keeps_a_copy_and_writes_the_launchers(tmp_path, monkeypatch):
    root = fake_install(tmp_path / "Llano-Lights", "stable", tmp_path / "m")
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    z = tmp_path / "Llano-Lights-1.14.0.7.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("Llano-Lights/runtime/pythonw.exe", b"exe")
        f.writestr("Llano-Lights/app/gigbar_app.py", b"test7")
    monkeypatch.setattr(updater, "CHANNEL", "stable")
    plan = json.loads(Path(updater.prepare(offer_for(z, version="1.14.0.7", channel="test", build=7), root)[2]).read_text())
    assert plan["keep"] == str(updater.stable_path(root))
    menu = tmp_path / "appdata" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / updater.ROLLBACK_NAME
    for launcher in (menu, root.parent / updater.ROLLBACK_NAME):
        text = launcher.read_text()
        assert f'"{updater.stable_path(root)}\\runtime\\python.exe" -m tools.gigbar_lights.rollback "{root}"' in text
    # a test build updating to the next test build keeps the stable copy it already has
    monkeypatch.setattr(updater, "CHANNEL", "test")
    plan = json.loads(Path(updater.prepare(offer_for(z, version="1.14.0.8", channel="test", build=8), root)[2]).read_text())
    assert plan["keep"] is None


def test_a_stable_copy_cleans_the_kept_copy_and_launchers_a_test_copy_keeps_them(tmp_path, monkeypatch):
    root = fake_install(tmp_path / "Llano-Lights", "x", tmp_path / "m")
    fake_install(updater.stable_path(root), "stable", tmp_path / "m")
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    updater.write_rollback_launchers(root)
    monkeypatch.setattr(updater, "CHANNEL", "test")
    updater.clean_leftovers(root)
    assert updater.stable_copy(root) and (root.parent / updater.ROLLBACK_NAME).exists()
    monkeypatch.setattr(updater, "CHANNEL", "stable")
    updater.clean_leftovers(root)
    assert not updater.stable_path(root).exists() and not (root.parent / updater.ROLLBACK_NAME).exists()


def test_the_launcher_program_refuses_to_run_from_anywhere_but_the_stable_copy(tmp_path, capsys):
    assert rollback.main([str(tmp_path / "Llano-Lights")]) == 2
    assert "stable copy" in capsys.readouterr().out


# --- probes ----------------------------------------------------------------------------------------

@pytest.fixture
def no_probe():
    probe.clear()
    yield
    probe.clear()
    probe.note = ""


def test_a_probe_holds_exact_bytes_then_lapses(no_probe):
    probe.set_probe(probe.clean({"24": 200, "25": "17", "0": 5, "600": 1, "26": 256, "x": 1}), time.time() + 0.3)
    u = probe.apply(bytes(512))
    assert (u[23], u[24], u[25]) == (200, 17, 0)
    assert probe.public()["channels"] == {"24": 200, "25": 17}
    time.sleep(0.35)
    assert probe.apply(bytes(512)) == bytes(512) and probe.active() == {}


def test_a_probe_never_outlasts_the_laptops_own_limit(no_probe):
    probe.set_probe({1: 255}, time.time() + 3600)
    assert probe.left() <= probe.PROBE_MAX


def _link(tmp_path, playing=False):
    settings = show_settings.SettingsFile(tmp_path / "settings.json")
    link = llano_sync.LlanoLink(settings, version="1.14.0", path=tmp_path / "link.json", song_playing=lambda: playing)
    link.token = "t" * 30
    return link


def _until(s):
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=s)).isoformat()


@needs_sync
def test_a_probe_from_llano_lands_and_a_new_token_ends_it(tmp_path, no_probe):
    link = _link(tmp_path)
    link._probe({"token": "1", "channels": {"30": 255}, "until": _until(10), "by": "session:x"})
    assert probe.active() == {30: 255} and probe.public()["by"] == "session:x"
    link._probe({"token": "1|stop", "channels": None, "until": None})
    assert probe.active() == {}


@needs_sync
def test_a_probe_is_refused_while_a_song_plays(tmp_path, no_probe):
    link = _link(tmp_path, playing=True)
    link._probe({"token": "2", "channels": {"30": 255}, "until": _until(10)})
    assert probe.active() == {} and probe.note == "refused: a song is playing"


@needs_sync
def test_the_kill_switch_refuses_probes(tmp_path, no_probe, monkeypatch):
    monkeypatch.setenv("LLANO_LIGHTS_PROBE", "0")
    _link(tmp_path)._probe({"token": "3", "channels": {"30": 255}, "until": _until(10)})
    assert probe.active() == {} and "switched off" in probe.note


@needs_sync
def test_the_pull_hands_a_test_build_to_the_app(tmp_path):
    seen = []
    link = _link(tmp_path)
    link.update_fn = seen.append
    link._update({"channel": "test", "build": 7, "version": "1.14.0.7"})
    link._update(None)
    assert seen == [{"channel": "test", "build": 7, "version": "1.14.0.7"}]


@needs_sync
def test_frames_cover_every_slot_the_rig_uses():
    assert llano_sync.frame_slots() == 192
    doc = contract.defaults()
    doc["rig"]["addresses"]["stick4"] = 300
    try:
        show_settings.set_current(doc)
        assert llano_sync.frame_slots() == 307
    finally:
        show_settings.set_current(contract.defaults())


def test_signed_helper_still_signs_with_the_test_seed():
    assert len(base64.b64decode(json.loads(signed({"a": 1}, SEED))["signature"])) == 64


# --- the review's destructive cases: a swap never deletes a copy that could be the last good one ---

@posix_only
def test_a_rollback_whose_stable_copy_never_comes_up_keeps_the_stable_copy(tmp_path):
    marker = tmp_path / "started.txt"
    root = fake_install(tmp_path / "Llano-Lights", "test7", marker)
    fake_install(updater.stable_path(root), "stable", marker, comes_up=False)
    run_swap(updater.stage_rollback(root), wait_s=2, ready_s=2)
    assert (root / "app" / "gigbar_app.py").read_text() == "test7"
    assert (updater.stable_path(root) / "app" / "gigbar_app.py").read_text() == "stable"   # still there
    assert wait_for(marker, 2) == ["stable", "--updated", "test7", "--update-failed"]


@posix_only
def test_a_rollback_with_no_test_copy_that_never_comes_up_leaves_the_stable_copy_installed(tmp_path):
    marker = tmp_path / "started.txt"
    root = tmp_path / "Llano-Lights"
    fake_install(updater.stable_path(root), "stable", marker, comes_up=False)
    run_swap(updater.stage_rollback(root), wait_s=2, ready_s=2)
    assert (root / "app" / "gigbar_app.py").read_text() == "stable"   # the only copy is never emptied
    assert not Path(str(root) + ".old").exists()
    assert wait_for(marker, 2)[-2:] == ["stable", "--update-failed"]


@posix_only
def test_a_test_build_that_never_comes_up_gives_the_stable_copy_back(tmp_path):
    marker = tmp_path / "started.txt"
    root = fake_install(tmp_path / "Llano-Lights", "stable", marker)
    new = fake_install(tmp_path / "Llano-Lights.new", "test7", marker, comes_up=False)
    run_swap(updater.stage_swap(root, new, "1.14.0.7", wait_s=2, keep=updater.stable_path(root)), ready_s=2)
    assert (root / "app" / "gigbar_app.py").read_text() == "stable"
    assert not updater.stable_path(root).exists() and not Path(str(root) + ".failed").exists()
    assert wait_for(marker, 2) == ["test7", "--updated", "stable", "--update-failed"]


@posix_only
def test_the_stable_copy_is_set_aside_before_the_test_build_starts(tmp_path):
    """The new copy's startup cleanup can never race the keep: .old is already gone when it runs."""
    marker = tmp_path / "started.txt"
    root = fake_install(tmp_path / "Llano-Lights", "stable", marker)
    new = fake_install(tmp_path / "Llano-Lights.new", "test7", marker)
    exe = new / "runtime" / "pythonw.exe"
    exe.write_text(exe.read_text().replace(
        "echo test7", f"[ -d '{root}.old' ] && echo OLD-STILL-THERE >> '{marker}'; "
                      f"[ -d '{root}.stable' ] && echo kept >> '{marker}'; echo test7"))
    run_swap(updater.stage_swap(root, new, "1.14.0.7", wait_s=2, keep=updater.stable_path(root)))
    got = wait_for(marker, 2)
    assert "OLD-STILL-THERE" not in got and got[:3] == ["kept", "test7", "--updated"]


def test_a_probe_ends_the_moment_a_song_starts(no_probe, monkeypatch):
    playing = {"on": False}
    monkeypatch.setattr(probe, "song_playing", lambda: playing["on"])
    probe.set_probe({24: 200}, time.time() + 30)
    assert probe.apply(bytes(512))[23] == 200
    playing["on"] = True
    assert probe.apply(bytes(512))[23] == 0 and probe.active() == {} and "song started" in probe.note


def test_the_launcher_survives_non_ascii_and_percent_paths(tmp_path):
    root = tmp_path / "José 100%" / "Llano-Lights"
    text = updater.rollback_launcher_text(root)
    assert text.splitlines()[1] == "chcp 65001 >nul"
    assert "José 100%%" in text and "100% " not in text.replace("100%%", "")
