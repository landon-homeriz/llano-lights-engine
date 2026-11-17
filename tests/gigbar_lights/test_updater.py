"""Auto-update: Ed25519, what a signed update file must prove, the zip unpack and the swap."""
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

from tools.gigbar_lights import ed25519, updater

SEED = bytes(range(32))
PUB = ed25519.public_key(SEED)
URL = "https://example.invalid/dl/k/latest.json"


def manifest(**over):
    m = {"product": "llano-lights", "version": "9.0.0", "zip": "Llano-Lights-9.0.0.zip",
         "sha256": "ab" * 32, "size": 1234, "notes": "new", "published": "2026-11-06"}
    m.update(over)
    return m


def signed(m, seed=SEED) -> bytes:
    return json.dumps(updater.sign_manifest(m, seed)).encode()


def parse(raw, current="1.1.0"):
    return updater.parse_update_file(raw, URL, current=current, public_key=PUB)


# --- Ed25519 ------------------------------------------------------------------------------

def test_rfc8032_vector_1():
    sk = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    pk = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
    sig = bytes.fromhex("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
                        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
    assert ed25519.public_key(sk) == pk
    assert ed25519.sign(sk, b"") == sig
    assert ed25519.verify(pk, b"", sig)
    assert not ed25519.verify(pk, b"x", sig)
    assert not ed25519.verify(pk, b"", sig[:-1] + bytes([sig[-1] ^ 1]))


# --- the update file ------------------------------------------------------------------------

def test_genuine_newer_update_is_offered():
    offer = parse(signed(manifest()))
    assert offer.version == "9.0.0"
    assert offer.zip_url == "https://example.invalid/dl/k/Llano-Lights-9.0.0.zip"
    assert (offer.size, offer.sha256, offer.notes) == (1234, "ab" * 32, "new")


@pytest.mark.parametrize("current", ["9.0.0", "9.0", "10.0.1"])
def test_same_or_older_version_is_not_offered(current):
    assert parse(signed(manifest()), current=current) is None


def test_signature_from_another_key_is_refused():
    with pytest.raises(updater.UpdateError, match="signature"):
        parse(signed(manifest(), seed=bytes(32)))


def test_edited_manifest_breaks_the_signature():
    outer = updater.sign_manifest(manifest(), SEED)
    body = json.loads(base64.b64decode(outer["manifest"]))
    body["sha256"] = "cd" * 32
    outer["manifest"] = base64.b64encode(json.dumps(body).encode()).decode()
    with pytest.raises(updater.UpdateError, match="signature"):
        parse(json.dumps(outer).encode())


@pytest.mark.parametrize("over, why", [
    ({"product": "something-else"}, "different product"),
    ({"zip": "../Llano-Lights-9.0.0.zip"}, "unexpected file"),
    ({"zip": "evil.exe"}, "unexpected file"),
    ({"sha256": "XYZ"}, "checksum"),
    ({"size": 0}, "size"),
    ({"size": 10 ** 10}, "size"),
    ({"version": "nine"}, "version"),
])
def test_signed_but_wrong_is_refused(over, why):
    with pytest.raises(updater.UpdateError, match=why):
        parse(signed(manifest(**over)))


@pytest.mark.parametrize("raw", [b"", b"not json", b"{}", b'{"format": 2, "manifest": "", "signature": ""}'])
def test_damaged_file_is_refused(raw):
    with pytest.raises(updater.UpdateError):
        parse(raw)


def test_check_never_raises_when_offline():
    offer, note = updater.check("http://127.0.0.1:1/latest.json")
    assert offer is None and note == updater.UNREACHABLE


# --- download + unpack ------------------------------------------------------------------------

def make_zip(path: Path, names: dict) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in names.items():
            z.writestr(name, data)
    return path


GOOD = {"Llano-Lights/runtime/pythonw.exe": b"exe", "Llano-Lights/app/gigbar_app.py": b"app"}


def offer_for(path: Path, **over) -> updater.Offer:
    data = path.read_bytes()
    kw = dict(version="9.0.0", notes="", zip_url=path.as_uri(),
              sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    kw.update(over)
    return updater.Offer(**kw)


def test_download_checks_size_and_hash(tmp_path):
    z = make_zip(tmp_path / "Llano-Lights-9.0.0.zip", GOOD)
    got = updater.download(offer_for(z), tmp_path / "dl" / "a.zip")
    assert got.read_bytes() == z.read_bytes()
    with pytest.raises(updater.UpdateError, match="checksum"):
        updater.download(offer_for(z, sha256="00" * 32), tmp_path / "dl" / "b.zip")
    with pytest.raises(updater.UpdateError, match="bigger"):
        updater.download(offer_for(z, size=10), tmp_path / "dl" / "c.zip")
    assert not list((tmp_path / "dl").glob("*.part"))


def test_unpack_strips_the_top_folder(tmp_path):
    root = updater.unpack(make_zip(tmp_path / "u.zip", GOOD), tmp_path / "new")
    assert (root / "app" / "gigbar_app.py").read_bytes() == b"app"


@pytest.mark.parametrize("bad", ["Llano-Lights/../escape.txt", "Other/app/x.py", "/abs.txt", "Llano-Lights/C:/x"])
def test_unpack_refuses_paths_that_climb_out(tmp_path, bad):
    with pytest.raises(updater.UpdateError, match="layout"):
        updater.unpack(make_zip(tmp_path / "u.zip", {**GOOD, bad: b"x"}), tmp_path / "new")
    assert not (tmp_path / "escape.txt").exists()


def test_unpack_refuses_an_incomplete_build(tmp_path):
    with pytest.raises(updater.UpdateError, match="missing"):
        updater.unpack(make_zip(tmp_path / "u.zip", {"Llano-Lights/app/gigbar_app.py": b"a"}), tmp_path / "new")


# --- the swap -----------------------------------------------------------------------------------

def fake_install(folder: Path, tag: str, marker: Path, comes_up: bool = True) -> Path:
    """An install whose 'pythonw.exe' records which copy started and with what flag, and
    (like the real app) writes the ready file it is handed once it is up."""
    (folder / "app").mkdir(parents=True)
    (folder / "runtime").mkdir()
    (folder / "app" / "gigbar_app.py").write_text(tag)
    exe = folder / "runtime" / "pythonw.exe"
    ready = '[ "$3" = "--ready-file" ] && echo up > "$4"\n' if comes_up else "sleep 30\n"
    exe.write_text(f"#!/bin/sh\necho {tag} \"$2\" >> '{marker}'\n{ready}")
    exe.chmod(0o755)
    return folder


def run_swap(cmd, **plan_over):
    plan = Path(cmd[2])
    p = json.loads(plan.read_text())
    p.update(plan_over)
    plan.write_text(json.dumps(p))
    subprocess.run([sys.executable, *cmd[1:]], check=False, timeout=90)  # cmd[0] is the Windows runtime
    return p


def wait_for(marker: Path, lines: int, s: float = 15):
    deadline = time.time() + s
    while time.time() < deadline and (not marker.exists() or len(marker.read_text().split("\n")) <= lines):
        time.sleep(0.1)
    return marker.read_text().split() if marker.exists() else []


posix_only = pytest.mark.skipif(os.name == "nt", reason="the fake runtime is a shell script")


@posix_only
def test_swap_puts_the_new_copy_in_place_and_starts_it(tmp_path):
    marker = tmp_path / "started.txt"
    root = fake_install(tmp_path / "Llano-Lights", "old", marker)
    new = fake_install(tmp_path / "Llano-Lights.new", "new", marker)
    plan = run_swap(updater.stage_swap(root, new, "9.0.0", wait_s=2))
    assert (root / "app" / "gigbar_app.py").read_text() == "new"
    assert not new.exists() and not Path(str(root) + ".old").exists()
    assert wait_for(marker, 1) == ["new", "--updated"]
    assert Path(plan["started"]).exists() and Path(plan["ready"]).exists()


@posix_only
def test_swap_rolls_back_when_the_new_copy_cannot_move(tmp_path):
    marker = tmp_path / "started.txt"
    root = fake_install(tmp_path / "Llano-Lights", "old", marker)
    fake_install(tmp_path / "Llano-Lights.new", "new", marker)
    run_swap(updater.stage_swap(root, tmp_path / "Llano-Lights.new", "9.0.0", wait_s=2),
             new=str(tmp_path / "gone"))  # the new copy vanished before the swap
    assert (root / "app" / "gigbar_app.py").read_text() == "old"
    assert wait_for(marker, 1) == ["old", "--update-failed"]


@posix_only
def test_swap_puts_the_old_copy_back_when_the_new_one_never_comes_up(tmp_path):
    marker = tmp_path / "started.txt"
    root = fake_install(tmp_path / "Llano-Lights", "old", marker)
    new = fake_install(tmp_path / "Llano-Lights.new", "new", marker, comes_up=False)
    run_swap(updater.stage_swap(root, new, "9.0.0", wait_s=2), ready_s=2)
    assert (root / "app" / "gigbar_app.py").read_text() == "old"
    assert not Path(str(root) + ".failed").exists() and not Path(str(root) + ".old").exists()
    assert wait_for(marker, 2) == ["new", "--updated", "old", "--update-failed"]


def test_swap_runs_on_the_current_runtime_not_the_new_one(tmp_path):
    marker = tmp_path / "m"
    root = fake_install(tmp_path / "Llano-Lights", "old", marker)
    new = fake_install(tmp_path / "Llano-Lights.new", "new", marker)
    (new / "runtime" / "pythonw.exe").write_text("broken")
    cmd = updater.stage_swap(root, new, "9.0.0")
    assert Path(cmd[0]).read_text() == (root / "runtime" / "pythonw.exe").read_text()


def test_launch_swap_refuses_when_the_installer_never_starts(tmp_path):
    with pytest.raises(updater.UpdateError, match="didn't start"):
        updater.launch_swap([sys.executable, "-c", "pass", str(tmp_path / "plan.json")], wait_s=3)
    with pytest.raises(updater.UpdateError, match="couldn't start"):
        updater.launch_swap([str(tmp_path / "missing.exe"), "x", str(tmp_path / "plan.json")], wait_s=1)


def test_is_installed_is_false_for_a_source_checkout():
    assert not updater.is_installed()


def test_swap_files_never_land_inside_the_install(tmp_path, monkeypatch):
    root = tmp_path / "Llano-Lights"
    (root / "app").mkdir(parents=True)
    monkeypatch.setattr(updater.tempfile, "tempdir", str(root / "app"))  # no TEMP: cwd fallback
    assert updater.scratch_dir(root) == tmp_path.resolve()
    monkeypatch.setattr(updater.tempfile, "tempdir", str(tmp_path / "temp"))
    assert updater.scratch_dir(root) == (tmp_path / "temp").resolve()


def test_a_build_with_no_feed_says_updates_are_off_and_asks_nothing(monkeypatch):
    """The open-source engine ships with no update URL (Llano BL #12514): no request, a plain line."""
    monkeypatch.delenv("LLANO_LIGHTS_UPDATE_URL", raising=False)
    monkeypatch.setattr(updater, "UPDATE_URL", "")
    monkeypatch.setattr(updater, "_get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked the network")))
    assert updater.check() == (None, updater.NO_FEED)
