"""Every build carries its version and build time; the history lists them; Windows lists the app with Uninstall."""
import datetime
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows"))
import history  # noqa: E402
from tools.gigbar_lights import ed25519, updater, version, windows_apps  # noqa: E402

UTC = datetime.timezone.utc
WIN = Path(__file__).resolve().parents[2] / "tools" / "gigbar_lights" / "windows"


# --- build time -------------------------------------------------------------------------------

@pytest.mark.parametrize("when, label", [
    (datetime.datetime(2026, 11, 6, 20, 40, tzinfo=UTC), "Nov 6, 2026, 2:40 PM CT"),   # CST
    (datetime.datetime(2026, 7, 4, 5, 5, tzinfo=UTC), "Jul 4, 2026, 12:05 AM CT"),     # CDT
    (datetime.datetime(2026, 11, 6, 18, 0, tzinfo=UTC), "Nov 6, 2026, 12:00 PM CT"),
])
def test_central_label(when, label):
    assert history.central_label(when) == label


def zip_with(tmp_path, info: str = None) -> Path:
    z = tmp_path / "Llano-Lights-9.0.0.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("Llano-Lights/app/gigbar_app.py", "")
        if info is not None:
            f.writestr(history.BUILD_INFO, info)
    return z


def test_build_time_reads_back_out_of_the_zip(tmp_path):
    when = datetime.datetime(2026, 11, 6, 20, 40, 12, 345, tzinfo=UTC)
    assert history.build_time_in(zip_with(tmp_path, history.build_info_source(when))) == \
        ("2026-11-06T20:40:12Z", "Nov 6, 2026, 2:40 PM CT")


@pytest.mark.parametrize("info", [None, "BUILT_UTC = '2026-11-06T20:40:12Z'\n"])
def test_a_zip_without_a_build_time_is_refused(tmp_path, info):
    with pytest.raises(ValueError, match="build"):
        history.build_time_in(zip_with(tmp_path, info))


def test_build_info_is_what_version_py_reads(tmp_path, monkeypatch):
    when = datetime.datetime(2026, 11, 6, 20, 40, tzinfo=UTC)
    ns = {}
    exec(history.build_info_source(when), ns)
    assert ns["BUILT_CT"] == "Nov 6, 2026, 2:40 PM CT" and ns["BUILT_UTC"] == "2026-11-06T20:40:00Z"
    monkeypatch.setattr(version, "BUILT_CT", ns["BUILT_CT"])
    assert version.label() == f"{version.VERSION}, built Nov 6, 2026, 2:40 PM CT"
    monkeypatch.setattr(version, "BUILT_CT", "")
    assert version.label() == f"{version.VERSION} (source copy)"


def test_the_signed_feed_carries_the_build_time():
    seed = bytes(range(32))
    m = {"product": "llano-lights", "version": "9.0.0", "zip": "Llano-Lights-9.0.0.zip", "sha256": "ab" * 32,
         "size": 1, "notes": "n", "published": "2026-11-06", "built": "2026-11-06T20:40:00Z",
         "built_ct": "Nov 6, 2026, 2:40 PM CT"}
    raw = json.dumps(updater.sign_manifest(m, seed)).encode()
    offer = updater.parse_update_file(raw, "https://example.invalid/dl/", current="1.1.0",
                                      public_key=ed25519.public_key(seed))
    assert offer.built == "Nov 6, 2026, 2:40 PM CT"


# --- source commit -------------------------------------------------------------------------------

SHA = "b704a1cbecdf" + "0" * 28


def test_the_build_stamp_carries_the_commit_and_release_reads_it_back(tmp_path):
    when = datetime.datetime(2026, 11, 8, 18, 0, tzinfo=datetime.timezone.utc)
    z = zip_with(tmp_path, history.build_info_source(when, SHA))
    assert history.build_commit_in(z) == SHA
    assert history.build_time_in(z) == ("2026-11-08T18:00:00Z", "Nov 8, 2026, 12:00 PM CT")
    ns = {}
    exec(history.build_info_source(when, SHA), ns)
    assert ns["BUILT_COMMIT"] == SHA


@pytest.mark.parametrize("commit", ["", SHA + "-dirty", "b704a1c"])
def test_release_refuses_a_zip_with_no_clean_full_commit(tmp_path, commit):
    when = datetime.datetime(2026, 11, 8, 18, 0, tzinfo=datetime.timezone.utc)
    with pytest.raises(ValueError):
        history.build_commit_in(zip_with(tmp_path, history.build_info_source(when, commit)))


