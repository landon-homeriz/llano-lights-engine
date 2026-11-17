"""Update now always ends with a copy that is up (Llano BL #11612, his 11-08 1.12.1 -> 1.14.0:
the window closed and nothing reopened, several tries)."""
from __future__ import annotations

import dataclasses
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools.gigbar_lights import updater

from test_updater import fake_install, run_swap, wait_for

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"))

posix_only = pytest.mark.skipif(os.name == "nt", reason="the fake runtime is a shell script")


def dies_at_start(folder: Path, tag: str, marker: Path) -> Path:
    """An install whose app records its start and exits at once, never saying it is up."""
    fake_install(folder, tag, marker)
    exe = folder / "runtime" / "pythonw.exe"
    exe.write_text(f"#!/bin/sh\necho {tag} \"$2\" >> '{marker}'\nexit 3\n")
    return folder


def log_of(tmp_path: Path) -> str:
    return (tmp_path / "update.log").read_text()


@posix_only
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root renames through a read-only folder")
def test_an_old_copy_that_will_not_let_go_comes_back_with_the_reason(tmp_path):
    marker = tmp_path / "started.txt"
    locked = tmp_path / "locked"
    root = fake_install(locked / "Llano-Lights", "old", marker)
    new = fake_install(tmp_path / "Llano-Lights.new", "new", marker)
    cmd = updater.stage_swap(root, new, "9.0.0", wait_s=2)
    locked.chmod(stat.S_IRUSR | stat.S_IXUSR)   # nothing in it can be renamed: a held file on Windows
    try:
        run_swap(cmd, log=str(tmp_path / "update.log"), hang_s=1, ready_s=5)
    finally:
        locked.chmod(stat.S_IRWXU)
    assert wait_for(marker, 1) == ["old", "--update-failed"]
    text = log_of(tmp_path)
    assert "still open after 1 s; closing it" in text
    assert "FAILED: Windows kept the old copy's files open" in text
    assert "is open again" in text


@posix_only
def test_a_new_copy_that_closes_at_start_puts_the_old_one_back_and_says_why(tmp_path):
    marker = tmp_path / "started.txt"
    root = fake_install(tmp_path / "Llano-Lights", "old", marker)
    new = dies_at_start(tmp_path / "Llano-Lights.new", "new", marker)
    run_swap(updater.stage_swap(root, new, "9.0.0", wait_s=2), log=str(tmp_path / "update.log"), ready_s=5)
    assert (root / "app" / "gigbar_app.py").read_text() == "old"
    assert wait_for(marker, 2) == ["new", "--updated", "old", "--update-failed"]
    assert "FAILED: 9.0.0 closed as it started" in log_of(tmp_path)


@posix_only
def test_when_no_copy_comes_up_windows_says_so(tmp_path):
    marker = tmp_path / "started.txt"
    root = dies_at_start(tmp_path / "Llano-Lights", "old", marker)
    new = dies_at_start(tmp_path / "Llano-Lights.new", "new", marker)
    run_swap(updater.stage_swap(root, new, "9.0.0", wait_s=2), log=str(tmp_path / "update.log"), ready_s=3)
    assert (root / "app" / "gigbar_app.py").read_text() == "old"   # the old copy is still the install
    text = log_of(tmp_path)
    assert "told him: Llano Lights couldn't update to 9.0.0 and didn't reopen on its own." in text
    assert "Open Llano Lights from the Start menu" in text


def test_last_swap_reads_the_last_run_and_its_reason(tmp_path, monkeypatch):
    log = tmp_path / "llano-lights-update.log"
    log.write_text("2026-11-08 20:00:00 swap started: 1.13.0 into C:\\x\n"
                   "2026-11-08 20:00:01 FAILED: an older reason\n"
                   "2026-11-08 21:07:00 swap started: 1.14.0 into C:\\x\n"
                   "2026-11-08 21:07:20 the old copy is still open after 20 s; closing it\n"
                   "2026-11-08 21:08:00 FAILED: Windows kept the old copy's files open, so the new version couldn't go in\n")
    monkeypatch.setattr(updater, "update_log", lambda root=None: log)
    lines, why = updater.last_swap()
    assert lines[0].endswith("swap started: 1.14.0 into C:\\x") and len(lines) == 3
    assert why == "Windows kept the old copy's files open, so the new version couldn't go in"
    log.write_text("2026-11-08 21:07:00 swap started: 1.14.0 into C:\\x\n2026-11-08 21:07:09 done\n")
    assert updater.last_swap()[1] == ""
    monkeypatch.setattr(updater, "update_log", lambda root=None: tmp_path / "missing.log")
    assert updater.last_swap() == ([], "")


