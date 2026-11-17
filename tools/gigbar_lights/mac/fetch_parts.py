"""Download what mac/build.py builds from, pinned and checked (Llano BL #12517).

  python tools/gigbar_lights/mac/fetch_parts.py PARTS_DIR

Into PARTS_DIR: dl/ (python-build-standalone 3.12 for Apple Silicon and Intel, each checked against
that release's SHA256SUMS), wheels-arm64/ and wheels-x86_64/ (pip download, binary wheels only), and
bin/rcodesign for this computer (checked against its published .sha256). Runs on Linux and on a Mac.
Then: LLANO_LIGHTS_MAC_PARTS=PARTS_DIR RCODESIGN=PARTS_DIR/bin/rcodesign python mac/build.py
"""
from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

PBS_TAG = "20261026"            # python-build-standalone release (CPython 3.12.16)
PBS_PYTHON = "3.12.16"
RCODESIGN = "0.29.0"
WHEELS = ("python-rtmidi==1.5.8", "pyserial==3.5", "numpy==2.4.6", "soundfile==0.14.0", "segno==1.6.6")
GH = "https://github.com"


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "llano-lights-build"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def pbs(dl: Path) -> None:
    base = f"{GH}/astral-sh/python-build-standalone/releases/download/{PBS_TAG}"
    sums = dict(line.split()[::-1] for line in get(f"{base}/SHA256SUMS").decode().splitlines() if line.strip())
    for arch in ("aarch64", "x86_64"):
        name = f"cpython-{PBS_PYTHON}+{PBS_TAG}-{arch}-apple-darwin-install_only.tar.gz"
        dest = dl / name
        if not (dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() == sums[name]):
            data = get(f"{base}/{name}")
            if hashlib.sha256(data).hexdigest() != sums[name]:
                sys.exit(f"{name}: checksum doesn't match the release's SHA256SUMS")
            dest.write_bytes(data)
        print("ok", name)


def wheels(parts: Path) -> None:
    for arch in ("arm64", "x86_64"):
        plats = [f for v in ("10_9", "10_13", "10_15", "11_0", "12_0", "13_0", "14_0")
                 for f in ("--platform", f"macosx_{v}_{arch}", "--platform", f"macosx_{v}_universal2")]
        subprocess.run([sys.executable, "-m", "pip", "download", "-q", "--only-binary=:all:", *plats,
                        "--python-version", "3.12", "--implementation", "cp", "--abi", "cp312", "--abi", "abi3",
                        "--abi", "none", "-d", str(parts / f"wheels-{arch}"), *WHEELS], check=True)
        print("ok", f"wheels-{arch}:", ", ".join(sorted(p.name.split("-")[0] for p in (parts / f"wheels-{arch}").glob("*.whl"))))


def rcodesign(bin_dir: Path) -> None:
    if sys.platform == "darwin":
        target = "macos-universal"
    else:
        target = f"{'aarch64' if platform.machine() in ('aarch64', 'arm64') else 'x86_64'}-unknown-linux-musl"
    name = f"apple-codesign-{RCODESIGN}-{target}.tar.gz"
    base = f"{GH}/indygreg/apple-platform-rs/releases/download/apple-codesign%2F{RCODESIGN}"
    data, want = get(f"{base}/{name}"), get(f"{base}/{name}.sha256").decode().split()[0]
    if hashlib.sha256(data).hexdigest() != want:
        sys.exit(f"{name}: checksum doesn't match its .sha256")
    tmp = bin_dir / name
    tmp.write_bytes(data)
    with tarfile.open(tmp) as t:
        member = next(m for m in t.getmembers() if m.name.endswith("/rcodesign"))
        member.name = "rcodesign"
        t.extract(member, bin_dir, filter="data")
    tmp.unlink()
    (bin_dir / "rcodesign").chmod(0o755)
    print("ok", bin_dir / "rcodesign")


def main() -> int:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    parts = Path(sys.argv[1]).resolve()
    for d in ("dl", "bin"):
        (parts / d).mkdir(parents=True, exist_ok=True)
    pbs(parts / "dl")
    wheels(parts)
    rcodesign(parts / "bin")
    return 0


if __name__ == "__main__":
    sys.exit(main())