def test_source_commit_is_the_full_sha_and_flags_uncommitted_changes(tmp_path):
    import subprocess
    run = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)
    assert history.source_commit(tmp_path) == ""  # not a git checkout
    run("init", "-q")
    (tmp_path / "f.txt").write_text("a")
    run("add", "f.txt")
    run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x")
    sha = history.source_commit(tmp_path)
    (tmp_path / "z").mkdir()
    assert len(sha) == 40 and history.build_commit_in(
        zip_with(tmp_path / "z", history.build_info_source(datetime.datetime.now(datetime.timezone.utc), sha))) == sha
    (tmp_path / "f.txt").write_text("b")
    assert history.source_commit(tmp_path) == sha + "-dirty"
    (tmp_path / "f.txt").write_text("a")
    (tmp_path / "untracked.txt").write_text("u")  # out/, dl/ and wheels/ are untracked; they don't count
    assert history.source_commit(tmp_path) == sha


def test_the_history_keeps_the_commit():
    h = {"product": "llano-lights", "releases": []}
    history.add_release(h, dict(manifest("1.11.0"), commit=SHA))
    assert h["releases"][0]["commit"] == SHA


# --- version history ----------------------------------------------------------------------------

def manifest(v):
    return {"version": v, "built": "2026-11-06T20:40:00Z", "built_ct": "Nov 6, 2026, 2:40 PM CT",
            "notes": f"notes {v}", "zip": f"Llano-Lights-{v}.zip", "sha256": "ab" * 32, "size": 9}


def test_history_is_newest_first_and_refuses_a_repeat():
    h = {"product": "llano-lights", "releases": []}
    history.add_release(h, manifest("1.1.0"))
    history.add_release(h, manifest("1.1.1"))
    assert [r["version"] for r in h["releases"]] == ["1.1.1", "1.1.0"]
    with pytest.raises(ValueError, match="already"):
        history.add_release(h, manifest("1.1.1"))


def test_room_table_links_every_build_and_marks_backfilled_times():
    h = {"releases": [dict(manifest("1.1.1"), built_ct="Nov 6, 2026, 2:40 PM CT", download="https://d/new"),
                      dict(manifest("1.1.0"), built_ct="Nov 6, 2026, 12:06 PM CT", download="https://d/old",
                           backfilled=True),
                      dict(manifest("1.0.0"), built_ct="Nov 6, 2026, 9:04 AM CT", download="")]}
    out = history.render(h).splitlines()
    assert out[2].startswith("| **1.1.1** | Nov 6, 2026, 2:40 PM CT |") and "(https://d/new)" in out[2]
    assert "12:06 PM CT\\*" in out[3] and "[Llano-Lights-1.1.0.zip](https://d/old)" in out[3]
    assert out[4].endswith("| not uploaded |")
    assert "numbered afterwards" in out[-1]


def test_the_committed_history_reads_and_starts_at_the_current_version():
    h = history.load()
    versions = [r["version"] for r in h["releases"]]
    assert versions == sorted(versions, key=updater.version_tuple, reverse=True)
    assert updater.version_tuple(version.VERSION) >= updater.version_tuple(versions[0])
    for r in h["releases"]:
        assert r["built_ct"].endswith(" CT") and r["zip"] == f"Llano-Lights-{r['version']}.zip"


# --- Windows Settings > Apps ----------------------------------------------------------------------

class FakeReg:
    HKEY_CURRENT_USER, KEY_ALL_ACCESS, REG_SZ, REG_DWORD = "HKCU", 1, "SZ", "DWORD"

    def __init__(self, existing=None):
        self.values = dict(existing or {})
        self.paths = []

    def CreateKeyEx(self, hive, path, reserved, access):
        self.paths.append((hive, path))
        reg = self

        class K:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return K()

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[name] = (value, kind)


def install(tmp_path) -> Path:
    root = tmp_path / "Llano-Lights"
    (root / "runtime").mkdir(parents=True)
    (root / "runtime" / "python.exe").write_bytes(b"x" * 4096)
    (root / "uninstall.ps1").write_text("# uninstall")
    (root / windows_apps.MANIFEST).write_text("runtime\r\nuninstall.ps1\r\nllano-lights.install\r\n")
    return root