def test_the_failed_update_goes_to_llano_as_a_report():
    import gigbar_app
    lines = ["2026-11-08 21:07:00 swap started: 1.14.0 into C:\\x", "2026-11-08 21:08:00 FAILED: it hung"]
    r = gigbar_app.update_report(lines, "it hung")
    assert r["started"] == "2026-11-08 21:07:00" and r["version"] == gigbar_app.VERSION
    assert r["lines"] == lines and r["fault"] == "update didn't finish: it hung"
    assert set(r) == {"version", "started", "lines", "fault"}   # what store._keep_crash keeps


def test_a_copy_quitting_for_an_update_always_ends(tmp_path):
    """exit_hard ends the process even with a thread that never finishes (the 1.12.1 hang)."""
    src = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src"
    code = ("import sys, threading; sys.path.insert(0, %r); import gigbar_app; "
            "threading.Thread(target=threading.Event().wait).start(); "
            "threading.Thread(target=gigbar_app.exit_hard, args=(0.5, 'test'), daemon=True).start()" % str(src))
    t = time.time()
    r = subprocess.run([sys.executable, "-c", code], cwd=str(src.parents[3]), timeout=60,
                       capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=str(src.parents[3])))
    assert r.returncode == 0, r.stderr
    assert time.time() - t < 30


def test_later_hides_the_banner_and_leaves_one_update_now():
    html = (Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows" / "src" / "app.html").read_text()
    assert 'btn("Later", "", () => post("/api/update-later")' in html
    assert 'u.state === "offered" && !u.later' in html
    # the top bar shows a button only once the banner is gone
    assert html.count('btn("Update now", "primary", () => post("/api/update")') == 2
    assert "if (u.later) el.append(" in html


def make_app(tmp_path, monkeypatch, **over):
    import argparse
    import gigbar_app
    from tools.gigbar_lights.venue import LayoutStore
    monkeypatch.setenv("HOME", str(tmp_path))   # never the real ~/.gigbar_lights
    monkeypatch.setattr(gigbar_app.updater, "check", lambda: (None, "no update in tests"))
    monkeypatch.setattr(gigbar_app, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(gigbar_app, "_enttec_port", lambda: None)
    monkeypatch.setattr(gigbar_app, "midi_port", lambda: "")
    opts = argparse.Namespace(**{"seconds": 0.0, "bpm": 128.0, "no_browser": True, "no_window": True,
                                 "updated": False, "update_failed": False, **over})
    a = gigbar_app.App(opts, gigbar_app.LogBuffer(tmp_path / "log.txt"))
    a.preview = gigbar_app.Preview("", LayoutStore(tmp_path / "profile"), app=a)
    return a


def test_later_is_per_offered_version(tmp_path, monkeypatch):
    a = make_app(tmp_path, monkeypatch)
    try:
        a.offer = updater.Offer(version="9.0.0", notes="n", zip_url="https://x/Llano-Lights-9.0.0.zip",
                                sha256="0" * 64, size=1)
        a.update_state = "offered"
        assert a.state()["update"]["later"] is False
        assert a.post("update-later", {}) == (200, {"ok": True})
        assert a.state()["update"]["later"] is True
        a.offer = dataclasses.replace(a.offer, version="9.0.1")   # a newer one shows again
        assert a.state()["update"]["later"] is False
    finally:
        a.quit.set()
        a.preview.close()


def test_a_failed_update_says_why_in_the_notice(tmp_path, monkeypatch):
    log = tmp_path / "u.log"
    log.write_text("2026-11-08 21:07:00 swap started: 9.0.0 into C:\\x\n2026-11-08 21:08:00 FAILED: it hung\n")
    monkeypatch.setattr(updater, "update_log", lambda root=None: log)
    a = make_app(tmp_path, monkeypatch, update_failed=True)
    try:
        assert a.notice.endswith(": it hung. Update now tries again.")
        assert a.update_why == "it hung" and len(a.update_log) == 2
    finally:
        a.quit.set()
        a.preview.close()
