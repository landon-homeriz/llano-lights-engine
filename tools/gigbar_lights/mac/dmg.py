"""The disk image a new user installs from: "Llano Lights.app" beside an Applications shortcut (Llano BL #12517).

Made on Linux the way Firefox's are: an HFS+ volume (mkfs.hfsplus), the app added to it and an
/Applications symlink (hfsplus), then compressed into a UDIF disk image (dmg). The tools run in a
container built from Dockerfile.dmg (Mozilla's libdmg-hfsplus at a pinned commit); on a Mac,
hdiutil makes the same image. build.py signs and notarizes the result when it has the Apple keys.

  python tools/gigbar_lights/mac/dmg.py "out/Llano Lights.app" out/Llano-Lights-1.40.0-mac.dmg
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

M = Path(__file__).resolve().parent
IMAGE = "llano-lights-dmg:e18579b"   # tag = the libdmg-hfsplus commit in Dockerfile.dmg
VOLUME = "Llano Lights"


def _size_mb(path: Path) -> int:
    total = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return int(total * 1.08 / 1e6) + 24   # file system overhead and slack (the image compresses it away)


def _docker(*args: str, mount: Path) -> None:
    subprocess.run(["docker", "run", "--rm", "--network", "none", "--user", f"{os.getuid()}:{os.getgid()}",
                    "-v", f"{mount}:/work", "-w", "/work", IMAGE, *args], check=True)


def make_dmg(app: Path, out: Path) -> Path:
    app, out = app.resolve(), out.resolve()
    if sys.platform == "darwin":
        with tempfile.TemporaryDirectory() as stage:
            shutil.copytree(app, Path(stage) / app.name, symlinks=True)
            os.symlink("/Applications", Path(stage) / "Applications")
            out.unlink(missing_ok=True)
            subprocess.run(["/usr/bin/hdiutil", "create", "-volname", VOLUME, "-srcfolder", stage,
                            "-format", "UDZO", "-fs", "HFS+", str(out)], check=True)
        return out
    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode != 0:
        subprocess.run(["docker", "build", "-q", "-t", IMAGE, "-f", str(M / "Dockerfile.dmg"), str(M)], check=True)
    work = Path(tempfile.mkdtemp(prefix="llano-dmg-", dir=out.parent))
    try:
        (work / "stage").mkdir()
        shutil.copytree(app, work / "stage" / app.name, symlinks=True)
        hfs = work / "stage.hfs"
        with open(hfs, "wb") as f:
            f.truncate(_size_mb(app) * 1024 * 1024)
        _docker("mkfs.hfsplus", "-v", VOLUME, "stage.hfs", mount=work)
        _docker("hfsplus", "stage.hfs", "addall", "stage", mount=work)
        _docker("hfsplus", "stage.hfs", "symlink", "/Applications", "/Applications", mount=work)
        _docker("dmg", "build", "stage.hfs", "out.dmg", mount=work)
        out.unlink(missing_ok=True)
        shutil.move(str(work / "out.dmg"), out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return out


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    print(make_dmg(Path(sys.argv[1]), Path(sys.argv[2])))