def test_registers_under_the_per_user_uninstall_key(tmp_path):
    root, reg = install(tmp_path), FakeReg()
    assert windows_apps.register(root, "1.1.1", reg=reg)
    assert reg.paths == [("HKCU", windows_apps.KEY)] and windows_apps.KEY.endswith(r"Uninstall\LlanoLights")
    v = {k: val for k, (val, kind) in reg.values.items()}
    assert v["DisplayName"] == "Llano Lights" and v["DisplayVersion"] == "1.1.1"
    assert v["InstallLocation"] == str(root) and v["DisplayIcon"] == str(root / "llano-lights.ico")
    assert f'-File "{root / "uninstall.ps1"}"' in v["UninstallString"] and "powershell.exe" in v["UninstallString"]
    assert reg.values["EstimatedSize"] == (4, "DWORD") and reg.values["NoModify"] == (1, "DWORD")


def test_an_update_keeps_the_first_install_date(tmp_path):
    reg = FakeReg({"InstallDate": "20261101"})
    windows_apps.register(install(tmp_path), "1.1.2", reg=reg)
    assert reg.values["InstallDate"] == ("20261101", "SZ")


@pytest.mark.parametrize("missing", ["uninstall.ps1", windows_apps.MANIFEST])
def test_no_entry_without_the_uninstaller_and_its_list(tmp_path, missing):
    root, reg = install(tmp_path), FakeReg()
    (root / missing).unlink()
    assert not windows_apps.register(root, "1.1.1", reg=reg) and reg.values == {}


def test_the_build_lists_what_it_shipped_for_uninstall():
    src = (WIN / "build.py").read_text()
    assert 'OUT / "llano-lights.install"' in src and windows_apps.MANIFEST == "llano-lights.install"


def test_uninstall_only_deletes_what_the_build_shipped_and_asks_before_layouts():
    ps = (WIN / "src" / "win" / "uninstall.ps1").read_text()
    assert r"Uninstall\LlanoLights" in ps and '$manifest = "llano-lights.install"' in ps
    # Refuses drive roots, Windows' own folders and any folder without the build's list, before anything.
    guard = ps.index("$isRoot -or ($special -contains $Root) -or -not (Test-Path")
    assert guard < ps.index('$ok = Ask ("Remove Llano Lights')
    # The folder itself goes only once the shipped names are gone and nothing else is left in it.
    assert "foreach ($name in $names) { Remove-Hard (Join-Path $Root $name) }" in ps
    assert "if (-not $left -and -not (Get-ChildItem -LiteralPath $Root -Force" in ps
    # The process kill matches the folder plus a separator and never this script.
    assert '$prefixes = @("$Root\\", "$Root.new\\", "$Root.old\\")' in ps and "($_.ProcessId -ne $PID)" in ps
    # Layouts: asked separately, No is the default button, and only a Yes deletes them.
    ask = ps[ps.index('$saved = Join-Path $env:USERPROFILE ".gigbar_lights"'):]
    assert '"YesNo" "Warning" "Button2"' in ask and 'if ($del -eq "Yes") { Remove-Hard $saved }' in ask
    for gone in ("Llano Lights.lnk", "Llano-Light-Link.js", "$Root.new", "$Root.old", ".llano-lights-download",
                 "llano-lights-swap-*", "llano-lights-update.log", "$profileDir"):
        assert gone in ps


def test_build_ships_every_file_the_app_loads_beside_itself():
    """1.11.0 shipped without shows.html, so Shows opened an empty page on his laptop (his 11-08
    2:40 PM recording). Every `HERE / "<name>"` the app reads must be in what build.py copies."""
    import re
    src = Path(history.__file__).resolve().parent / "src"
    shipped = {f.name for f in history.app_files(src)} | {"icons"}   # build.py copies icons/ too
    wanted = set(re.findall(r'HERE / "([^"]+)"', (src / "gigbar_app.py").read_text(encoding="utf-8")))
    assert "shows.html" in wanted
    assert not wanted - shipped, f"the build leaves out {sorted(wanted - shipped)}"
    assert all(f.is_file() for f in history.app_files(src))


def test_a_parts_folder_missing_a_wheel_is_named_so_build_refuses_it(tmp_path):
    """1.15.0 and 1.16.0 shipped without soundcard, winrt and segno because the parts folder lacked them."""
    for n in history.REQUIRED_WHEELS:
        (tmp_path / f"{n}-1.0-py3-none-any.whl").write_bytes(b"")
    assert history.missing_wheels(tmp_path) == []
    (tmp_path / "segno-1.0-py3-none-any.whl").unlink()
    (tmp_path / "winrt_windows_foundation-1.0-py3-none-any.whl").unlink()
    assert history.missing_wheels(tmp_path) == ["segno", "winrt_windows_foundation"]   # _collections does not stand in
